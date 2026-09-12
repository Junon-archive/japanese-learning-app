"""SQLAlchemy 모델. Alembic이 `Base.metadata`를 쓰므로 전 모델을 여기서 import한다."""

from __future__ import annotations

from app.models.base import Base
from app.models.content import (
    ContentFlag,
    LearningItem,
    Sentence,
    SentenceItem,
    SentenceItemExplanation,
    SentenceItemSpan,
)
from app.models.jobs import GenerationJob, PromptVersion, WorkerHeartbeat
from app.models.learning import (
    ReviewState,
    UserItemLearningState,
    UserMastery,
    UserSentenceCandidate,
    UserSentenceCandidateTarget,
)
from app.models.study import (
    ItemExposure,
    LearningEvent,
    StudyPresentation,
    StudySession,
)
from app.models.user import AuthSession, User

__all__ = [
    "AuthSession",
    "Base",
    "ContentFlag",
    "GenerationJob",
    "ItemExposure",
    "LearningEvent",
    "LearningItem",
    "PromptVersion",
    "ReviewState",
    "Sentence",
    "SentenceItem",
    "SentenceItemExplanation",
    "SentenceItemSpan",
    "StudyPresentation",
    "StudySession",
    "User",
    "UserItemLearningState",
    "UserMastery",
    "UserSentenceCandidate",
    "UserSentenceCandidateTarget",
    "WorkerHeartbeat",
]
