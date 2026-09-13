"""백업·rotation·restore 검증 (`12_TEST_PLAN.md` Integration의 backup/restore, rotation).

`scripts/db_backup.py`와 `scripts/db_restore_check.py`를 **실제 pg_dump / pg_restore**(pgserver
번들, ADR-020 결정 2)로 돌린다. 운영 경로(`data/backups/`, `data/postgres/`)와 개발 DB
(`data/pgdata`)는 쓰지 않는다 --- 백업은 `tmp_path`, DB는 테스트 pgserver의 일회용 DB다.

## 무엇을 단정하는가

-   backup/restore: migration + seed + create-user + 학습 진행(presentation 완료, self-report,
    history에 행)으로 만든 DB를 백업하고 별도 DB에 복원해 `restore 검증` 여섯 가지가 통과한다.
-   **음성 대조군이 빨개진다.** 복원 직후 복원본을 훼손하는 경우(행 내용, index, 제약,
    sequence, alembic_version, 코드가 모르는 새 테이블)마다 명령이 non-zero이고 무엇이
    달랐는지 이름을 댄다. 이것이 없으면 항상 "같다"고 답하는 비교가 통과한다.
-   rotation: 새 백업이 실패하면 옛 백업이 하나도 지워지지 않고 non-zero, 성공하면 가장
    오래된 것부터 지워져 보관 개수가 유지된다. 무관한 파일은 남는다. 파일은 **쓰이는 동안에도**
    0600이다.
-   password가 어떤 subprocess argv에도 없고 `PGPASSWORD`로만 넘어간다.

비교할 테이블 이름 목록은 여기에도 없다. 훼손 대상으로 몇 개를 **지목**할 뿐이다.
"""

from __future__ import annotations

import importlib.util
import io
import os
import subprocess
import sys
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx2
import pgserver
import pytest
import sqlalchemy as sa
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy.engine import URL, make_url
from sqlalchemy.pool import NullPool

from app.config import get_config
from app.db import get_engine, new_session
from app.main import create_app
from app.models import StudyPresentation, UserSentenceCandidateTarget
from app.models.enums import ExplicitSignal
from app.settings import get_settings
from tests import db_support

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
PG_BIN = Path(pgserver.__file__).parent / "pginstall" / "bin"

LOGIN_ID = "restore-learner"
PASSWORD = "correct horse battery staple"
ORIGIN = "https://app.test"
# DSN에 넣는 password. 테스트 pgserver는 trust 인증이라 값과 무관하게 붙는다 --- 여기서 보는
# 것은 인증이 아니라 "이 문자열이 argv와 출력에 새지 않는가"다.
DSN_PASSWORD = "nc-sentinel-dsn-password-7f3a"

EXIT_FAILED = 2


def load_script(name: str) -> ModuleType:
    """scripts/는 패키지가 아니므로 파일 경로로 적재한다 (test_db_reset.py와 같은 방식)."""
    spec = importlib.util.spec_from_file_location(name, SCRIPTS_DIR / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # `db_restore_check`의 dataclass는 적재 중에 자기 모듈을 sys.modules에서 찾는다.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def render(dsn: URL) -> str:
    return dsn.render_as_string(hide_password=False)


@contextmanager
def app_env(**values: str) -> Iterator[None]:
    """설정은 환경변수로만 들어간다. module fixture에서도 쓰므로 monkeypatch fixture를 쓰지 않는다."""
    with pytest.MonkeyPatch.context() as patch:
        for name, value in values.items():
            patch.setenv(name, value)
        get_settings.cache_clear()
        get_config.cache_clear()
        try:
            yield
        finally:
            get_settings.cache_clear()
            get_config.cache_clear()


@contextmanager
def stdin_line(value: str) -> Iterator[None]:
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("sys.stdin", io.StringIO(f"{value}\n"))
        yield


def ok(response: httpx2.Response, status: int = 200) -> dict[str, Any]:
    assert response.status_code == status, response.text
    if status == 204:
        return {}
    payload = response.json()
    assert isinstance(payload, dict)
    return payload


# --------------------------------------------------------------------------
# 학습이 진행된 원본 DB (module 1회)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class LearnedDatabase:
    dsn: URL
    history_sessions: int
    history_items: int


def _learn() -> tuple[int, int]:
    """login -> session -> presentation -> target item self-report -> 완료 -> history."""
    app = create_app()
    try:
        with TestClient(app, base_url="https://testserver", headers={"Origin": ORIGIN}) as client:
            ok(client.post("/api/auth/login", json={"login_id": LOGIN_ID, "password": PASSWORD}))
            session_id = ok(client.post("/api/study/session"))["session"]["session_id"]
            presentation = ok(client.post(f"/api/study/session/{session_id}/next"))["presentation"]
            assert presentation is not None, "seed에서 Ready Pool이 만들어지지 않았다"
            presentation_id = presentation["presentation_id"]

            # target item에 신호를 줘야 exposure와 mastery가 함께 남아 item history가 생긴다.
            with new_session() as db:
                targets = set(
                    db.scalars(
                        sa.select(UserSentenceCandidateTarget.learning_item_id).where(
                            UserSentenceCandidateTarget.candidate_id
                            == sa.select(StudyPresentation.candidate_id)
                            .where(StudyPresentation.id == presentation_id)
                            .scalar_subquery()
                        )
                    )
                )
            tappable = [
                t for t in presentation["tappable_items"] if t["learning_item_id"] in targets
            ]
            assert tappable, presentation["tappable_items"]
            ok(
                client.post(
                    f"/api/study/presentations/{presentation_id}/self-report",
                    json={
                        "client_event_id": str(uuid.uuid4()),
                        "sentence_item_id": tappable[0]["sentence_item_id"],
                        "value": ExplicitSignal.UNKNOWN.value,
                    },
                ),
                status=204,
            )
            ok(client.post(f"/api/study/presentations/{presentation_id}/complete"))
            sessions = ok(client.get("/api/history/sessions"))["sessions"]
            items = ok(client.get("/api/history/items"))["items"]
    finally:
        engine = get_engine()
        if engine is not None:
            engine.dispose()
    # 빈 history끼리 같다는 비교는 5를 아무것도 증명하지 않게 만든다.
    assert sessions and items
    return len(sessions), len(items)


@pytest.fixture(scope="module")
def learned_database(postgres_admin_dsn: URL) -> Iterator[LearnedDatabase]:
    name = f"nc_backup_{uuid.uuid4().hex[:12]}"
    dsn = db_support.recreate_database(postgres_admin_dsn, name).set(password=DSN_PASSWORD)
    try:
        db_support.alembic_upgrade(dsn)
        with app_env(DATABASE_URL=render(dsn), CORS_ALLOW_ORIGINS=ORIGIN):
            assert load_script("load_seed").main([]) == 0
            with stdin_line(PASSWORD):
                create_user = load_script("create_user")
                assert create_user.main(["--login-id", LOGIN_ID, "--password-stdin"]) == 0
            sessions, items = _learn()
        yield LearnedDatabase(dsn=dsn, history_sessions=sessions, history_items=items)
    finally:
        db_support.drop_database(postgres_admin_dsn, name)


@pytest.fixture(scope="module")
def backup_file(
    learned_database: LearnedDatabase, tmp_path_factory: pytest.TempPathFactory
) -> Path:
    backup_dir = tmp_path_factory.mktemp("backups")
    with app_env(DATABASE_URL=render(learned_database.dsn)):
        code = load_script("db_backup").main(
            ["--pg-bin", str(PG_BIN), "--backup-dir", str(backup_dir)]
        )
    assert code == 0
    [path] = list(backup_dir.iterdir())
    return path


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Call:
    argv: list[str]
    env: dict[str, str]


@pytest.fixture
def subprocess_calls(monkeypatch: pytest.MonkeyPatch) -> list[Call]:
    """스크립트가 띄운 모든 subprocess의 argv와 환경. 실제 실행은 그대로 한다."""
    calls: list[Call] = []
    real: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run

    def recording(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        env = kwargs.get("env")
        calls.append(
            Call(argv=[str(a) for a in argv], env=dict(env) if isinstance(env, dict) else {})
        )
        return real(argv, **kwargs)

    monkeypatch.setattr(subprocess, "run", recording)
    return calls


def run_restore_check(
    module: ModuleType, dsn: URL, backup: Path, capsys: pytest.CaptureFixture[str]
) -> tuple[int, str]:
    capsys.readouterr()
    with app_env(DATABASE_URL=render(dsn)), stdin_line(PASSWORD):
        code = module.main(
            [
                "--pg-bin",
                str(PG_BIN),
                "--backup",
                str(backup),
                "--login-id",
                LOGIN_ID,
                "--password-stdin",
            ]
        )
    captured = capsys.readouterr()
    return int(code), captured.out + captured.err


def tamper_after_restore(
    monkeypatch: pytest.MonkeyPatch, module: ModuleType, tamper: Callable[[sa.Connection], None]
) -> None:
    """복원이 끝난 직후, 비교 전에 복원본을 바꾼다. 명령의 나머지는 그대로 돈다."""
    real_restore = module.restore

    def restore_then_tamper(backup: Path, target: URL, *, pg_bin: Path) -> None:
        real_restore(backup, target, pg_bin=pg_bin)
        engine = sa.create_engine(target, poolclass=NullPool)
        try:
            with engine.begin() as connection:
                tamper(connection)
        finally:
            engine.dispose()

    monkeypatch.setattr(module, "restore", restore_then_tamper)


def leftover_restore_databases(dsn: URL) -> list[str]:
    engine = sa.create_engine(dsn, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            return list(
                connection.execute(
                    sa.text("SELECT datname FROM pg_database WHERE starts_with(datname, :prefix)"),
                    {"prefix": f"{dsn.database}_restore_"},
                ).scalars()
            )
    finally:
        engine.dispose()


def _sql(statement: str) -> Callable[[sa.Connection], None]:
    def run(connection: sa.Connection) -> None:
        connection.execute(sa.text(statement))

    return run


# --------------------------------------------------------------------------
# DSN -> libpq (DB 없음)
# --------------------------------------------------------------------------


def test_a_sqlalchemy_dsn_is_split_into_conninfo_and_pgpassword() -> None:
    pg_tools = load_script("pg_tools")
    dsn = make_url(f"postgresql+psycopg://nc:{DSN_PASSWORD}@127.0.0.1:5432/nihongo")

    conninfo, extra_env = pg_tools.libpq_connection(dsn)

    assert DSN_PASSWORD not in conninfo
    assert set(conninfo.split()) == {"host=127.0.0.1", "port=5432", "user=nc", "dbname=nihongo"}
    assert extra_env == {"PGPASSWORD": DSN_PASSWORD}


def test_a_unix_socket_dsn_without_password_leaves_pgpassword_unset() -> None:
    """pgserver 형식. password가 비어 있으면 PGPASSWORD를 넣지 않는다(~/.pgpass로 간다)."""
    pg_tools = load_script("pg_tools")
    dsn = make_url("postgresql+psycopg://postgres:@/nihongo?host=%2Ftmp%2Fpg%20sock")

    conninfo, extra_env = pg_tools.libpq_connection(dsn)

    assert "host='/tmp/pg sock'" in conninfo
    assert "dbname=nihongo" in conninfo
    assert extra_env == {}
    assert "host=/tmp/pg sock port=(default) database=nihongo" in pg_tools.describe_target(dsn)


def test_the_printed_target_masks_the_password() -> None:
    pg_tools = load_script("pg_tools")
    dsn = make_url(f"postgresql+psycopg://nc:{DSN_PASSWORD}@127.0.0.1:5432/nihongo")

    described = pg_tools.describe_target(dsn)

    assert DSN_PASSWORD not in described
    assert "host=127.0.0.1 port=5432 database=nihongo" in described


@pytest.mark.parametrize(
    "query",
    [
        f"password={DSN_PASSWORD}",
        "dbname=other",
        "user=other",
        "port=6543",
        "service=other",
        "passfile=%2Ftmp%2Fpgpass",
        "options=-csearch_path%3Dother",
    ],
)
def test_a_query_key_other_than_host_is_rejected_without_its_value(query: str) -> None:
    """query의 연결 대상·인증 키는 userinfo/경로를 이기거나 argv로 새므로 거부한다."""
    pg_tools = load_script("pg_tools")
    dsn = make_url(f"postgresql+psycopg://nc:secret@127.0.0.1:5432/nihongo?{query}")
    key, value = query.split("=", 1)

    for call in (pg_tools.describe_target, pg_tools.libpq_connection):
        with pytest.raises(ValueError, match=key) as caught:
            call(dsn)
        assert value not in str(caught.value)
        assert "secret" not in str(caught.value)


def test_a_query_host_is_rejected_when_the_dsn_already_has_a_host() -> None:
    """psycopg는 query의 host를, libpq 변환은 경로의 host를 쓴다. 백업과 upgrade 대상이 갈린다."""
    pg_tools = load_script("pg_tools")
    dsn = make_url("postgresql+psycopg://u@127.0.0.1:5432/prod?host=%2Ftmp%2Fnc-socket")

    for call in (pg_tools.describe_target, pg_tools.libpq_connection):
        with pytest.raises(ValueError, match="host") as caught:
            call(dsn)
        assert "nc-socket" not in str(caught.value)


def test_a_query_password_is_not_printed_by_the_backup_command(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dsn = f"postgresql+psycopg://u@/prod?host=%2Ftmp&password={DSN_PASSWORD}"
    with app_env(DATABASE_URL=dsn):
        code = load_script("db_backup").main(
            ["--pg-bin", str(PG_BIN), "--backup-dir", str(tmp_path)]
        )
    captured = capsys.readouterr()

    assert code == EXIT_FAILED
    assert "password" in captured.err
    assert DSN_PASSWORD not in captured.out + captured.err


def test_a_query_dbname_is_rejected_before_the_restore_check_connects(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """query의 dbname은 `set(database=...)`를 이겨 복원 DB 대신 원본에 붙게 한다."""
    backup = tmp_path / "backup.dump"
    backup.write_bytes(b"")
    dsn = make_url("postgresql+psycopg://u@127.0.0.1:1/prod?dbname=prod")

    code, output = run_restore_check(load_script("db_restore_check"), dsn, backup, capsys)

    assert code == EXIT_FAILED, output
    assert "dbname" in output
    assert "restore database:" not in output


def test_the_pgserver_uri_with_only_host_in_the_query_is_accepted() -> None:
    """`pgserver.get_uri()`가 주는 그대로의 형태(인코딩 안 된 socket 경로)."""
    pg_tools = load_script("pg_tools")
    dsn = make_url("postgresql://postgres:@/nihongo?host=/tmp/pgserver-sock").set(
        drivername="postgresql+psycopg"
    )

    conninfo, extra_env = pg_tools.libpq_connection(dsn)

    assert set(conninfo.split()) == {"host=/tmp/pgserver-sock", "user=postgres", "dbname=nihongo"}
    assert extra_env == {}
    assert "host=/tmp/pgserver-sock port=(default)" in pg_tools.describe_target(dsn)


def test_a_restore_database_name_over_63_bytes_is_rejected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """잘린 이름이 원본과 같아지면 마지막 DROP이 원본을 지운다. 연결 전에 거부한다."""
    backup = tmp_path / "backup.dump"
    backup.write_bytes(b"")
    dsn = make_url(f"postgresql+psycopg://u@127.0.0.1:1/{'n' * 40}")

    code, output = run_restore_check(load_script("db_restore_check"), dsn, backup, capsys)

    assert code == EXIT_FAILED, output
    assert "would be truncated by PostgreSQL" in output


def test_pg_bin_is_required() -> None:
    """기본값도 PATH 탐색도 없다(ADR-020 결정 2)."""
    with pytest.raises(SystemExit):
        load_script("db_backup").main([])
    with pytest.raises(SystemExit):
        load_script("db_restore_check").main(["--backup", "x", "--login-id", "x"])


# --------------------------------------------------------------------------
# backup/restore
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_backup_then_restore_check_passes_all_six_checks(
    learned_database: LearnedDatabase,
    tmp_path: Path,
    subprocess_calls: list[Call],
    capsys: pytest.CaptureFixture[str],
) -> None:
    backup_dir = tmp_path / "backups"
    dsn = learned_database.dsn

    with app_env(DATABASE_URL=render(dsn)):
        code = load_script("db_backup").main(
            ["--pg-bin", str(PG_BIN), "--backup-dir", str(backup_dir)]
        )
    backup_output = capsys.readouterr()
    assert code == 0, backup_output.err

    # 작업 전에 대상과 두 버전이 보인다. password는 보이지 않는다.
    assert f"database={dsn.database}" in backup_output.out
    assert "pg_dump client: pg_dump (PostgreSQL) 16" in backup_output.out
    assert "server version: 16" in backup_output.out
    assert DSN_PASSWORD not in backup_output.out + backup_output.err

    [backup] = list(backup_dir.iterdir())
    assert load_script("db_backup").BACKUP_NAME_PATTERN.fullmatch(backup.name)
    assert backup.stat().st_mode & 0o777 == 0o600

    code, output = run_restore_check(load_script("db_restore_check"), dsn, backup, capsys)
    assert code == 0, output
    assert "restore check passed" in output
    assert DSN_PASSWORD not in output
    assert PASSWORD not in output

    head = ScriptDirectory.from_config(db_support.alembic_config(dsn)).get_current_head()
    compared = output.index(f"compared: alembic_version={head} (head)")
    negative = output.index("negative control: corrupted one row of")
    api = output.index(
        f"api: login ok, history sessions={learned_database.history_sessions} "
        f"items={learned_database.history_items}"
    )
    # 5(login이 auth_sessions에 쓴다)는 1~4와 6 뒤다.
    assert compared < negative < api
    assert leftover_restore_databases(dsn) == []

    # password는 어떤 argv에도 없고, DB에 붙는 호출에는 PGPASSWORD로만 간다.
    tools = [Path(call.argv[0]).name for call in subprocess_calls]
    assert "pg_dump" in tools and "pg_restore" in tools, tools
    for call in subprocess_calls:
        assert all(DSN_PASSWORD not in arg for arg in call.argv), call.argv
    connecting = [
        call for call in subprocess_calls if any(a.startswith("--dbname=") for a in call.argv)
    ]
    assert {Path(call.argv[0]).name for call in connecting} == {"pg_dump", "pg_restore"}
    assert all(call.env.get("PGPASSWORD") == DSN_PASSWORD for call in connecting)


@pytest.mark.parametrize(
    ("tamper", "expected"),
    [
        pytest.param(
            _sql(
                "UPDATE learning_items SET lemma = lemma || '#' "
                "WHERE id = (SELECT min(id) FROM learning_items)"
            ),
            "table learning_items: rows source=",
            id="row-content",
        ),
        pytest.param(
            _sql("DROP INDEX uq_learning_events_evidence"),
            "index learning_events.uq_learning_events_evidence: missing in restored",
            id="partial-index-evidence",
        ),
        pytest.param(
            _sql("DROP INDEX uq_study_presentations_open"),
            "index study_presentations.uq_study_presentations_open: missing in restored",
            id="partial-index-open-presentation",
        ),
        pytest.param(
            _sql(
                "ALTER TABLE user_mastery DROP CONSTRAINT uq_user_mastery_user_id_learning_item_id"
            ),
            "constraint user_mastery.uq_user_mastery_user_id_learning_item_id: missing in restored",
            id="constraint",
        ),
        pytest.param(
            _sql("SELECT setval(pg_get_serial_sequence('users', 'id'), 100000)"),
            "sequence public.users_id_seq: last_value",
            id="sequence",
        ),
        pytest.param(
            _sql("UPDATE alembic_version SET version_num = '0002'"),
            "alembic_version:",
            id="alembic-version",
        ),
    ],
)
@pytest.mark.integration
def test_a_tampered_restore_fails_and_names_what_differs(
    learned_database: LearnedDatabase,
    backup_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tamper: Callable[[sa.Connection], None],
    expected: str,
) -> None:
    """음성 대조군. 같은 명령이 훼손 하나를 그 이름으로 잡는다."""
    module = load_script("db_restore_check")
    tamper_after_restore(monkeypatch, module, tamper)

    code, output = run_restore_check(module, learned_database.dsn, backup_file, capsys)

    assert code == EXIT_FAILED, output
    assert expected in output, output
    assert "restore check passed" not in output
    assert leftover_restore_databases(learned_database.dsn) == []


@pytest.mark.integration
def test_a_table_the_code_does_not_know_is_still_compared(
    learned_database: LearnedDatabase,
    backup_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """테이블 목록을 적어 둔 검증은 새 테이블을 영영 보지 않는다. catalog에서 나열해야 잡힌다.

    모델에도 migration에도 없는 테이블을 원본과 복원본 양쪽에 같은 행 수, 다른 내용으로 둔다.
    제약·index도 양쪽이 같으므로 이 차이를 잡을 수 있는 것은 catalog 기반 내용 비교뿐이다.
    """
    table = "nc_added_after_this_test_was_written"
    create = f"CREATE TABLE {table} (note text)"
    engine = sa.create_engine(learned_database.dsn, poolclass=NullPool)
    try:
        with engine.begin() as connection:
            connection.execute(sa.text(create))
            connection.execute(sa.text(f"INSERT INTO {table} VALUES ('kept')"))  # noqa: S608
        module = load_script("db_restore_check")
        tamper_after_restore(
            monkeypatch,
            module,
            _sql(f"{create}; INSERT INTO {table} VALUES ('lost')"),  # noqa: S608
        )

        code, output = run_restore_check(module, learned_database.dsn, backup_file, capsys)
    finally:
        with engine.begin() as connection:
            connection.execute(sa.text(f"DROP TABLE IF EXISTS {table}"))
        engine.dispose()

    assert code == EXIT_FAILED, output
    assert f"table {table}: rows source=1 restored=1, content hash differs" in output, output


@pytest.mark.integration
def test_a_restore_that_matches_but_is_not_head_fails(
    learned_database: LearnedDatabase,
    backup_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """1은 "원본과 같다"만이 아니라 "그 값이 head다"까지다."""
    engine = sa.create_engine(learned_database.dsn, poolclass=NullPool)
    with engine.begin() as connection:
        head = connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one()
    stale = _sql("UPDATE alembic_version SET version_num = '0002'")
    try:
        with engine.begin() as connection:
            stale(connection)
        module = load_script("db_restore_check")
        tamper_after_restore(monkeypatch, module, stale)

        code, output = run_restore_check(module, learned_database.dsn, backup_file, capsys)
    finally:
        with engine.begin() as connection:
            connection.execute(
                sa.text("UPDATE alembic_version SET version_num = :head"), {"head": head}
            )
        engine.dispose()

    assert code == EXIT_FAILED, output
    assert f"alembic_version: restored=('0002',) head={head}" in output, output
    assert "table alembic_version" not in output


@pytest.mark.integration
def test_a_comparison_that_always_agrees_fails_the_negative_control(
    learned_database: LearnedDatabase,
    backup_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """6이 명령 안에서 실제로 돈다. 비교가 무엇이든 "같다"고 하면 명령이 실패한다."""
    module = load_script("db_restore_check")
    monkeypatch.setattr(module, "differences", lambda source, restored: [])

    code, output = run_restore_check(module, learned_database.dsn, backup_file, capsys)

    assert code == EXIT_FAILED, output
    assert "negative control:" in output and "was not detected" in output, output
    assert "api: login ok" not in output


# --------------------------------------------------------------------------
# rotation
# --------------------------------------------------------------------------

OLD_BACKUPS = (
    "backup-20260101T041700Z.dump",
    "backup-20260102T041700Z.dump",
    "backup-20260103T041700Z.dump",
)
# 이름 패턴이 아닌 파일. 전부 옛 백업보다 "오래돼 보이는" 이름이라 패턴을 무시하면 먼저 지워진다.
UNRELATED = (
    ".gitkeep",
    "backup-20250101T000000Z.dump.partial",
    "backup-20250101T000000Z.dump.bak",
    "notes.txt",
)
KEEP = len(OLD_BACKUPS)


def _populated_backup_dir(tmp_path: Path) -> Path:
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    for name in OLD_BACKUPS + UNRELATED:
        (backup_dir / name).write_bytes(name.encode())
    return backup_dir


def _state(directory: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in directory.iterdir()}


def _pg_bin_with_pg_dump(tmp_path: Path, body: str) -> Path:
    """pg_dump만 바꾼 `--pg-bin`. `--version`과 pg_restore는 실제 바이너리다."""
    bin_dir = tmp_path / "pg-bin"
    bin_dir.mkdir()
    real = PG_BIN / "pg_dump"
    script = bin_dir / "pg_dump"
    script.write_text(
        f'#!/bin/sh\nif [ "$1" = "--version" ]; then exec "{real}" --version; fi\n{body}',
        encoding="utf-8",
    )
    script.chmod(0o755)
    (bin_dir / "pg_restore").symlink_to(PG_BIN / "pg_restore")
    return bin_dir


def _run_backup(dsn: URL, pg_bin: Path, backup_dir: Path) -> int:
    with app_env(DATABASE_URL=render(dsn)):
        code = load_script("db_backup").main(
            ["--pg-bin", str(pg_bin), "--backup-dir", str(backup_dir), "--keep", str(KEEP)]
        )
    return int(code)


@pytest.mark.parametrize(
    "pg_dump_body",
    [
        pytest.param("echo 'pg_dump: error: simulated' >&2\nexit 1\n", id="dump-fails"),
        pytest.param("exit 0\n", id="empty-file"),
        pytest.param("printf 'not a pg_dump archive'\nexit 0\n", id="unreadable-toc"),
    ],
)
@pytest.mark.integration
def test_a_failed_backup_deletes_nothing(
    database_url: URL,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    pg_dump_body: str,
) -> None:
    backup_dir = _populated_backup_dir(tmp_path)
    before = _state(backup_dir)

    code = _run_backup(database_url, _pg_bin_with_pg_dump(tmp_path, pg_dump_body), backup_dir)

    assert code == EXIT_FAILED
    assert "nothing was rotated" in capsys.readouterr().err
    # 옛 백업은 하나도 지워지지 않았고, 실패한 파일(.partial)도 남지 않았다.
    assert _state(backup_dir) == before


@pytest.mark.integration
def test_a_successful_backup_rotates_the_oldest_and_is_0600_while_written(
    database_url: URL, tmp_path: Path
) -> None:
    backup_dir = _populated_backup_dir(tmp_path)
    modes_log = tmp_path / "modes-during-dump.txt"
    # 실제 pg_dump를 부르기 직전에 쓰이고 있는 파일의 권한을 기록한다. 만든 뒤 chmod로 줄이는
    # 구현은 umask 0 아래에서 여기에 0600이 아닌 값을 남긴다.
    pg_bin = _pg_bin_with_pg_dump(
        tmp_path,
        f'stat -c "%n %a" "{backup_dir}"/*.partial > "{modes_log}"\n'
        f'exec "{PG_BIN / "pg_dump"}" "$@"\n',
    )

    previous_umask = os.umask(0)
    try:
        code = _run_backup(database_url, pg_bin, backup_dir)
    finally:
        os.umask(previous_umask)

    assert code == 0
    after = _state(backup_dir)
    backups = sorted(name for name in after if name.endswith(".dump"))
    [new] = [name for name in backups if name not in OLD_BACKUPS]
    # 가장 오래된 것 하나가 지워져 보관 개수가 유지된다.
    assert backups == [*OLD_BACKUPS[1:], new]
    for name in UNRELATED:
        assert after[name] == name.encode()
    assert f"{new}.partial" not in after
    modes = dict(line.rsplit(" ", 1) for line in modes_log.read_text(encoding="utf-8").splitlines())
    being_written = {Path(path).name: mode for path, mode in modes.items()}
    assert being_written.pop("backup-20250101T000000Z.dump.partial") is not None  # 무관한 파일
    assert being_written == {f"{new}.partial": "600"}
    assert (backup_dir / new).stat().st_mode & 0o777 == 0o600
    listing = subprocess.run(  # noqa: S603
        [str(PG_BIN / "pg_restore"), "--list", str(backup_dir / new)],
        capture_output=True,
        check=False,
    )
    assert listing.returncode == 0
