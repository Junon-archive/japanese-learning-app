"""Background job queue와 prompt version (04_DB_SPEC.md, 09_BACKGROUND_JOBS.md)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, bigint_pk, created_at_column, enum_column
from app.models.enums import GenerationJobStatus, JobType, LlmTaskType


class GenerationJob(Base):
    """Worker 실행은 at-least-once다. DB persistence는 idempotent해야 한다."""

    __tablename__ = "generation_jobs"

    id: Mapped[int] = bigint_pk()
    job_type: Mapped[JobType] = mapped_column(enum_column(JobType, "job_type"), nullable=False)
    status: Mapped[GenerationJobStatus] = mapped_column(
        enum_column(GenerationJobStatus, "status"), nullable=False
    )
    payload_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
    )
    # 생성된 sentence/explanation id 집합.
    result_ref: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # 이 unique가 없으면 retry가 콘텐츠를 중복 생성한다. 사후 복구가 어렵다.
    idempotency_key: Mapped[str] = mapped_column(sa.Text, nullable=False)
    retry_count: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.text("0")
    )
    # 기본값(max_job_attempts)은 14_CONFIGURATION.md가 canonical이다.
    max_attempts: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    next_attempt_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    last_error: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = created_at_column()
    started_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))

    __table_args__ = (
        sa.UniqueConstraint("idempotency_key"),
        sa.Index("ix_generation_jobs_status_next_attempt_at", "status", "next_attempt_at"),
    )


class PromptVersion(Base):
    __tablename__ = "prompt_versions"

    id: Mapped[int] = bigint_pk()
    task_type: Mapped[LlmTaskType] = mapped_column(
        enum_column(LlmTaskType, "task_type"), nullable=False
    )
    version: Mapped[str] = mapped_column(sa.Text, nullable=False)
    provider: Mapped[str] = mapped_column(sa.Text, nullable=False)
    model: Mapped[str] = mapped_column(sa.Text, nullable=False)
    created_at: Mapped[datetime] = created_at_column()
    # 현재 사용 중인 버전 표시.
    active: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.text("false")
    )

    __table_args__ = (sa.UniqueConstraint("task_type", "version"),)
