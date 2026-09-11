from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import get_config
from app.db import _build_engine
from app.main import create_app
from app.settings import get_settings

_ENV_VARS = ("APP_ENV", "DATABASE_URL", "CORS_ALLOW_ORIGINS", "NC_CONFIG_PATH")

REPO_ROOT = Path(__file__).resolve().parents[2]


def _clear_caches() -> None:
    get_settings.cache_clear()
    get_config.cache_clear()
    _build_engine.cache_clear()


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """설정은 환경변수로만 주입한다. 주변 환경이 테스트에 새지 않게 한다."""
    for name in _ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    _clear_caches()
    yield
    _clear_caches()


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as test_client:
        yield test_client
