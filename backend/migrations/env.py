"""Alembic 환경.

DSN은 `alembic.ini`가 아니라 `app.settings`(환경변수 `DATABASE_URL`)에서 읽는다.
credential을 Git에 넣지 않기 위해서다(AGENTS.md #7).
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app.models import Base
from app.settings import get_settings

config = context.config

if config.config_file_name is not None:
    # `disable_existing_loggers`의 기본값은 True다. 그대로 두면 migration을 in-process로
    # 돌린 뒤 **이미 만들어져 있던 로거가 전부 꺼진다** --- 테스트 세션이 alembic을 한 번
    # 돌린 다음부터 `app.jobs` 로그가 조용히 사라지는 형태로 드러난다.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _database_url() -> str:
    url = get_settings().database_url
    if not url:
        raise RuntimeError("DATABASE_URL must be set to run migrations")
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(_database_url(), poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()

    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
