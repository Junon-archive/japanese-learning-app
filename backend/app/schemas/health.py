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
    # unknown = heartbeat 행이 없다(worker를 아직 띄우지 않았거나 DB를 못 봤다).
    # 그 자체로 degraded가 아니고, stale은 degraded다 (05_API_SPEC.md).
    status: Literal["unknown", "ok", "stale"]
    last_heartbeat_at: datetime | None = None

    @field_serializer("last_heartbeat_at")
    def _serialize_last_heartbeat_at(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


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
