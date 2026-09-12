"""review 기록의 행동 고정 (07_SRS_SPEC.md).

기대값을 날짜 리터럴로 박지 않는다. 테스트가 `Scheduler(enable_fuzzing=False)`로
**직접 계산**해서 비교한다 --- 리터럴로 박으면 라이브러리를 올릴 때 무엇이 바뀐
것인지 알 수 없고, 우리가 라이브러리 계산을 그대로 쓰는지도 증명되지 않는다.

정책값(`passive_review_deferral_hours`)은 config에서 읽는다.
"""

from __future__ import annotations

import ast
import inspect
from datetime import datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from fsrs import Card, Rating, Scheduler
from sqlalchemy.orm import Session

from app.config import get_config
from app.models.enums import ExplicitSignal
from app.models.learning import ReviewState
from app.srs import review
from app.srs.fsrs_binding import FSRS_PARAMS_VERSION
from app.srs.review import record_explicit_review, record_no_signal_review
from tests import factories
from tests.clock import DEFAULT_START, MutableClock

# review_states의 FSRS 상태 전부. 무신호 review는 이 중 어느 것도 건드리지 않는다.
FSRS_COLUMNS = (
    "stability",
    "difficulty",
    "state",
    "step",
    "last_review_at",
    "next_review_at",
)
COUNTER_COLUMNS = ("reps", "lapses")

# state = Review. 무신호 테스트는 카드를 재구성하지 않으므로 값 자체는 무관하다.
REVIEW_STATE_FILLER = 2


def _snapshot(state: ReviewState, names: tuple[str, ...]) -> dict[str, Any]:
    return {name: getattr(state, name) for name in names}


def _expected(card: Card, rating: Rating, now: datetime) -> Card:
    """라이브러리가 직접 계산한 기대 카드."""
    scheduler = Scheduler(enable_fuzzing=get_config().srs.fsrs_enable_fuzzing)
    reviewed, _log = scheduler.review_card(card, rating, now)
    return reviewed


def _assert_matches(state: ReviewState, card: Card) -> None:
    assert state.state == int(card.state)
    assert state.step == card.step
    assert state.stability == card.stability
    assert state.difficulty == card.difficulty
    assert state.next_review_at == card.due
    assert state.last_review_at == card.last_review


def _reload(db_session: Session, state: ReviewState) -> ReviewState:
    """DB를 실제로 왕복시킨다. 저장되지 않은 값을 저장된 것처럼 읽지 않는다."""
    db_session.flush()
    db_session.expire_all()
    reloaded = db_session.get(ReviewState, state.id)
    assert reloaded is not None
    return reloaded


# --------------------------------------------------------------------------
# 불변식 #2: 구조 검사 (DB 없음)
# --------------------------------------------------------------------------


def test_no_signal_review_assigns_nothing_but_deferred_until() -> None:
    """무신호 review는 FSRS rating을 만들지 않는다 (불변식 #2).

    값 비교(아래 integration)만으로는 "우연히 같은 값을 다시 쓴" 대입을 놓칠 수
    있다. 여기서는 대입문 자체가 없음을 본다.
    """
    source = inspect.getsource(record_no_signal_review)
    tree = ast.parse(inspect.cleandoc(source))

    assigned = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store)
    }

    assert assigned == {"deferred_until"}


def test_only_one_place_increments_reps_and_lapses() -> None:
    """ADR-003: `reps` / `lapses`는 애플리케이션 카운터이고 증가 지점은 한 곳이다."""
    tree = ast.parse(inspect.getsource(review))

    incremented = [
        node.target.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.AugAssign)
        and isinstance(node.target, ast.Attribute)
        and node.target.attr in COUNTER_COLUMNS
    ]

    assert sorted(incremented) == ["lapses", "reps"]


# --------------------------------------------------------------------------
# explicit review
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_a_first_explicit_review_matches_the_library(db_session: Session) -> None:
    """스케줄은 FSRS가 계산한 값 그대로다. 우리가 손대는 값이 없다."""
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    now = DEFAULT_START

    state = record_explicit_review(
        db_session,
        user_id=user.id,
        learning_item_id=item.id,
        signal=ExplicitSignal.KNOWN,
        now=now,
        config=get_config(),
    )

    expected = _expected(Card(card_id=1, due=now), Rating.Good, now)
    _assert_matches(_reload(db_session, state), expected)


@pytest.mark.integration
def test_the_stored_card_is_what_the_next_review_continues_from(db_session: Session) -> None:
    """두 번째 review가 첫 번째 결과 위에서 계산된다.

    `to_card`가 한 필드라도 흘리면 여기서 값이 갈린다.
    """
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    clock = MutableClock()
    config = get_config()

    first = _expected(Card(card_id=1, due=clock.now()), Rating.Good, clock.now())
    record_explicit_review(
        db_session,
        user_id=user.id,
        learning_item_id=item.id,
        signal=ExplicitSignal.KNOWN,
        now=clock.now(),
        config=config,
    )

    later = clock.advance(timedelta(days=3))
    second = _expected(first, Rating.Hard, later)
    state = record_explicit_review(
        db_session,
        user_id=user.id,
        learning_item_id=item.id,
        signal=ExplicitSignal.UNCERTAIN,
        now=later,
        config=config,
    )

    _assert_matches(_reload(db_session, state), second)


@pytest.mark.integration
def test_every_explicit_review_counts_and_only_again_lapses(db_session: Session) -> None:
    """`reps`는 explicit review마다, `lapses`는 `몰랐음`에만 오른다 (ADR-003)."""
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    clock = MutableClock()
    config = get_config()

    counts = []
    for signal in (
        ExplicitSignal.KNOWN,
        ExplicitSignal.UNKNOWN,
        ExplicitSignal.UNCERTAIN,
        ExplicitSignal.UNKNOWN,
    ):
        state = record_explicit_review(
            db_session,
            user_id=user.id,
            learning_item_id=item.id,
            signal=signal,
            now=clock.advance(timedelta(days=1)),
            config=config,
        )
        counts.append((state.reps, state.lapses))

    assert counts == [(1, 0), (2, 1), (3, 1), (4, 2)]


@pytest.mark.integration
def test_an_explicit_review_stamps_the_params_version(db_session: Session) -> None:
    """어느 파라미터로 만든 스케줄인지 남는다. 재계산 판단의 근거다."""
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)

    state = record_explicit_review(
        db_session,
        user_id=user.id,
        learning_item_id=item.id,
        signal=ExplicitSignal.KNOWN,
        now=DEFAULT_START,
        config=get_config(),
    )

    assert _reload(db_session, state).fsrs_params_version == FSRS_PARAMS_VERSION


@pytest.mark.integration
def test_an_explicit_review_clears_the_deferral(db_session: Session) -> None:
    """증거가 도착하면 deferral을 지운다 (07_SRS_SPEC.md의 `deferral 해제`).

    남겨 두면 `Again` 직후 몇 분 뒤로 잡힌 due를 deferral이 몇 시간 동안 가린다.
    그것은 스케줄 준수가 아니라 스케줄 무시다. 무한 due loop를 막는 것은 deferral의
    지속이 아니라 무신호 presentation마다 다시 거는 동작이다.
    """
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    config = get_config()
    clock = MutableClock()
    record_explicit_review(
        db_session,
        user_id=user.id,
        learning_item_id=item.id,
        signal=ExplicitSignal.UNCERTAIN,
        now=clock.now(),
        config=config,
    )
    deferred = record_no_signal_review(
        db_session,
        user_id=user.id,
        learning_item_id=item.id,
        now=clock.advance(timedelta(days=30)),
        config=config,
    )
    assert deferred is not None and deferred.deferred_until is not None

    state = record_explicit_review(
        db_session,
        user_id=user.id,
        learning_item_id=item.id,
        signal=ExplicitSignal.UNKNOWN,
        now=clock.advance(timedelta(minutes=1)),
        config=config,
    )

    assert _reload(db_session, state).deferred_until is None


@pytest.mark.integration
def test_a_first_explicit_review_starts_without_a_deferral(db_session: Session) -> None:
    """새로 만든 스케줄에도 deferral이 남지 않는다. 해제 지점은 rating 기록 한 곳이다."""
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)

    state = record_explicit_review(
        db_session,
        user_id=user.id,
        learning_item_id=item.id,
        signal=ExplicitSignal.UNKNOWN,
        now=DEFAULT_START,
        config=get_config(),
    )

    assert _reload(db_session, state).deferred_until is None


# --------------------------------------------------------------------------
# no-signal review (불변식 #2)
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_a_no_signal_review_changes_only_deferred_until(db_session: Session) -> None:
    """FSRS 6컬럼과 `reps` / `lapses`가 **완전히** 그대로다.

    no-click은 Good이 아니다. 증거 없는 review가 memory state를 건드리는 순간
    사용자가 아무 것도 하지 않은 것이 학습 성공으로 기록된다.
    """
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    config = get_config()
    clock = MutableClock()

    state = record_explicit_review(
        db_session,
        user_id=user.id,
        learning_item_id=item.id,
        signal=ExplicitSignal.UNCERTAIN,
        now=clock.now(),
        config=config,
    )
    tracked = FSRS_COLUMNS + COUNTER_COLUMNS
    before = _snapshot(_reload(db_session, state), tracked)

    later = clock.advance(timedelta(days=30))
    deferred = record_no_signal_review(
        db_session,
        user_id=user.id,
        learning_item_id=item.id,
        now=later,
        config=config,
    )

    assert deferred is not None
    after_row = _reload(db_session, deferred)
    assert _snapshot(after_row, tracked) == before
    assert after_row.deferred_until == later + timedelta(
        hours=config.learning.passive_review_deferral_hours
    )


@pytest.mark.integration
def test_an_item_is_still_due_after_a_no_signal_review(db_session: Session) -> None:
    """`next_review_at`이 그대로이므로 item은 여전히 due다. 그것이 의도다.

    무신호 처리의 목적은 스케줄을 미루는 것이 아니라 같은 세션에서의 즉시 반복만
    막는 것이다.
    """
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    config = get_config()
    factories.make_review_state(
        db_session,
        user,
        item,
        state=REVIEW_STATE_FILLER,
        params_version=FSRS_PARAMS_VERSION,
    )
    now = DEFAULT_START + timedelta(days=1)

    state = record_no_signal_review(
        db_session,
        user_id=user.id,
        learning_item_id=item.id,
        now=now,
        config=config,
    )

    assert state is not None
    assert state.next_review_at <= now
    assert state.deferred_until is not None
    assert state.deferred_until > now


@pytest.mark.integration
def test_a_no_signal_review_without_a_schedule_does_nothing(db_session: Session) -> None:
    """`new` / `exploration`에는 `review_states` 행이 없다. defer할 대상이 없다.

    여기서 행을 만들면 아직 배우지도 않은 item에 무신호 evidence로 스케줄이 생긴다.
    """
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)

    state = record_no_signal_review(
        db_session,
        user_id=user.id,
        learning_item_id=item.id,
        now=DEFAULT_START,
        config=get_config(),
    )

    db_session.flush()
    assert state is None
    assert db_session.scalars(sa.select(ReviewState)).all() == []
