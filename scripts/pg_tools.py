"""백업·restore 검증·migration 명령이 함께 쓰는 libpq 연결 처리 (ADR-020 결정 2).

`DATABASE_URL`은 SQLAlchemy 형식(`postgresql+psycopg://...`)이라 pg_dump / pg_restore가
읽지 못한다. 여기서 libpq 연결 문자열로 풀어 **password를 뺀 채** `--dbname=`으로
넘기고, password는 자식 프로세스 환경의 `PGPASSWORD`로만 넘긴다. argv는 같은 호스트의
모든 사용자가 `ps`로 볼 수 있지만 프로세스 환경은 같은 사용자와 root만 읽는다.

DSN에 password가 없으면(운영 호스트 DSN) `PGPASSWORD`를 넣지 않고 libpq가 `~/.pgpass`를
읽는다. pgserver의 unix socket DSN(`...@/db?host=<dir>`)도 같은 규칙으로 풀린다 ---
query의 `host`는 libpq keyword와 이름이 같다.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping
from pathlib import Path

import sqlalchemy as sa
from psycopg.conninfo import make_conninfo
from sqlalchemy.engine import URL
from sqlalchemy.pool import NullPool

# query에 허용하는 키. pgserver의 unix socket DSN(`?host=<dir>`)만 query를 쓴다. 나머지는
# 거부한다: `dbname`/`user`/`port` 등은 psycopg에서 경로·userinfo를 이겨 연결 대상을 바꾸고
# (restore 검증이 복원 DB 대신 원본에 붙는다), `password`는 가려지지 않고 출력·argv로 샌다.
ALLOWED_QUERY_KEYS = frozenset({"host"})


def _query_params(dsn: URL) -> dict[str, str]:
    params: dict[str, str] = {}
    for key, value in dsn.query.items():
        if key not in ALLOWED_QUERY_KEYS:
            # 값은 넣지 않는다(password일 수 있다).
            raise ValueError(
                f"DATABASE_URL has unsupported query parameter {key!r} "
                f"(allowed: {', '.join(sorted(ALLOWED_QUERY_KEYS))})"
            )
        if key == "host" and dsn.host:
            # psycopg는 query의 host를, libpq_connection은 경로의 host를 쓴다. 대상이 갈린다.
            raise ValueError("DATABASE_URL has a host in both the address and the query")
        if not isinstance(value, str):
            # SQLAlchemy의 multi-host 형식(`?host=a&host=b`). 백업 대상이 하나로 정해지지 않는다.
            raise ValueError(f"DATABASE_URL has repeated query parameter {key!r}")
        params[key] = value
    return params


def describe_target(dsn: URL) -> str:
    """작업 전에 출력할 대상. password는 가린다(`make db-reset`의 출력과 같은 형태)."""
    # host가 경로에 있어도 query를 검사한다. 출력 전에 거부해야 query의 password가 안 샌다.
    params = _query_params(dsn)
    host = dsn.host or params.get("host") or "(libpq default)"
    port = dsn.port or "(default)"
    return (
        f"target: host={host} port={port} database={dsn.database}\n"
        f"dsn: {dsn.render_as_string(hide_password=True)}\n"
    )


def libpq_connection(dsn: URL) -> tuple[str, dict[str, str]]:
    """(password 없는 libpq 연결 문자열, 자식 프로세스 환경에 더할 값)."""
    params = _query_params(dsn)
    password = dsn.password
    if dsn.host:
        params["host"] = dsn.host
    if dsn.port:
        params["port"] = str(dsn.port)
    if dsn.username:
        params["user"] = dsn.username
    if dsn.database:
        params["dbname"] = dsn.database
    extra_env = {"PGPASSWORD": password} if password else {}
    return make_conninfo(**params), extra_env


def tool(pg_bin: Path, name: str) -> Path:
    """`--pg-bin` 안의 실행 파일. PATH를 찾지 않는다(ADR-020 결정 2)."""
    path = pg_bin / name
    if not (path.is_file() and os.access(path, os.X_OK)):
        raise FileNotFoundError(f"{name} is not an executable in --pg-bin {pg_bin}")
    return path


def run(
    argv: list[str], *, extra_env: Mapping[str, str], stdout: int | None = None
) -> subprocess.CompletedProcess[str]:
    """셸을 거치지 않는다. password는 `extra_env`로만 들어온다."""
    return subprocess.run(  # noqa: S603  (argv는 --pg-bin의 도구와 이 모듈이 만든 인자다)
        argv,
        env={**os.environ, **extra_env},
        stdout=subprocess.PIPE if stdout is None else stdout,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )


def client_version(pg_tool: Path) -> str:
    result = run([str(pg_tool), "--version"], extra_env={})
    if result.returncode != 0:
        raise OSError(f"{pg_tool.name} --version failed: {result.stderr.strip()}")
    return result.stdout.strip()


def server_version(dsn: URL) -> str:
    engine = sa.create_engine(dsn, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            return str(connection.execute(sa.text("SHOW server_version")).scalar_one())
    finally:
        engine.dispose()
