"""Exploration target 선정 (06_LEARNING_ENGINE.md의 `Exploration Item 선정`).

Exploration은 희귀어 랜덤 공급이 아니라 **mastery 정보가 부족한 item을 확인하는
것**이다. 후보 조건 3개와 3단 정렬의 canonical 정의가 그 절이고 여기가 구현이다.

cold start 분기를 두지 않는다. 첫 세션에는 조건을 만족하는 item이 과다하지만,
아래 정렬이 그대로 "starter seed item 중 고빈도부터"를 만든다. 분기를 두면 두
경로가 서로 다른 순서를 내고 첫 세션만 다른 규칙으로 도는 것을 아무도 눈치채지
못한다.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.learning.exposure import exposed_recently
from app.models.content import LearningItem
from app.models.learning import UserItemLearningState, UserMastery

# `difficulty_label`과 `starting_level`이 공유하는 단조 ladder. 06_LEARNING_ENGINE.md가
# 이 3단계를 canonical로 고정한다. label을 늘리려면 여기를 먼저 고친다.
LADDER: Mapping[str, int] = {"beginner": 0, "intermediate": 1, "advanced": 2}

# 정렬 tuple의 첫 칸. distance를 계산할 수 있는 item이 항상 앞이고, 알 수 없는
# label은 (알려진 label을 모두 소진한 뒤에만 선택되도록) 맨 뒤다.
_KNOWN_DISTANCE = 0
_UNKNOWN_DISTANCE: tuple[int, int] = (1, 0)

# frequency_key의 3단계. 두 값은 의미가 다르므로(언어 빈도 vs 파일 위치) 같은 숫자
# 공간에서 섞어 비교하지 않는다. 앞칸이 출처, 뒷칸이 그 출처 안에서의 순위다.
_FROM_FREQUENCY_RANK = 0
_FROM_SEED_ORDER = 1
_NO_FREQUENCY: tuple[int, int] = (2, 0)

ExplorationSortKey = tuple[tuple[int, int], tuple[int, int], int]


def difficulty_distance(label: str | None, starting_level: str) -> int | None:
    """ladder index 차이의 절댓값. 계산할 수 없으면 None이다.

    label이 NULL이거나 ladder에 없는 값이면 "거리가 크다"가 아니라 **모른다**이므로
    큰 수를 지어내지 않는다. 정렬에서 맨 뒤로 보내는 일은 호출부가 한다.
    """
    if label is None:
        return None
    item_rank = LADDER.get(label)
    user_rank = LADDER.get(starting_level)
    if item_rank is None or user_rank is None:
        return None
    return abs(item_rank - user_rank)


def frequency_key(metadata_json: Mapping[str, Any] | None) -> tuple[int, int]:
    """`metadata_json`에서 빈도 정렬 키를 뽑는다 (06_LEARNING_ENGINE.md).

    `learning_items`에 frequency 컬럼을 추가하지 않는다. 값이 정수가 아니면
    (문자열 / float / null) 그 단계를 쓸 수 없으므로 다음 단계로 강등한다 ---
    float을 int로 반올림하거나 문자열을 파싱하면 seed 파일의 오타가 조용히
    빈도 순서가 된다.

    `bool`은 `int`의 하위 타입이지만 빈도값이 아니므로 제외한다.
    """
    metadata = metadata_json or {}
    rank = metadata.get("frequency_rank")
    if isinstance(rank, int) and not isinstance(rank, bool):
        return (_FROM_FREQUENCY_RANK, rank)
    seed_order = metadata.get("seed_order")
    if isinstance(seed_order, int) and not isinstance(seed_order, bool):
        return (_FROM_SEED_ORDER, seed_order)
    return _NO_FREQUENCY


def exploration_sort_key(row: LearningItem, *, starting_level: str) -> ExplorationSortKey:
    """difficulty_distance ASC -> frequency_key ASC -> learning_item_id ASC."""
    distance = difficulty_distance(row.difficulty_label, starting_level)
    ranked = _UNKNOWN_DISTANCE if distance is None else (_KNOWN_DISTANCE, distance)
    return (ranked, frequency_key(row.metadata_json), row.id)


def eligible_exploration_targets(
    db: Session,
    *,
    user_id: int,
    item_ids: Iterable[int],
    now: datetime,
    recent_days: int,
) -> set[int]:
    """후보 조건 3개를 **모두** 만족하는 item id만 남긴다.

    조건 3의 판정 소스는 `item_exposures`다. denormalized cache인
    `review_states.meaningful_exposure_count`는 쓰지 않는다 --- 그 값은 무효화된
    exposure를 빼지 않고, 애초에 review_states 행이 없는 item에는 존재하지도 않는다.

    Ready Pool에 이미 있는 exploration candidate를 고를 때도 이 함수로 다시
    확인한다. candidate를 만든 뒤에 사용자가 그 item을 클릭해 학습 target으로
    승격시켰을 수 있다.
    """
    ids = list(dict.fromkeys(item_ids))
    if not ids:
        return set()

    # 조건 1: user_mastery 행이 없거나 comprehension_mastery IS NULL.
    # NULL은 "능력 0"이 아니라 "아직 evidence 없음"이므로 후보로 남는다.
    measured = db.execute(
        sa.select(UserMastery.learning_item_id).where(
            UserMastery.user_id == user_id,
            UserMastery.learning_item_id.in_(ids),
            UserMastery.comprehension_mastery.is_not(None),
        )
    ).scalars()

    # 조건 2: 이미 정식 학습 대상으로 승격된 item을 exploration으로 다시 잡지 않는다.
    active = db.execute(
        sa.select(UserItemLearningState.learning_item_id).where(
            UserItemLearningState.user_id == user_id,
            UserItemLearningState.learning_item_id.in_(ids),
            UserItemLearningState.is_active_learning_target.is_(True),
        )
    ).scalars()

    # 조건 3: 최근 recent_days 안에 노출되지 않음.
    recent = exposed_recently(
        db,
        user_id=user_id,
        learning_item_ids=ids,
        since=now - timedelta(days=recent_days),
    )

    return set(ids) - set(measured) - set(active) - recent
