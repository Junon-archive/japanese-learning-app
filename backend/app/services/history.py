"""기본 history 조회 (05_API_SPEC.md의 `History`).

**읽기 전용이다.** 행을 만들지 않고, event를 남기지 않으며, `touch()`를 부르지
않는다. 조회가 `active_seconds`를 올리면 기록을 보는 행위가 학습 시간으로 집계된다.
commit도 하지 않는다 --- 쓰기가 없으므로 닫을 트랜잭션이 없다.

정책 판단이 없으므로 `app.learning` / `app.srs`를 보지 않고 `AppConfig`도 받지 않는다.
시각도 받지 않는다: 두 목록 모두 저장된 값을 그대로 내보내고 "지금"과 비교하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.models.content import LearningItem
from app.models.enums import LearningItemType
from app.models.learning import ReviewState, UserItemLearningState, UserMastery
from app.models.study import ItemExposure, StudyPresentation, StudySession

# 05_API_SPEC.md의 `개수 상한`. 두 endpoint 공통이고 고정이다. **학습 정책값이 아니라
# 응답 계약 상수이므로 `14_CONFIGURATION.md`에 두지 않는다** --- 실사용 관찰로
# 조정하는 파라미터가 아니고, 바꾸면 화면 계약이 바뀐다(`PROBE_PROMPT`와 같은 취급).
#
# pagination·기간 필터·정렬 옵션을 두지 않는다. 상한을 넘으면 오래된 것부터 잘리고,
# 잘렸다는 사실은 화면이 문구로 알린다(03_UI_UX_SPEC.md의 `History`).
HISTORY_LIMIT = 50

# 잘림 판정은 `HISTORY_LIMIT + 1`건을 조회해 **51번째 행의 존재**로 한다. 반환은
# 여전히 50건이다(05_API_SPEC.md).
#
# `COUNT(*)`를 쓰지 않는 이유: 전체 개수는 화면이 쓰지 않는데, 행이 많은 사용자는 매
# 조회마다 전수 카운트를 치른다. `len(rows) == HISTORY_LIMIT`으로 판정하지 않는 이유:
# 정확히 50건뿐인 사용자와 구분되지 않아 **잘리지 않았는데 잘렸다고** 표시된다.
_PROBE_LIMIT = HISTORY_LIMIT + 1


@dataclass(frozen=True)
class SessionHistoryRow:
    """`study_sessions` 한 행의 history 표시값.

    `policy_snapshot_json`과 `summary_json`이 없다. 전자는 설정값 묶음이고(사용자에게
    정책값을 노출하지 않는다), 후자는 MVP에 채우는 경로가 없다(05_API_SPEC.md).
    """

    session_id: int
    started_at: datetime
    ended_at: datetime | None
    active_seconds: int
    target_minutes: int
    extended_minutes: int
    completed_sentence_count: int


@dataclass(frozen=True)
class ItemHistoryRow:
    """학습·복습한 item 하나의 history 표시값.

    `comprehension_mastery`와 `next_review_at`은 해당 행이 없으면 `None`이다. `None`은
    "아직 evidence 없음"이며 0으로 바꿔 내리지 않는다(02_LEARNING_POLICY.md).
    `listening_mastery`는 싣지 않는다 --- MVP에서 항상 NULL이다.
    """

    learning_item_id: int
    lemma: str
    item_type: LearningItemType
    comprehension_mastery: float | None
    exposure_count: int
    next_review_at: datetime | None


@dataclass(frozen=True)
class SessionHistory:
    """`GET /api/history/sessions`가 돌려줄 것. 행은 최대 `HISTORY_LIMIT`개다.

    `total`을 담지 않는다. 화면이 쓰지 않고, 내보내면 pagination을 만들라는 압력이
    된다 --- 명세는 pagination을 금지했다(05_API_SPEC.md의 `개수 상한`).
    """

    sessions: list[SessionHistoryRow]
    truncated: bool


@dataclass(frozen=True)
class ItemHistory:
    """`GET /api/history/items`가 돌려줄 것. 행은 최대 `HISTORY_LIMIT`개다."""

    items: list[ItemHistoryRow]
    truncated: bool


def recent_sessions(db: Session, *, user_id: int) -> SessionHistory:
    """최근 session 요약. 아직 열려 있는 session도 포함한다(`ended_at`이 `None`이다).

    빼면 오늘 진행 중인 세션이 기록에서 사라진다.

    `completed_sentence_count`는 `completed_at IS NOT NULL`인 presentation만 센다.
    idle timeout으로 닫힌 session에는 영원히 미완료로 남는 행이 있고, 그것을 세면
    **보지 않고 떠난 문장이 학습 기록이 된다**(05_API_SPEC.md).
    """
    completed_sentence_count = (
        sa.select(sa.func.count())
        .select_from(StudyPresentation)
        .where(
            StudyPresentation.study_session_id == StudySession.id,
            StudyPresentation.completed_at.is_not(None),
        )
        .scalar_subquery()
    )
    statement = (
        sa.select(StudySession, completed_sentence_count)
        .where(StudySession.user_id == user_id)
        # 두 번째 키가 없으면 같은 시각의 두 행 순서가 실행마다 달라져 화면이 흔들린다.
        .order_by(StudySession.started_at.desc(), StudySession.id.desc())
        .limit(_PROBE_LIMIT)
    )
    rows = db.execute(statement).all()
    return SessionHistory(
        sessions=[
            SessionHistoryRow(
                session_id=session.id,
                started_at=session.started_at,
                ended_at=session.ended_at,
                active_seconds=session.active_seconds,
                target_minutes=session.target_minutes,
                extended_minutes=session.extended_minutes,
                completed_sentence_count=count,
            )
            for session, count in rows[:HISTORY_LIMIT]
        ],
        truncated=len(rows) > HISTORY_LIMIT,
    )


def recent_items(db: Session, *, user_id: int) -> ItemHistory:
    """학습·복습한 item 요약. 목록 대상은 `user_item_learning_state` 행이다.

    그 행은 item이 target으로 제시되었을 때나 explicit evidence를 받았을 때 생기므로,
    눌러만 보고 지나간 item은 들어오지 않는다(05_API_SPEC.md). `user_mastery`나
    `review_states`가 없어도 목록에서 빠지지 않는다 --- 그래서 outer join이다.

    `exposure_count`는 cache(`review_states.meaningful_exposure_count`)가 아니라
    canonical source인 `item_exposures`를 센다. flag 직후 cache 재계산이 어긋난 창에서
    무효화된 노출이 그대로 보이기 때문이다(07_SRS_SPEC.md의 `Meaningful Exposure 정의`).
    """
    exposure_count = (
        sa.select(sa.func.count())
        .select_from(ItemExposure)
        .where(
            ItemExposure.user_id == UserItemLearningState.user_id,
            ItemExposure.learning_item_id == UserItemLearningState.learning_item_id,
            ItemExposure.invalidated_at.is_(None),
        )
        .scalar_subquery()
    )
    statement = (
        sa.select(
            UserItemLearningState.learning_item_id,
            LearningItem.lemma,
            LearningItem.type,
            UserMastery.comprehension_mastery,
            exposure_count,
            ReviewState.next_review_at,
        )
        .join(LearningItem, LearningItem.id == UserItemLearningState.learning_item_id)
        .outerjoin(
            UserMastery,
            sa.and_(
                UserMastery.user_id == UserItemLearningState.user_id,
                UserMastery.learning_item_id == UserItemLearningState.learning_item_id,
            ),
        )
        .outerjoin(
            ReviewState,
            sa.and_(
                ReviewState.user_id == UserItemLearningState.user_id,
                ReviewState.learning_item_id == UserItemLearningState.learning_item_id,
            ),
        )
        .where(UserItemLearningState.user_id == user_id)
        .order_by(
            UserItemLearningState.updated_at.desc(),
            UserItemLearningState.learning_item_id.desc(),
        )
        .limit(_PROBE_LIMIT)
    )
    rows = db.execute(statement).all()
    return ItemHistory(
        items=[
            ItemHistoryRow(
                learning_item_id=learning_item_id,
                lemma=lemma,
                item_type=item_type,
                comprehension_mastery=comprehension_mastery,
                exposure_count=count,
                next_review_at=next_review_at,
            )
            for (
                learning_item_id,
                lemma,
                item_type,
                comprehension_mastery,
                count,
                next_review_at,
            ) in rows[:HISTORY_LIMIT]
        ],
        truncated=len(rows) > HISTORY_LIMIT,
    )
