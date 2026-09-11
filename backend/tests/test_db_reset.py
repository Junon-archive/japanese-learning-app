"""scripts/db_reset.py의 안전장치 (구현 지시서 §11).

DROP DATABASE는 되돌릴 수 없다. 여섯 개의 거부 분기는 전부 engine 생성 **전에**
return하므로 DB 없이 검증할 수 있고, 그래서 integration 마크를 붙이지 않는다.

각 거부 테스트는 "exit code가 2다"로 끝내지 않는다. `sa.create_engine`과
`alembic.command.upgrade`를 폭발하게 바꿔 두고, 그 폭발이 일어나지 않았다는 것으로
**DB를 실제로 건드리지 않았음**을 확인한다. exit code만 보면 "지우고 나서 2를
반환하는" 구현도 통과한다.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import NoReturn

import pytest

from app.settings import get_settings

DB_RESET_PATH = Path(__file__).resolve().parents[2] / "scripts" / "db_reset.py"

SAFE_DSN = "postgresql+psycopg://nc:pw@127.0.0.1:5432/nihongo_dev"

EXIT_FAILED = 2


class _DetonatedError(Exception):
    """DB를 건드리려는 시도. 거부 분기에서는 절대 일어나면 안 된다."""


def _load_db_reset() -> ModuleType:
    spec = importlib.util.spec_from_file_location("db_reset", DB_RESET_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def db_reset(monkeypatch: pytest.MonkeyPatch) -> Iterator[ModuleType]:
    """DB에 닿는 모든 출구를 막은 db_reset 모듈."""
    module = _load_db_reset()

    def _explode(*args: object, **kwargs: object) -> NoReturn:
        raise _DetonatedError

    monkeypatch.setattr(module.sa, "create_engine", _explode)
    monkeypatch.setattr(module.command, "upgrade", _explode)
    yield module


def _env(monkeypatch: pytest.MonkeyPatch, **values: str) -> None:
    """설정은 환경변수로만 주입한다. lru_cache를 비워야 스크립트가 새 값을 본다."""
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()


def test_the_guard_fixture_is_not_vacuous(
    db_reset: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """거부 테스트들이 "어차피 아무 일도 안 일어나서" 통과하는 것이 아님을 보인다.

    모든 관문을 통과시키면 스크립트는 실제로 engine을 만들려 한다. 이 테스트가
    깨지면 아래 거부 테스트들은 전부 무의미해진 것이다.
    """
    _env(monkeypatch, APP_ENV="local", DATABASE_URL=SAFE_DSN)

    with pytest.raises(_DetonatedError):
        db_reset.main(["--yes"])


def test_production_is_refused(
    db_reset: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _env(monkeypatch, APP_ENV="production", DATABASE_URL=SAFE_DSN)

    # --yes가 있어도 거부한다. production 가드가 --yes보다 앞이어야 한다.
    assert db_reset.main(["--yes"]) == EXIT_FAILED
    assert "production" in capsys.readouterr().err


def test_a_missing_database_url_is_refused(
    db_reset: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    _env(monkeypatch, APP_ENV="local")

    assert db_reset.main(["--yes"]) == EXIT_FAILED
    assert "DATABASE_URL" in capsys.readouterr().err


def test_a_dsn_without_a_database_name_is_refused(
    db_reset: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # 이름이 없으면 maintenance DB에 붙은 채 DROP을 쏘게 된다.
    _env(monkeypatch, APP_ENV="local", DATABASE_URL="postgresql+psycopg://nc:pw@127.0.0.1:5432/")

    assert db_reset.main(["--yes"]) == EXIT_FAILED
    assert "database name" in capsys.readouterr().err


def test_the_maintenance_database_is_refused(
    db_reset: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _env(
        monkeypatch,
        APP_ENV="local",
        DATABASE_URL="postgresql+psycopg://nc:pw@127.0.0.1:5432/postgres",
    )

    assert db_reset.main(["--yes"]) == EXIT_FAILED
    assert "postgres" in capsys.readouterr().err


def test_a_quoted_database_name_is_refused(
    db_reset: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """식별자는 큰따옴표로 감싸서 SQL에 들어간다. 이름에 따옴표가 있으면 탈출한다."""
    _env(
        monkeypatch,
        APP_ENV="local",
        DATABASE_URL='postgresql+psycopg://nc:pw@127.0.0.1:5432/db"; DROP SCHEMA public CASCADE; --',
    )

    assert db_reset.main(["--yes"]) == EXIT_FAILED
    assert "quote" in capsys.readouterr().err


def test_without_yes_nothing_happens(
    db_reset: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _env(monkeypatch, APP_ENV="local", DATABASE_URL=SAFE_DSN)

    assert db_reset.main([]) == EXIT_FAILED
    captured = capsys.readouterr()
    assert "--yes" in captured.err
    # 무엇을 지우려 했는지는 거부할 때도 보여준다.
    assert "nihongo_dev" in captured.out


def test_the_printed_dsn_masks_the_password(
    db_reset: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """지울 대상을 출력하다가 credential을 터미널/CI 로그에 남기지 않는다."""
    _env(monkeypatch, APP_ENV="local", DATABASE_URL=SAFE_DSN)

    db_reset.main([])

    assert "pw" not in capsys.readouterr().out


@pytest.mark.parametrize("app_env", ["local", "development"])
def test_non_production_environments_are_allowed_to_proceed(
    db_reset: ModuleType, monkeypatch: pytest.MonkeyPatch, app_env: str
) -> None:
    """production 가드가 "전부 거부"로 굳어 버리면 스크립트가 쓸모없어진다."""
    _env(monkeypatch, APP_ENV=app_env, DATABASE_URL=SAFE_DSN)

    with pytest.raises(_DetonatedError):
        db_reset.main(["--yes"])
