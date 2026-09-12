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

    __table_args__ = (
        sa.UniqueConstraint("task_type", "version"),
        # active는 task_type당 최대 하나이며 **partial** unique로 강제한다
        # (04_DB_SPEC.md의 active 유일성). "가장 최근 행이 active"로 추론하면 옛
        # version으로 되돌리는 rollback이 불가능해진다. 전체 unique로 만들면
        # inactive 이력 행을 task_type당 하나밖에 둘 수 없어 version 이력 자체가
        # 사라진다.
        #
        # 이름은 uq_user_sentence_candidates_active와 같은 방식으로 짧게 고정한다.
        # Index는 ix convention(`ix_%(column_0_label)s`)을 타므로 이름을 주지 않으면
        # unique index에 ix_ 접두가 붙고, 컬럼을 나열하는 uq convention을 흉내 내면
        # 이름이 PostgreSQL identifier 한계(63자)에서 잘린다.
        sa.Index(
            "uq_prompt_versions_active",
            "task_type",
            unique=True,
            postgresql_where=sa.text("active"),
        ),
    )


class WorkerHeartbeat(Base):
    """worker 프로세스의 생존 신호 (04_DB_SPEC.md, ADR-017-worker-heartbeat-storage).

    `GET /api/health`의 `components.worker`가 읽는 유일한 소스다. `generation_jobs`의
    최근 활동으로 추론하는 대안은 "job이 0건인 정상적인 날"과 "worker 사망"을
    구분하지 못해 heartbeat가 가장 필요한 순간에 틀린다. 사용자 종속 테이블이
    아니므로 `user_id`가 없다.
    """

    __tablename__ = "worker_heartbeats"

    # MVP의 worker는 하나('default')지만 upsert에는 대상 키가 필요하고, worker가
    # 둘이 되는 날 migration 없이 행만 늘면 된다 (04_DB_SPEC.md).
    worker_name: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    last_heartbeat_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
