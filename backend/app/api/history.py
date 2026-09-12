"""History endpoint (05_API_SPEC.md의 `History`).

인증과 Origin 검증은 이 모듈이 붙이지 않는다. `app.api.router`가 `api_router`에
올리면서 router 레벨 dependency로 건다.

**대상 사용자를 지정하는 파라미터를 받지 않는다.** 받지 않으면 권한 검사를 빠뜨릴
자리 자체가 없다 --- 두 목록은 언제나 `current_user.id`의 행만 담는다.

`app.learning` / `app.srs`를 import하지 않는다(G2). 여기에는 정책 판단이 없다.
`Depends(get_now)`도 받지 않는다 --- 두 목록은 저장된 값을 그대로 내보내고 "지금"과
비교하지 않으므로 시각이 필요 없다.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.schemas.history import (
    HistoryItemPayload,
    HistoryItemsResponse,
    HistorySessionPayload,
    HistorySessionsResponse,
)
from app.services import history

CurrentUser = Annotated[User, Depends(get_current_user)]
Db = Annotated[Session, Depends(get_db)]

router = APIRouter(prefix="/api/history", tags=["history"])


@router.get("/sessions")
def read_session_history(current_user: CurrentUser, db: Db) -> HistorySessionsResponse:
    """최근 session 요약. 읽기 전용이며 `last_activity_at`을 건드리지 않는다."""
    history_view = history.recent_sessions(db, user_id=current_user.id)
    return HistorySessionsResponse(
        sessions=[
            HistorySessionPayload(
                session_id=row.session_id,
                started_at=row.started_at,
                ended_at=row.ended_at,
                active_seconds=row.active_seconds,
                target_minutes=row.target_minutes,
                extended_minutes=row.extended_minutes,
                completed_sentence_count=row.completed_sentence_count,
            )
            for row in history_view.sessions
        ],
        truncated=history_view.truncated,
    )


@router.get("/items")
def read_item_history(current_user: CurrentUser, db: Db) -> HistoryItemsResponse:
    """학습·복습한 item 요약. 읽기 전용이다."""
    history_view = history.recent_items(db, user_id=current_user.id)
    return HistoryItemsResponse(
        items=[
            HistoryItemPayload(
                learning_item_id=row.learning_item_id,
                lemma=row.lemma,
                item_type=row.item_type,
                comprehension_mastery=row.comprehension_mastery,
                exposure_count=row.exposure_count,
                next_review_at=row.next_review_at,
            )
            for row in history_view.items
        ],
        truncated=history_view.truncated,
    )
