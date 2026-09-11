"""Meaningful exposure 기록 (불변식 #5, 07_SRS_SPEC.md).

`item_exposures`가 canonical source다. `review_states.meaningful_exposure_count`는
캐시일 뿐이며 이 모듈이 아니라 exposure를 기록하는 service가 소유한다(ADR-007).

같은 presentation의 같은 item은 최대 1회다. click / explanation reveal /
self-report를 각각 세면 최소 5회 노출이 조기 충족되어 reinforcement가 사라진다.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.enums import ExposureModality
from app.models.study import ItemExposure, StudyPresentation


def record_meaningful_exposure(
    db: Session,
    *,
    presentation: StudyPresentation,
    target_item_ids: Iterable[int],
    now: datetime,
) -> int:
    """이 presentation의 target item들에 exposure를 1회씩 남기고 삽입된 수를 반환한다.

    중복은 `ON CONFLICT (study_presentation_id, learning_item_id) DO NOTHING`으로
    조용히 무시된다. 애플리케이션이 먼저 조회해 거르지 않고 **DB unique에 기댄다**
    --- 조회 후 삽입은 같은 presentation에 대한 재시도/동시 요청에서 경합하고,
    그때 터지는 IntegrityError는 호출부의 트랜잭션 전체를 무효로 만든다.

    `created_at`은 주입된 `now`다. DB 시계를 쓰면 `exploration_recent_days` 판정과
    시계가 갈려 시간 기반 테스트가 거짓 통과한다(ADR-007).
    """
    # dict로 중복을 제거한다. 같은 배치 안의 중복은 ON CONFLICT가 잡지 못한다
    # (PostgreSQL은 한 INSERT 안의 중복 행에 대해 여전히 에러를 낸다).
    unique_item_ids = list(dict.fromkeys(target_item_ids))
    if not unique_item_ids:
        return 0

    statement = (
        pg_insert(ItemExposure)
        .values(
            [
                {
                    "user_id": presentation.user_id,
                    "learning_item_id": item_id,
                    "study_presentation_id": presentation.id,
                    "sentence_id": presentation.sentence_id,
                    "modality": ExposureModality.READING,
                    "context_stage": presentation.context_stage,
                    "created_at": now,
                }
                for item_id in unique_item_ids
            ]
        )
        .on_conflict_do_nothing(index_elements=["study_presentation_id", "learning_item_id"])
        .returning(ItemExposure.id)
    )
    inserted = db.execute(statement).scalars().all()
    return len(inserted)


def invalidate_presentation_exposures(
    db: Session, *, presentation_id: int, now: datetime
) -> list[int]:
    """content flag/quarantine 시 그 presentation의 exposure를 무효화한다.

    행을 지우지 않는다. `item_exposures`는 immutable log이고, 무효화는 삭제가 아니라
    `invalidated_at`으로 표현한다(10_ERROR_HANDLING.md). 이미 무효화된 행은 시각을
    덮어쓰지 않는다.

    무효화된 item id 목록을 반환한다 --- 호출한 service가 캐시 카운터를 다시 계산해야
    한다.
    """
    statement = (
        sa.update(ItemExposure)
        .where(
            ItemExposure.study_presentation_id == presentation_id,
            ItemExposure.invalidated_at.is_(None),
        )
        .values(invalidated_at=now)
        .returning(ItemExposure.learning_item_id)
        # 세션에 남은 ORM 인스턴스를 동기화하지 않는다. 유효 exposure 수는 항상
        # `count_valid_exposures`로 다시 질의한다.
        .execution_options(synchronize_session=False)
    )
    return list(db.execute(statement).scalars().all())


def count_valid_exposures(db: Session, *, user_id: int, learning_item_id: int) -> int:
    """무효화되지 않은 exposure만 센다. 최소 5회 판정이 이 값을 쓴다."""
    count = db.execute(
        sa.select(sa.func.count())
        .select_from(ItemExposure)
        .where(
            ItemExposure.user_id == user_id,
            ItemExposure.learning_item_id == learning_item_id,
            ItemExposure.invalidated_at.is_(None),
        )
    ).scalar_one()
    return int(count)


def exposed_recently(
    db: Session, *, user_id: int, learning_item_ids: Iterable[int], since: datetime
) -> set[int]:
    """`since` 이후에 노출된 item id 집합. exploration 후보 조건 3이 쓴다.

    `since`는 호출부가 주입된 `now`에서 계산한다(`now - exploration_recent_days`).
    """
    item_ids = list(dict.fromkeys(learning_item_ids))
    if not item_ids:
        return set()

    rows = db.execute(
        sa.select(ItemExposure.learning_item_id)
        .where(
            ItemExposure.user_id == user_id,
            ItemExposure.learning_item_id.in_(item_ids),
            ItemExposure.created_at >= since,
            ItemExposure.invalidated_at.is_(None),
        )
        .distinct()
    ).scalars()
    return set(rows)
