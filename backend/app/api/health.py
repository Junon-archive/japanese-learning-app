"""GET /api/health — FastAPI / DB / worker 상태 (05_API_SPEC.md)."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime

from fastapi import APIRouter
from sqlalchemy import text

from app.db import get_engine
from app.schemas.health import (
    ApiComponent,
    DatabaseComponent,
    HealthComponents,
    HealthResponse,
    WorkerComponent,
)

APP_VERSION = "0.1.0"

# 05_API_SPEC.md: "status = degraded는 component 중 하나 이상이 down 또는
# stale일 때다. unknown은 그 자체로 degraded가 아니다."
# worker는 Wave 3까지 항상 unknown이므로 이 규칙을 뒤집으면 health가 영구히
# degraded가 된다.
_DEGRADED_COMPONENT_STATUSES = frozenset({"down", "stale"})

logger = logging.getLogger(__name__)

router = APIRouter()


def _check_database() -> DatabaseComponent:
    try:
        engine = get_engine()
    except Exception as exc:
        # DSN 자체가 잘못된 경우. 예외 메시지에 credential이 들어갈 수 있으므로
        # 타입 이름만 남긴다.
        logger.warning("database health check could not build an engine: %s", type(exc).__name__)
        return DatabaseComponent(status="down")
    if engine is None:
        return DatabaseComponent(status="unknown")

    started = time.perf_counter()
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:
        logger.warning("database health check failed: %s", type(exc).__name__)
        return DatabaseComponent(status="down")
    latency_ms = int((time.perf_counter() - started) * 1000)
    return DatabaseComponent(status="ok", latency_ms=latency_ms)


@router.get("/api/health")
def read_health() -> HealthResponse:
    components = HealthComponents(
        api=ApiComponent(status="ok"),
        database=_check_database(),
        # worker heartbeat 저장 위치는 아직 명세에 없다 (Wave 3).
        worker=WorkerComponent(status="unknown"),
    )
    statuses = {components.api.status, components.database.status, components.worker.status}
    return HealthResponse(
        status="degraded" if statuses & _DEGRADED_COMPONENT_STATUSES else "ok",
        checked_at=datetime.now(UTC),
        version=APP_VERSION,
        components=components,
    )
