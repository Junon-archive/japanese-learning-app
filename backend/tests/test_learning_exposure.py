"""Meaningful exposure 기록 (불변식 #5).

DB unique가 최종 방어선이고 애플리케이션이 거기에 기댄다. 그래서 "두 번 불러도
예외가 새어나오지 않고 행은 1개"가 이 파일의 중심 단정이다.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.learning.exposure import (
    count_valid_exposures,
    exposed_recently,
    invalidate_presentation_exposures,
    record_meaningful_exposure,
)
from app.models import ItemExposure, LearningItem, StudyPresentation, User
from app.models.enums import CandidateStatus, ExposureModality
from tests import factories
from tests.clock import MutableClock

pytestmark = pytest.mark.integration

SESSION_MINUTES_FILLER = 1


def _presentation(db_session: Session, user: User) -> StudyPresentation:
    sentence = factories.make_sentence(db_session)
    study_session = factories.make_study_session(
        db_session, user, target_minutes=SESSION_MINUTES_FILLER
    )
    candidate = factories.make_candidate(db_session, user, sentence, status=CandidateStatus.READY)
    return factories.make_presentation(db_session, user, study_session, candidate, sentence)


def _stored(db_session: Session, user: User, item: LearningItem) -> list[ItemExposure]:
    return list(
        db_session.execute(
            sa.select(ItemExposure).where(
                ItemExposure.user_id == user.id,
                ItemExposure.learning_item_id == item.id,
            )
        )
        .scalars()
        .all()
    )


def test_recording_the_same_item_twice_in_one_presentation_stores_one_row(
    db_session: Session,
) -> None:
    """click / explanation reveal / self-report가 각각 exposure가 되면 최소 5회가
    조기 충족되고 reinforcement가 사라진다. 두 번째 호출은 조용히 무시된다."""
    clock = MutableClock()
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    presentation = _presentation(db_session, user)

    first = record_meaningful_exposure(
        db_session, presentation=presentation, target_item_ids=[item.id], now=clock.now()
    )
    # 예외가 새어나오면 호출부의 트랜잭션이 통째로 무효가 된다.
    second = record_meaningful_exposure(
        db_session,
        presentation=presentation,
        target_item_ids=[item.id],
        now=clock.advance(timedelta(seconds=30)),
    )

    assert (first, second) == (1, 0)
    assert len(_stored(db_session, user, item)) == 1
    assert count_valid_exposures(db_session, user_id=user.id, learning_item_id=item.id) == 1


def test_duplicate_ids_inside_one_call_store_one_row(db_session: Session) -> None:
    clock = MutableClock()
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    presentation = _presentation(db_session, user)

    inserted = record_meaningful_exposure(
        db_session,
        presentation=presentation,
        target_item_ids=[item.id, item.id],
        now=clock.now(),
    )

    assert inserted == 1
    assert count_valid_exposures(db_session, user_id=user.id, learning_item_id=item.id) == 1


def test_the_same_item_in_another_presentation_is_a_second_exposure(db_session: Session) -> None:
    clock = MutableClock()
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)

    record_meaningful_exposure(
        db_session,
        presentation=_presentation(db_session, user),
        target_item_ids=[item.id],
        now=clock.now(),
    )
    record_meaningful_exposure(
        db_session,
        presentation=_presentation(db_session, user),
        target_item_ids=[item.id],
        now=clock.advance(timedelta(days=1)),
    )

    assert count_valid_exposures(db_session, user_id=user.id, learning_item_id=item.id) == 2


def test_the_row_carries_the_injected_clock_and_the_presentation_context(
    db_session: Session,
) -> None:
    """`created_at`이 DB 시계면 `exploration_recent_days` 판정과 시계가 갈린다(ADR-007)."""
    clock = MutableClock()
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    presentation = _presentation(db_session, user)

    record_meaningful_exposure(
        db_session, presentation=presentation, target_item_ids=[item.id], now=clock.now()
    )

    (exposure,) = _stored(db_session, user, item)
    assert exposure.created_at == clock.now()
    assert exposure.study_presentation_id == presentation.id
    assert exposure.sentence_id == presentation.sentence_id
    assert exposure.context_stage == presentation.context_stage
    assert exposure.modality == ExposureModality.READING
    assert exposure.invalidated_at is None


def test_no_targets_stores_nothing(db_session: Session) -> None:
    clock = MutableClock()
    user = factories.make_user(db_session)
    presentation = _presentation(db_session, user)

    assert (
        record_meaningful_exposure(
            db_session, presentation=presentation, target_item_ids=[], now=clock.now()
        )
        == 0
    )


def test_invalidation_marks_the_row_instead_of_deleting_it(db_session: Session) -> None:
    """`item_exposures`는 immutable log다. quarantine은 삭제가 아니라 표시다."""
    clock = MutableClock()
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    presentation = _presentation(db_session, user)
    record_meaningful_exposure(
        db_session, presentation=presentation, target_item_ids=[item.id], now=clock.now()
    )

    invalidated_at = clock.advance(timedelta(hours=2))
    affected = invalidate_presentation_exposures(
        db_session, presentation_id=presentation.id, now=invalidated_at
    )

    assert affected == [item.id]
    assert count_valid_exposures(db_session, user_id=user.id, learning_item_id=item.id) == 0
    (exposure,) = _stored(db_session, user, item)
    assert exposure.invalidated_at == invalidated_at


def test_invalidating_one_presentation_leaves_the_others_valid(db_session: Session) -> None:
    clock = MutableClock()
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    first = _presentation(db_session, user)
    second = _presentation(db_session, user)
    for presentation in (first, second):
        record_meaningful_exposure(
            db_session, presentation=presentation, target_item_ids=[item.id], now=clock.now()
        )

    invalidate_presentation_exposures(
        db_session, presentation_id=first.id, now=clock.advance(timedelta(hours=1))
    )

    assert count_valid_exposures(db_session, user_id=user.id, learning_item_id=item.id) == 1


def test_invalidating_twice_keeps_the_first_moment(db_session: Session) -> None:
    clock = MutableClock()
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    presentation = _presentation(db_session, user)
    record_meaningful_exposure(
        db_session, presentation=presentation, target_item_ids=[item.id], now=clock.now()
    )
    first_moment = clock.advance(timedelta(hours=1))
    invalidate_presentation_exposures(db_session, presentation_id=presentation.id, now=first_moment)

    again = invalidate_presentation_exposures(
        db_session, presentation_id=presentation.id, now=clock.advance(timedelta(hours=1))
    )

    assert again == []
    (exposure,) = _stored(db_session, user, item)
    assert exposure.invalidated_at == first_moment


def test_exposures_are_counted_per_user(db_session: Session) -> None:
    clock = MutableClock()
    item = factories.make_learning_item(db_session)
    owner = factories.make_user(db_session)
    other = factories.make_user(db_session)
    record_meaningful_exposure(
        db_session,
        presentation=_presentation(db_session, owner),
        target_item_ids=[item.id],
        now=clock.now(),
    )

    assert count_valid_exposures(db_session, user_id=other.id, learning_item_id=item.id) == 0


def test_exposed_recently_answers_with_the_injected_window(db_session: Session) -> None:
    clock = MutableClock()
    user = factories.make_user(db_session)
    recent = factories.make_learning_item(db_session)
    old = factories.make_learning_item(db_session)
    never = factories.make_learning_item(db_session)

    record_meaningful_exposure(
        db_session,
        presentation=_presentation(db_session, user),
        target_item_ids=[old.id],
        now=clock.now(),
    )
    cutoff = clock.advance(timedelta(days=10))
    record_meaningful_exposure(
        db_session,
        presentation=_presentation(db_session, user),
        target_item_ids=[recent.id],
        now=clock.advance(timedelta(days=1)),
    )

    seen = exposed_recently(
        db_session,
        user_id=user.id,
        learning_item_ids=[recent.id, old.id, never.id],
        since=cutoff,
    )

    assert seen == {recent.id}


def test_exposed_recently_ignores_invalidated_exposures(db_session: Session) -> None:
    clock = MutableClock()
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    presentation = _presentation(db_session, user)
    since = clock.now()
    record_meaningful_exposure(
        db_session, presentation=presentation, target_item_ids=[item.id], now=clock.now()
    )
    invalidate_presentation_exposures(
        db_session, presentation_id=presentation.id, now=clock.advance(timedelta(hours=1))
    )

    assert (
        exposed_recently(db_session, user_id=user.id, learning_item_ids=[item.id], since=since)
        == set()
    )


def test_exposed_recently_with_no_candidates_asks_nothing(db_session: Session) -> None:
    clock = MutableClock()
    user = factories.make_user(db_session)

    assert (
        exposed_recently(db_session, user_id=user.id, learning_item_ids=[], since=clock.now())
        == set()
    )
