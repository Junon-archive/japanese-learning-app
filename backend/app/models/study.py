"""학습 세션, presentation, exposure, immutable event log."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, bigint_pk, created_at_column, enum_column
from app.models.enums import (
    ContextStage,
    EventType,
    ExposureModality,
    PresentationRole,
    ReviewReason,
)


class StudySession(Base):
    __tablename__ = "study_sessions"

    id: Mapped[int] = bigint_pk()
    user_id: Mapped[int] = mapped_column(sa.BigInteger, sa.ForeignKey("users.id"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    last_activity_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    # interaction interval 기반 active time. 긴 idle gap은 제외한다.
    active_seconds: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.text("0")
    )
    # 기본값(default_session_minutes)은 14_CONFIGURATION.md가 canonical이다.
    target_minutes: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    extended_minutes: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.text("0")
    )
    # 해당 세션에 적용된 config/policy 값.
    policy_snapshot_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
    )
    summary_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
    )

    __table_args__ = (sa.Index("ix_study_sessions_user_id_started_at", "user_id", "started_at"),)


class StudyPresentation(Base):
    """어떤 문장을 어떤 이유로 보여줬는지의 기록."""

    __tablename__ = "study_presentations"

    id: Mapped[int] = bigint_pk()
    study_session_id: Mapped[int] = mapped_column(
        sa.BigInteger, sa.ForeignKey("study_sessions.id"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(sa.BigInteger, sa.ForeignKey("users.id"), nullable=False)
    candidate_id: Mapped[int] = mapped_column(
        sa.BigInteger, sa.ForeignKey("user_sentence_candidates.id"), nullable=False
    )
    sentence_id: Mapped[int] = mapped_column(
        sa.BigInteger, sa.ForeignKey("sentences.id"), nullable=False
    )
    presentation_role: Mapped[PresentationRole] = mapped_column(
        enum_column(PresentationRole, "presentation_role"), nullable=False
    )
    review_reason: Mapped[ReviewReason | None] = mapped_column(
        enum_column(ReviewReason, "review_reason")
    )
    context_stage: Mapped[ContextStage] = mapped_column(
        enum_column(ContextStage, "context_stage"), nullable=False
    )
    shown_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))

    __table_args__ = (
        sa.Index("ix_study_presentations_study_session_id", "study_session_id"),
        sa.Index("ix_study_presentations_user_id_shown_at", "user_id", "shown_at"),
    )


class ItemExposure(Base):
    """meaningful exposure의 canonical source. immutable log다.

    무효화는 UPDATE로 의미를 바꾸지 않고 `invalidated_at`으로 표현한다.
    """

    __tablename__ = "item_exposures"

    id: Mapped[int] = bigint_pk()
    user_id: Mapped[int] = mapped_column(sa.BigInteger, sa.ForeignKey("users.id"), nullable=False)
    learning_item_id: Mapped[int] = mapped_column(
        sa.BigInteger, sa.ForeignKey("learning_items.id"), nullable=False
    )
    study_presentation_id: Mapped[int] = mapped_column(
        sa.BigInteger, sa.ForeignKey("study_presentations.id"), nullable=False
    )
    sentence_id: Mapped[int] = mapped_column(
        sa.BigInteger, sa.ForeignKey("sentences.id"), nullable=False
    )
    modality: Mapped[ExposureModality] = mapped_column(
        enum_column(ExposureModality, "modality"), nullable=False
    )
    context_stage: Mapped[ContextStage] = mapped_column(
        enum_column(ContextStage, "context_stage"), nullable=False
    )
    created_at: Mapped[datetime] = created_at_column()
    # content flag/quarantine 시 재계산에서 제외한다.
    invalidated_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))

    __table_args__ = (
        # 한 presentation의 같은 item은 최대 1 exposure다(불변식 5). 이 unique가
        # 없으면 click/explanation reveal/self-report가 각각 집계되어 minimum 5
        # exposure가 조기 충족되고 reinforcement가 사라진다.
        sa.UniqueConstraint("study_presentation_id", "learning_item_id"),
        # exploration 후보 조건 3(최근 노출 여부) 조회용.
        sa.Index(
            "ix_item_exposures_user_id_learning_item_id_created_at",
            "user_id",
            "learning_item_id",
            "created_at",
        ),
    )


class LearningEvent(Base):
    """Immutable raw history. mastery 알고리즘이 바뀌어도 replay할 수 있게 원본을 남긴다."""

    __tablename__ = "learning_events"

    id: Mapped[int] = bigint_pk()
    user_id: Mapped[int] = mapped_column(sa.BigInteger, sa.ForeignKey("users.id"), nullable=False)
    study_session_id: Mapped[int] = mapped_column(
        sa.BigInteger, sa.ForeignKey("study_sessions.id"), nullable=False
    )
    study_presentation_id: Mapped[int | None] = mapped_column(
        sa.BigInteger, sa.ForeignKey("study_presentations.id")
    )
    sentence_id: Mapped[int | None] = mapped_column(sa.BigInteger, sa.ForeignKey("sentences.id"))
    learning_item_id: Mapped[int | None] = mapped_column(
        sa.BigInteger, sa.ForeignKey("learning_items.id")
    )
    event_type: Mapped[EventType] = mapped_column(
        enum_column(EventType, "event_type"), nullable=False
    )
    payload_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
    )
    # idempotency용 client 생성 UUID. 텍스트로 두면 대소문자 차이로 idempotency가
    # 깨지므로 uuid 타입을 쓴다(불변식 10).
    client_event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        sa.UniqueConstraint("user_id", "client_event_id"),
        sa.Index("ix_learning_events_user_id_created_at", "user_id", "created_at"),
    )
