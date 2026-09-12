from __future__ import annotations

import inspect
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker

from app.api.deps import get_now
from app.config import get_config
from app.db import get_engine
from app.main import create_app
from app.services.heartbeat import DEFAULT_WORKER_NAME, write_heartbeat
from app.settings import get_settings
from tests.clock import MutableClock
from tests.conftest import override_config

UNREACHABLE_DSN = "postgresql+psycopg://nc_test_user:nc_test_password@127.0.0.1:1/nc_test_db"

# 기본값(120)이 아닌 값을 주입한다. 기본값으로 검사하면 config를 아예 읽지 않는
# 구현도 통과한다 (13_ACCEPTANCE_CRITERIA.md의 `수치 취급 원칙`).
STALE_SECONDS = 300


def test_unknown_components_do_not_make_the_service_degraded(client: TestClient) -> None:
    # 05_API_SPEC.md: "status = degraded는 component 중 하나 이상이 down 또는
    # stale일 때다. unknown은 그 자체로 degraded가 아니다."
    # worker는 Wave 3까지 항상 unknown이므로 이 규칙을 뒤집으면 health가 영구히
    # degraded가 되어 신호로 쓸 수 없다. 이 테스트를 뒤집지 말 것.
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["components"]["database"]["status"] == "unknown"
    assert body["components"]["worker"]["status"] == "unknown"
    assert body["status"] == "ok"
    assert body["components"]["api"]["status"] == "ok"
    assert body["components"]["database"]["latency_ms"] is None


def test_worker_is_unknown_without_a_database(client: TestClient) -> None:
    """DB를 확인할 수 없으면 worker도 unknown이다. 그것만을 위해 별도 연결을 만들지 않는다."""
    body = client.get("/api/health").json()
    assert body["components"]["worker"] == {"status": "unknown", "last_heartbeat_at": None}


def test_checked_at_is_utc_aware(client: TestClient) -> None:
    body = client.get("/api/health").json()
    assert body["checked_at"].endswith("Z")
    checked_at = datetime.fromisoformat(body["checked_at"])
    assert checked_at.tzinfo is not None
    assert checked_at.utcoffset() == UTC.utcoffset(None)


def _client_with_database_url(monkeypatch: pytest.MonkeyPatch, dsn: str) -> TestClient:
    monkeypatch.setenv("DATABASE_URL", dsn)
    get_settings.cache_clear()
    return TestClient(create_app())


def test_unreachable_database_reports_down_without_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    # down인 component가 하나라도 있으면 degraded다 (05_API_SPEC.md).
    with _client_with_database_url(monkeypatch, UNREACHABLE_DSN) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["components"]["database"]["status"] == "down"
    assert body["status"] == "degraded"


def test_health_response_never_leaks_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    with _client_with_database_url(monkeypatch, UNREACHABLE_DSN) as client:
        text = client.get("/api/health").text
    for needle in ("nc_test_user", "nc_test_password", "nc_test_db", "127.0.0.1", "postgresql"):
        assert needle not in text, needle


def _iter_api_routes(router: FastAPI | APIRouter) -> Iterator[APIRoute]:
    """FastAPI가 include_router를 wrapper로 감싸므로 재귀적으로 펼친다."""
    for route in router.routes:
        if isinstance(route, APIRoute):
            yield route
            continue
        nested: FastAPI | APIRouter | None = getattr(route, "original_router", None)
        if nested is not None:
            yield from _iter_api_routes(nested)


def test_no_demo_or_anonymous_routes_exist() -> None:
    app = create_app()
    paths = [route.path for route in _iter_api_routes(app)] + list(app.openapi()["paths"])
    assert paths
    assert [path for path in paths if "demo" in path or "anonymous" in path] == []


def test_api_endpoints_are_synchronous() -> None:
    api_routes = list(_iter_api_routes(create_app()))
    assert api_routes
    for route in api_routes:
        assert not inspect.iscoroutinefunction(route.endpoint), route.path


def test_cors_wildcard_origin_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "*")
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="wildcard"):
        create_app()


@pytest.mark.parametrize(
    "value",
    [
        "null",
        "null, https://jp.test",
        "https://a.test/",
        "https://a.test/path",
        "ftp://x.test",
        "https://a.test,,https://b.test",
        "a.test",
    ],
)
def test_malformed_cors_origin_is_rejected(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", value)
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="invalid origin"):
        create_app()


@pytest.mark.parametrize(
    "value", ["http://localhost:5173", "https://a.test", "https://a.test, http://127.0.0.1:8000"]
)
def test_well_formed_cors_origins_are_accepted(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", value)
    get_settings.cache_clear()
    assert create_app() is not None


def test_empty_cors_setting_allows_no_origin(client: TestClient) -> None:
    response = client.get("/api/health", headers={"Origin": "https://evil.test"})
    assert "access-control-allow-origin" not in response.headers


def test_openapi_and_docs_are_closed_by_default(client: TestClient) -> None:
    # 05_API_SPEC.md는 인증 없는 호출을 /api/health에만 허용한다.
    for path in ("/openapi.json", "/docs", "/redoc"):
        assert client.get(path).status_code == 404, path


def test_openapi_and_docs_are_open_in_development(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    get_settings.cache_clear()
    with TestClient(create_app()) as client:
        for path in ("/openapi.json", "/docs", "/redoc"):
            assert client.get(path).status_code == 200, path


# --------------------------------------------------------------------------
# worker heartbeat (05_API_SPEC.md, ADR-017)
#
# `db_client`를 쓸 수 없다. health는 `get_db`를 거치지 않고 자기 커넥션으로 DB를
# 확인하므로(그래야 DSN이 없을 때 unknown을 답할 수 있다) 롤백되는 테스트 세션의
# 미확정 write를 보지 못한다. heartbeat는 커밋되어야 보인다.
# --------------------------------------------------------------------------


@pytest.fixture
def heartbeat_client(
    committed_db: sessionmaker[Session],
    database_url: URL,
    monkeypatch: pytest.MonkeyPatch,
    study_clock: MutableClock,
) -> Iterator[TestClient]:
    monkeypatch.setenv("DATABASE_URL", database_url.render_as_string(hide_password=False))
    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[get_now] = study_clock.now
    app.dependency_overrides[get_config] = lambda: override_config(
        get_config(), jobs={"heartbeat_stale_seconds": STALE_SECONDS}
    )
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()
        engine = get_engine()
        if engine is not None:
            engine.dispose()


def _worker_component(client: TestClient) -> dict[str, object]:
    body = client.get("/api/health").json()
    assert body["components"]["database"]["status"] == "ok", body
    component: dict[str, object] = body["components"]["worker"]
    return component


@pytest.mark.integration
def test_worker_is_unknown_before_the_first_heartbeat(
    heartbeat_client: TestClient,
) -> None:
    """worker를 아직 띄우지 않은 환경. unknown은 그 자체로 degraded가 아니다."""
    body = heartbeat_client.get("/api/health").json()
    assert body["components"]["worker"] == {"status": "unknown", "last_heartbeat_at": None}
    assert body["status"] == "ok"


@pytest.mark.integration
def test_a_recent_heartbeat_is_ok(
    heartbeat_client: TestClient, committed_db: sessionmaker[Session], study_clock: MutableClock
) -> None:
    with committed_db() as db:
        write_heartbeat(db, worker_name=DEFAULT_WORKER_NAME, now=study_clock.now())

    # 기본 임계값(120)이라면 stale일 시점이지만 주입한 값은 300이다.
    study_clock.advance(timedelta(seconds=STALE_SECONDS - 1))
    component = _worker_component(heartbeat_client)

    assert component["status"] == "ok"
    assert component["last_heartbeat_at"] is not None
    assert str(component["last_heartbeat_at"]).endswith("Z")
    assert heartbeat_client.get("/api/health").json()["status"] == "ok"


@pytest.mark.integration
def test_a_stopped_worker_goes_stale_and_degrades_the_service(
    heartbeat_client: TestClient, committed_db: sessionmaker[Session], study_clock: MutableClock
) -> None:
    """worker만 죽는 사고는 조용히 일어난다. 학습 세션은 pool로 계속 돌기 때문이다(ADR-017)."""
    with committed_db() as db:
        write_heartbeat(db, worker_name=DEFAULT_WORKER_NAME, now=study_clock.now())

    study_clock.advance(timedelta(seconds=STALE_SECONDS + 1))
    body = heartbeat_client.get("/api/health").json()

    assert body["components"]["worker"]["status"] == "stale"
    assert body["status"] == "degraded"


@pytest.mark.integration
def test_the_health_response_carries_no_threshold_or_worker_name(
    heartbeat_client: TestClient, committed_db: sessionmaker[Session], study_clock: MutableClock
) -> None:
    """이 endpoint는 설정값을 노출하지 않는다 (05_API_SPEC.md)."""
    with committed_db() as db:
        write_heartbeat(db, worker_name=DEFAULT_WORKER_NAME, now=study_clock.now())

    text = heartbeat_client.get("/api/health").text

    for needle in (DEFAULT_WORKER_NAME, str(STALE_SECONDS), "openai", "provider"):
        assert needle not in text, needle
