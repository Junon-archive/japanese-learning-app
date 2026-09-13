"""`scripts/db_migrate.py` --- 데이터를 보존하는 운영 migration 경로 (04_DB_SPEC.md).

    1. 대상 출력 -> 2. 이미 head면 종료 -> 3. 직전 백업(검증 포함) -> 4. alembic upgrade head

-   revision 0002에 데이터가 있는 DB가 head까지 올라가고, 테이블별 내용이 보존되며, 0002
    시점의 백업 파일이 남는다. `APP_ENV=production`에서 실행된다(`db_reset.py`와 반대).
    내용 비교는 **migration 전에 있던 컬럼 전부**로 한다. migration이 더한 컬럼은 명세의 additive
    컬럼(`sentences.ruby_json`)뿐이고 전부 NULL이어야 한다(불변식 19).
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


# migration 0003 이후가 더하는 컬럼. 명세 밖의 컬럼이 생기면 보존 검사가 실패한다.
ADDED_COLUMNS: dict[str, tuple[str, ...]] = {"sentences": ("ruby_json",)}


def _columns(dsn: URL) -> dict[str, tuple[str, ...]]:
    engine = sa.create_engine(dsn, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                sa.text(
                    "SELECT table_name, column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' ORDER BY table_name, ordinal_position"
                )
            ).all()
    finally:
        engine.dispose()
    columns: dict[str, tuple[str, ...]] = {}
    for table, column in rows:
        columns[str(table)] = (*columns.get(str(table), ()), str(column))
    return columns


def _contents_of_columns(
    dsn: URL, columns: dict[str, tuple[str, ...]]
) -> dict[str, tuple[int, str]]:
    """테이블별 (행 수, 주어진 컬럼 전부의 행 텍스트 해시). `take_snapshot`과 같은 방식이다.

    행 전체(`nc_row::text`) 대신 migration 전 컬럼 목록의 `ROW(...)::text`를 해시한다. 새 컬럼은
    이 해시에 들어가지 않고, 기존 컬럼은 하나도 빠지지 않는다.
    """
    engine = sa.create_engine(dsn, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            connection.execute(sa.text("SET TIME ZONE 'UTC'"))
            quote = connection.dialect.identifier_preparer.quote
            contents: dict[str, tuple[int, str]] = {}
            for table, names in columns.items():
                row = ", ".join(f"nc_row.{quote(name)}" for name in names)
                rows, digest = connection.execute(
                    sa.text(
                        "SELECT count(*), md5(coalesce(string_agg(nc_text, chr(10) "  # noqa: S608
                        "ORDER BY nc_text COLLATE \"C\"), '')) "
                        f"FROM (SELECT ROW({row})::text AS nc_text "
                        f"FROM public.{quote(table)} AS nc_row) AS nc_rows"
                    )
                ).one()
                contents[table] = (int(rows), str(digest))
    finally:
        engine.dispose()
    return contents


@pytest.fixture
def database_at_0002(postgres_admin_dsn: URL) -> Iterator[URL]:
    """seed와 사용자를 넣은 0002 DB. **커밋한다.**

    데이터는 head에서 현재 ORM(`load_seed`)으로 넣고 0002로 downgrade한다. ORM 모델은 head
    스키마(`sentences.ruby_json` 포함)를 가리키므로 0002 스키마에 직접 쓸 수 없다. downgrade는
    0002 이후 migration이 더한 것만 걷어 내므로 남는 행과 컬럼은 0002 스키마 그대로다.
    """
    name = f"nc_migrate_{uuid.uuid4().hex[:12]}"
    dsn = db_support.recreate_database(postgres_admin_dsn, name)
    try:
        db_support.alembic_upgrade(dsn)
        engine = sa.create_engine(dsn, poolclass=NullPool)
        try:
            with Session(engine) as session:
                load_seed(session, SEED_DIR, now=datetime.now(UTC))
                factories.make_user(session)
                session.commit()
        finally:
            engine.dispose()
        db_support.alembic_downgrade(dsn, BEFORE_REVISION)
        assert _revision(dsn) == BEFORE_REVISION
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
    before_columns = _columns(dsn)
    del before_columns[ALEMBIC_VERSION_TABLE]
    before = _contents_of_columns(dsn, before_columns)
    assert any(rows for rows, _ in before.values())
    backup_dir = tmp_path / "backups"

    code = _migrate(monkeypatch, dsn, PG_BIN, backup_dir)

    output = capsys.readouterr()
    assert code == 0, output.err
    assert _revision(dsn) == head

    # 테이블별 내용이 migration 전 컬럼 전부에서 보존된다. alembic_version만 바뀐다.
    after_columns = _columns(dsn)
    del after_columns[ALEMBIC_VERSION_TABLE]
    assert after_columns == {
        table: (*names, *ADDED_COLUMNS.get(table, ())) for table, names in before_columns.items()
    }
    assert _contents_of_columns(dsn, before_columns) == before

    # 더해진 컬럼은 기존 행에서 전부 NULL이다(미계산, backfill 대상).
    engine = sa.create_engine(dsn, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            filled = connection.execute(
                sa.text("SELECT count(*) FROM sentences WHERE ruby_json IS NOT NULL")
            ).scalar_one()
            sentences = connection.execute(sa.text("SELECT count(*) FROM sentences")).scalar_one()
    finally:
        engine.dispose()
    assert sentences > 0
    assert filled == 0

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
