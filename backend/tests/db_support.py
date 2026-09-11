"""테스트 전용 PostgreSQL 지원 (ADR-002).

이 모듈은 `backend/tests/` 아래에만 존재한다. `pgserver` import가 `backend/app/`로
새어 들어가면 ADR-002의 "애플리케이션 코드는 두 경로를 분기하지 않는다"가 깨진다
(`test_schema_invariants.py::test_app_tree_does_not_import_pgserver`가 감시한다).

원칙:
-   DSN 하나만 다르고 나머지는 운영과 같다. `TEST_DATABASE_URL`이 있으면 pgserver를
    띄우지 않고 그 서버를 쓴다(docker compose의 postgres:16이든 CI의 서비스 컨테이너든).
-   스키마는 항상 `alembic upgrade head`로 만든다. `Base.metadata.create_all()`을 쓰면
    migration과 모델이 어긋나도 테스트가 통과해버린다.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import URL, make_url

from app.settings import get_settings

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"

# 고정 경로다. tmp_path_factory를 쓰면 세션마다 initdb(수 초)를 다시 돈다.
# .gitignore에 등록되어 있다.
PGDATA_DIR = REPO_ROOT / "data" / "pgtest"


# psycopg2가 아니라 psycopg 3을 쓴다. pgserver의 get_uri()는 드라이버 없는
# "postgresql://"를 주는데, 그대로 SQLAlchemy에 넘기면 psycopg2를 찾다가 실패한다.
DRIVER = "postgresql+psycopg"


def _normalize(dsn: str) -> URL:
    return make_url(dsn).set(drivername=DRIVER)


def session_database_name() -> str:
    """이 pytest 프로세스가 쓸 테스트 DB 이름.

    pid를 붙이는 이유: 같은 머신에서 두 pytest 실행이 겹칠 때(병렬 작업, watch 모드)
    한쪽의 `DROP DATABASE ... WITH (FORCE)`가 다른 쪽의 커넥션을 끊어버린다.
    실제로 그 충돌을 한 번 겪었다.

    migration 왕복 테스트는 이 DB도 쓰지 않는다. downgrade가 스키마를 파괴하므로
    일회용 DB를 따로 만든다.
    """
    return f"nihongo_test_{os.getpid()}"


def start_postgres() -> URL:
    """maintenance DB("postgres")를 가리키는 DSN을 돌려준다.

    `TEST_DATABASE_URL`이 있으면 그 서버를 쓴다. 없으면 pgserver를 기동한다.
    기동 실패는 skip이 아니라 error다 --- pgserver는 dev 의존성이므로
    `uv sync`한 환경에 "DB가 없는 경우"는 존재하지 않는다. skip 가드를 두면
    integration 테스트가 조용히 0건 실행되며 썩는다.
    """
    external = os.environ.get("TEST_DATABASE_URL")
    if external:
        return _normalize(external)

    # 테스트 전용 의존성. import를 모듈 최상단(= app이 보는 경로)으로 끌어올리지 않는다.
    import pgserver

    # cleanup_mode="stop": 서버는 내리고 data 디렉터리는 남긴다.
    # "delete"면 매 세션 initdb를 다시 돌고, None이면 유령 postgres가 남는다.
    # pgserver는 get_server를 __all__로 re-export하지 않아 strict mypy가 attr-defined로 본다.
    server = pgserver.get_server(PGDATA_DIR, cleanup_mode="stop")  # type: ignore[attr-defined]
    return _normalize(server.get_uri())


def database_dsn(admin_dsn: URL, database: str) -> URL:
    return admin_dsn.set(database=database)


@contextmanager
def _autocommit(admin_dsn: URL) -> Iterator[sa.Connection]:
    engine = sa.create_engine(admin_dsn, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            yield connection
    finally:
        engine.dispose()


def recreate_database(admin_dsn: URL, database: str) -> URL:
    """빈 DB를 보장한다. 남아 있는 것은 지운다(테스트는 항상 빈 DB에서 시작한다)."""
    with _autocommit(admin_dsn) as connection:
        # 식별자는 이 모듈 안의 상수/uuid에서만 온다. 사용자 입력이 아니다.
        connection.execute(sa.text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)'))
        connection.execute(sa.text(f'CREATE DATABASE "{database}"'))
    return database_dsn(admin_dsn, database)


def drop_database(admin_dsn: URL, database: str) -> None:
    with _autocommit(admin_dsn) as connection:
        connection.execute(sa.text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)'))


@contextmanager
def _database_url_env(dsn: URL) -> Iterator[None]:
    """`backend/migrations/env.py`는 alembic.ini가 아니라 `app.settings`에서 DSN을 읽는다.

    credential을 Git에 넣지 않기 위한 설계이므로 테스트도 같은 경로로 주입한다.
    """
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = dsn.render_as_string(hide_password=False)
    get_settings.cache_clear()
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        get_settings.cache_clear()


def alembic_config(dsn: URL) -> Config:
    config = Config(str(ALEMBIC_INI))
    # alembic.ini의 sqlalchemy.url은 비어 있다. env.py가 환경변수를 읽지만
    # ini를 직접 소비하는 경로가 생겨도 같은 DSN을 보게 맞춰 둔다.
    # configparser 보간 때문에 unix socket 경로의 %2F를 escape해야 한다.
    rendered = dsn.render_as_string(hide_password=False).replace("%", "%%")
    config.set_main_option("sqlalchemy.url", rendered)
    return config


def alembic_upgrade(dsn: URL, revision: str = "head") -> None:
    """in-process 실행. subprocess로 돌리면 실패 시 스택트레이스가 사라지고 -x가 안 먹는다."""
    with _database_url_env(dsn):
        command.upgrade(alembic_config(dsn), revision)


def alembic_downgrade(dsn: URL, revision: str = "base") -> None:
    with _database_url_env(dsn):
        command.downgrade(alembic_config(dsn), revision)
