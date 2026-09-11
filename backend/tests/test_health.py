from __future__ import annotations

import inspect
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import get_settings

UNREACHABLE_DSN = "postgresql+psycopg://nc_test_user:nc_test_password@127.0.0.1:1/nc_test_db"


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


def test_worker_is_unknown_in_wave_0(client: TestClient) -> None:
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
