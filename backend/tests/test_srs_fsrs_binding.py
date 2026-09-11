"""FSRS 바인딩 단위 테스트. DB를 쓰지 않는다.

여기서 고정하는 것은 세 가지다: explicit signal -> Rating 매핑(07_SRS_SPEC.md),
`Card` <-> `review_states` 왕복 무손실(ADR-003 매핑표), fuzzing을 끈 scheduler의
결정성. 정책값은 전부 config에서 읽는다.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from fsrs import Card, Rating, Scheduler, State

from app.config import AppConfig, SrsConfig, get_config
from app.models.enums import ExplicitSignal
from app.models.learning import ReviewState
from app.srs.fsrs_binding import (
    RATING_BY_SIGNAL,
    build_scheduler,
    rating_for_signal,
    to_card,
    write_card,
)
from tests.clock import DEFAULT_START

# 매핑과 왕복만 보는 테스트라 값 자체에는 의미가 없다. 정책값이 아니다.
FSRS_PARAMS_VERSION_FILLER = "test"


def _config_with_fuzzing(*, enabled: bool) -> AppConfig:
    """fuzzing 여부만 바꾼 config. 나머지 정책값은 실제 파일에서 온다."""
    return get_config().model_copy(update={"srs": SrsConfig(fsrs_enable_fuzzing=enabled)})


def _review_state(
    *,
    state: int,
    step: int | None,
    stability: float | None,
    difficulty: float | None,
    next_review_at: datetime,
    last_review_at: datetime | None,
) -> ReviewState:
    """세션에 붙지 않은 ORM 인스턴스. 왕복 검사에는 DB가 필요 없다."""
    return ReviewState(
        user_id=1,
        learning_item_id=1,
        state=state,
        step=step,
        stability=stability,
        difficulty=difficulty,
        next_review_at=next_review_at,
        last_review_at=last_review_at,
        reps=0,
        lapses=0,
        fsrs_params_version=FSRS_PARAMS_VERSION_FILLER,
    )


# --------------------------------------------------------------------------
# signal -> Rating
# --------------------------------------------------------------------------


def test_each_explicit_signal_maps_to_the_rating_in_the_spec() -> None:
    """몰랐음 -> Again / 애매함 -> Hard / 알고 있었음 -> Good (07_SRS_SPEC.md).

    probe incorrect / uncertain / correct도 같은 3값으로 들어오므로 같은 매핑이다.
    """
    assert rating_for_signal(ExplicitSignal.UNKNOWN) is Rating.Again
    assert rating_for_signal(ExplicitSignal.UNCERTAIN) is Rating.Hard
    assert rating_for_signal(ExplicitSignal.KNOWN) is Rating.Good


def test_easy_is_never_produced() -> None:
    """`Easy`는 MVP UI에 없다. 어떤 signal도 Easy를 만들지 않는다."""
    assert Rating.Easy not in RATING_BY_SIGNAL.values()


def test_every_explicit_signal_has_a_rating() -> None:
    """signal 값이 늘면 매핑도 함께 늘어야 한다. 조용한 KeyError를 막는다."""
    assert set(RATING_BY_SIGNAL) == set(ExplicitSignal)


# --------------------------------------------------------------------------
# Card <-> review_states
# --------------------------------------------------------------------------


def test_a_review_state_round_trips_through_card_without_loss() -> None:
    """ADR-003 매핑표의 6개 필드가 왕복해도 그대로다.

    한 필드라도 새면 다음 review가 다른 카드를 스케줄한다.
    """
    original = _review_state(
        state=int(State.Relearning),
        step=1,
        stability=12.5,
        difficulty=6.25,
        next_review_at=DEFAULT_START + timedelta(days=3),
        last_review_at=DEFAULT_START - timedelta(days=1),
    )

    card = to_card(original)
    restored = _review_state(
        state=int(State.Learning),
        step=None,
        stability=None,
        difficulty=None,
        next_review_at=DEFAULT_START,
        last_review_at=None,
    )
    write_card(restored, card)

    assert restored.state == original.state
    assert restored.step == original.step
    assert restored.stability == original.stability
    assert restored.difficulty == original.difficulty
    assert restored.next_review_at == original.next_review_at
    assert restored.last_review_at == original.last_review_at


def test_a_review_state_in_the_review_phase_round_trips_with_a_null_step() -> None:
    """`state = Review`이면 step은 NULL이다. 0으로 바뀌면 안 된다."""
    original = _review_state(
        state=int(State.Review),
        step=None,
        stability=40.0,
        difficulty=5.0,
        next_review_at=DEFAULT_START + timedelta(days=40),
        last_review_at=DEFAULT_START,
    )

    card = to_card(original)
    assert card.state is State.Review
    assert card.step is None


def test_the_card_id_has_nowhere_to_be_stored() -> None:
    """identity는 `(user_id, learning_item_id)` 하나다(ADR-003).

    card_id를 저장할 컬럼이 생기면 canonical identity가 둘이 된다.
    """
    assert "card_id" not in ReviewState.__table__.columns


# --------------------------------------------------------------------------
# scheduler
# --------------------------------------------------------------------------


def test_the_scheduler_is_deterministic_when_fuzzing_is_off() -> None:
    """같은 입력이 항상 같은 due를 낸다 (ADR-003).

    fuzzing은 대규모 덱의 due 쏠림을 흩는 jitter이고, MVP에서는 재현성을 택한다.
    """
    now = DEFAULT_START
    dues = set()
    for _ in range(20):
        scheduler = build_scheduler(_config_with_fuzzing(enabled=False))
        reviewed, _log = scheduler.review_card(Card(card_id=1, due=now), Rating.Good, now)
        dues.add(reviewed.due)

    assert len(dues) == 1


def test_the_scheduler_only_changes_fuzzing() -> None:
    """interval을 cap하지 않는다 (불변식 #4, 07_SRS_SPEC.md).

    `learning_steps` / `maximum_interval`을 손대면 최소 노출 5회를 FSRS 스케줄을
    왜곡해서 채우는 길이 열린다. 그 일은 `reinforcement` presentation이 한다.
    """
    defaults = Scheduler()
    built = build_scheduler(_config_with_fuzzing(enabled=False))

    assert built.learning_steps == defaults.learning_steps
    assert built.relearning_steps == defaults.relearning_steps
    assert built.maximum_interval == defaults.maximum_interval
    assert built.parameters == defaults.parameters
    assert built.desired_retention == defaults.desired_retention


def test_the_scheduler_takes_fuzzing_from_config() -> None:
    """정책값은 코드가 아니라 config에서 온다."""
    assert build_scheduler(_config_with_fuzzing(enabled=True)).enable_fuzzing is True
    assert build_scheduler(_config_with_fuzzing(enabled=False)).enable_fuzzing is False
