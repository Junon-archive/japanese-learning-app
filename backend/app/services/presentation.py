"""Presentation 수명 주기: `/next`와 `/complete` (05_API_SPEC.md).

**`finalize_presentation()`이 meaningful exposure를 기록하는 유일한 자리다.**
click / explanation reveal / translation reveal / self-report / probe 응답 핸들러는
`record_meaningful_exposure()`를 부르지 않는다. 부르는 순간 한 presentation의 같은
item이 여러 번 세어지고, 최소 5회 노출이 조기 충족되어 reinforcement가 사라진다
(불변식 #5, 07_SRS_SPEC.md의 `중복 집계 금지`).

같은 함수 안에 exposure 기록과 무신호 처리가 **나란히** 있다. 둘은 모순이 아니다.

``` text
meaningful exposure   문맥을 실제로 경험한 횟수      (무신호여도 늘어난다)
FSRS evidence         기억에 대한 증거              (무신호면 만들지 않는다)
```

무신호 review는 07_SRS_SPEC.md의 3조건을 그대로 만족하므로 exposure 1회를 만들고,
동시에 FSRS rating을 추론하지 않고 `deferred_until`만 민다(불변식 #2).

**provider를 부르지 않는다**(불변식 #1). Ready Pool이 비면 job을 enqueue하고 200으로
`presentation: null`을 돌려준다. 트랜잭션은 이 모듈의 진입점이 소유하고 끝에서
commit을 한 번 한다(ADR-007).
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.config import AppConfig
from app.jobs.replenishment import enqueue_materialization_gaps, enqueue_replenishment
from app.learning.exposure import count_valid_exposures, record_meaningful_exposure
from app.learning.probe import choose_probe
from app.learning.progression import UNKNOWN_SIGNAL_EVENTS, advance_context_stage, bump_no_signal
from app.learning.selection import MaterializationGaps, select_next
from app.models.content import Sentence, SentenceItem, SentenceItemSpan
from app.models.enums import (
    CandidateStatus,
    ContextStage,
    EventType,
    ExplicitSignal,
    PresentationRole,
    ReviewReason,
    SentenceStatus,
)
from app.models.learning import ReviewState, UserSentenceCandidate, UserSentenceCandidateTarget
from app.models.study import LearningEvent, StudyPresentation
from app.models.user import User
from app.render import (
    RenderSegment,
    SpanRef,
    TappableItem,
    build_render_segments,
    build_tappable_items,
)
from app.services.events import record_event, server_client_event_id
from app.services.study_session import (
    StudySessionClosedError,
    StudySessionNotFoundError,
    load_owned_session,
    touch,
)
from app.srs.review import record_no_signal_review

# 07_SRS_SPEC.md의 `No-signal review`가 canonical이다. **FSRS rating을 만드는 event만**
# 신호다. `item_clicked` / `explanation_revealed` / `translation_revealed` /
# `mastery_probe_shown` / `mastery_probe_skipped`는 전부 무신호이며, 여기에 넣으면
# 클릭 한 번이 `deferred_until`을 막아 같은 due item이 한 세션에서 무한히 다시 뽑힌다.
FSRS_RATING_EVENTS: frozenset[EventType] = frozenset(
    {
        EventType.SELF_REPORT_KNOWN,
        EventType.SELF_REPORT_UNCERTAIN,
        EventType.SELF_REPORT_UNKNOWN,
        EventType.MASTERY_PROBE_KNOWN,
        EventType.MASTERY_PROBE_UNCERTAIN,
        EventType.MASTERY_PROBE_UNKNOWN,
    }
)

# probe 응답 4값 -> event_type. `None`이 skip이다. skip을 `ExplicitSignal`로 표현할 수
# 없게 두는 것이 핵심이다(02_LEARNING_POLICY.md의 `Skip`).
#
# 응답을 **쓰는** 쪽은 `app/services/interactions.py`지만 선언은 여기 있다. 이 모듈이
# "이미 답한 probe를 다시 싣지 않는다"를 판정하려면 같은 목록이 필요한데,
# `interactions`가 이 모듈을 import하므로 거기서 가져올 수 없다. 양쪽에 따로 적으면
# 어긋날 수 있으니 **한 곳에만** 둔다.
PROBE_RESPONSE_EVENTS: Mapping[ExplicitSignal | None, EventType] = {
    ExplicitSignal.KNOWN: EventType.MASTERY_PROBE_KNOWN,
    ExplicitSignal.UNCERTAIN: EventType.MASTERY_PROBE_UNCERTAIN,
    ExplicitSignal.UNKNOWN: EventType.MASTERY_PROBE_UNKNOWN,
    None: EventType.MASTERY_PROBE_SKIPPED,
}

# probe 하나에 대한 "답했다"의 전부. `mastery_probe_skipped`가 들어 있다 --- skip은
# FSRS rating을 만들지 않지만(위 `FSRS_RATING_EVENTS`에 없다) 응답이기는 하므로 같은
# probe를 다시 싣지 않는다.
PROBE_ANSWER_EVENTS: frozenset[EventType] = frozenset(PROBE_RESPONSE_EVENTS.values())


class PresentationNotFoundError(Exception):
    """그 id의 presentation이 없거나 요청 사용자의 것이 아니다 (HTTP 404).

    "남의 presentation"과 "없는 presentation"을 구분하지 않는다. 403으로 갈라주면
    id를 훑어 다른 사용자의 presentation 존재 여부를 알아내는 oracle이 된다.
    """


class PresentationClosedError(Exception):
    """이미 완료된 presentation에 상호작용이 도착했다 (HTTP 409, ADR-014).

    presentation을 닫는 트랜잭션에서 exposure 확정과 무신호 처리가 끝난다. 그 뒤에
    붙는 explicit evidence는 같은 노출을 두 번, 서로 다르게 평가한다. session이
    열려 있어도 마찬가지라서(`/complete` 직후 같은 pid) session 상태와 별개로 본다.
    """


@dataclass(frozen=True)
class ProbeView:
    probe_id: int
    learning_item_id: int
    expression: str


@dataclass(frozen=True)
class PresentationView:
    """`/next`가 화면에 필요한 값만 모아 돌려주는 것. 번역은 들어 있지 않다."""

    presentation_id: int
    sentence_id: int
    japanese: str
    render_segments: list[RenderSegment]
    tappable_items: list[TappableItem]
    presentation_role: PresentationRole
    review_reason: ReviewReason | None
    context_stage: ContextStage
    translation_revealed: bool
    probe: ProbeView | None


# --------------------------------------------------------------------------
# /next
# --------------------------------------------------------------------------


def next_presentation(
    db: Session, *, user: User, session_id: int, now: datetime, cfg: AppConfig
) -> PresentationView | None:
    """`POST /api/study/session/{id}/next`. 보여줄 것이 없으면 None이다.

    `열린 presentation 불변식`: 그 세션에 완료되지 않은 presentation이 있으면 **새로
    만들지 않고 그것을 그대로 돌려준다.** 재시도나 더블탭으로 presentation이 중복
    생성되지 않고 candidate가 헛되이 소비되지 않는다. 다음 문장으로 넘어가려면
    client가 먼저 `/complete`를 호출한다 --- `/next`가 직전 문장을 암묵 완료시키면
    그 재시도가 다시 새 presentation을 만들어 불변식이 깨진다.

    None은 Pool Fallback 3단계(replenishment enqueue)까지 끝났다는 뜻이다. 그때도
    **provider를 부르지 않는다**(불변식 #1). 호출부는 이것을 200 + `presentation:
    null`로 내보낸다(10_ERROR_HANDLING.md의 `Empty Pool`).

    session 행을 `FOR UPDATE`로 잠그고 시작한다. 그 불변식의 판정이
    `SELECT ... LIMIT 1`이므로 잠그지 않으면 동시 `/next` 2건이 둘 다 "열린
    presentation 없음"을 읽고 각자 만든다. DB의 `uq_study_presentations_open`이 그
    INSERT를 거부하기는 하지만, 거부는 경합에서 진 요청에게 500이다. 이 잠금 덕분에
    두 번째 요청은 첫 번째가 만든 presentation을 보고 **같은 문장**을 받는다.
    """
    session = load_owned_session(db, user_id=user.id, session_id=session_id, for_update=True)
    if session.ended_at is not None:
        # 05_API_SPEC.md의 `세션·presentation 상태 게이트`. 끝난 세션에 presentation을
        # 더 만들면 그 세션의 `ended_at` 이후에 시작된 문장이 생긴다.
        raise StudySessionClosedError("session is already finished")
    touch(session, now=now, cfg=cfg.session)

    open_presentation = _open_presentation(db, study_session_id=session.id)
    if open_presentation is not None:
        view = _build_view(db, presentation=open_presentation, now=now, cfg=cfg, fresh=False)
        db.commit()
        return view

    # Pool Fallback 0단계의 materialization이 만들지 못한 candidate의 사유를 받아
    # job으로 바꾼다. **selection을 찾았더라도** enqueue한다 --- 트리거는 "검사한 문장에
    # explanation이 없었다" / "그 stage의 문장이 없었다"는 사실 자체이고, 다른 category가
    # 이번에 보여줄 문장을 찾은 것과 무관하다(09_BACKGROUND_JOBS.md).
    gaps = MaterializationGaps()
    selection = select_next(
        db, user=user, study_session_id=session.id, now=now, cfg=cfg.learning, gaps=gaps
    )
    enqueue_materialization_gaps(db, user_id=user.id, gaps=gaps, now=now, cfg=cfg)
    if selection is None:
        _request_replenishment(db, user_id=user.id, now=now, cfg=cfg)
        db.commit()
        return None

    presentation = StudyPresentation(
        study_session_id=session.id,
        user_id=user.id,
        candidate_id=selection.candidate_id,
        sentence_id=selection.sentence_id,
        presentation_role=selection.presentation_role,
        review_reason=selection.review_reason,
        context_stage=selection.context_stage,
        shown_at=now,
    )
    db.add(presentation)
    db.flush()

    # candidate를 `shown`으로 옮긴다. 남겨두면 다음 세션의 select_next가 같은
    # ready candidate를 다시 집어간다.
    candidate = db.get(UserSentenceCandidate, selection.candidate_id)
    if candidate is not None:
        candidate.status = CandidateStatus.SHOWN
        candidate.updated_at = now

    record_event(
        db,
        user_id=user.id,
        study_session_id=session.id,
        event_type=EventType.SENTENCE_VIEWED,
        client_event_id=server_client_event_id(
            EventType.SENTENCE_VIEWED, study_presentation_id=presentation.id
        ),
        presentation_id=presentation.id,
        sentence_id=presentation.sentence_id,
        now=now,
    )

    view = _build_view(db, presentation=presentation, now=now, cfg=cfg, fresh=True)
    db.commit()
    return view


def _request_replenishment(db: Session, *, user_id: int, now: datetime, cfg: AppConfig) -> None:
    """Pool Fallback 3단계. `select_next`가 None이면 **모든** role의 pool이 비어 있다.

    그래서 role 하나만 enqueue하지 않는다. job의 idempotency key가 `(user, role, UTC
    날짜)`라서(`app/jobs/replenishment.py`) role을 하나로 좁히면 그날 내내 나머지
    pool에 대한 생성 요청이 만들어지지 않는다. 억제 창 덕분에 이 호출이 하루에 role당
    job 1개를 넘기지 못한다.
    """
    for role in PresentationRole:
        enqueue_replenishment(db, user_id=user_id, role=role, now=now, cfg=cfg)


# --------------------------------------------------------------------------
# /complete
# --------------------------------------------------------------------------


def complete_presentation(
    db: Session, *, user_id: int, presentation_id: int, now: datetime, cfg: AppConfig
) -> StudyPresentation:
    """`POST /api/study/presentations/{pid}/complete`. client가 `Next`에서 명시 호출한다.

    `begin_interaction()`을 쓰지 않는다. 상태 게이트가 다른 5종과 다르기 때문이다
    (05_API_SPEC.md의 `세션·presentation 상태 게이트`, ADR-014).

    -   **이미 완료된 presentation이면 session 상태와 무관하게 그대로 돌려준다.**
        성공한 `/complete`의 네트워크 재시도가 그 사이 도착한 `/finish` 때문에
        실패로 보이면 client는 완료된 문장을 완료되지 않은 것으로 취급한다.
        `touch()`도 commit도 하지 않는다 --- 끝난 요청의 재시도가 세션 시계를 밀면
        안 되고, 바꿀 것이 없으므로 확정할 것도 없다.
    -   열린 presentation인데 session이 닫혔으면 409다. 그 문장을 닫는 것은 이미
        `/finish`가 `finalize_presentation()`으로 했다.
    """
    presentation = load_owned_presentation(db, user_id=user_id, presentation_id=presentation_id)
    if presentation.completed_at is not None:
        return presentation

    session = load_owned_session(db, user_id=user_id, session_id=presentation.study_session_id)
    if session.ended_at is not None:
        raise StudySessionClosedError("session is already finished")

    touch(session, now=now, cfg=cfg.session)
    finalize_presentation(db, presentation=presentation, now=now, cfg=cfg)
    db.commit()
    return presentation


def begin_interaction(
    db: Session, *, user_id: int, presentation_id: int, now: datetime, cfg: AppConfig
) -> StudyPresentation:
    """presentation 상호작용 endpoint의 공통 진입: 소유권 확인 + 세션 활동 시각 갱신.

    **`touch()`를 여기 한 곳에 모은다.** endpoint마다 따로 부르면 하나를 빠뜨리는
    순간 그 endpoint만 `last_activity_at`을 멈추고, 두 가지가 조용히 깨진다.

    ``` text
    idle timeout    한 문장을 오래 탐구하는 동안 last_activity_at이 멈춰 있으면
                    실제로 학습 중인 세션이 study_session_idle_timeout_minutes를
                    넘겨 만료된다. timeout은 "사용자가 떠났다"는 뜻이지
                    "Next를 안 눌렀다"가 아니다.
    active_seconds  상호작용 시간이 /next 시점의 긴 gap 하나로 뭉쳐지고, 그 gap이
                    active_time_idle_gap_seconds를 넘으면 0이 더해진다. 설명을
                    3분 읽으면 그 3분이 통째로 학습 시간에서 사라진다.
    ```

    session을 한 번 더 조회한다. presentation row는 `study_session_id`만 들고 있고
    `touch()`는 `last_activity_at` / `active_seconds`를 써야 하므로 행 자체가
    필요하다. `load_owned_session()`을 쓰는 이유는 소유권 확인을 복제하지 않기
    위해서다 --- presentation이 이미 이 사용자 것임을 확인했으므로 결과는 같지만,
    조건을 두 번 적지 않는 쪽이 한쪽에서 `user_id`를 빠뜨릴 여지를 없앤다.

    **상태 게이트도 여기 한 곳에 모은다**(05_API_SPEC.md의 `세션·presentation 상태
    게이트`, ADR-014). 이 함수를 쓰는 5종(click / explanation-revealed /
    translation reveal / self-report / probe-response)은 닫힌 session이나 완료된
    presentation에서 전부 409다. 판정 순서는 소유권(404) -> 상태(409)이고,
    **게이트가 `touch()`보다 앞선다** --- 뒤에 두면 거부당한 요청이 끝난 세션의
    `last_activity_at`과 `active_seconds`를 먼저 밀어 놓는다.

    `/complete`와 `/flag`는 게이트가 달라서 이 함수를 쓰지 않는다.
    """
    presentation = load_owned_presentation(db, user_id=user_id, presentation_id=presentation_id)
    session = load_owned_session(db, user_id=user_id, session_id=presentation.study_session_id)
    if session.ended_at is not None:
        raise StudySessionClosedError("session is already finished")
    if presentation.completed_at is not None:
        raise PresentationClosedError("presentation is already completed")
    touch(session, now=now, cfg=cfg.session)
    return presentation


def finalize_presentation(
    db: Session, *, presentation: StudyPresentation, now: datetime, cfg: AppConfig
) -> None:
    """presentation을 닫는 **단일 진입점**. `/complete`와 `/finish`가 둘 다 여기로 온다.

    commit하지 않는다. 트랜잭션은 부른 진입점이 닫는다(ADR-007).

    순서와 이유:

    1.  이미 닫혔으면 아무것도 하지 않는다. 재호출이 exposure를 한 번 더 만들거나
        `deferred_until`을 다시 밀면 idempotency가 이름뿐이 된다.
    2.  quarantined content면 **exposure를 만들지 않는다.** 07_SRS_SPEC.md의
        meaningful exposure 조건 3이다. flag된 문장을 본 것은 학습 경험이 아니다.
    3.  exposure를 기록하고 `review_states.meaningful_exposure_count` 캐시를
        **다시 계산해서 대입한다.** `+= 1`로 올리지 않는다 --- flag/quarantine이
        `invalidated_at`을 설정한 뒤에는 증가분과 실제 유효 건수가 갈린다.
    4.  exposure를 기록한 target의 `context_stage`를 한 칸 옮긴다. 노출을 세는
        자리와 ladder를 움직이는 자리가 같아야 두 값이 어긋나지 않고, 1의 guard가
        그대로 전이의 idempotency가 된다(07_SRS_SPEC.md의 `전이 규칙`, ADR-012).
    5.  무신호 target을 처리한다. exposure(3)와 나란히 있는 것이 의도다.
    6.  candidate를 `consumed`로 옮긴다.
    """
    if presentation.completed_at is not None:
        return

    target_item_ids = _target_item_ids(db, candidate_id=presentation.candidate_id)

    if not _is_quarantined(db, presentation=presentation):
        record_meaningful_exposure(
            db, presentation=presentation, target_item_ids=target_item_ids, now=now
        )
        _refresh_exposure_cache(db, user_id=presentation.user_id, item_ids=target_item_ids)
        _advance_context_stages(
            db, presentation=presentation, target_item_ids=target_item_ids, now=now
        )
        _handle_no_signal_targets(
            db, presentation=presentation, target_item_ids=target_item_ids, now=now, cfg=cfg
        )
        _consume_candidate(db, candidate_id=presentation.candidate_id, now=now)

    presentation.completed_at = now
    record_event(
        db,
        user_id=presentation.user_id,
        study_session_id=presentation.study_session_id,
        event_type=EventType.SENTENCE_COMPLETED,
        client_event_id=server_client_event_id(
            EventType.SENTENCE_COMPLETED, study_presentation_id=presentation.id
        ),
        presentation_id=presentation.id,
        sentence_id=presentation.sentence_id,
        now=now,
    )
    db.flush()


def _handle_no_signal_targets(
    db: Session,
    *,
    presentation: StudyPresentation,
    target_item_ids: Sequence[int],
    now: datetime,
    cfg: AppConfig,
) -> None:
    """FSRS rating을 만드는 event가 하나도 없는 target을 무신호로 처리한다.

    판정 단위는 presentation 전체가 아니라 **(presentation, target item) 쌍**이다.
    target이 둘인데 하나만 self-report를 받았다면 나머지 하나는 무신호다
    (07_SRS_SPEC.md).

    무신호일 때 하는 일은 정확히 둘이고, **rating은 추론하지 않는다.**

    ``` text
    review              deferred_until = now + passive_review_deferral_hours
    review / new / exploration
                        passive_no_signal_count += 1
    ```

    `deferred_until`은 `review`에만 적용한다 --- `new` / `exploration`에는
    `review_states` 행이 아직 없어 defer할 스케줄 자체가 없다. 행이 없으면
    `record_no_signal_review()`가 None을 돌려주고 **행을 만들지 않는다.**
    반면 `passive_no_signal_count`는 모든 role에서 올린다. 그것이
    `passive_exposures_before_probe`가 세는 "스쳐 지나가기만 한 횟수"이고,
    07_SRS_SPEC.md는 스케줄이 없는 경우에 대해 "이때는
    `passive_no_signal_count`만 올린다"고 적고 있다.
    """
    if not target_item_ids:
        return
    signalled = _items_with_events(
        db,
        user_id=presentation.user_id,
        presentation_id=presentation.id,
        item_ids=target_item_ids,
        event_types=FSRS_RATING_EVENTS,
    )
    for item_id in target_item_ids:
        if item_id in signalled:
            continue
        if presentation.presentation_role is PresentationRole.REVIEW:
            record_no_signal_review(
                db,
                user_id=presentation.user_id,
                learning_item_id=item_id,
                now=now,
                config=cfg,
            )
        bump_no_signal(db, user_id=presentation.user_id, learning_item_id=item_id, now=now)


def _advance_context_stages(
    db: Session,
    *,
    presentation: StudyPresentation,
    target_item_ids: Sequence[int],
    now: datetime,
) -> None:
    """방금 exposure를 만든 target마다 context ladder를 옮긴다 (07_SRS_SPEC.md).

    대상은 **그 presentation의 candidate target**뿐이다. 화면에 보인 tappable item
    전체가 아니다 --- 다른 item을 위해 고른 문맥의 stage가 이 item의 ladder를
    움직이면 progression이 자기 노출 이력과 무관해진다(ADR-013).

    내리는 것은 그 (presentation, item)의 explicit `몰랐음` 하나뿐이다. 무신호와
    `애매함`과 `알고 있었음`은 모두 올린다. 표의 단위가 signal이 아니라 exposure
    수이기 때문이다.

    quarantined content에서는 호출되지 않는다. exposure를 만들지 않는 presentation은
    ladder도 움직이지 않는다.
    """
    if not target_item_ids:
        return
    failed = _items_with_events(
        db,
        user_id=presentation.user_id,
        presentation_id=presentation.id,
        item_ids=target_item_ids,
        event_types=UNKNOWN_SIGNAL_EVENTS,
    )
    for item_id in target_item_ids:
        advance_context_stage(
            db,
            user_id=presentation.user_id,
            learning_item_id=item_id,
            shown_stage=presentation.context_stage,
            failed=item_id in failed,
            now=now,
        )


def _items_with_events(
    db: Session,
    *,
    user_id: int,
    presentation_id: int,
    item_ids: Sequence[int],
    event_types: Collection[EventType],
) -> set[int]:
    """이 presentation에서 주어진 event를 받은 item 집합.

    무신호 판정(`FSRS_RATING_EVENTS`)과 실패 판정(`UNKNOWN_SIGNAL_EVENTS`)이 같은
    질의를 쓴다. 둘 다 판정 단위가 **(presentation, item) 쌍**이다.
    """
    rows = db.execute(
        sa.select(LearningEvent.learning_item_id)
        .where(
            LearningEvent.user_id == user_id,
            LearningEvent.study_presentation_id == presentation_id,
            LearningEvent.learning_item_id.in_(item_ids),
            LearningEvent.event_type.in_(event_types),
        )
        .distinct()
    ).scalars()
    return {row for row in rows if row is not None}


def _refresh_exposure_cache(db: Session, *, user_id: int, item_ids: Sequence[int]) -> None:
    """`review_states.meaningful_exposure_count`는 `item_exposures`의 캐시다.

    행이 없으면 **만들지 않는다.** FSRS 스케줄이 없는 item에 스케줄 행을 만들어
    주는 것은 `app/srs/`의 일이고, 캐시를 채우려고 스케줄을 발명하면 아직 배우지
    않은 item이 due 목록에 들어간다.
    """
    for item_id in item_ids:
        state = db.execute(
            sa.select(ReviewState).where(
                ReviewState.user_id == user_id,
                ReviewState.learning_item_id == item_id,
            )
        ).scalar_one_or_none()
        if state is None:
            continue
        state.meaningful_exposure_count = count_valid_exposures(
            db, user_id=user_id, learning_item_id=item_id
        )


def _consume_candidate(db: Session, *, candidate_id: int, now: datetime) -> None:
    candidate = db.get(UserSentenceCandidate, candidate_id)
    if candidate is None or candidate.status is CandidateStatus.QUARANTINED:
        return
    candidate.status = CandidateStatus.CONSUMED
    candidate.updated_at = now


def _is_quarantined(db: Session, *, presentation: StudyPresentation) -> bool:
    sentence_status = db.execute(
        sa.select(Sentence.status).where(Sentence.id == presentation.sentence_id)
    ).scalar_one()
    if sentence_status is SentenceStatus.QUARANTINED:
        return True
    candidate_status = db.execute(
        sa.select(UserSentenceCandidate.status).where(
            UserSentenceCandidate.id == presentation.candidate_id
        )
    ).scalar_one_or_none()
    return candidate_status is CandidateStatus.QUARANTINED


# --------------------------------------------------------------------------
# 조회 / 조립
# --------------------------------------------------------------------------


def load_owned_presentation(
    db: Session, *, user_id: int, presentation_id: int
) -> StudyPresentation:
    """요청 사용자의 presentation. 아니면 `PresentationNotFoundError`다."""
    presentation = db.execute(
        sa.select(StudyPresentation).where(
            StudyPresentation.id == presentation_id,
            StudyPresentation.user_id == user_id,
        )
    ).scalar_one_or_none()
    if presentation is None:
        raise PresentationNotFoundError(f"presentation {presentation_id} is not available")
    return presentation


def _open_presentation(db: Session, *, study_session_id: int) -> StudyPresentation | None:
    return db.execute(
        sa.select(StudyPresentation)
        .where(
            StudyPresentation.study_session_id == study_session_id,
            StudyPresentation.completed_at.is_(None),
        )
        .order_by(StudyPresentation.id)
        .limit(1)
    ).scalar_one_or_none()


def _target_item_ids(db: Session, *, candidate_id: int) -> list[int]:
    return list(
        db.execute(
            sa.select(UserSentenceCandidateTarget.learning_item_id)
            .where(UserSentenceCandidateTarget.candidate_id == candidate_id)
            .order_by(UserSentenceCandidateTarget.learning_item_id)
        )
        .scalars()
        .all()
    )


def _spans(db: Session, *, sentence_id: int) -> list[SpanRef]:
    rows = db.execute(
        sa.select(
            SentenceItem.id,
            SentenceItem.learning_item_id,
            SentenceItem.is_tappable,
            SentenceItemSpan.start_codepoint,
            SentenceItemSpan.end_codepoint,
        )
        .join(SentenceItemSpan, SentenceItemSpan.sentence_item_id == SentenceItem.id)
        .where(SentenceItem.sentence_id == sentence_id)
        .order_by(SentenceItemSpan.start_codepoint, SentenceItemSpan.span_order)
    ).all()
    return [
        SpanRef(
            sentence_item_id=row[0],
            learning_item_id=row[1],
            is_tappable=row[2],
            start_codepoint=row[3],
            end_codepoint=row[4],
        )
        for row in rows
    ]


def translation_revealed(db: Session, *, user_id: int, presentation_id: int) -> bool:
    return (
        db.execute(
            sa.select(LearningEvent.id)
            .where(
                LearningEvent.user_id == user_id,
                LearningEvent.study_presentation_id == presentation_id,
                LearningEvent.event_type == EventType.TRANSLATION_REVEALED,
            )
            .limit(1)
        ).scalar_one_or_none()
        is not None
    )


def _build_view(
    db: Session,
    *,
    presentation: StudyPresentation,
    now: datetime,
    cfg: AppConfig,
    fresh: bool,
) -> PresentationView:
    sentence = db.get(Sentence, presentation.sentence_id)
    if sentence is None:  # pragma: no cover - FK가 막는다
        raise PresentationNotFoundError(f"sentence {presentation.sentence_id} is missing")
    spans = _spans(db, sentence_id=sentence.id)
    target_item_ids = _target_item_ids(db, candidate_id=presentation.candidate_id)
    return PresentationView(
        presentation_id=presentation.id,
        sentence_id=sentence.id,
        japanese=sentence.japanese,
        render_segments=build_render_segments(sentence.japanese, spans),
        tappable_items=build_tappable_items(spans),
        presentation_role=presentation.presentation_role,
        review_reason=presentation.review_reason,
        context_stage=presentation.context_stage,
        translation_revealed=translation_revealed(
            db, user_id=presentation.user_id, presentation_id=presentation.id
        ),
        probe=_probe_view(
            db,
            presentation=presentation,
            target_item_ids=target_item_ids,
            now=now,
            cfg=cfg,
            fresh=fresh,
        ),
    )


def _probe_view(
    db: Session,
    *,
    presentation: StudyPresentation,
    target_item_ids: Sequence[int],
    now: datetime,
    cfg: AppConfig,
    fresh: bool,
) -> ProbeView | None:
    """이미 낸 probe가 있으면 그것을 그대로 다시 싣는다.

    `choose_probe()`는 **idempotent하지 않다**(그 모듈 docstring). probe를 하나 실으면
    그 사실이 세션 event에 남아 다음 호출의 pacing과 제외 집합이 달라진다. 그래서
    `열린 presentation 불변식`으로 같은 presentation을 다시 돌려주는 경로에서는
    `choose_probe()`를 **다시 부르지 않고** ADR-009의 uuid5 자연키로 기존
    `mastery_probe_shown` event를 조회한다. 그러면 `probe_id`가 같은 값으로 유지되어
    client가 응답을 재전송해도 대상이 흔들리지 않는다.

    **이미 답한 probe는 다시 싣지 않는다.** probe 하나에 응답은 최대 1건이므로
    (05_API_SPEC.md) 다시 실어봐야 client는 답할 수 없는 질문을 렌더한다. skip도
    응답이다 --- 건너뛴 probe가 reload마다 되살아나면 `Skip`이 의미를 잃는다.
    """
    existing = _existing_probe_event(
        db,
        user_id=presentation.user_id,
        presentation_id=presentation.id,
        target_item_ids=target_item_ids,
    )
    if existing is not None:
        if _probe_is_answered(db, presentation=presentation, event=existing):
            return None
        return _probe_view_of(db, presentation=presentation, event=existing)
    if not fresh:
        return None

    target = choose_probe(
        db,
        user_id=presentation.user_id,
        study_session_id=presentation.study_session_id,
        presentation_id=presentation.id,
        target_item_ids=list(target_item_ids),
        now=now,
        config=cfg,
    )
    if target is None:
        return None

    event, _created = record_event(
        db,
        user_id=presentation.user_id,
        study_session_id=presentation.study_session_id,
        event_type=EventType.MASTERY_PROBE_SHOWN,
        client_event_id=server_client_event_id(
            EventType.MASTERY_PROBE_SHOWN,
            study_presentation_id=presentation.id,
            learning_item_id=target.learning_item_id,
        ),
        presentation_id=presentation.id,
        sentence_id=presentation.sentence_id,
        learning_item_id=target.learning_item_id,
        now=now,
    )
    return _probe_view_of(db, presentation=presentation, event=event)


def _probe_is_answered(
    db: Session, *, presentation: StudyPresentation, event: LearningEvent
) -> bool:
    """이 probe에 응답 event가 이미 있는가. `(user_id, ...)` 조건은 event와 같은 행이다."""
    if event.learning_item_id is None:  # pragma: no cover - 기록 시 항상 채운다
        return False
    return (
        db.execute(
            sa.select(LearningEvent.id)
            .where(
                LearningEvent.user_id == presentation.user_id,
                LearningEvent.study_presentation_id == presentation.id,
                LearningEvent.learning_item_id == event.learning_item_id,
                LearningEvent.event_type.in_(PROBE_ANSWER_EVENTS),
            )
            .limit(1)
        ).scalar_one_or_none()
        is not None
    )


def _existing_probe_event(
    db: Session, *, user_id: int, presentation_id: int, target_item_ids: Sequence[int]
) -> LearningEvent | None:
    """ADR-009의 자연키로 조회한다. `(user_id, client_event_id)` unique를 그대로 탄다."""
    if not target_item_ids:
        return None
    keys = [
        server_client_event_id(
            EventType.MASTERY_PROBE_SHOWN,
            study_presentation_id=presentation_id,
            learning_item_id=item_id,
        )
        for item_id in target_item_ids
    ]
    return db.execute(
        sa.select(LearningEvent)
        .where(
            LearningEvent.user_id == user_id,
            LearningEvent.client_event_id.in_(keys),
            LearningEvent.event_type == EventType.MASTERY_PROBE_SHOWN,
        )
        .order_by(LearningEvent.id)
        .limit(1)
    ).scalar_one_or_none()


def _probe_view_of(
    db: Session, *, presentation: StudyPresentation, event: LearningEvent
) -> ProbeView | None:
    item_id = event.learning_item_id
    if item_id is None:  # pragma: no cover - 기록 시 항상 채운다
        return None
    return ProbeView(
        probe_id=event.id,
        learning_item_id=item_id,
        expression=_expression_of(db, sentence_id=presentation.sentence_id, item_id=item_id),
    )


def _expression_of(db: Session, *, sentence_id: int, item_id: int) -> str:
    """화면에 보인 표기(`surface_form`)를 묻는다. lemma를 물으면 본 적 없는 형태가 된다."""
    surface = db.execute(
        sa.select(SentenceItem.surface_form)
        .where(
            SentenceItem.sentence_id == sentence_id,
            SentenceItem.learning_item_id == item_id,
        )
        .order_by(SentenceItem.id)
        .limit(1)
    ).scalar_one_or_none()
    return surface or ""


__all__ = [
    "FSRS_RATING_EVENTS",
    "PROBE_ANSWER_EVENTS",
    "PROBE_RESPONSE_EVENTS",
    "PresentationClosedError",
    "PresentationNotFoundError",
    "PresentationView",
    "ProbeView",
    "StudySessionClosedError",
    "StudySessionNotFoundError",
    "begin_interaction",
    "complete_presentation",
    "finalize_presentation",
    "load_owned_presentation",
    "next_presentation",
    "translation_revealed",
]
