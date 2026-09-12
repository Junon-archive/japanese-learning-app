"""Study session 수명 주기 (05_API_SPEC.md의 `Study Session`, 04_DB_SPEC.md의 `study_sessions`).

HTTP를 모른다. 상태 코드 판정은 `app.api`가 이 모듈의 예외를 보고 한다.

트랜잭션을 소유한다: 진입점 하나가 끝에서 `commit`을 **한 번** 한다(ADR-007).
저장에 실패하면 예외가 그대로 올라간다 --- 실패를 성공처럼 응답하지 않는다
(10_ERROR_HANDLING.md의 `DB Failure`).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.config import AppConfig, SessionConfig
from app.learning.mastery import MASTERY_ALGORITHM_VERSION
from app.learning.selection import materialize_candidates
from app.models.enums import EventType
from app.models.study import StudyPresentation, StudySession
from app.models.user import User
from app.services.events import record_event, server_client_event_id
from app.srs.fsrs_binding import FSRS_PARAMS_VERSION


class StudySessionNotFoundError(Exception):
    """그 id의 session이 없거나 요청 사용자의 것이 아니다 (HTTP 404).

    "남의 session"과 "없는 session"을 구분하지 않는다. 구분하면 id를 훑어 다른
    사용자의 session 존재 여부를 알아낼 수 있다.
    """


class StudySessionClosedError(Exception):
    """이미 끝난 session은 연장할 수 없다 (HTTP 409)."""


@dataclass(frozen=True)
class SessionStart:
    """`POST /api/study/session`의 결과.

    `timed_out_session_id`는 idle timeout으로 이번에 닫힌 직전 session이다. client가
    "이전 세션이 종료됐다"를 표시할 수 있게 남긴다.
    """

    session: StudySession
    resumed: bool
    timed_out_session_id: int | None


def build_policy_snapshot(cfg: AppConfig) -> dict[str, Any]:
    """이 세션에 적용된 학습 정책 값 (`study_sessions.policy_snapshot_json`).

    목적은 replay다 --- 나중에 "그때 alpha와 비율이 얼마였나"를 이 행만 보고 재현할 수
    있어야 한다. 그래서 세션 중 엔진이 실제로 읽는 세 섹션(`learning`, `session`,
    `srs`)을 통째로 담는다. 키를 골라 담지 않는다: 고르면 새 config 키가 추가될 때마다
    snapshot이 조용히 뒤처진다.

    `mastery_algorithm_version`과 `fsrs_params_version`을 **함께 담는다.** 값만으로는
    replay가 되지 않기 때문이다. `mastery_ema_alpha = 0.4`는 그 alpha를 어떤 식에
    넣었는지 말해주지 않고, `fsrs_enable_fuzzing = false`는 어떤 파라미터 집합의
    FSRS였는지 말해주지 않는다. 두 버전 문자열이 계산 코드의 신원이고, 저장된 mastery /
    review_states 행의 같은 이름 컬럼과 대조할 수 있다.

    **secret / DSN / 환경변수를 담지 않는다.** `app.settings`를 import하지 않는 것이
    그 보장이다. `llm`과 `content` 섹션도 제외한다 --- 둘 다 worker가 콘텐츠를 만들
    때 적용하는 값이라 이 세션의 정책이 아니고, `llm`은 운영 한도(비용 ceiling)까지
    들고 있다. `user` 섹션의 timezone은 `users.timezone` 컬럼이 canonical이다.
    """
    return {
        "learning": cfg.learning.model_dump(),
        "session": cfg.session.model_dump(),
        "srs": cfg.srs.model_dump(),
        "mastery_algorithm_version": MASTERY_ALGORITHM_VERSION,
        "fsrs_params_version": FSRS_PARAMS_VERSION,
    }


def touch(session: StudySession, *, now: datetime, cfg: SessionConfig) -> None:
    """active time을 누적하고 마지막 활동 시각을 옮긴다.

    **상태를 바꾸는 모든 경로가 이 함수 하나를 통과한다.** 경로마다 따로 계산하면
    한 곳에서 상한 검사를 빠뜨리는 순간 idle 시간이 학습 시간으로 샌다.

    `active_time_idle_gap_seconds`를 넘는 gap은 **0을 더한다. 잘라서 더하지 않는다**
    --- 상한값을 더하면 자리를 비운 30분이 매번 2분씩 학습 시간으로 들어오고,
    `active_seconds`는 "실제로 학습한 시간"이라는 의미를 잃는다. 그 간격 동안 사용자가
    앱을 보고 있었다는 증거가 없으므로 0이 정답이다.
    """
    gap = (now - session.last_activity_at).total_seconds()
    if 0 <= gap <= cfg.active_time_idle_gap_seconds:
        session.active_seconds += int(gap)
    session.last_activity_at = now


def get_open_session(db: Session, *, user_id: int) -> StudySession | None:
    """아직 끝나지 않은 session. 없으면 None (`GET /api/study/session`).

    idle timeout을 여기서 적용하지 않는다. 조회는 상태를 바꾸지 않는다.
    """
    return db.execute(
        sa.select(StudySession)
        .where(StudySession.user_id == user_id, StudySession.ended_at.is_(None))
        .order_by(StudySession.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def start_or_resume(db: Session, *, user: User, now: datetime, cfg: AppConfig) -> SessionStart:
    """`POST /api/study/session`. idle timeout 이내면 resume, 초과면 새 session이다.

    session을 만들거나 resume한 직후 Candidate Materialization을 **이 사용자 한 명분**
    실행한다(05_API_SPEC.md). seed만 적재된 신규 사용자의 Ready Pool이 이 시점에
    채워진다. LLM을 부르지 않는다 --- 이미 validated인 콘텐츠를 사용자에게 투영하는
    결정론적 DB 연산이다(불변식 #1).
    """
    open_session = get_open_session(db, user_id=user.id)
    timed_out_session_id: int | None = None

    if open_session is not None:
        idle = now - open_session.last_activity_at
        if idle <= timedelta(minutes=cfg.session.study_session_idle_timeout_minutes):
            touch(open_session, now=now, cfg=cfg.session)
            materialize_candidates(db, user=user, now=now, cfg=cfg.learning)
            db.commit()
            return SessionStart(session=open_session, resumed=True, timed_out_session_id=None)
        _expire_idle_session(db, session=open_session, now=now)
        timed_out_session_id = open_session.id

    session = StudySession(
        user_id=user.id,
        started_at=now,
        last_activity_at=now,
        active_seconds=0,
        target_minutes=cfg.learning.default_session_minutes,
        extended_minutes=0,
        policy_snapshot_json=build_policy_snapshot(cfg),
        summary_json={},
    )
    db.add(session)
    db.flush()

    record_event(
        db,
        user_id=user.id,
        study_session_id=session.id,
        event_type=EventType.SESSION_STARTED,
        client_event_id=server_client_event_id(
            EventType.SESSION_STARTED, study_session_id=session.id
        ),
        now=now,
    )
    materialize_candidates(db, user=user, now=now, cfg=cfg.learning)
    db.commit()
    return SessionStart(session=session, resumed=False, timed_out_session_id=timed_out_session_id)


def finish(
    db: Session, *, user_id: int, session_id: int, now: datetime, cfg: AppConfig
) -> StudySession:
    """`POST /api/study/session/{id}/finish`.

    열려 있는 presentation이 있으면 `finalize_presentation()`으로 완료 처리한다
    (05_API_SPEC.md의 `열린 presentation 불변식`). 그래서 세션을 그냥 끝낸 사용자도
    마지막 문장의 meaningful exposure를 얻는다 --- 07_SRS_SPEC.md의 조건 2가
    "`Next`로 이동했거나 **세션을 정상 완료**했다"이기 때문이다. `sentence_completed`의
    key는 presentation id 기반 server 발급이라 동시에 도착한 `/complete`와 중복
    기록되지 않는다.

    이미 끝난 session에 다시 호출하면 같은 session을 그대로 돌려주고 event를 더 만들지
    않는다.
    """
    session = load_owned_session(db, user_id=user_id, session_id=session_id)
    if session.ended_at is not None:
        return session

    touch(session, now=now, cfg=cfg.session)
    _complete_open_presentation(db, session=session, now=now, cfg=cfg)
    session.ended_at = now
    record_event(
        db,
        user_id=user_id,
        study_session_id=session.id,
        event_type=EventType.SESSION_FINISHED,
        client_event_id=server_client_event_id(
            EventType.SESSION_FINISHED, study_session_id=session.id
        ),
        now=now,
    )
    db.commit()
    return session


def extend(
    db: Session,
    *,
    user_id: int,
    session_id: int,
    client_event_id: uuid.UUID,
    now: datetime,
    cfg: AppConfig,
) -> StudySession:
    """`POST /api/study/session/{id}/extend`. `+extra_session_minutes` 연장.

    이 event만 client가 `client_event_id`를 들고 온다. `+5분`은 한 세션에서 여러 번
    정당하게 일어나고 서버에는 재시도와 두 번째 연장을 구분할 자연키가 없기 때문이다
    (ADR-008).

    그래서 **연장은 `created`가 True일 때만 적용한다.** 재전송이 `extended_minutes`를
    한 번 더 올리면 그 UUID는 idempotency key가 아니라 그냥 장식이 된다.
    """
    session = load_owned_session(db, user_id=user_id, session_id=session_id)
    if session.ended_at is not None:
        raise StudySessionClosedError("session is already finished")

    _, created = record_event(
        db,
        user_id=user_id,
        study_session_id=session.id,
        event_type=EventType.SESSION_EXTENDED,
        client_event_id=client_event_id,
        now=now,
    )
    if created:
        session.extended_minutes += cfg.learning.extra_session_minutes
    touch(session, now=now, cfg=cfg.session)
    db.commit()
    return session


def load_owned_session(db: Session, *, user_id: int, session_id: int) -> StudySession:
    """요청 사용자의 session. 아니면 `StudySessionNotFoundError`다.

    presentation service도 이것을 쓴다. 소유권 확인이 두 곳에 복제되면 한쪽에서
    `user_id` 조건을 빠뜨리는 순간 남의 세션에 문장을 붙일 수 있다.
    """
    session = db.execute(
        sa.select(StudySession).where(
            StudySession.id == session_id, StudySession.user_id == user_id
        )
    ).scalar_one_or_none()
    if session is None:
        raise StudySessionNotFoundError(f"study session {session_id} is not available")
    return session


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


def _complete_open_presentation(
    db: Session, *, session: StudySession, now: datetime, cfg: AppConfig
) -> None:
    """`/finish`가 남은 presentation을 `finalize_presentation()`에 넘긴다.

    닫는 규칙(exposure 확정, 무신호 처리, candidate 소비, `sentence_completed`)은
    **전부 그 함수 하나에만** 있다. 여기서 일부를 다시 구현하면 `/complete`로 닫은
    문장과 `/finish`로 닫은 문장이 서로 다른 상태를 남긴다.

    import는 함수 안에서 한다. `app.services.presentation`이 session 소유권 확인과
    `touch()` 때문에 이 모듈을 import하므로, 모듈 최상단에서 맞import하면 순환이
    된다. 방향은 `presentation -> study_session`이고, 이 한 줄만 반대로 간다.
    """
    presentation = _open_presentation(db, study_session_id=session.id)
    if presentation is None:
        return
    from app.services.presentation import finalize_presentation

    finalize_presentation(db, presentation=presentation, now=now, cfg=cfg)


def _expire_idle_session(db: Session, *, session: StudySession, now: datetime) -> None:
    """idle timeout으로 밀려난 session을 닫는다.

    **미완료 presentation을 완료 처리하지 않는다.** `/finish`는 사용자의 명시적
    "끝낸다"이지만 timeout은 부재의 추론이다. 보지 않고 떠난 문장에
    `sentence_completed`를 남기면 없는 신호를 만들어내는 것이고, 그것은 "no-click을
    Known으로 추론하지 않는다"(불변식 #2)와 같은 종류의 실수다. `열린 presentation
    불변식`은 session 하나 안에서의 규칙이므로 닫힌 session에 남은 미완료 행은 그것을
    깨지 않는다. 그 행에 뒤늦게 도착하는 상호작용은 05_API_SPEC.md의
    `세션·presentation 상태 게이트`가 409로 막는다(ADR-014).

    **`ended_at = last_activity_at`은 아직 명세 공백이다.** 05_API_SPEC.md와
    04_DB_SPEC.md는 "초과면 새 session을 만든다"만 말하고 밀려난 session의 `ended_at`을
    정하지 않았다. `now`로 채우면 사용자가 자리를 비운 30분+가 세션 길이에 들어가
    `ended_at - started_at`이 실제보다 길어진다. `active_seconds`가 긴 gap을 이미
    배제하는 것과 같은 이유로 종료 시각도 마지막으로 관측된 활동 시각으로 둔다.
    명세가 정해지면 여기만 고친다.

    `session_finished` event는 남긴다. key가 session id 기반 server 발급이라 나중에
    같은 session에 `/finish`가 도착해도 중복되지 않는다.
    """
    session.ended_at = session.last_activity_at
    record_event(
        db,
        user_id=session.user_id,
        study_session_id=session.id,
        event_type=EventType.SESSION_FINISHED,
        client_event_id=server_client_event_id(
            EventType.SESSION_FINISHED, study_session_id=session.id
        ),
        payload={"reason": "idle_timeout"},
        now=now,
    )
