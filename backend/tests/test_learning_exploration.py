"""Exploration target 선정 (06_LEARNING_ENGINE.md의 `Exploration Item 선정`).

정렬 3단과 후보 조건 3개가 이 파일의 전부다. 정렬은 DB를 보지 않으므로 순수
함수로 검증하고(`make test-unit`), 후보 조건만 DB를 쓴다.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.config import get_config
from app.learning.exploration import (
    LADDER,
    difficulty_distance,
    eligible_exploration_targets,
    exploration_sort_key,
    frequency_key,
)
from app.learning.exposure import invalidate_presentation_exposures, record_meaningful_exposure
from app.models import LearningItem, User, UserItemLearningState
from app.models.enums import (
    CandidateStatus,
    ContextStage,
    LearningItemOrigin,
    LearningItemType,
    StartingLevel,
)
from tests import factories
from tests.clock import MutableClock

SESSION_MINUTES_FILLER = 1
MASTERY_ALGORITHM_FILLER = "test"

# 정렬 입력으로 **주입하는** 값이다. 정책값이 아니므로 config에서 읽지 않는다.
BEGINNER = StartingLevel.BEGINNER


def _item(
    item_id: int, *, label: str | None = None, metadata: dict[str, Any] | None = None
) -> LearningItem:
    """세션에 붙지 않은 transient row. 정렬은 DB를 보지 않는다."""
    item = LearningItem(
        type=LearningItemType.WORD,
        lemma="x",
        reading="x",
        default_meaning="x",
        origin=LearningItemOrigin.SEED,
        difficulty_label=label,
        metadata_json=metadata or {},
    )
    item.id = item_id
    return item


# --------------------------------------------------------------------------
# difficulty_distance
# --------------------------------------------------------------------------


def test_the_ladder_is_the_three_monotonic_mvp_levels() -> None:
    """ladder는 `difficulty_label`과 `starting_level`이 **공유**한다. 갈리면 거리가 무의미해진다."""
    assert LADDER == {"beginner": 0, "intermediate": 1, "advanced": 2}
    assert set(LADDER) == {level.value for level in StartingLevel}


def test_distance_is_the_absolute_ladder_gap() -> None:
    assert difficulty_distance("beginner", BEGINNER) == 0
    assert difficulty_distance("intermediate", BEGINNER) == 1
    assert difficulty_distance("advanced", BEGINNER) == 2
    assert difficulty_distance("beginner", StartingLevel.ADVANCED) == 2


def test_an_unknown_or_missing_label_has_no_distance() -> None:
    """ "모른다"를 큰 수로 지어내지 않는다. 지어내면 ladder를 늘릴 때 값이 뒤섞인다."""
    assert difficulty_distance(None, BEGINNER) is None
    assert difficulty_distance("n5", BEGINNER) is None


# --------------------------------------------------------------------------
# frequency_key
# --------------------------------------------------------------------------


def test_frequency_rank_wins_when_it_is_an_integer() -> None:
    assert frequency_key({"frequency_rank": 12, "seed_order": 3}) == (0, 12)


def test_seed_order_is_used_only_when_frequency_rank_is_missing() -> None:
    assert frequency_key({"seed_order": 3}) == (1, 3)


def test_the_two_sources_never_share_a_number_space() -> None:
    """seed_order 3(파일 3번째 줄)이 frequency_rank 12(언어 빈도)보다 앞서지 않는다."""
    assert frequency_key({"seed_order": 3}) > frequency_key({"frequency_rank": 12})


@pytest.mark.parametrize("value", ["12", 12.0, None, True])
def test_a_non_integer_frequency_rank_is_demoted(value: object) -> None:
    """문자열/float/null/bool은 빈도값이 아니다. 파싱하거나 반올림하면 seed 파일의
    오타가 조용히 빈도 순서가 된다."""
    assert frequency_key({"frequency_rank": value, "seed_order": 7}) == (1, 7)


@pytest.mark.parametrize("value", ["7", 7.5, None, False])
def test_a_non_integer_seed_order_is_demoted(value: object) -> None:
    assert frequency_key({"seed_order": value}) == (2, 0)


def test_missing_metadata_is_the_last_bucket() -> None:
    assert frequency_key({}) == (2, 0)
    assert frequency_key(None) == (2, 0)


# --------------------------------------------------------------------------
# exploration_sort_key
# --------------------------------------------------------------------------


def _sorted_ids(items: list[LearningItem]) -> list[int]:
    return [
        item.id
        for item in sorted(
            items, key=lambda row: exploration_sort_key(row, starting_level=BEGINNER)
        )
    ]


def test_difficulty_distance_is_the_first_sort_level() -> None:
    """빈도가 아무리 높아도 난이도가 먼 item을 먼저 주지 않는다."""
    near = _item(2, label="beginner", metadata={"frequency_rank": 900})
    far = _item(1, label="advanced", metadata={"frequency_rank": 1})

    assert _sorted_ids([far, near]) == [2, 1]


def test_an_unknown_label_sorts_behind_every_known_one() -> None:
    """알려진 label을 모두 소진한 뒤에만 선택된다."""
    unknown = _item(1, label=None, metadata={"frequency_rank": 1})
    worst_known = _item(2, label="advanced", metadata={"frequency_rank": 900})

    assert _sorted_ids([unknown, worst_known]) == [2, 1]


def test_frequency_breaks_equal_distance_and_id_breaks_equal_frequency() -> None:
    """cold start가 "seed item 중 고빈도부터"가 되는 것이 바로 이 두 단계다."""
    ranked = _item(4, label="beginner", metadata={"frequency_rank": 5})
    seeded = _item(3, label="beginner", metadata={"seed_order": 1})
    bare_high_id = _item(9, label="beginner")
    bare_low_id = _item(8, label="beginner", metadata={"frequency_rank": None})

    assert _sorted_ids([bare_high_id, seeded, bare_low_id, ranked]) == [4, 3, 8, 9]


# --------------------------------------------------------------------------
# 후보 조건 (DB)
# --------------------------------------------------------------------------


def _recent_days() -> int:
    return get_config().learning.exploration_recent_days


def _expose(db_session: Session, user: User, item: LearningItem, now: datetime) -> int:
    sentence = factories.make_sentence(db_session)
    study_session = factories.make_study_session(
        db_session, user, target_minutes=SESSION_MINUTES_FILLER
    )
    candidate = factories.make_candidate(db_session, user, sentence, status=CandidateStatus.READY)
    presentation = factories.make_presentation(db_session, user, study_session, candidate, sentence)
    record_meaningful_exposure(
        db_session, presentation=presentation, target_item_ids=[item.id], now=now
    )
    return presentation.id


def _learning_state(
    db_session: Session, user: User, item: LearningItem, *, active: bool, now: datetime
) -> None:
    db_session.add(
        UserItemLearningState(
            user_id=user.id,
            learning_item_id=item.id,
            context_stage=ContextStage.ANCHOR,
            is_active_learning_target=active,
            updated_at=now,
        )
    )
    db_session.flush()


@pytest.mark.integration
def test_an_untouched_item_is_a_candidate(db_session: Session) -> None:
    clock = MutableClock()
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)

    assert eligible_exploration_targets(
        db_session,
        user_id=user.id,
        item_ids=[item.id],
        now=clock.now(),
        recent_days=_recent_days(),
    ) == {item.id}


@pytest.mark.integration
def test_a_null_comprehension_mastery_row_still_qualifies(db_session: Session) -> None:
    """NULL은 "능력 0"이 아니라 "아직 evidence 없음"이다. 그래서 확인 대상이다."""
    clock = MutableClock()
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    factories.make_mastery(
        db_session,
        user,
        item,
        comprehension_mastery=None,
        algorithm_version=MASTERY_ALGORITHM_FILLER,
    )

    assert eligible_exploration_targets(
        db_session,
        user_id=user.id,
        item_ids=[item.id],
        now=clock.now(),
        recent_days=_recent_days(),
    ) == {item.id}


@pytest.mark.integration
def test_a_measured_item_is_not_a_candidate(db_session: Session) -> None:
    clock = MutableClock()
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    factories.make_mastery(
        db_session,
        user,
        item,
        comprehension_mastery=0.4,
        algorithm_version=MASTERY_ALGORITHM_FILLER,
    )

    assert (
        eligible_exploration_targets(
            db_session,
            user_id=user.id,
            item_ids=[item.id],
            now=clock.now(),
            recent_days=_recent_days(),
        )
        == set()
    )


@pytest.mark.integration
def test_an_active_learning_target_is_not_explored_again(db_session: Session) -> None:
    """incidental click으로 승격된 item을 exploration이 다시 잡으면 두 category가 겹친다."""
    clock = MutableClock()
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    _learning_state(db_session, user, item, active=True, now=clock.now())

    assert (
        eligible_exploration_targets(
            db_session,
            user_id=user.id,
            item_ids=[item.id],
            now=clock.now(),
            recent_days=_recent_days(),
        )
        == set()
    )


@pytest.mark.integration
def test_an_inactive_learning_state_row_still_qualifies(db_session: Session) -> None:
    clock = MutableClock()
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    _learning_state(db_session, user, item, active=False, now=clock.now())

    assert eligible_exploration_targets(
        db_session,
        user_id=user.id,
        item_ids=[item.id],
        now=clock.now(),
        recent_days=_recent_days(),
    ) == {item.id}


@pytest.mark.integration
def test_a_recent_exposure_disqualifies_and_an_old_one_does_not(db_session: Session) -> None:
    """판정 소스는 `item_exposures`다. `meaningful_exposure_count`는 캐시이며 쓰지 않는다."""
    clock = MutableClock()
    user = factories.make_user(db_session)
    recent = factories.make_learning_item(db_session)
    old = factories.make_learning_item(db_session)
    recent_days = _recent_days()

    _expose(db_session, user, old, clock.now())
    clock.advance(timedelta(days=recent_days + 1))
    _expose(db_session, user, recent, clock.now())

    assert eligible_exploration_targets(
        db_session,
        user_id=user.id,
        item_ids=[recent.id, old.id],
        now=clock.now(),
        recent_days=recent_days,
    ) == {old.id}


@pytest.mark.integration
def test_an_invalidated_exposure_does_not_disqualify(db_session: Session) -> None:
    """quarantine된 문장에서 본 것은 노출로 세지 않는다(10_ERROR_HANDLING.md)."""
    clock = MutableClock()
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    presentation_id = _expose(db_session, user, item, clock.now())
    invalidate_presentation_exposures(
        db_session, presentation_id=presentation_id, now=clock.advance(timedelta(hours=1))
    )

    assert eligible_exploration_targets(
        db_session,
        user_id=user.id,
        item_ids=[item.id],
        now=clock.now(),
        recent_days=_recent_days(),
    ) == {item.id}


@pytest.mark.integration
def test_another_users_exposure_does_not_disqualify(db_session: Session) -> None:
    clock = MutableClock()
    owner = factories.make_user(db_session)
    other = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    _expose(db_session, other, item, clock.now())

    assert eligible_exploration_targets(
        db_session,
        user_id=owner.id,
        item_ids=[item.id],
        now=clock.now(),
        recent_days=_recent_days(),
    ) == {item.id}


@pytest.mark.integration
def test_an_empty_item_list_asks_nothing(db_session: Session) -> None:
    clock = MutableClock()
    user = factories.make_user(db_session)

    assert (
        eligible_exploration_targets(
            db_session,
            user_id=user.id,
            item_ids=[],
            now=clock.now(),
            recent_days=_recent_days(),
        )
        == set()
    )


@pytest.mark.integration
def test_the_query_never_returns_items_outside_the_asked_set(db_session: Session) -> None:
    """호출부는 정렬 대상을 이 결과로 좁힌다. 묻지 않은 id가 새어 나오면 안 된다."""
    clock = MutableClock()
    user = factories.make_user(db_session)
    asked = factories.make_learning_item(db_session)
    unasked = factories.make_learning_item(db_session)

    result = eligible_exploration_targets(
        db_session,
        user_id=user.id,
        item_ids=[asked.id],
        now=clock.now(),
        recent_days=_recent_days(),
    )

    assert result == {asked.id}
    assert unasked.id not in result
