"""`learning_events` 기록과 event idempotency key (ADR-008).

발급 주체 표의 canonical 위치는 `05_API_SPEC.md`의 `event idempotency key`이고,
컬럼 의미는 `04_DB_SPEC.md`의 `client_event_id 발급 주체`다. 이 모듈은 그 표의
server 발급분을 계산하고, 발급 주체와 무관하게 **모든** event를 한 경로로 기록한다.

트랜잭션을 확정하지 않는다(commit 없음). 요청 하나의 commit은 이 모듈을 부르는
service 진입점이 한 번만 한다(ADR-007의 `트랜잭션 경계`).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.enums import EventType
from app.models.study import LearningEvent

# 한 번 생성해 코드에 고정한 UUID다. **설정값이 아니다.** 바꾸면 과거 event의
# idempotency key를 재계산할 수 없다(ADR-008의 `한계`).
NC_EVENT_NAMESPACE = uuid.UUID("ed0686c8-7f6a-4cde-b0df-729410a1da08")

# server 발급 event와 그 자연키를 이루는 식별자. 05_API_SPEC.md의 표 그대로다.
# **시각도 순번도 들어가지 않는다** --- 들어가면 재시도마다 값이 달라져 idempotency가
# 사라진다. 여기 없는 event_type은 client가 key를 들고 온다.
SERVER_ISSUED_NATURAL_KEY: Mapping[EventType, tuple[str, ...]] = {
    EventType.SESSION_STARTED: ("study_session_id",),
    EventType.SENTENCE_VIEWED: ("study_presentation_id",),
    EventType.SENTENCE_COMPLETED: ("study_presentation_id",),
    EventType.MASTERY_PROBE_SHOWN: ("study_presentation_id", "learning_item_id"),
    EventType.SESSION_FINISHED: ("study_session_id",),
}


class EventKeyConflictError(Exception):
    """같은 `client_event_id`가 다른 `event_type`으로 이미 기록되어 있다 (HTTP 409).

    client가 한 UUID를 여러 endpoint에 재사용한 경우다. 기존 event를 그대로 돌려주면
    호출부는 "내 요청이 처리됐다"고 읽지만 실제로 기록된 것은 다른 행위다. 잘못된
    응답을 돌려주느니 거부한다.
    """


def server_client_event_id(
    event_type: EventType,
    *,
    study_session_id: int | None = None,
    study_presentation_id: int | None = None,
    learning_item_id: int | None = None,
) -> uuid.UUID:
    """server 발급 event의 `client_event_id` = `uuid5(NC_EVENT_NAMESPACE, 자연키)`.

    같은 자연키는 언제 계산해도 같은 UUID다. 그래서 `/session`, `/next`, `/finish`,
    `/complete`를 재시도해도 event가 두 번 기록되지 않고, request body로
    `client_event_id`를 받을 필요도 없다.
    """
    parts = SERVER_ISSUED_NATURAL_KEY.get(event_type)
    if parts is None:
        raise ValueError(
            f"{event_type.value} is client-issued; its client_event_id comes from the request body"
        )
    available = {
        "study_session_id": study_session_id,
        "study_presentation_id": study_presentation_id,
        "learning_item_id": learning_item_id,
    }
    missing = [name for name in parts if available[name] is None]
    if missing:
        raise ValueError(f"{event_type.value} natural key needs {', '.join(missing)}")
    natural_key = ":".join([event_type.value, *(str(available[name]) for name in parts)])
    return uuid.uuid5(NC_EVENT_NAMESPACE, natural_key)


def record_event(
    db: Session,
    *,
    user_id: int,
    study_session_id: int,
    event_type: EventType,
    client_event_id: uuid.UUID,
    presentation_id: int | None = None,
    sentence_id: int | None = None,
    learning_item_id: int | None = None,
    payload: Mapping[str, Any] | None = None,
    now: datetime,
) -> tuple[LearningEvent, bool]:
    """event 1건을 기록하고 `(event, created)`를 돌려준다 (불변식 #10).

    **호출부 규약: `created`가 False면 이 요청의 모든 부수효과를 건너뛴다.**
    mastery EMA, `reps`, `extended_minutes`, exposure 카운터처럼 "한 번 더 적용되면
    값이 달라지는" 것은 전부 `created`가 True인 경로 안에만 둔다. 재전송이 같은
    결과를 내는 근거가 event row의 존재가 아니라 **부수효과를 건너뛰는 이 규약**이다.
    행만 중복되지 않고 EMA가 두 번 돌면 idempotency는 이미 깨진 것이다.

    `(user_id, client_event_id)` unique 위에서 `ON CONFLICT DO NOTHING`으로 판정한다.
    먼저 SELECT해서 있으면 건너뛰는 방식을 쓰지 않는다 --- 재시도/동시 요청이 그 사이에
    끼면 IntegrityError가 나고 호출부의 트랜잭션 전체가 무효가 된다.

    commit하지 않는다. `created_at`은 주입된 `now`다(ADR-007, server_default 없음).
    """
    statement = (
        pg_insert(LearningEvent)
        .values(
            user_id=user_id,
            study_session_id=study_session_id,
            study_presentation_id=presentation_id,
            sentence_id=sentence_id,
            learning_item_id=learning_item_id,
            event_type=event_type,
            payload_json=dict(payload) if payload is not None else {},
            client_event_id=client_event_id,
            created_at=now,
        )
        .on_conflict_do_nothing(index_elements=["user_id", "client_event_id"])
        .returning(LearningEvent.id)
    )
    inserted_id = db.execute(statement).scalar_one_or_none()

    event = db.execute(
        sa.select(LearningEvent).where(
            LearningEvent.user_id == user_id,
            LearningEvent.client_event_id == client_event_id,
        )
    ).scalar_one()

    if inserted_id is not None:
        return event, True
    if event.event_type is not event_type:
        raise EventKeyConflictError(
            f"client_event_id is already recorded as {event.event_type.value}, "
            f"not {event_type.value}"
        )
    return event, False
