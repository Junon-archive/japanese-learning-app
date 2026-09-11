"""event idempotency (불변식 #10, ADR-008).

핵심은 "행이 하나"가 아니라 **부수효과가 한 번**이다. 행만 중복되지 않고 mastery EMA가
두 번 돌면 재전송은 이미 다른 결과를 냈다. 그래서 아래 테스트는 record_event 단독이
아니라 mastery를 함께 거는 호출부 모양으로 검증한다.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.config import get_config
from app.learning.mastery import OBSERVATION, record_explicit_evidence
from app.models import LearningEvent, LearningItem, StudySession, User, UserMastery
from app.models.enums import EventType, ExplicitSignal
from app.services.events import (
    NC_EVENT_NAMESPACE,
    EventKeyConflictError,
    record_event,
    server_client_event_id,
)
from tests import factories
from tests.clock import MutableClock

# --------------------------------------------------------------------------
# server 발급 key (순수)
# --------------------------------------------------------------------------


def test_the_server_key_is_uuid5_of_the_natural_key_in_the_spec() -> None:
    """자연키 문자열은 05_API_SPEC.md의 표 그대로다. 여기가 바뀌면 과거 event의 key를
    다시 계산할 수 없으므로 문자열을 통째로 고정한다."""
    cases = [
        (
            server_client_event_id(EventType.SESSION_STARTED, study_session_id=7),
            "session_started:7",
        ),
        (
            server_client_event_id(EventType.SESSION_FINISHED, study_session_id=7),
            "session_finished:7",
        ),
        (
            server_client_event_id(EventType.SENTENCE_VIEWED, study_presentation_id=42),
            "sentence_viewed:42",
        ),
        (
            server_client_event_id(EventType.SENTENCE_COMPLETED, study_presentation_id=42),
            "sentence_completed:42",
        ),
        (
            server_client_event_id(
                EventType.MASTERY_PROBE_SHOWN, study_presentation_id=42, learning_item_id=5
            ),
            "mastery_probe_shown:42:5",
        ),
    ]

    for produced, natural_key in cases:
        assert produced == uuid.uuid5(NC_EVENT_NAMESPACE, natural_key)


def test_the_same_natural_key_produces_the_same_uuid_every_time() -> None:
    """재시도 안전성의 전부다. 시각이나 순번이 섞이면 여기가 깨진다."""
    first = server_client_event_id(EventType.SESSION_STARTED, study_session_id=7)
    second = server_client_event_id(EventType.SESSION_STARTED, study_session_id=7)

    assert first == second


def test_different_rows_and_different_event_types_get_different_keys() -> None:
    assert server_client_event_id(
        EventType.SESSION_STARTED, study_session_id=7
    ) != server_client_event_id(EventType.SESSION_STARTED, study_session_id=8)
    assert server_client_event_id(
        EventType.SENTENCE_VIEWED, study_presentation_id=42
    ) != server_client_event_id(EventType.SENTENCE_COMPLETED, study_presentation_id=42)


@pytest.mark.parametrize(
    "event_type",
    [EventType.SESSION_EXTENDED, EventType.ITEM_CLICKED, EventType.MASTERY_PROBE_KNOWN],
)
def test_client_issued_event_types_have_no_server_key(event_type: EventType) -> None:
    """client 발급 event의 key를 서버가 만들어내면 재시도와 두 번째 입력을 구분할 수
    없게 된다(ADR-008)."""
    with pytest.raises(ValueError, match="client-issued"):
        server_client_event_id(event_type, study_session_id=7)


def test_a_missing_identifier_is_refused_instead_of_becoming_the_string_none() -> None:
    """`"session_started:None"`은 여러 세션이 같은 key를 갖게 만든다."""
    with pytest.raises(ValueError, match="study_session_id"):
        server_client_event_id(EventType.SESSION_STARTED)
    with pytest.raises(ValueError, match="learning_item_id"):
        server_client_event_id(EventType.MASTERY_PROBE_SHOWN, study_presentation_id=42)


# --------------------------------------------------------------------------
# 기록 (DB)
# --------------------------------------------------------------------------


def _fixture(db: Session) -> tuple[User, StudySession, LearningItem]:
    user = factories.make_user(db)
    study_session = factories.make_study_session(
        db, user, target_minutes=get_config().learning.default_session_minutes
    )
    return user, study_session, factories.make_learning_item(db)


def _count_events(db: Session, *, user_id: int) -> int:
    return int(
        db.execute(
            sa.select(sa.func.count())
            .select_from(LearningEvent)
            .where(LearningEvent.user_id == user_id)
        ).scalar_one()
    )


def _self_report_known(
    db: Session,
    *,
    user: User,
    study_session: StudySession,
    item: LearningItem,
    client_event_id: uuid.UUID,
    clock: MutableClock,
) -> bool:
    """호출부 규약 그대로의 최소 handler.

    `created`가 False면 **부수효과를 건너뛴다.** 이 한 줄이 재전송 안전성의 전부다.
    """
    _, created = record_event(
        db,
        user_id=user.id,
        study_session_id=study_session.id,
        event_type=EventType.SELF_REPORT_KNOWN,
        client_event_id=client_event_id,
        learning_item_id=item.id,
        now=clock.now(),
    )
    if not created:
        return False
    record_explicit_evidence(
        db,
        user_id=user.id,
        learning_item_id=item.id,
        signal=ExplicitSignal.KNOWN,
        now=clock.now(),
        alpha=get_config().learning.mastery_ema_alpha,
    )
    return True


@pytest.mark.integration
def test_the_first_record_returns_created_and_stores_what_it_was_given(
    db_session: Session, study_clock: MutableClock
) -> None:
    user, study_session, item = _fixture(db_session)

    event, created = record_event(
        db_session,
        user_id=user.id,
        study_session_id=study_session.id,
        event_type=EventType.ITEM_CLICKED,
        client_event_id=uuid.uuid4(),
        learning_item_id=item.id,
        payload={"sentence_item_id": 11},
        now=study_clock.now(),
    )

    assert created is True
    assert event.event_type is EventType.ITEM_CLICKED
    assert event.learning_item_id == item.id
    assert event.payload_json == {"sentence_item_id": 11}
    # created_at은 DB 시계가 아니라 주입된 now다(ADR-007).
    assert event.created_at == study_clock.now()


@pytest.mark.integration
def test_resending_the_same_key_inserts_one_row_and_reports_not_created(
    db_session: Session, study_clock: MutableClock
) -> None:
    user, study_session, item = _fixture(db_session)
    client_event_id = uuid.uuid4()

    first, first_created = record_event(
        db_session,
        user_id=user.id,
        study_session_id=study_session.id,
        event_type=EventType.ITEM_CLICKED,
        client_event_id=client_event_id,
        learning_item_id=item.id,
        now=study_clock.now(),
    )
    study_clock.advance(timedelta(seconds=5))
    second, second_created = record_event(
        db_session,
        user_id=user.id,
        study_session_id=study_session.id,
        event_type=EventType.ITEM_CLICKED,
        client_event_id=client_event_id,
        learning_item_id=item.id,
        now=study_clock.now(),
    )

    assert (first_created, second_created) == (True, False)
    assert second.id == first.id
    assert _count_events(db_session, user_id=user.id) == 1


@pytest.mark.integration
def test_a_resent_event_does_not_apply_the_side_effect_twice(
    db_session: Session, study_clock: MutableClock
) -> None:
    """행 하나만으로는 부족하다. EMA가 두 번 돌면 재전송이 다른 결과를 낸 것이다."""
    user, study_session, item = _fixture(db_session)
    client_event_id = uuid.uuid4()

    applied_first = _self_report_known(
        db_session,
        user=user,
        study_session=study_session,
        item=item,
        client_event_id=client_event_id,
        clock=study_clock,
    )
    applied_second = _self_report_known(
        db_session,
        user=user,
        study_session=study_session,
        item=item,
        client_event_id=client_event_id,
        clock=study_clock,
    )

    assert (applied_first, applied_second) == (True, False)
    mastery = db_session.execute(
        sa.select(UserMastery).where(
            UserMastery.user_id == user.id, UserMastery.learning_item_id == item.id
        )
    ).scalar_one()
    assert mastery.evidence_count == 1
    assert mastery.comprehension_mastery == OBSERVATION[ExplicitSignal.KNOWN]
    assert _count_events(db_session, user_id=user.id) == 1


@pytest.mark.integration
def test_reusing_one_key_for_another_event_type_is_refused(
    db_session: Session, study_clock: MutableClock
) -> None:
    """잘못된 응답을 돌려주느니 거부한다. 기존 event를 그대로 주면 호출부는 자기 요청이
    처리됐다고 읽는다."""
    user, study_session, item = _fixture(db_session)
    client_event_id = uuid.uuid4()
    record_event(
        db_session,
        user_id=user.id,
        study_session_id=study_session.id,
        event_type=EventType.ITEM_CLICKED,
        client_event_id=client_event_id,
        learning_item_id=item.id,
        now=study_clock.now(),
    )

    with pytest.raises(EventKeyConflictError):
        record_event(
            db_session,
            user_id=user.id,
            study_session_id=study_session.id,
            event_type=EventType.EXPLANATION_REVEALED,
            client_event_id=client_event_id,
            learning_item_id=item.id,
            now=study_clock.now(),
        )


@pytest.mark.integration
def test_two_users_may_send_the_same_key(db_session: Session, study_clock: MutableClock) -> None:
    """unique는 `(user_id, client_event_id)`다. client가 만든 UUID가 전역 유일하다고
    가정하지 않는다."""
    user_a, session_a, item = _fixture(db_session)
    user_b, session_b, _ = _fixture(db_session)
    client_event_id = uuid.uuid4()

    for user, study_session in ((user_a, session_a), (user_b, session_b)):
        _, created = record_event(
            db_session,
            user_id=user.id,
            study_session_id=study_session.id,
            event_type=EventType.ITEM_CLICKED,
            client_event_id=client_event_id,
            learning_item_id=item.id,
            now=study_clock.now(),
        )
        assert created is True
