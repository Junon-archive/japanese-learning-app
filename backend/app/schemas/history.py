"""History endpoint 스키마 (05_API_SPEC.md의 `History`).

`app/schemas/study.py`와 같은 규약을 따른다: id는 전부 JSON number이고(ADR-005),
timestamp는 UTC ISO-8601(`UtcTimestamp`)이다. 직렬화기를 복제하지 않고 study 스키마의
것을 그대로 쓴다 --- 둘로 갈리면 같은 컬럼이 endpoint마다 다른 문자열로 나간다.

**집계 필드를 더하지 않는다.** 통계·차트·기간 선택·item별 상세는 MVP 밖이다
(00_SCOPE.md의 `advanced analytics`).
"""

from __future__ import annotations

from pydantic import BaseModel

from app.models.enums import LearningItemType
from app.schemas.study import UtcTimestamp


class HistorySessionPayload(BaseModel):
    """진행 중인 session은 `ended_at`이 `null`이다. 목록에서 빼지 않는다."""

    session_id: int
    started_at: UtcTimestamp
    ended_at: UtcTimestamp | None
    active_seconds: int
    target_minutes: int
    extended_minutes: int
    completed_sentence_count: int


class HistorySessionsResponse(BaseModel):
    """`truncated`는 고정 상한에 걸려 오래된 행이 잘렸다는 뜻이다(05_API_SPEC.md).

    총 개수를 담지 않는다. 화면은 "잘렸다"만 알리면 되고, `total`을 내보내면
    pagination을 만들라는 압력이 된다 --- 명세는 pagination을 금지했다.
    """

    sessions: list[HistorySessionPayload]
    truncated: bool


class HistoryItemPayload(BaseModel):
    """`comprehension_mastery`가 `null`이면 "아직 evidence 없음"이다. 0이 아니다."""

    learning_item_id: int
    lemma: str
    item_type: LearningItemType
    comprehension_mastery: float | None
    exposure_count: int
    next_review_at: UtcTimestamp | None


class HistoryItemsResponse(BaseModel):
    items: list[HistoryItemPayload]
    truncated: bool
