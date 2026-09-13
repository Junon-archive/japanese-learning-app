#!/usr/bin/env python
"""restore 검증 (spec/04_SECURITY_AND_DATA.md의 `restore 검증`).

    export DATABASE_URL=<백업한 원본 DB의 DSN>
    uv run python scripts/db_restore_check.py --pg-bin <PG_BIN> \\
        --backup data/backups/backup-<UTC>.dump --login-id <id>

**전제: 원본은 dump 시점부터 이 명령이 끝날 때까지 쓰기가 없어야 한다.** API와 worker를
멈춘 상태에서 dump하고 이 명령을 돌린다. worker는 job이 없어도 `worker_heartbeats`를,
API는 인증 요청마다 `auth_sessions.last_used_at`을 쓰므로 살아 있는 원본과 비교하면
테이블 내용 비교가 거짓으로 실패한다.

백업 파일을 **별도 DB**(`<원본>_restore_<UTC>`)에 복원하고 원본과 비교한다. 원본은 읽기만
한다. 복원 DB는 끝나면(성공이든 실패든) 지운다 --- password hash가 든 사본을 남기지 않는다.

1. alembic_version   복원 DB와 원본이 같고 migration head다
2. 테이블 내용       catalog에서 나열한 모든 public 테이블의 행 수와 내용 해시가 같다
3. sequence          모든 sequence의 last_value가 같다
4. 제약·index        제약 이름 집합과 index 이름 집합이 같다 (partial unique index 포함)
6. 음성 대조군       복원본 1행을 (롤백될 트랜잭션 안에서) 훼손하면 2가 그 테이블을 잡는다
5. 동작              복원 DB에 붙인 API로 login과 history가 동작한다

5는 1~4와 6 **뒤에** 한다. login이 복원 DB의 `auth_sessions`에 행을 쓰기 때문이다. 6을
5보다 앞에 두는 이유도 같다: login 뒤에는 어떤 훼손 없이도 비교가 실패하므로 음성 대조군이
아무것도 증명하지 않는다.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy.engine import URL, make_url
from sqlalchemy.pool import NullPool

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import pg_tools  # noqa: E402

from app.clock import utc_now  # noqa: E402
from app.db import get_engine  # noqa: E402
from app.main import create_app  # noqa: E402
from app.services.auth import normalize_login_id  # noqa: E402
from app.settings import get_settings  # noqa: E402

EXIT_OK = 0
EXIT_FAILED = 2

ALEMBIC_INI = REPO_ROOT / "alembic.ini"
MAINTENANCE_DATABASE = "postgres"
# PostgreSQL은 더 긴 식별자를 조용히 자른다. 잘린 복원 DB 이름이 원본 이름과 같아지면
# 마지막의 DROP이 원본을 지운다. 그래서 자르지 않고 거부한다.
MAX_IDENTIFIER_BYTES = 63
ALEMBIC_VERSION_TABLE = "alembic_version"

# 복원 DB에 붙인 in-process API가 받아들일 Origin. `.invalid`는 예약 TLD다.
CHECK_ORIGIN = "https://restore-check.invalid"
CHECK_BASE_URL = "https://testserver"


class RestoreCheckError(Exception):
    pass


def _fail(message: str) -> int:
    sys.stderr.write(f"error: {message}\n")
    return EXIT_FAILED


def _out(message: str) -> None:
    sys.stdout.write(message)
    sys.stdout.flush()


# --------------------------------------------------------------------------
# 1~4: catalog snapshot과 비교
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Snapshot:
    alembic_versions: tuple[str, ...]
    # 테이블 이름 -> (행 수, 내용 해시)
    tables: dict[str, tuple[int, str]]
    sequences: dict[str, int | None]
    # "<table>.<name>"
    constraints: frozenset[str]
    indexes: frozenset[str]


def take_snapshot(connection: sa.Connection) -> Snapshot:
    """비교 대상을 **매번 catalog에서** 나열한다. 테이블 목록을 적어 두지 않는다."""
    # timestamptz의 텍스트 표현이 세션 TimeZone을 따른다. DB별 설정(ALTER DATABASE SET)은
    # pg_dump가 옮기지 않으므로 양쪽을 같은 값으로 고정한다.
    connection.execute(sa.text("SET TIME ZONE 'UTC'"))
    quote = connection.dialect.identifier_preparer.quote
    names = connection.execute(
        sa.text("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename")
    ).scalars()
    tables: dict[str, tuple[int, str]] = {}
    for name in names.all():
        # 행 전체의 텍스트를 정렬해 이어 붙인 md5. 물리 순서와 collation에 기대지 않는다.
        rows, digest = connection.execute(
            sa.text(
                "SELECT count(*), md5(coalesce(string_agg(nc_row::text, chr(10) "  # noqa: S608
                f"ORDER BY nc_row::text COLLATE \"C\"), '')) FROM public.{quote(name)} AS nc_row"
            )
        ).one()
        tables[name] = (int(rows), str(digest))

    versions: tuple[str, ...] = ()
    if ALEMBIC_VERSION_TABLE in tables:
        versions = tuple(
            connection.execute(
                sa.text(f"SELECT version_num FROM {ALEMBIC_VERSION_TABLE} ORDER BY 1")  # noqa: S608
            ).scalars()
        )
    sequences = {
        str(name): (None if value is None else int(value))
        for name, value in connection.execute(
            sa.text(
                "SELECT schemaname || '.' || sequencename, last_value FROM pg_sequences "
                "WHERE schemaname NOT IN ('pg_catalog', 'information_schema')"
            )
        ).all()
    }
    constraints = frozenset(
        connection.execute(
            sa.text(
                "SELECT coalesce(rel.relname, '') || '.' || con.conname FROM pg_constraint con "
                "JOIN pg_namespace ns ON ns.oid = con.connamespace "
                "LEFT JOIN pg_class rel ON rel.oid = con.conrelid "
                "WHERE ns.nspname = 'public'"
            )
        ).scalars()
    )
    indexes = frozenset(
        connection.execute(
            sa.text(
                "SELECT tablename || '.' || indexname FROM pg_indexes WHERE schemaname = 'public'"
            )
        ).scalars()
    )
    return Snapshot(
        alembic_versions=versions,
        tables=tables,
        sequences=sequences,
        constraints=constraints,
        indexes=indexes,
    )


def _missing(kind: str, source: frozenset[str], restored: frozenset[str]) -> list[str]:
    return [f"{kind} {name}: missing in restored" for name in sorted(source - restored)] + [
        f"{kind} {name}: only in restored" for name in sorted(restored - source)
    ]


def differences(source: Snapshot, restored: Snapshot) -> list[str]:
    """어긋난 것을 하나씩 이름으로 적는다. 빈 목록이면 1(head 여부 제외)~4가 같다."""
    found: list[str] = []
    if source.alembic_versions != restored.alembic_versions:
        found.append(
            f"alembic_version: source={source.alembic_versions} "
            f"restored={restored.alembic_versions}"
        )
    for name in sorted(source.tables.keys() | restored.tables.keys()):
        left, right = source.tables.get(name), restored.tables.get(name)
        if right is None:
            found.append(f"table {name}: missing in restored")
        elif left is None:
            found.append(f"table {name}: only in restored")
        elif left != right:
            hashes = "same" if left[1] == right[1] else "differs"
            found.append(
                f"table {name}: rows source={left[0]} restored={right[0]}, content hash {hashes}"
            )
    for name in sorted(source.sequences.keys() | restored.sequences.keys()):
        if name not in restored.sequences:
            found.append(f"sequence {name}: missing in restored")
        elif name not in source.sequences:
            found.append(f"sequence {name}: only in restored")
        elif source.sequences[name] != restored.sequences[name]:
            found.append(
                f"sequence {name}: last_value source={source.sequences[name]} "
                f"restored={restored.sequences[name]}"
            )
    found += _missing("constraint", source.constraints, restored.constraints)
    found += _missing("index", source.indexes, restored.indexes)
    return found


# --------------------------------------------------------------------------
# 6: 음성 대조군
# --------------------------------------------------------------------------


def corrupt_one_row(connection: sa.Connection) -> str | None:
    """열린 트랜잭션 안에서 행 수를 바꾸지 않고 1행의 내용만 바꾼다. 호출부가 롤백한다.

    행 수가 같게 훼손하는 이유: 행을 지우면 "행 수만 세는" 비교도 실패하므로 해시에 행
    내용이 들어가는지를 증명하지 못한다. 제약(CHECK, 길이)에 걸리는 열은 건너뛴다.
    """
    quote = connection.dialect.identifier_preparer.quote
    candidates = connection.execute(
        sa.text(
            "SELECT c.table_name, c.column_name FROM information_schema.columns c "
            "JOIN pg_tables t ON t.schemaname = c.table_schema AND t.tablename = c.table_name "
            "WHERE c.table_schema = 'public' AND c.table_name <> :bookkeeping "
            "AND c.data_type IN ('text', 'character varying') "
            "ORDER BY c.table_name, c.ordinal_position"
        ),
        {"bookkeeping": ALEMBIC_VERSION_TABLE},
    ).all()
    for table, column in candidates:
        qt, qc = quote(table), quote(column)
        savepoint = connection.begin_nested()
        try:
            result = connection.execute(
                sa.text(
                    f"UPDATE public.{qt} SET {qc} = {qc} || '#' WHERE ctid = "  # noqa: S608
                    f"(SELECT ctid FROM public.{qt} WHERE {qc} IS NOT NULL LIMIT 1)"
                )
            )
        except sa.exc.DBAPIError:
            savepoint.rollback()
            continue
        if result.rowcount == 1:
            savepoint.commit()
            return str(table)
        savepoint.rollback()
    return None


# --------------------------------------------------------------------------
# 5: 복원 DB에 붙인 API
# --------------------------------------------------------------------------


@contextmanager
def _environment(values: dict[str, str]) -> Iterator[None]:
    """앱은 설정을 환경변수로만 받는다. 이 블록 동안만 복원 DB를 가리키게 한다."""
    previous = {name: os.environ.get(name) for name in values}
    os.environ.update(values)
    get_settings.cache_clear()
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        get_settings.cache_clear()


def check_api(restored: URL, *, login_id: str, password: str) -> str:
    """login이 되고, history 두 endpoint가 복원된 기록을 돌려준다."""
    engine = sa.create_engine(restored, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            stored_sessions = connection.execute(
                sa.text(
                    "SELECT count(*) FROM study_sessions s JOIN users u ON u.id = s.user_id "
                    "WHERE u.login_id = :login_id"
                ),
                {"login_id": normalize_login_id(login_id)},
            ).scalar_one()
    finally:
        engine.dispose()

    env = {
        "DATABASE_URL": restored.render_as_string(hide_password=False),
        "CORS_ALLOW_ORIGINS": CHECK_ORIGIN,
    }
    with _environment(env):
        try:
            with TestClient(
                create_app(), base_url=CHECK_BASE_URL, headers={"Origin": CHECK_ORIGIN}
            ) as client:
                login = client.post(
                    "/api/auth/login", json={"login_id": login_id, "password": password}
                )
                if login.status_code != 200:
                    raise RestoreCheckError(f"login returned {login.status_code}")
                sessions = client.get("/api/history/sessions")
                items = client.get("/api/history/items")
        finally:
            app_engine = get_engine()
            if app_engine is not None:
                app_engine.dispose()

    for path, response in (("sessions", sessions), ("items", items)):
        if response.status_code != 200:
            raise RestoreCheckError(f"GET /api/history/{path} returned {response.status_code}")
    session_rows = sessions.json()["sessions"]
    item_rows = items.json()["items"]
    if bool(session_rows) != bool(stored_sessions):
        raise RestoreCheckError(
            f"history returned {len(session_rows)} sessions but the restored database "
            f"has {stored_sessions} for {login_id!r}"
        )
    return f"api: login ok, history sessions={len(session_rows)} items={len(item_rows)}\n"


# --------------------------------------------------------------------------
# 진입점
# --------------------------------------------------------------------------


def restore(backup: Path, target: URL, *, pg_bin: Path) -> None:
    """이미 만들어 둔 빈 DB에 복원한다. exit 0은 검증이 아니다(뒤의 비교가 검증이다)."""
    conninfo, extra_env = pg_tools.libpq_connection(target)
    result = pg_tools.run(
        [
            str(pg_tools.tool(pg_bin, "pg_restore")),
            "--no-owner",
            "--exit-on-error",
            "--no-password",
            f"--dbname={conninfo}",
            str(backup),
        ],
        extra_env=extra_env,
    )
    if result.returncode != 0:
        raise RestoreCheckError(f"pg_restore exited with {result.returncode}: {result.stderr}")


def verify(source: URL, restored: URL, *, login_id: str, password: str) -> None:
    """1~4 -> 6 -> 5. 실패하면 무엇이 달랐는지 담아 `RestoreCheckError`."""
    head = ScriptDirectory.from_config(Config(str(ALEMBIC_INI))).get_current_head()
    source_engine = sa.create_engine(source, poolclass=NullPool)
    restored_engine = sa.create_engine(restored, poolclass=NullPool)
    try:
        with source_engine.connect() as connection:
            source_snapshot = take_snapshot(connection)
        with restored_engine.connect() as connection:
            restored_snapshot = take_snapshot(connection)

        found = differences(source_snapshot, restored_snapshot)
        if restored_snapshot.alembic_versions != (head,):
            found.insert(
                0, f"alembic_version: restored={restored_snapshot.alembic_versions} head={head}"
            )
        if found:
            raise RestoreCheckError("restored database differs:\n  " + "\n  ".join(found))
        _out(
            f"compared: alembic_version={head} (head), {len(source_snapshot.tables)} tables, "
            f"{len(source_snapshot.sequences)} sequences, "
            f"{len(source_snapshot.constraints)} constraints, "
            f"{len(source_snapshot.indexes)} indexes\n"
        )

        with restored_engine.connect() as connection:
            corrupted = corrupt_one_row(connection)
            caught: list[str] = []
            if corrupted is not None:
                caught = [
                    line
                    for line in differences(source_snapshot, take_snapshot(connection))
                    if line.startswith(f"table {corrupted}:")
                ]
            connection.rollback()
        if corrupted is None:
            raise RestoreCheckError("negative control: no row in the restored database to corrupt")
        if not caught:
            raise RestoreCheckError(
                f"negative control: corrupting one row of {corrupted} was not detected"
            )
        _out(f"negative control: corrupted one row of {corrupted} -> detected, rolled back\n")
    finally:
        source_engine.dispose()
        restored_engine.dispose()

    _out(check_api(restored, login_id=login_id, password=password))


def _read_password(*, from_stdin: bool) -> str | None:
    if from_stdin:
        return sys.stdin.readline().rstrip("\n")
    if not sys.stdin.isatty():
        return None
    return getpass.getpass("Password: ")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Restore a backup into a separate database and verify it against DATABASE_URL. "
            "전제: API와 worker를 dump 전에 멈추고, 이 명령이 끝날 때까지 원본에 쓰기가 없어야 "
            "한다 (worker_heartbeats, auth_sessions.last_used_at)."
        )
    )
    parser.add_argument(
        "--pg-bin",
        type=Path,
        required=True,
        help="pg_restore가 있는 디렉터리. 기본값도 PATH 탐색도 없다.",
    )
    parser.add_argument("--backup", type=Path, required=True, help="복원할 백업 파일.")
    parser.add_argument(
        "--login-id", required=True, help="복원 DB에서 login과 history를 확인할 계정."
    )
    parser.add_argument(
        "--password-stdin",
        action="store_true",
        help="stdin 한 줄에서 password를 읽는다. 없으면 TTY 프롬프트다(argv로 받지 않는다).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    database_url = get_settings().database_url
    if not database_url:
        return _fail("DATABASE_URL is not configured")
    source = make_url(database_url)
    if not source.database:
        return _fail("DATABASE_URL has no database name")
    try:
        _out(pg_tools.describe_target(source))
    except ValueError as exc:
        return _fail(str(exc))
    _out(
        "precondition: API and worker are stopped, and nothing writes to the source database "
        "from the dump until this check ends\n"
    )
    if not args.backup.is_file():
        return _fail(f"backup file not found: {args.backup}")
    password = _read_password(from_stdin=args.password_stdin)
    if password is None:
        return _fail("password input failed (no TTY without --password-stdin)")

    restore_name = f"{source.database}_restore_{utc_now():%Y%m%dT%H%M%SZ}"
    if len(restore_name.encode()) > MAX_IDENTIFIER_BYTES:
        return _fail(f"restore database name would be truncated by PostgreSQL: {restore_name}")
    restored = source.set(database=restore_name)

    admin = sa.create_engine(
        source.set(database=MAINTENANCE_DATABASE), isolation_level="AUTOCOMMIT", poolclass=NullPool
    )
    created = False
    try:
        with admin.connect() as connection:
            quoted = connection.dialect.identifier_preparer.quote(restore_name)
            exists = connection.execute(
                sa.text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": restore_name}
            ).first()
            if exists is not None:
                return _fail(f"restore database already exists: {restore_name}")
            connection.execute(sa.text(f"CREATE DATABASE {quoted}"))
            created = True
        _out(f"restore database: {restore_name}\n")

        restore(args.backup, restored, pg_bin=args.pg_bin)
        _out(f"pg_restore: done ({args.backup.name})\n")
        verify(source, restored, login_id=args.login_id, password=password)
    except (RestoreCheckError, FileNotFoundError, ValueError) as exc:
        return _fail(f"restore check failed: {exc}")
    finally:
        if created:
            with admin.connect() as connection:
                connection.execute(sa.text(f"DROP DATABASE IF EXISTS {quoted} WITH (FORCE)"))
            _out(f"dropped restore database: {restore_name}\n")
        admin.dispose()
    _out("restore check passed\n")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
