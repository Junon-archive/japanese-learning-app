"""`user_item_learning_state` --- 무신호 카운터, incidental 승격, probe 기록.

핵심 단정 둘:
  - `알고 있었음`은 승격시키지 않는다(02_LEARNING_POLICY.md의 Incidental Item Click).
  - probe skip은 mastery evidence도 FSRS grade도 아니다(같은 문서의 Skip).
"""

from __future__ import annotations

from datetime import timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.learning.progression import (
    INITIAL_CONTEXT_STAGE,
    bump_no_signal,
    promote_incidental,
    record_probe_outcome,
)
from app.models import LearningItem, ReviewState, User, UserItemLearningState, UserMastery
from app.models.enums import ExplicitSignal
from tests import factories
from tests.clock import MutableClock

pytestmark = pytest.mark.integration

FSRS_PARAMS_VERSION_FILLER = "test"
FSRS_STATE_FILLER = 1


def _state(db_session: Session, user: User, item: LearningItem) -> UserItemLearningState:
    return db_session.execute(
        sa.select(UserItemLearningState).where(
            UserItemLearningState.user_id == user.id,
            UserItemLearningState.learning_item_id == item.id,
        )
    ).scalar_one()


def _pair(db_session: Session) -> tuple[User, LearningItem]:
    return factories.make_user(db_session), factories.make_learning_item(db_session)


def test_the_first_no_signal_creates_the_row_at_the_anchor_stage(db_session: Session) -> None:
    """행이 생기는 시점은 item을 처음 만나는 때이므로 초기 stage는 anchor다
    (07_SRS_SPEC.md의 `Exposure 1 -> anchor`)."""
    clock = MutableClock()
    user, item = _pair(db_session)

    bump_no_signal(db_session, user_id=user.id, learning_item_id=item.id, now=clock.now())

    state = _state(db_session, user, item)
    assert state.context_stage == INITIAL_CONTEXT_STAGE
    assert state.passive_no_signal_count == 1
    assert state.is_active_learning_target is False
    assert state.last_probe_at is None
    assert state.updated_at == clock.now()


def test_no_signal_counts_accumulate_on_one_row(db_session: Session) -> None:
    """`passive_exposures_before_probe`가 이 값을 본다."""
    clock = MutableClock()
    user, item = _pair(db_session)

    for _ in range(3):
        bump_no_signal(
            db_session,
            user_id=user.id,
            learning_item_id=item.id,
            now=clock.advance(timedelta(hours=1)),
        )

    assert _state(db_session, user, item).passive_no_signal_count == 3


def test_no_signal_does_not_touch_mastery(db_session: Session) -> None:
    """불변식 #2: 무신호는 evidence가 아니다."""
    clock = MutableClock()
    user, item = _pair(db_session)

    bump_no_signal(db_session, user_id=user.id, learning_item_id=item.id, now=clock.now())

    assert (
        db_session.execute(
            sa.select(sa.func.count())
            .select_from(UserMastery)
            .where(UserMastery.user_id == user.id)
        ).scalar_one()
        == 0
    )


@pytest.mark.parametrize("signal", [ExplicitSignal.UNKNOWN, ExplicitSignal.UNCERTAIN])
def test_not_knowing_promotes_the_clicked_item(db_session: Session, signal: ExplicitSignal) -> None:
    clock = MutableClock()
    user, item = _pair(db_session)

    promoted = promote_incidental(
        db_session,
        user_id=user.id,
        learning_item_id=item.id,
        signal=signal,
        now=clock.now(),
    )

    assert promoted is True
    assert _state(db_session, user, item).is_active_learning_target is True


def test_knowing_does_not_promote_the_clicked_item(db_session: Session) -> None:
    """이미 아는 표현을 SRS 신규 item으로 강제 등록하지 않는다."""
    clock = MutableClock()
    user, item = _pair(db_session)

    promoted = promote_incidental(
        db_session,
        user_id=user.id,
        learning_item_id=item.id,
        signal=ExplicitSignal.KNOWN,
        now=clock.now(),
    )

    assert promoted is False
    assert (
        db_session.execute(
            sa.select(sa.func.count())
            .select_from(UserItemLearningState)
            .where(UserItemLearningState.user_id == user.id)
        ).scalar_one()
        == 0
    )


def test_knowing_does_not_demote_an_already_active_target(db_session: Session) -> None:
    clock = MutableClock()
    user, item = _pair(db_session)
    promote_incidental(
        db_session,
        user_id=user.id,
        learning_item_id=item.id,
        signal=ExplicitSignal.UNKNOWN,
        now=clock.now(),
    )

    promote_incidental(
        db_session,
        user_id=user.id,
        learning_item_id=item.id,
        signal=ExplicitSignal.KNOWN,
        now=clock.advance(timedelta(minutes=1)),
    )

    assert _state(db_session, user, item).is_active_learning_target is True


def test_promoting_twice_reports_the_transition_only_once(db_session: Session) -> None:
    """호출부가 신규 학습 target 등록을 두 번 하지 않게 한다."""
    clock = MutableClock()
    user, item = _pair(db_session)

    first = promote_incidental(
        db_session,
        user_id=user.id,
        learning_item_id=item.id,
        signal=ExplicitSignal.UNCERTAIN,
        now=clock.now(),
    )
    second = promote_incidental(
        db_session,
        user_id=user.id,
        learning_item_id=item.id,
        signal=ExplicitSignal.UNCERTAIN,
        now=clock.advance(timedelta(minutes=1)),
    )

    assert (first, second) == (True, False)


def test_a_skipped_probe_is_recorded_but_is_not_evidence(db_session: Session) -> None:
    """skip = mastery evidence 아님 / FSRS grade 아님 / 무신호."""
    clock = MutableClock()
    user, item = _pair(db_session)
    review_state = factories.make_review_state(
        db_session, user, item, state=FSRS_STATE_FILLER, params_version=FSRS_PARAMS_VERSION_FILLER
    )
    before = (
        review_state.stability,
        review_state.difficulty,
        review_state.state,
        review_state.reps,
        review_state.lapses,
        review_state.next_review_at,
        review_state.deferred_until,
    )

    record_probe_outcome(
        db_session, user_id=user.id, learning_item_id=item.id, response=None, now=clock.now()
    )

    state = _state(db_session, user, item)
    assert state.probe_skip_count == 1
    assert state.last_probe_at == clock.now()
    assert (
        db_session.execute(
            sa.select(sa.func.count())
            .select_from(UserMastery)
            .where(UserMastery.user_id == user.id)
        ).scalar_one()
        == 0
    )
    db_session.expire(review_state)
    reloaded = db_session.get(ReviewState, review_state.id)
    assert reloaded is not None
    assert (
        reloaded.stability,
        reloaded.difficulty,
        reloaded.state,
        reloaded.reps,
        reloaded.lapses,
        reloaded.next_review_at,
        reloaded.deferred_until,
    ) == before


def test_an_answered_probe_records_the_moment_without_counting_a_skip(db_session: Session) -> None:
    """mastery 갱신은 호출부가 따로 한다. 여기서 하면 evidence가 이중 집계된다."""
    clock = MutableClock()
    user, item = _pair(db_session)

    record_probe_outcome(
        db_session,
        user_id=user.id,
        learning_item_id=item.id,
        response=ExplicitSignal.UNCERTAIN,
        now=clock.now(),
    )

    state = _state(db_session, user, item)
    assert state.probe_skip_count == 0
    assert state.last_probe_at == clock.now()
    assert (
        db_session.execute(
            sa.select(sa.func.count())
            .select_from(UserMastery)
            .where(UserMastery.user_id == user.id)
        ).scalar_one()
        == 0
    )


def test_probe_cooldown_sees_the_latest_probe(db_session: Session) -> None:
    clock = MutableClock()
    user, item = _pair(db_session)
    record_probe_outcome(
        db_session, user_id=user.id, learning_item_id=item.id, response=None, now=clock.now()
    )

    later = clock.advance(timedelta(days=1))
    record_probe_outcome(
        db_session, user_id=user.id, learning_item_id=item.id, response=None, now=later
    )

    state = _state(db_session, user, item)
    assert state.last_probe_at == later
    assert state.probe_skip_count == 2


def test_all_three_writers_share_one_row(db_session: Session) -> None:
    clock = MutableClock()
    user, item = _pair(db_session)

    bump_no_signal(db_session, user_id=user.id, learning_item_id=item.id, now=clock.now())
    promote_incidental(
        db_session,
        user_id=user.id,
        learning_item_id=item.id,
        signal=ExplicitSignal.UNKNOWN,
        now=clock.advance(timedelta(minutes=1)),
    )
    record_probe_outcome(
        db_session,
        user_id=user.id,
        learning_item_id=item.id,
        response=None,
        now=clock.advance(timedelta(minutes=1)),
    )

    assert (
        db_session.execute(
            sa.select(sa.func.count())
            .select_from(UserItemLearningState)
            .where(UserItemLearningState.user_id == user.id)
        ).scalar_one()
        == 1
    )
    state = _state(db_session, user, item)
    assert (state.passive_no_signal_count, state.probe_skip_count) == (1, 1)
    assert state.is_active_learning_target is True
    # 아무도 stage를 전진시키지 않는다. 전이 규칙은 아직 명세 공백이다.
    assert state.context_stage == INITIAL_CONTEXT_STAGE
