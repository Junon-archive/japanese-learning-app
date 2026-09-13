"""Global content: learning item, sentence, annotation, explanation, content flag.

Sentence는 global content entity다. "이 사용자에게 지금 어떤 목적으로 보여주는가"는
`user_sentence_candidates`와 `study_presentations`가 가진다(04_DB_SPEC.md).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, bigint_pk, created_at_column, enum_column
from app.models.enums import (
    ContentFlagReason,
    ExplanationStatus,
    LearningItemOrigin,
    LearningItemType,
    SentenceSourceType,
    SentenceStatus,
)


class LearningItem(Base):
    __tablename__ = "learning_items"

    id: Mapped[int] = bigint_pk()
    type: Mapped[LearningItemType] = mapped_column(
        enum_column(LearningItemType, "type"), nullable=False
    )
    lemma: Mapped[str] = mapped_column(sa.Text, nullable=False)
    reading: Mapped[str] = mapped_column(sa.Text, nullable=False)
    # canonical/default 의미. 문맥 의미는 sentence_item_explanations에 있다.
    default_meaning: Mapped[str] = mapped_column(sa.Text, nullable=False)
    # CHECK를 두지 않는다. 06_LEARNING_ENGINE.md가 ladder 밖 값을 "정렬 맨 뒤"로
    # 명시적으로 전제하므로 DB에서 막으면 그 분기가 도달 불가능해진다.
    difficulty_label: Mapped[str | None] = mapped_column(sa.Text)
    topic_tags: Mapped[list[str] | None] = mapped_column(sa.ARRAY(sa.Text))
    origin: Mapped[LearningItemOrigin] = mapped_column(
        enum_column(LearningItemOrigin, "origin"), nullable=False
    )
    # frequency_rank는 여기 담는다. frequency 전용 컬럼을 만들지 않는다
    # (06_LEARNING_ENGINE.md). 파이썬 속성명을 `metadata`로 두면 declarative
    # 예약 속성과 충돌해 import 시점에 터진다.
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = created_at_column()


class Sentence(Base):
    """`user_id`도, 사용자별 role도 두지 않는다(불변식 11)."""

    __tablename__ = "sentences"

    id: Mapped[int] = bigint_pk()
    japanese: Mapped[str] = mapped_column(sa.Text, nullable=False)
    korean_translation: Mapped[str] = mapped_column(sa.Text, nullable=False)
    source_type: Mapped[SentenceSourceType] = mapped_column(
        enum_column(SentenceSourceType, "source_type"), nullable=False
    )
    source_id: Mapped[str | None] = mapped_column(sa.Text)
    difficulty_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
    )
    # model / provider / prompt_version / generated_at / parent_sentence_id
    provenance_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
    )
    generation_job_id: Mapped[int | None] = mapped_column(
        sa.BigInteger, sa.ForeignKey("generation_jobs.id")
    )
    # review context 재생성 lineage
    parent_sentence_id: Mapped[int | None] = mapped_column(
        sa.BigInteger, sa.ForeignKey("sentences.id")
    )
    # duplicate 검출용 정규화 해시. 유사도 기반 판정이므로 unique가 아니다.
    normalized_hash: Mapped[str] = mapped_column(sa.Text, nullable=False)
    status: Mapped[SentenceStatus] = mapped_column(
        enum_column(SentenceStatus, "status"), nullable=False
    )
    # 후리가나 표시 보조(MVP-02, ADR-021 결정 2). NULL = 미계산이며 backfill 대상이다.
    # server default를 두지 않는다: `'{}'`나 `spans: []`가 기본값이면 "계산했고 달 읽기가
    # 없다"와 "계산하지 않았다"가 구별되지 않는다. 무결성은 다른 테이블과 대조해야 하므로
    # CHECK도 두지 않는다(`app/render.py`의 검증이 계산·표시 시점에 본다).
    # `none_as_null=True`: Python `None`을 JSON `null`이 아니라 **SQL NULL**로 쓴다. 기본값(False)이면
    # 계산 실패로 `ruby_json=None`을 넣은 행이 `'null'::jsonb`가 되어 `ruby_json IS NULL`(backfill
    # 대상, 미계산 잔량 조회)에 걸리지 않는다. DDL은 바뀌지 않는다.
    ruby_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (sa.Index("ix_sentences_normalized_hash", "normalized_hash"),)


class SentenceItem(Base):
    """Sentence와 LearningItem의 언어적 annotation.

    `role` 컬럼을 두지 않는다. new/review/exploration은 사용자별·시점별 속성이며
    v0.2의 `role = incidental` 설계는 제거되었다(04_DB_SPEC.md).
    """

    __tablename__ = "sentence_items"

    id: Mapped[int] = bigint_pk()
    sentence_id: Mapped[int] = mapped_column(
        sa.BigInteger, sa.ForeignKey("sentences.id"), nullable=False
    )
    learning_item_id: Mapped[int] = mapped_column(
        sa.BigInteger, sa.ForeignKey("learning_items.id"), nullable=False
    )
    surface_form: Mapped[str] = mapped_column(sa.Text, nullable=False)
    is_tappable: Mapped[bool] = mapped_column(sa.Boolean, nullable=False)
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        sa.Index("ix_sentence_items_sentence_id", "sentence_id"),
        sa.Index("ix_sentence_items_learning_item_id", "learning_item_id"),
    )


class SentenceItemSpan(Base):
    """Offset 기준은 Unicode code point index다. byte도 UTF-16 code unit도 아니다.

    불연속 표현(`気が全然乗らない`)은 여러 span row로 표현하므로 span 간 overlap
    금지 제약(EXCLUDE)을 두지 않는다. overlap 검증은 생성 validation 소관이다.
    """

    __tablename__ = "sentence_item_spans"

    id: Mapped[int] = bigint_pk()
    sentence_item_id: Mapped[int] = mapped_column(
        sa.BigInteger, sa.ForeignKey("sentence_items.id"), nullable=False
    )
    start_codepoint: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    end_codepoint: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    span_order: Mapped[int] = mapped_column(sa.Integer, nullable=False)

    __table_args__ = (
        sa.CheckConstraint(
            "start_codepoint >= 0 AND end_codepoint > start_codepoint",
            name="codepoint_range",
        ),
        sa.UniqueConstraint("sentence_item_id", "span_order"),
    )


class SentenceItemExplanation(Base):
    """tap 시 표시할 문맥 설명의 저장소.

    `meaning_in_context`는 이 문장에서의 의미이며
    `learning_items.default_meaning`(canonical 의미)과 섞지 않는다.
    """

    __tablename__ = "sentence_item_explanations"

    id: Mapped[int] = bigint_pk()
    sentence_item_id: Mapped[int] = mapped_column(
        sa.BigInteger, sa.ForeignKey("sentence_items.id"), nullable=False
    )
    reading: Mapped[str] = mapped_column(sa.Text, nullable=False)
    core_meaning: Mapped[str] = mapped_column(sa.Text, nullable=False)
    meaning_in_context: Mapped[str] = mapped_column(sa.Text, nullable=False)
    nuance: Mapped[str] = mapped_column(sa.Text, nullable=False)
    example_sentence: Mapped[str] = mapped_column(sa.Text, nullable=False)
    example_translation: Mapped[str | None] = mapped_column(sa.Text)
    provider: Mapped[str | None] = mapped_column(sa.Text)
    model: Mapped[str | None] = mapped_column(sa.Text)
    prompt_version: Mapped[str | None] = mapped_column(sa.Text)
    generated_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    status: Mapped[ExplanationStatus] = mapped_column(
        enum_column(ExplanationStatus, "status"), nullable=False
    )

    __table_args__ = (
        sa.Index("ix_sentence_item_explanations_sentence_item_id", "sentence_item_id"),
    )


class ContentFlag(Base):
    """flag의 실제 동작(quarantine, evidence 무효화)은 10_ERROR_HANDLING.md."""

    __tablename__ = "content_flags"

    id: Mapped[int] = bigint_pk()
    user_id: Mapped[int] = mapped_column(sa.BigInteger, sa.ForeignKey("users.id"), nullable=False)
    sentence_id: Mapped[int | None] = mapped_column(sa.BigInteger, sa.ForeignKey("sentences.id"))
    learning_item_id: Mapped[int | None] = mapped_column(
        sa.BigInteger, sa.ForeignKey("learning_items.id")
    )
    study_presentation_id: Mapped[int | None] = mapped_column(
        sa.BigInteger, sa.ForeignKey("study_presentations.id")
    )
    reason: Mapped[ContentFlagReason] = mapped_column(
        enum_column(ContentFlagReason, "reason"), nullable=False
    )
    note: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = created_at_column()
    resolved_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))

    __table_args__ = (sa.Index("ix_content_flags_user_id", "user_id"),)
