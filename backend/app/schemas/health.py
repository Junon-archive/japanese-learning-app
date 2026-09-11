"""GET /api/health 응답 스키마 (05_API_SPEC.md)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, field_serializer


class ApiComponent(BaseModel):
    status: Literal["ok"]


class DatabaseComponent(BaseModel):
    status: Literal["ok", "down", "unknown"]
    latency_ms: int | None = None


class WorkerComponent(BaseModel):
    status: Literal["unknown"]
    last_heartbeat_at: datetime | None = None


class HealthComponents(BaseModel):
    api: ApiComponent
    database: DatabaseComponent
    worker: WorkerComponent


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    checked_at: datetime
    version: str
    components: HealthComponents

    @field_serializer("checked_at")
    def _serialize_checked_at(self, value: datetime) -> str:
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
