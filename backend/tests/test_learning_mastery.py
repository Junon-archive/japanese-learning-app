"""Mastery EMA와 explicit evidence 기록.

EMA 자체는 DB가 필요 없는 순수 함수다. `alpha`는 **주입**하고, 값이 달라지면 결과도
달라지는지 본다 --- alpha를 무시하고 상수를 쓰는 구현이 통과하지 못하게 하려는
것이다. 정책값(`mastery_ema_alpha`)은 테스트에 적지 않고 config에서 읽는다.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.config import get_config
from app.learning.mastery import (
    MASTERY_ALGORITHM_VERSION,
    OBSERVATION,
    ema,
    record_explicit_evidence,
)
from app.models.enums import CandidateStatus, ExplicitSignal
from app.models.learning import ReviewState, UserMastery
from tests import factories
from tests.clock import DEFAULT_START

# EMA와 무관한 자리 채우기 alpha. 정책값이 아니다.
ALPHA_HALF = 0.5
FSRS_PARAMS_VERSION_FILLER = "test"
FSRS_STATE_FILLER = 1


def _configured_alpha() -> float:
    return get_config().learning.mastery_ema_alpha


# --------------------------------------------------------------------------
# ema --- 순수 함수
# --------------------------------------------------------------------------


def test_the_first_evidence_becomes_the_value_itself() -> None:
    """NULL은 "능력 0"이 아니라 "evidence 없음"이다. 0.0에서 끌어올리지 않는다."""
    for observation in OBSERVATION.values():
        assert ema(None, observation, ALPHA_HALF) == observation


def test_each_signal_has_its_own_observation() -> None:
    assert OBSERVATION[ExplicitSignal.UNKNOWN] < OBSERVATION[ExplicitSignal.UNCERTAIN]
    assert OBSERVATION[ExplicitSignal.UNCERTAIN] < OBSERVATION[ExplicitSignal.KNOWN]
    assert all(0.0 <= value <= 1.0 for value in OBSERVATION.values())
    # `알고 있었음` 한 번은 완전한 이해의 증거가 아니다(02_LEARNING_POLICY.md).
    assert OBSERVATION[ExplicitSignal.KNOWN] < 1.0
    assert set(OBSERVATION) == set(ExplicitSignal)


def test_alpha_decides_how_much_of_the_new_observation_lands() -> None:
    old = 0.2
    observation = OBSERVATION[ExplicitSignal.KNOWN]
    slow = ema(old, observation, 0.1)
    fast = ema(old, observation, 0.9)

    # alpha를 무시하는 구현(예: 항상 observation을 쓰거나 고정 계수를 쓰는 것)은
    # 두 값이 같아져 여기서 걸린다.
    assert slow != fast
    assert old < slow < fast < observation


def test_alpha_bounds_are_the_two_degenerate_cases() -> None:
    old = 0.2
    observation = OBSERVATION[ExplicitSignal.UNKNOWN]
    assert ema(old, observation, 0.0) == pytest.approx(old)
    assert ema(old, observation, 1.0) == pytest.approx(observation)


def test_ema_stays_inside_the_stored_range() -> None:
    """`comprehension_mastery`에는 [0, 1] CHECK가 걸려 있다."""
    value: float | None = None
    for signal in (ExplicitSignal.KNOWN, ExplicitSignal.UNKNOWN, ExplicitSignal.UNCERTAIN) * 5:
        value = ema(value, OBSERVATION[signal], _configured_alpha())
        assert 0.0 <= value <= 1.0


# --------------------------------------------------------------------------
# record_explicit_evidence --- 저장
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_the_first_explicit_evidence_creates_the_row(db_session: Session) -> None:
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    alpha = _configured_alpha()

    mastery = record_explicit_evidence(
        db_session,
        user_id=user.id,
        learning_item_id=item.id,
        signal=ExplicitSignal.UNCERTAIN,
        now=DEFAULT_START,
        alpha=alpha,
    )

    assert mastery.comprehension_mastery == pytest.approx(OBSERVATION[ExplicitSignal.UNCERTAIN])
    assert mastery.evidence_count == 1
    assert mastery.mastery_algorithm_version == MASTERY_ALGORITHM_VERSION
    assert mastery.last_updated_at == DEFAULT_START


@pytest.mark.integration
def test_listening_mastery_is_never_written(db_session: Session) -> None:
    """MVP에는 audio가 없다. NULL은 "능력 0"이 아니라 "측정하지 않음"이다."""
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)

    record_explicit_evidence(
        db_session,
        user_id=user.id,
        learning_item_id=item.id,
        signal=ExplicitSignal.KNOWN,
        now=DEFAULT_START,
        alpha=_configured_alpha(),
    )

    stored = db_session.execute(
        sa.select(UserMastery.listening_mastery).where(UserMastery.user_id == user.id)
    ).scalar_one()
    assert stored is None


@pytest.mark.integration
def test_later_evidence_updates_the_same_row_by_ema(db_session: Session) -> None:
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    alpha = _configured_alpha()

    first = record_explicit_evidence(
        db_session,
        user_id=user.id,
        learning_item_id=item.id,
        signal=ExplicitSignal.KNOWN,
        now=DEFAULT_START,
        alpha=alpha,
    )
    before = first.comprehension_mastery

    second = record_explicit_evidence(
        db_session,
        user_id=user.id,
        learning_item_id=item.id,
        signal=ExplicitSignal.UNKNOWN,
        now=DEFAULT_START,
        alpha=alpha,
    )

    assert second.id == first.id
    assert second.evidence_count == 2
    assert second.comprehension_mastery == pytest.approx(
        ema(before, OBSERVATION[ExplicitSignal.UNKNOWN], alpha)
    )
    assert (
        db_session.execute(
            sa.select(sa.func.count())
            .select_from(UserMastery)
            .where(UserMastery.user_id == user.id)
        ).scalar_one()
        == 1
    )


@pytest.mark.integration
def test_evidence_count_is_not_the_exposure_count(db_session: Session) -> None:
    """`evidence_count`는 explicit evidence 개수다. exposure를 세지 않는다."""
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    sentence = factories.make_sentence(db_session)
    study_session = factories.make_study_session(db_session, user, target_minutes=1)
    candidate = factories.make_candidate(db_session, user, sentence, status=CandidateStatus.READY)
    presentation = factories.make_presentation(db_session, user, study_session, candidate, sentence)
    factories.make_exposure(db_session, user, item, presentation, sentence)

    mastery = record_explicit_evidence(
        db_session,
        user_id=user.id,
        learning_item_id=item.id,
        signal=ExplicitSignal.KNOWN,
        now=DEFAULT_START,
        alpha=_configured_alpha(),
    )

    assert mastery.evidence_count == 1


@pytest.mark.integration
def test_recording_mastery_does_not_touch_the_fsrs_schedule(db_session: Session) -> None:
    """불변식 #3: mastery 갱신은 scheduling state를 건드리지 않는다(ADR-003)."""
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
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

    record_explicit_evidence(
        db_session,
        user_id=user.id,
        learning_item_id=item.id,
        signal=ExplicitSignal.UNKNOWN,
        now=DEFAULT_START,
        alpha=_configured_alpha(),
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
