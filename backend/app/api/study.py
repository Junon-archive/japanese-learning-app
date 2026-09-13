"""Study endpoint (05_API_SPEC.md의 `Study Session` / `Interaction`).

인증과 Origin 검증은 이 모듈이 붙이지 않는다. `app.api.router`가 `api_router`에
올리면서 router 레벨 dependency로 건다. endpoint마다 붙이면 하나를 빠뜨리는 순간
무인증 학습 API가 생긴다.

이 모듈은 **HTTP만 한다.**

-   `app.learning` / `app.srs`를 import하지 않는다(ADR-007의 G2). 정책에는
    `app.services`를 통해서만 닿는다.
-   `commit` / `rollback`을 호출하지 않는다(G7). 트랜잭션은 service가 닫는다.
-   시각은 `Depends(get_now)`로 요청당 한 번 받아 값으로 넘긴다(G9).
-   정책값을 읽지 않는다. `AppConfig`를 통째로 service에 넘긴다.

service 예외 -> 상태 코드 변환은 `_http_errors()` 한 곳에 모은다. handler마다 따로
매핑하면 한 곳에서 404를 403으로 잘못 내는 순간 그것이 존재 여부 oracle이 된다.

**handler는 그 매핑을 스스로 걸지 않는다.** `router`의 `route_class`가 요청 처리
전체(dependency 해석, 파라미터 검증, handler 본문)를 `_http_errors()`로 감싼다.
`api/router.py`가 인증을 router 레벨에서 거는 것과 같은 이유다 --- handler마다
`with _http_errors():`를 적게 하면 언젠가 하나가 빠지고, 그 endpoint만 service
예외를 500으로 흘린다(실제로 `POST /session`이 그랬다). 이 router에 올리기만 하면
아무것도 하지 않아도 매핑이 걸리고, 빠지면 `tests/test_route_error_mapping.py`가
빨개진다.

client가 보내는 id는 path든 body든 `ResourceId`다. bigint 범위 밖 정수를 그대로
조회에 넘기면 DB가 던지는 오류가 500이 되어 나간다.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine, Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, get_now
from app.config import AppConfig, get_config
from app.models.study import StudySession
from app.models.user import User
from app.schemas.study import (
    PROBE_OPTIONS,
    PROBE_PROMPT,
    ClientEventRequest,
    CompletePresentationResponse,
    ContentFlagRequest,
    ExplanationResponse,
    IdOutOfRangeError,
    NextPresentationResponse,
    OpenSessionResponse,
    PresentationPayload,
    ProbePayload,
    ProbeResponseRequest,
    ProbeResponseValue,
    ProbeResultResponse,
    RenderSegmentPayload,
    ResourceId,
    RubyPartPayload,
    SelfReportRequest,
    StartSessionResponse,
    StudySessionPayload,
    TappableItemPayload,
    TranslationResponse,
)
from app.services import content_flag, interactions, presentation, study_session
from app.services.events import EventKeyConflictError, ServerEventKeyConflictError

CurrentUser = Annotated[User, Depends(get_current_user)]
Db = Annotated[Session, Depends(get_db)]
Now = Annotated[datetime, Depends(get_now)]
Config = Annotated[AppConfig, Depends(get_config)]


@contextmanager
def _http_errors() -> Iterator[None]:
    """service 예외를 상태 코드로 옮긴다. 내부 사정을 응답에 담지 않는다."""
    try:
        yield
    except (
        study_session.StudySessionNotFoundError,
        presentation.PresentationNotFoundError,
        interactions.SentenceItemNotFoundError,
        IdOutOfRangeError,
    ) as exc:
        # 남의 것과 없는 것을 구분하지 않는다. 403으로 갈라주면 id를 훑어 다른
        # 사용자의 데이터 존재 여부를 알아낼 수 있다.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except study_session.StudySessionClosedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Session is already finished"
        ) from exc
    except presentation.PresentationClosedError as exc:
        # 05_API_SPEC.md의 `세션·presentation 상태 게이트`. `/flag`와 `/complete`는
        # 여기 오지 않는다 --- 게이트가 다르다(ADR-014).
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Presentation is already completed"
        ) from exc
    except interactions.EvidenceAlreadyRecordedError as exc:
        # 05_API_SPEC.md의 `노출당 evidence 상한`. 게이트 409와 **사유가 다르다** ---
        # 이쪽은 어떤 재시도도 성공하지 못하므로 client는 세션을 다시 얻지 않고
        # "이미 기록했습니다"로 끝낸다(같은 절의 `409 사유 구분`).
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This exposure already has recorded evidence",
        ) from exc
    except EventKeyConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="client_event_id is already used by another event",
        ) from exc
    except ServerEventKeyConflictError as exc:
        # server 발급 key의 충돌은 client가 만들 수 없다(client key는 v4만 허용된다).
        # 409로 돌려주면 고칠 수 없는 요청을 재시도하게 만든다. 어떤 key가 무엇으로
        # 점유돼 있는지는 내부 사정이므로 detail에 담지 않는다.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Event could not be recorded",
        ) from exc
    except interactions.ProbeNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid probe_id"
        ) from exc
    except interactions.ExplanationMissingError as exc:
        # Ready invariant 위반이다. 여기서 LLM을 부르지 않는다(불변식 #1).
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Explanation is not available",
        ) from exc


class ErrorMappedRoute(APIRoute):
    """이 router의 모든 라우트를 `_http_errors()`로 감싸는 route class.

    dependency 해석과 파라미터 검증도 안에 든다. 범위 밖 id는 handler에 닿기 전
    pydantic 단계에서 걸리므로, handler 본문만 감싸면 그 경로가 500으로 샌다.
    """

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handle = super().get_route_handler()

        async def mapped(request: Request) -> Response:
            with _http_errors():
                return await handle(request)

        return mapped


# 이 router에 올린 endpoint는 아무것도 하지 않아도 예외 매핑을 상속한다.
router = APIRouter(prefix="/api/study", tags=["study"], route_class=ErrorMappedRoute)


# --------------------------------------------------------------------------
# session
# --------------------------------------------------------------------------


@router.get("/session")
def read_open_session(current_user: CurrentUser, db: Db) -> OpenSessionResponse:
    """조회는 상태를 바꾸지 않는다. idle timeout을 여기서 적용하지 않는다."""
    session = study_session.get_open_session(db, user_id=current_user.id)
    return OpenSessionResponse(
        session=None if session is None else _session_payload(session),
    )


@router.post("/session")
def start_session(current_user: CurrentUser, db: Db, now: Now, cfg: Config) -> StartSessionResponse:
    """idle timeout 이내면 resume, 초과면 새 session이다. body를 받지 않는다.

    `client_event_id`를 받지 않는 이유는 `session_started`의 key가 session id 기반
    server 발급이기 때문이다(ADR-008).
    """
    started = study_session.start_or_resume(db, user=current_user, now=now, cfg=cfg)
    return StartSessionResponse(
        session=_session_payload(started.session),
        resumed=started.resumed,
        timed_out_session_id=started.timed_out_session_id,
    )


@router.post("/session/{session_id}/next")
def next_presentation(
    session_id: ResourceId, current_user: CurrentUser, db: Db, now: Now, cfg: Config
) -> NextPresentationResponse:
    """열린 presentation이 있으면 **그것을** 돌려준다(`열린 presentation 불변식`).

    Ready Pool이 비면 `presentation: null` + **200**이다. 예외를 던지지 않는다 ---
    빈 pool은 오류가 아니라 상태이고, 오류로 만들면 client가 무한 spinner나 오류
    화면으로 간다(10_ERROR_HANDLING.md의 `Empty Pool`).
    """
    view = presentation.next_presentation(
        db, user=current_user, session_id=session_id, now=now, cfg=cfg
    )
    return NextPresentationResponse(
        presentation=None if view is None else _presentation_payload(view),
    )


@router.post("/session/{session_id}/finish")
def finish_session(
    session_id: ResourceId, current_user: CurrentUser, db: Db, now: Now, cfg: Config
) -> StudySessionPayload:
    session = study_session.finish(
        db, user_id=current_user.id, session_id=session_id, now=now, cfg=cfg
    )
    return _session_payload(session)


@router.post("/session/{session_id}/extend")
def extend_session(
    session_id: ResourceId,
    payload: ClientEventRequest,
    current_user: CurrentUser,
    db: Db,
    now: Now,
    cfg: Config,
) -> StudySessionPayload:
    """client가 `client_event_id`를 들고 오는 **유일한** session endpoint다(ADR-008)."""
    session = study_session.extend(
        db,
        user_id=current_user.id,
        session_id=session_id,
        client_event_id=payload.client_event_id,
        now=now,
        cfg=cfg,
    )
    return _session_payload(session)


# --------------------------------------------------------------------------
# presentation
# --------------------------------------------------------------------------


@router.post("/presentations/{presentation_id}/complete")
def complete_presentation(
    presentation_id: ResourceId, current_user: CurrentUser, db: Db, now: Now, cfg: Config
) -> CompletePresentationResponse:
    """`Next`를 누를 때 client가 명시적으로 호출한다. 재호출해도 결과가 같다."""
    completed = presentation.complete_presentation(
        db, user_id=current_user.id, presentation_id=presentation_id, now=now, cfg=cfg
    )
    if completed.completed_at is None:  # pragma: no cover - finalize가 항상 채운다
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Not completed"
        )
    return CompletePresentationResponse(
        presentation_id=completed.id, completed_at=completed.completed_at
    )


@router.post("/presentations/{presentation_id}/items/{sentence_item_id}/click")
def click_item(
    presentation_id: ResourceId,
    sentence_item_id: ResourceId,
    payload: ClientEventRequest,
    current_user: CurrentUser,
    db: Db,
    now: Now,
    cfg: Config,
) -> ExplanationResponse:
    """precomputed 설명을 그대로 돌려준다. live LLM 호출이 없다."""
    view = interactions.click_item(
        db,
        user_id=current_user.id,
        presentation_id=presentation_id,
        sentence_item_id=sentence_item_id,
        client_event_id=payload.client_event_id,
        now=now,
        cfg=cfg,
    )
    return ExplanationResponse(
        sentence_item_id=view.sentence_item_id,
        learning_item_id=view.learning_item_id,
        canonical_form=view.canonical_form,
        reading=view.reading,
        item_type=view.item_type,
        core_meaning=view.core_meaning,
        meaning_in_context=view.meaning_in_context,
        nuance=view.nuance,
        example_sentence=view.example_sentence,
        example_translation=view.example_translation,
    )


@router.post(
    "/presentations/{presentation_id}/items/{sentence_item_id}/explanation-revealed",
    status_code=status.HTTP_204_NO_CONTENT,
)
def reveal_explanation(
    presentation_id: ResourceId,
    sentence_item_id: ResourceId,
    payload: ClientEventRequest,
    current_user: CurrentUser,
    db: Db,
    now: Now,
    cfg: Config,
) -> None:
    interactions.reveal_explanation(
        db,
        user_id=current_user.id,
        presentation_id=presentation_id,
        sentence_item_id=sentence_item_id,
        client_event_id=payload.client_event_id,
        now=now,
        cfg=cfg,
    )


@router.post("/presentations/{presentation_id}/translation/reveal")
def reveal_translation(
    presentation_id: ResourceId,
    payload: ClientEventRequest,
    current_user: CurrentUser,
    db: Db,
    now: Now,
    cfg: Config,
) -> TranslationResponse:
    """번역이 나가는 **유일한** endpoint다. `/next` 응답에는 필드 자체가 없다."""
    translation = interactions.reveal_translation(
        db,
        user_id=current_user.id,
        presentation_id=presentation_id,
        client_event_id=payload.client_event_id,
        now=now,
        cfg=cfg,
    )
    return TranslationResponse(korean_translation=translation)


@router.post("/presentations/{presentation_id}/self-report", status_code=status.HTTP_204_NO_CONTENT)
def self_report(
    presentation_id: ResourceId,
    payload: SelfReportRequest,
    current_user: CurrentUser,
    db: Db,
    now: Now,
    cfg: Config,
) -> None:
    interactions.self_report(
        db,
        user_id=current_user.id,
        presentation_id=presentation_id,
        sentence_item_id=payload.sentence_item_id,
        signal=payload.value,
        client_event_id=payload.client_event_id,
        now=now,
        cfg=cfg,
    )


@router.post("/presentations/{presentation_id}/probe-response")
def respond_to_probe(
    presentation_id: ResourceId,
    payload: ProbeResponseRequest,
    current_user: CurrentUser,
    db: Db,
    now: Now,
    cfg: Config,
) -> ProbeResultResponse:
    """`learning_item_id`는 body가 아니라 조회한 probe event에서 온다(ADR-009)."""
    result = interactions.respond_to_probe(
        db,
        user_id=current_user.id,
        presentation_id=presentation_id,
        probe_id=payload.probe_id,
        signal=payload.value.to_signal(),
        client_event_id=payload.client_event_id,
        now=now,
        cfg=cfg,
    )
    return ProbeResultResponse(
        probe_id=result.probe_id,
        learning_item_id=result.learning_item_id,
        value=(
            ProbeResponseValue.SKIP
            if result.signal is None
            else ProbeResponseValue(result.signal.value)
        ),
    )


@router.post("/presentations/{presentation_id}/flag", status_code=status.HTTP_204_NO_CONTENT)
def flag_content(
    presentation_id: ResourceId,
    payload: ContentFlagRequest,
    current_user: CurrentUser,
    db: Db,
    now: Now,
    cfg: Config,
) -> None:
    """문장과 candidate를 즉시 quarantine하고 그 presentation의 exposure를 무효화한다."""
    content_flag.flag_content(
        db,
        user_id=current_user.id,
        presentation_id=presentation_id,
        reason=payload.reason,
        note=payload.note,
        client_event_id=payload.client_event_id,
        now=now,
        cfg=cfg,
    )


# --------------------------------------------------------------------------
# payload 조립
# --------------------------------------------------------------------------


def _session_payload(session: StudySession) -> StudySessionPayload:
    return StudySessionPayload(
        session_id=session.id,
        started_at=session.started_at,
        last_activity_at=session.last_activity_at,
        ended_at=session.ended_at,
        active_seconds=session.active_seconds,
        target_minutes=session.target_minutes,
        extended_minutes=session.extended_minutes,
    )


def _presentation_payload(view: presentation.PresentationView) -> PresentationPayload:
    return PresentationPayload(
        presentation_id=view.presentation_id,
        sentence_id=view.sentence_id,
        japanese=view.japanese,
        render_segments=[
            RenderSegmentPayload(
                text=segment.text,
                sentence_item_id=segment.sentence_item_id,
                ruby=[
                    RubyPartPayload(text=part.text, reading=part.reading) for part in segment.ruby
                ],
            )
            for segment in view.render_segments
        ],
        presentation_role=view.presentation_role,
        review_reason=view.review_reason,
        context_stage=view.context_stage,
        translation_revealed=view.translation_revealed,
        tappable_items=[
            TappableItemPayload(
                sentence_item_id=item.sentence_item_id,
                learning_item_id=item.learning_item_id,
            )
            for item in view.tappable_items
        ],
        probe=(
            None
            if view.probe is None
            else ProbePayload(
                probe_id=view.probe.probe_id,
                learning_item_id=view.probe.learning_item_id,
                prompt=PROBE_PROMPT,
                expression=view.probe.expression,
                options=PROBE_OPTIONS,
            )
        ),
    )
