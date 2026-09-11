"""사용자별 학습 상태: mastery, FSRS 스케줄, context progression, Ready Pool."""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, bigint_pk, created_at_column, enum_column
from app.models.enums import CandidateStatus, ContextStage, PresentationRole, ReviewReason


class UserMastery(Base):
    """NULL은 "능력이 0"이 아니라 "아직 충분한 evidence가 없음"이다.

    따라서 boolean Known/Unknown으로 구현하지 않는다(02_LEARNING_POLICY.md).
    """

    __tablename__ = "user_mastery"

    id: Mapped[int] = bigint_pk()
    user_id: Mapped[int] = mapped_column(sa.BigInteger, sa.ForeignKey("users.id"), nullable=False)
    learning_item_id: Mapped[int] = mapped_column(
        sa.BigInteger, sa.ForeignKey("learning_items.id"), nullable=False
    )
    comprehension_mastery: Mapped[float | None] = mapped_column(sa.Double)
    # MVP에서는 항상 NULL이다. 갱신하지 않는다.
    listening_mastery: Mapped[float | None] = mapped_column(sa.Double)
    # mastery update에 실제 사용된 explicit evidence 개수.
    # meaningful exposure count와 다른 값이다.
    evidence_count: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.text("0")
    )
    mastery_algorithm_version: Mapped[str] = mapped_column(sa.Text, nullable=False)
    last_updated_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)

    __table_args__ = (
        sa.UniqueConstraint("user_id", "learning_item_id"),
        sa.CheckConstraint(
            "comprehension_mastery IS NULL "
            "OR (comprehension_mastery >= 0.0 AND comprehension_mastery <= 1.0)",
            name="comprehension_mastery_range",
        ),
        sa.CheckConstraint(
            "listening_mastery IS NULL OR (listening_mastery >= 0.0 AND listening_mastery <= 1.0)",
            name="listening_mastery_range",
        ),
    )


class ReviewState(Base):
    """FSRS scheduling 상태. mastery score와 별도 테이블이다(ADR-003).

    `Card`는 매 review마다 이 컬럼들에서 재구성한다. `card_id`와 `scheduled_days`는
    저장하지 않는다.
    """

    __tablename__ = "review_states"

    id: Mapped[int] = bigint_pk()
    user_id: Mapped[int] = mapped_column(sa.BigInteger, sa.ForeignKey("users.id"), nullable=False)
    learning_item_id: Mapped[int] = mapped_column(
        sa.BigInteger, sa.ForeignKey("learning_items.id"), nullable=False
    )
    stability: Mapped[float | None] = mapped_column(sa.Double)
    difficulty: Mapped[float | None] = mapped_column(sa.Double)
    # fsrs 6 열거값: 1 = Learning, 2 = Review, 3 = Relearning.
    state: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False)
    # learning/relearning step index. state = Review이면 NULL이다.
    step: Mapped[int | None] = mapped_column(sa.Integer)
    last_review_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    # Card.due. 스케줄은 절대시각으로만 저장한다.
    next_review_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    # FSRS가 주는 값이 아니라 애플리케이션이 유지하는 카운터다(ADR-003).
    reps: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default=sa.text("0"))
    lapses: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default=sa.text("0"))
    fsrs_params_version: Mapped[str] = mapped_column(sa.Text, nullable=False)
    # 무신호 passive review 후 단기 재노출 방지. FSRS memory state와 무관하다.
    deferred_until: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    # denormalized cache. canonical source는 item_exposures다.
    meaningful_exposure_count: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.text("0")
    )

    __table_args__ = (
        sa.UniqueConstraint("user_id", "learning_item_id"),
        sa.CheckConstraint("state IN (1, 2, 3)", name="state_enum"),
        sa.Index("ix_review_states_user_id_next_review_at", "user_id", "next_review_at"),
    )


class UserItemLearningState(Base):
    """Context progression과 probe 상태."""

    __tablename__ = "user_item_learning_state"

    id: Mapped[int] = bigint_pk()
    user_id: Mapped[int] = mapped_column(sa.BigInteger, sa.ForeignKey("users.id"), nullable=False)
    learning_item_id: Mapped[int] = mapped_column(
        sa.BigInteger, sa.ForeignKey("learning_items.id"), nullable=False
    )
    # 최초 학습 문맥.
    anchor_sentence_id: Mapped[int | None] = mapped_column(
        sa.BigInteger, sa.ForeignKey("sentences.id")
    )
    context_stage: Mapped[ContextStage] = mapped_column(
        enum_column(ContextStage, "context_stage"), nullable=False
    )
    passive_no_signal_count: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.text("0")
    )
    last_probe_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    probe_skip_count: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.text("0")
    )
    # incidental click에서 승격되었는지 포함한다.
    is_active_learning_target: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.text("false")
    )
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)

    __table_args__ = (sa.UniqueConstraint("user_id", "learning_item_id"),)


class UserSentenceCandidate(Base):
    """Ready Pool은 이 테이블의 `status = ready` 집합이다."""

    __tablename__ = "user_sentence_candidates"

    id: Mapped[int] = bigint_pk()
    user_id: Mapped[int] = mapped_column(sa.BigInteger, sa.ForeignKey("users.id"), nullable=False)
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
    status: Mapped[CandidateStatus] = mapped_column(
        enum_column(CandidateStatus, "status"), nullable=False
    )
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)

    __table_args__ = (
        sa.Index(
            "ix_user_sentence_candidates_user_id_status_role",
            "user_id",
            "status",
            "presentation_role",
        ),
    )


class UserSentenceCandidateTarget(Base):
    """문장당 target item 1~2개."""

    __tablename__ = "user_sentence_candidate_targets"

    id: Mapped[int] = bigint_pk()
    candidate_id: Mapped[int] = mapped_column(
        sa.BigInteger, sa.ForeignKey("user_sentence_candidates.id"), nullable=False
    )
    learning_item_id: Mapped[int] = mapped_column(
        sa.BigInteger, sa.ForeignKey("learning_items.id"), nullable=False
    )
    is_new_item: Mapped[bool] = mapped_column(sa.Boolean, nullable=False)

    __table_args__ = (sa.UniqueConstraint("candidate_id", "learning_item_id"),)
