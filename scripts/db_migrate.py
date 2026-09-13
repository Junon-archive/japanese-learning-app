#!/usr/bin/env python
"""데이터가 있는 DB에 migration을 적용한다 (04_DB_SPEC.md의 `운영 DB에 migration을 적용하는 경로`).

    export APP_ENV=production DATABASE_URL=postgresql+psycopg://<user>@127.0.0.1:5432/<db>
    uv run python scripts/db_migrate.py --pg-bin <PG_BIN>

1. 대상 출력    password를 가린 DSN을 먼저 출력한다
2. pending 확인 이미 head면 아무것도 하지 않고 성공한다 (백업도 만들지 않는다)
3. 직전 백업    pending이 있으면 `db_backup.py`와 같은 백업(새 백업 검증 포함)을 만든다.
                실패하면 migration을 하지 않고 실패한다
4. upgrade      alembic upgrade head

**전제: 3부터 4가 끝날 때까지 API와 worker를 멈춘다.** 롤백은 3의 백업을 복원하는 것이고,
그 사이의 쓰기는 복원이 조용히 지운다.

-   백업을 건너뛰는 옵션도 downgrade 명령도 두지 않는다. 롤백은 downgrade가 아니라 백업 복원이다.
-   `APP_ENV=production`에서 **실행된다.** `db_reset.py`와 반대다 --- 이 경로는 데이터를 보존한다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.engine import URL, make_url
from sqlalchemy.pool import NullPool

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import db_backup  # noqa: E402
import pg_tools  # noqa: E402

from app.settings import get_settings  # noqa: E402

ALEMBIC_INI = REPO_ROOT / "alembic.ini"

EXIT_OK = 0
EXIT_FAILED = 2

PRECONDITION = (
    "precondition: API and worker are stopped until the upgrade finishes "
    "(rollback = restoring the backup taken below)\n"
)


def _fail(message: str) -> int:
    sys.stderr.write(f"error: {message}\n")
    return EXIT_FAILED


def _out(message: str) -> None:
    sys.stdout.write(message)
    sys.stdout.flush()


def _alembic_config(dsn: URL) -> Config:
    config = Config(str(ALEMBIC_INI))
    # env.py는 DATABASE_URL 환경변수를 읽는다. ini를 직접 소비하는 경로가 생겨도 같은 DSN을
    # 보게 맞춘다. configparser 보간 때문에 unix socket 경로의 %2F를 escape한다(db_reset.py).
    rendered = dsn.render_as_string(hide_password=False).replace("%", "%%")
    config.set_main_option("sqlalchemy.url", rendered)
    return config


def _current_revision(dsn: URL) -> str | None:
    engine = sa.create_engine(dsn, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Apply pending Alembic migrations to DATABASE_URL, taking a verified backup first. "
            "전제: 백업부터 upgrade가 끝날 때까지 API와 worker를 멈춘다. "
            "백업 생략 옵션과 downgrade는 없다 --- 롤백은 백업 복원이다."
        )
    )
    parser.add_argument(
        "--pg-bin",
        type=Path,
        required=True,
        help="pg_dump / pg_restore가 있는 디렉터리. 기본값도 PATH 탐색도 없다.",
    )
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=db_backup.DEFAULT_BACKUP_DIR,
        help=f"백업 디렉터리 (기본값 {db_backup.DEFAULT_BACKUP_DIR}).",
    )
    parser.add_argument(
        "--keep",
        type=db_backup.positive_int,
        default=db_backup.DEFAULT_KEEP,
        help=f"보관 개수 (기본값 {db_backup.DEFAULT_KEEP}). 직전 백업도 한 개로 센다.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    database_url = get_settings().database_url
    if not database_url:
        return _fail("DATABASE_URL is not configured")
    dsn = make_url(database_url)
    if not dsn.database:
        return _fail("DATABASE_URL has no database name")

    # 1. 대상 출력
    try:
        _out(pg_tools.describe_target(dsn))
    except ValueError as exc:
        return _fail(str(exc))

    # 2. pending 확인
    script = ScriptDirectory.from_config(_alembic_config(dsn))
    head = script.get_current_head()
    current = _current_revision(dsn)
    if current == head:
        _out(f"already at head ({head}); nothing to do, no backup taken\n")
        return EXIT_OK
    known = {revision.revision for revision in script.walk_revisions()}
    if current is not None and current not in known:
        return _fail(f"database revision {current!r} is not in this code's migration history")
    _out(f"pending migrations: {current or '(empty database)'} -> {head}\n")
    _out(PRECONDITION)

    # 3. 직전 백업
    try:
        backup = db_backup.create_backup(
            dsn, pg_bin=args.pg_bin, backup_dir=args.backup_dir, keep=args.keep
        )
    except db_backup.BackupError as exc:
        return _fail(f"backup failed; migration was not applied: {exc}")

    # 4. upgrade. in-process 실행이다(실패 시 스택트레이스를 남긴다).
    try:
        command.upgrade(_alembic_config(dsn), "head")
    except Exception:
        sys.stderr.write(f"error: upgrade failed; roll back by restoring {backup}\n")
        raise
    _out(f"alembic upgrade head: done ({current or '(empty database)'} -> {head})\n")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
