#!/usr/bin/env python
"""개발용 DB 초기화: DROP DATABASE -> CREATE DATABASE -> `alembic upgrade head`.

    export DATABASE_URL=...
    uv run python scripts/db_reset.py --yes

되돌릴 수 없는 작업이므로 안전장치를 둔다(구현 지시서 §11).

-   `APP_ENV=production`이면 무조건 거부한다.
-   그 외에도 `--yes` 없이는 실행하지 않는다.
-   지울 DB 이름을 실행 전에 출력한다.

pgserver(ADR-002)든 docker compose의 postgres:16이든 코드 경로는 하나다.
차이는 `DATABASE_URL` 하나뿐이며 이 스크립트는 그것을 분기하지 않는다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import URL, make_url

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.settings import get_settings  # noqa: E402

ALEMBIC_INI = REPO_ROOT / "alembic.ini"

# DROP/CREATE DATABASE는 대상 DB에 붙은 채로는 실행할 수 없다.
MAINTENANCE_DATABASE = "postgres"

EXIT_OK = 0
EXIT_FAILED = 2


def _fail(message: str) -> int:
    sys.stderr.write(f"error: {message}\n")
    return EXIT_FAILED


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Drop and recreate the development database.")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="정말 지운다. 이 플래그 없이는 아무것도 하지 않는다.",
    )
    return parser.parse_args(argv)


def _alembic_config(dsn: URL) -> Config:
    config = Config(str(ALEMBIC_INI))
    # env.py는 환경변수에서 DSN을 읽지만, ini를 직접 소비하는 경로가 생겨도 같은
    # DSN을 보게 맞춰 둔다. configparser 보간 때문에 unix socket 경로의 %2F를 escape한다.
    rendered = dsn.render_as_string(hide_password=False).replace("%", "%%")
    config.set_main_option("sqlalchemy.url", rendered)
    return config


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    settings = get_settings()

    if settings.app_env == "production":
        return _fail("refusing to reset the database while APP_ENV=production")
    if not settings.database_url:
        return _fail("DATABASE_URL is not configured")

    dsn = make_url(settings.database_url)
    database = dsn.database
    if not database:
        return _fail("DATABASE_URL has no database name")
    if database == MAINTENANCE_DATABASE:
        return _fail(f"refusing to drop the maintenance database '{MAINTENANCE_DATABASE}'")
    if '"' in database:
        return _fail(f"refusing to drop a database whose name contains a quote: {database!r}")

    # 무엇을 지우는지 먼저 보여준다. password는 마스킹된다.
    sys.stdout.write(f"target database: {database}\n")
    sys.stdout.write(f"dsn: {dsn.render_as_string(hide_password=True)}\n")
    # pipe로 넘길 때 stdout은 block buffered다. 지우기 전에 실제로 보이게 한다.
    sys.stdout.flush()
    if not args.yes:
        return _fail("refusing to drop the database without --yes")

    admin_engine = sa.create_engine(
        dsn.set(database=MAINTENANCE_DATABASE), isolation_level="AUTOCOMMIT"
    )
    try:
        with admin_engine.connect() as connection:
            connection.execute(sa.text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)'))
            connection.execute(sa.text(f'CREATE DATABASE "{database}"'))
    except sa.exc.SQLAlchemyError as exc:
        return _fail(f"drop/create failed: {exc}")
    finally:
        admin_engine.dispose()
    sys.stdout.write(f"recreated database {database!r}\n")

    # in-process 실행. subprocess로 돌리면 실패 시 스택트레이스가 사라진다.
    command.upgrade(_alembic_config(dsn), "head")
    sys.stdout.write("alembic upgrade head: done\n")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
