"""`scripts/db_migrate.py` --- 데이터를 보존하는 운영 migration 경로 (04_DB_SPEC.md).

    1. 대상 출력 -> 2. 이미 head면 종료 -> 3. 직전 백업(검증 포함) -> 4. alembic upgrade head

-   revision 0002에 데이터가 있는 DB가 head까지 올라가고, 테이블별 내용이 보존되며, 0002
    시점의 백업 파일이 남는다. `APP_ENV=production`에서 실행된다(`db_reset.py`와 반대).
-   **백업이 실패하면 non-zero이고 revision이 0002 그대로다.** "백업 후 upgrade"의 순서만이
    아니라 "백업 실패면 upgrade 없음"을 본다.
-   이미 head면 아무것도 하지 않고 exit 0이며 백업을 시도하지도 않는다.

DB는 테스트 pgserver의 일회용 DB, 백업은 `tmp_path`다.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import pgserver
import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.services.seed_loader import load_seed
from app.settings import get_settings
from tests import db_support, factories

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
SEED_DIR = REPO_ROOT / "seed"
PG_BIN = Path(pgserver.__file__).parent / "pginstall" / "bin"

BEFORE_REVISION = "0002"
ALEMBIC_VERSION_TABLE = "alembic_version"
EXIT_FAILED = 2


def load_script(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, SCRIPTS_DIR / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _revision(dsn: URL) -> str | None:
    engine = sa.create_engine(dsn, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()


def _table_contents(dsn: URL) -> dict[str, tuple[int, str]]:
    """catalog에서 나열한 테이블별 (행 수, 내용 해시). restore 검증과 같은 함수다."""
    restore_check = load_script("db_restore_check")
    engine = sa.create_engine(dsn, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            tables: dict[str, tuple[int, str]] = restore_check.take_snapshot(connection).tables
    finally:
        engine.dispose()
    return tables


def _failing_pg_bin(tmp_path: Path) -> Path:
    """호출되면 실패하는 pg_dump. 이미 head인 경우에는 불리지도 않아야 한다."""
    bin_dir = tmp_path / "failing-pg-bin"
    bin_dir.mkdir()
    script = bin_dir / "pg_dump"
    # `--version`은 실제 값으로 답한다. dump 단계에서 실패해야 "dump가 실패한 백업"이다.
    script.write_text(
        f'#!/bin/sh\nif [ "$1" = "--version" ]; then exec "{PG_BIN / "pg_dump"}" --version; fi\n'
        "echo 'pg_dump: error: simulated' >&2\nexit 1\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    (bin_dir / "pg_restore").symlink_to(PG_BIN / "pg_restore")
    return bin_dir


@pytest.fixture
def database_at_0002(postgres_admin_dsn: URL) -> Iterator[URL]:
    """0002까지 올리고 seed와 사용자를 넣은 DB. **커밋한다.**"""
    name = f"nc_migrate_{uuid.uuid4().hex[:12]}"
    dsn = db_support.recreate_database(postgres_admin_dsn, name)
    try:
        db_support.alembic_upgrade(dsn, BEFORE_REVISION)
        engine = sa.create_engine(dsn, poolclass=NullPool)
        try:
            with Session(engine) as session:
                load_seed(session, SEED_DIR, now=datetime.now(UTC))
                factories.make_user(session)
                session.commit()
        finally:
            engine.dispose()
        yield dsn
    finally:
        db_support.drop_database(postgres_admin_dsn, name)


def _migrate(monkeypatch: pytest.MonkeyPatch, dsn: URL, pg_bin: Path, backup_dir: Path) -> int:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", dsn.render_as_string(hide_password=False))
    get_settings.cache_clear()
    code = load_script("db_migrate").main(
        ["--pg-bin", str(pg_bin), "--backup-dir", str(backup_dir)]
    )
    return int(code)


def test_pending_migrations_are_backed_up_then_applied_in_production(
    database_at_0002: URL,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dsn = database_at_0002
    head = ScriptDirectory.from_config(db_support.alembic_config(dsn)).get_current_head()
    assert head != BEFORE_REVISION, "0002가 head면 이 테스트는 pending을 보지 않는다"
    before = _table_contents(dsn)
    assert any(rows for name, (rows, _) in before.items() if name != ALEMBIC_VERSION_TABLE)
    backup_dir = tmp_path / "backups"

    code = _migrate(monkeypatch, dsn, PG_BIN, backup_dir)

    output = capsys.readouterr()
    assert code == 0, output.err
    assert _revision(dsn) == head

    # 테이블별 내용이 보존된다. alembic_version만 바뀐다.
    after = _table_contents(dsn)
    del before[ALEMBIC_VERSION_TABLE], after[ALEMBIC_VERSION_TABLE]
    assert after == before

    # 대상 출력이 백업보다 먼저이고, 멈춤 전제가 출력된다.
    assert output.out.index(f"database={dsn.database}") < output.out.index("backup verified:")
    assert "API and worker are stopped" in output.out

    # 0002 시점의 검증된 백업이 남는다.
    [backup] = list(backup_dir.iterdir())
    assert load_script("db_backup").BACKUP_NAME_PATTERN.fullmatch(backup.name)
    assert backup.stat().st_mode & 0o777 == 0o600
    alembic_rows = subprocess.run(  # noqa: S603
        [
            str(PG_BIN / "pg_restore"),
            "--data-only",
            f"--table={ALEMBIC_VERSION_TABLE}",
            "--file=-",
            str(backup),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert alembic_rows.returncode == 0, alembic_rows.stderr
    assert f"{BEFORE_REVISION}\n" in alembic_rows.stdout


def test_a_failed_backup_leaves_the_revision_untouched(
    database_at_0002: URL,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    backup_dir = tmp_path / "backups"
    before = _table_contents(database_at_0002)

    code = _migrate(monkeypatch, database_at_0002, _failing_pg_bin(tmp_path), backup_dir)

    assert code == EXIT_FAILED
    assert "migration was not applied: pg_dump exited with 1" in capsys.readouterr().err
    assert _revision(database_at_0002) == BEFORE_REVISION
    assert _table_contents(database_at_0002) == before
    assert list(backup_dir.iterdir()) == []


def test_already_at_head_does_nothing_and_takes_no_backup(
    postgres_admin_dsn: URL,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    name = f"nc_migrate_{uuid.uuid4().hex[:12]}"
    dsn = db_support.recreate_database(postgres_admin_dsn, name)
    try:
        db_support.alembic_upgrade(dsn)
        head = _revision(dsn)
        backup_dir = tmp_path / "backups"

        # pg_dump가 불리면 실패하므로, exit 0은 백업을 시도하지 않았다는 뜻이기도 하다.
        code = _migrate(monkeypatch, dsn, _failing_pg_bin(tmp_path), backup_dir)

        output = capsys.readouterr()
        assert code == 0, output.err
        assert f"database={dsn.database}" in output.out
        assert "already at head" in output.out
        assert _revision(dsn) == head
        assert not backup_dir.exists()
    finally:
        db_support.drop_database(postgres_admin_dsn, name)
