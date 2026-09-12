"""`user_item_learning_state` --- context ladder, 무신호 카운터, 승격, probe 기록.

핵심 단정 넷:
  - `context_stage` 전이표(07_SRS_SPEC.md의 `전이 규칙`)가 양방향으로 성립하고
    경계에서 clamp된다. 낮은 stage의 노출이 이미 진행한 ladder를 끌어내리지 않는다.
  - 승격은 그 문장을 `anchor_sentence_id`로 남긴다(같은 문서의 `anchor_sentence_id 지정`).
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
    advance_context_stage,
    bump_no_signal,
    promote_incidental,
    record_probe_outcome,
)
from app.models import LearningItem, ReviewState, User, UserItemLearningState, UserMastery
from app.models.enums import ContextStage, ExplicitSignal
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


def _sentence_id(db_session: Session) -> int:
    """승격이 최초 학습 문맥으로 기록할 문장. 문장 내용은 이 단위 테스트와 무관하다."""
    return factories.make_sentence(db_session).id


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
        sentence_id=_sentence_id(db_session),
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
        sentence_id=_sentence_id(db_session),
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
        sentence_id=_sentence_id(db_session),
        signal=ExplicitSignal.UNKNOWN,
        now=clock.now(),
    )

    promote_incidental(
        db_session,
        user_id=user.id,
        learning_item_id=item.id,
        sentence_id=_sentence_id(db_session),
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
        sentence_id=_sentence_id(db_session),
        signal=ExplicitSignal.UNCERTAIN,
        now=clock.now(),
    )
    second = promote_incidental(
        db_session,
        user_id=user.id,
        learning_item_id=item.id,
        sentence_id=_sentence_id(db_session),
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
        sentence_id=_sentence_id(db_session),
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
    # 이 세 writer는 stage를 움직이지 않는다. ladder를 미는 것은
    # `advance_context_stage` 하나뿐이고, 그것은 exposure 확정과 같은 자리에 있다.
    assert state.context_stage == INITIAL_CONTEXT_STAGE


# --------------------------------------------------------------------------
# context ladder 전이 (07_SRS_SPEC.md의 `전이 규칙 (MVP 확정)`, ADR-012)
# --------------------------------------------------------------------------

ANCHOR = ContextStage.ANCHOR
NEAR_ORIGINAL = ContextStage.NEAR_ORIGINAL
VARIED = ContextStage.VARIED
NEW_CONTEXT = ContextStage.NEW_CONTEXT


@pytest.mark.parametrize(
    ("current", "shown", "failed", "expected"),
    [
        # 실패가 없는 경로는 표의 exact sequence를 그대로 따라간다.
        (ANCHOR, ANCHOR, False, NEAR_ORIGINAL),
        (NEAR_ORIGINAL, NEAR_ORIGINAL, False, VARIED),
        (VARIED, VARIED, False, NEW_CONTEXT),
        # 천장. `new_context`에서의 성공은 `new_context`에 머문다.
        (NEW_CONTEXT, NEW_CONTEXT, False, NEW_CONTEXT),
        # explicit `몰랐음`은 실제로 본 문맥을 기준으로 한 칸 내려간다.
        (NEW_CONTEXT, NEW_CONTEXT, True, VARIED),
        (VARIED, VARIED, True, NEAR_ORIGINAL),
        (NEAR_ORIGINAL, NEAR_ORIGINAL, True, ANCHOR),
        # 바닥. anchor보다 쉬운 문맥은 MVP에 없다.
        (ANCHOR, ANCHOR, True, ANCHOR),
        # max: 낮은 stage의 노출(Pool Fallback의 anchor reinforcement 등)이 이미
        # 진행한 ladder를 끌어내리지 않는다.
        (NEW_CONTEXT, ANCHOR, False, NEW_CONTEXT),
        (VARIED, NEAR_ORIGINAL, False, VARIED),
        # min: 실패는 S_shown 기준이므로 현재 stage보다 낮아질 때만 내려간다.
        (NEAR_ORIGINAL, NEW_CONTEXT, True, NEAR_ORIGINAL),
        (NEW_CONTEXT, ANCHOR, True, ANCHOR),
    ],
    ids=lambda value: value.value if isinstance(value, ContextStage) else str(value),
)
def test_the_transition_table_moves_one_step_in_each_direction(
    db_session: Session,
    current: ContextStage,
    shown: ContextStage,
    failed: bool,
    expected: ContextStage,
) -> None:
    """무신호/`애매함`/`알고 있었음`은 올리고 explicit `몰랐음`만 내린다.

    ladder에 config 키는 없다(ADR-012). 기대값을 표에서 직접 읽는 이유가 그것이다
    --- 이 표 자체가 명세다.
    """
    clock = MutableClock()
    user, item = _pair(db_session)
    factories.make_learning_state(db_session, user, item, context_stage=current)

    updated = advance_context_stage(
        db_session,
        user_id=user.id,
        learning_item_id=item.id,
        shown_stage=shown,
        failed=failed,
        now=clock.now(),
    )

    assert updated is expected
    assert _state(db_session, user, item).context_stage is expected


def test_the_first_exposure_creates_the_row_and_leaves_the_anchor_behind(
    db_session: Session,
) -> None:
    """행이 없으면 `anchor`에서 시작한다. 첫 노출이 곧바로 varied인 것처럼 기록되지 않는다."""
    clock = MutableClock()
    user, item = _pair(db_session)

    updated = advance_context_stage(
        db_session,
        user_id=user.id,
        learning_item_id=item.id,
        shown_stage=INITIAL_CONTEXT_STAGE,
        failed=False,
        now=clock.now(),
    )

    assert updated is NEAR_ORIGINAL
    state = _state(db_session, user, item)
    assert state.context_stage is NEAR_ORIGINAL
    assert state.updated_at == clock.now()


def test_a_transition_that_changes_nothing_does_not_touch_the_row(db_session: Session) -> None:
    """천장에서의 성공은 stage도 `updated_at`도 움직이지 않는다."""
    clock = MutableClock()
    user, item = _pair(db_session)
    state = factories.make_learning_state(db_session, user, item, context_stage=NEW_CONTEXT)
    before = state.updated_at

    advance_context_stage(
        db_session,
        user_id=user.id,
        learning_item_id=item.id,
        shown_stage=NEW_CONTEXT,
        failed=False,
        now=clock.advance(timedelta(hours=1)),
    )

    assert _state(db_session, user, item).updated_at == before


def test_promotion_records_the_sentence_as_the_first_learning_context(
    db_session: Session,
) -> None:
    """사용자가 실제로 만나 물어본 문장이 그 item의 최초 학습 문맥이다.

    이것이 없으면 anchor가 `sentences.id ASC`로 뽑힌 낯선 문장이 되고, target이
    아닌 item의 self-report가 만든 문맥이 통째로 사라진다(ADR-013).
    """
    clock = MutableClock()
    user, item = _pair(db_session)
    sentence = factories.make_sentence(db_session)

    promote_incidental(
        db_session,
        user_id=user.id,
        learning_item_id=item.id,
        sentence_id=sentence.id,
        signal=ExplicitSignal.UNKNOWN,
        now=clock.now(),
    )

    assert _state(db_session, user, item).anchor_sentence_id == sentence.id


def test_promotion_never_overwrites_an_existing_anchor(db_session: Session) -> None:
    """이미 값이 있으면 덮어쓰지 않는다. 재지정은 quarantine 규칙 한 곳이 소유한다."""
    clock = MutableClock()
    user, item = _pair(db_session)
    first = factories.make_sentence(db_session)
    later = factories.make_sentence(db_session)
    factories.make_learning_state(db_session, user, item, anchor_sentence_id=first.id)

    promote_incidental(
        db_session,
        user_id=user.id,
        learning_item_id=item.id,
        sentence_id=later.id,
        signal=ExplicitSignal.UNKNOWN,
        now=clock.now(),
    )

    assert _state(db_session, user, item).anchor_sentence_id == first.id


def test_a_signal_that_promotes_nothing_records_no_anchor(db_session: Session) -> None:
    """`알고 있었음`은 승격도 anchor 기록도 하지 않는다 --- 학습 문맥이 아니다."""
    clock = MutableClock()
    user, item = _pair(db_session)
    sentence = factories.make_sentence(db_session)
    factories.make_learning_state(db_session, user, item, is_active_learning_target=False)

    promote_incidental(
        db_session,
        user_id=user.id,
        learning_item_id=item.id,
        sentence_id=sentence.id,
        signal=ExplicitSignal.KNOWN,
        now=clock.now(),
    )

    assert _state(db_session, user, item).anchor_sentence_id is None
