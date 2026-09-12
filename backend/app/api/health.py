"""GET /api/health — FastAPI / DB / worker 상태 (05_API_SPEC.md)."""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text

from app.api.deps import get_now
from app.config import AppConfig, get_config
from app.db import get_engine
from app.schemas.health import (
    ApiComponent,
    DatabaseComponent,
    HealthComponents,
    HealthResponse,
    WorkerComponent,
)
from app.services.heartbeat import latest_heartbeat_at, worker_status

APP_VERSION = "0.1.0"

# 05_API_SPEC.md: "status = degraded는 component 중 하나 이상이 down 또는
# stale일 때다. unknown은 그 자체로 degraded가 아니다."
# worker를 아직 띄우지 않은 환경(heartbeat 행 없음)은 계속 unknown이므로 이 규칙을
# 뒤집으면 그런 환경의 health가 영구히 degraded가 된다.
_DEGRADED_COMPONENT_STATUSES = frozenset({"down", "stale"})

logger = logging.getLogger(__name__)

router = APIRouter()


def _check_database() -> tuple[DatabaseComponent, datetime | None]:
    """DB 상태와 worker heartbeat 최대값을 **한 커넥션에서** 함께 읽는다.

    "worker 상태를 위해 별도 연결을 만들지 않는다"(05_API_SPEC.md). DB를 확인할 수
    없으면 heartbeat도 읽을 수 없고 worker는 `unknown`이다 --- 그것이 이 함수가
    heartbeat를 두 번째 반환값으로 내는 이유다.
    """
    try:
        engine = get_engine()
    except Exception as exc:
        # DSN 자체가 잘못된 경우. 예외 메시지에 credential이 들어갈 수 있으므로
        # 타입 이름만 남긴다.
        logger.warning("database health check could not build an engine: %s", type(exc).__name__)
        return DatabaseComponent(status="down"), None
    if engine is None:
        return DatabaseComponent(status="unknown"), None

    started = time.perf_counter()
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            heartbeat_at = latest_heartbeat_at(connection)
    except Exception as exc:
        logger.warning("database health check failed: %s", type(exc).__name__)
        return DatabaseComponent(status="down"), None
    latency_ms = int((time.perf_counter() - started) * 1000)
    return DatabaseComponent(status="ok", latency_ms=latency_ms), heartbeat_at


@router.get("/api/health")
def read_health(
    now: Annotated[datetime, Depends(get_now)],
    cfg: Annotated[AppConfig, Depends(get_config)],
) -> HealthResponse:
    database, heartbeat_at = _check_database()
    components = HealthComponents(
        api=ApiComponent(status="ok"),
        database=database,
        worker=WorkerComponent(
            status=worker_status(
                last_heartbeat_at=heartbeat_at,
                now=now,
                stale_seconds=cfg.jobs.heartbeat_stale_seconds,
            ),
            last_heartbeat_at=heartbeat_at,
        ),
    )
    statuses = {components.api.status, components.database.status, components.worker.status}
    return HealthResponse(
        status="degraded" if statuses & _DEGRADED_COMPONENT_STATUSES else "ok",
        checked_at=now,
        version=APP_VERSION,
        components=components,
    )
