"""restart 후 state 유지 (`13_ACCEPTANCE_CRITERIA.md`, `12_TEST_PLAN.md`).

로그인하고 study session을 열어 presentation 완료와 self-report까지 진행한 뒤

-   (a) API와 worker를 **새 프로세스로** 다시 띄운다.
-   (b) Postgres를 멈췄다가 **같은 data 디렉터리로** 다시 띄운다.

각각의 뒤에 재시작 전에 받은 cookie로 인증된 요청이 성공하고, idle timeout 이내의
`POST /api/study/session`이 같은 session을 이어받으며(`resumed`), 그 사용자의
`item_exposures` / `user_mastery` / history 응답이 재시작 전과 같다.

## 왜 in-process 캐시 비우기가 아니라 진짜 프로세스인가

`12_TEST_PLAN.md`가 못박는다: "(a)의 새 프로세스는 같은 프로세스 안에서 캐시를 비우는
것이 아니다". `get_settings` / `get_config` / `_build_engine`의 `lru_cache`나
connection pool이 살아 있으면 그 상태에 기댄 구현도 통과한다. 같은 프로세스에서
`cache_clear()` + `dispose()`를 부르고 "비워졌다"를 단언하는 테스트는 **우리가 아는
캐시**만 비운다 --- 누군가 모듈 전역에 새 캐시를 두면 그것은 살아남고 테스트는 초록이다.
프로세스를 바꾸면 모르는 캐시까지 전부 사라진다.

그래서 uvicorn(`make run`과 같은 진입점)과 worker loop를 subprocess로 띄우고 SIGKILL로
죽인다. 정상 종료(SIGTERM)가 아니라 kill인 이유: 응답을 내기 전에 commit하지 않은
구현은 graceful shutdown에서는 우연히 살아남을 수 있다.

## "B가 새 커넥션으로 DB를 읽었다"의 증거

프로세스 pid가 달라졌다는 것만으로는 부족하다(B가 떠 있어도 A가 아직 요청을 받고
있을 수 있다). 두 가지를 더 본다.

1.  A의 DB backend(`pg_stat_activity`)가 **전부 사라진 뒤에** B를 띄운다.
2.  B의 요청 뒤에 보이는 backend는 **전부** A가 사라진 시점 이후에 시작됐다
    (`backend_start`). pid만 비교하면 OS의 pid 재사용에 속을 수 있어 시작 시각으로 본다.

두 프로세스는 **같은 DSN**을 쓴다(실제 재시작이 그렇다). `application_name`은 A/B를
가르는 표지가 아니라 "이 테스트가 띄운 API/worker의 backend"를 다른 테스트의 커넥션과
구분하는 표지다.

## Postgres 재시작 (b)

공유 pgserver(`data/pgtest`)는 **멈추지 않는다.** 같은 머신의 다른 pytest 실행(다른
에이전트, watch 모드)이 그 서버를 함께 쓰고 있어서 멈추면 그쪽 테스트가 무작위로 죽는다.
대신 이 테스트 전용 pgserver를 `tmp_path`에 따로 initdb해서 멈추고 다시 띄운다. 공유
서버와는 data 디렉터리와 소켓이 모두 다르다.

API 프로세스가 끊긴 DB 연결에서 스스로 회복하는지는 이 기준이 요구하지 않으므로
(`12_TEST_PLAN.md`), Postgres를 다시 띄운 뒤에는 API도 새로 띄운다. (b)가 단정하는 것은
데이터가 남는가다.

정책값은 테스트가 쥔 config를 파일로 써서 `NC_CONFIG_PATH`로 두 프로세스에 똑같이
넣는다. idle timeout 이내라는 전제도 그 값에서 확인한다(숫자를 적지 않는다).
"""

from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any

import httpx2
import pytest
import sqlalchemy as sa
import yaml
from sqlalchemy.engine import URL, Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import AppConfig, get_config
from app.llm.prompts import explain_item, review_context, sentence_gen
from app.models import (
    ItemExposure,
    StudyPresentation,
    UserMastery,
    UserSentenceCandidateTarget,
    WorkerHeartbeat,
)
from app.models.enums import ExplicitSignal, LlmTaskType
from app.services.auth import SESSION_COOKIE_NAME, hash_password
from app.services.seed_loader import load_seed
from tests import db_support, factories

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
SEED_DIR = REPO_ROOT / "seed"

ORIGIN = "https://app.test"
PASSWORD = "correct horse battery staple"
HOST = "127.0.0.1"

# 이 테스트가 띄운 프로세스의 backend를 다른 커넥션과 구분하는 표지.
API_APPLICATION_NAME = "nc-restart-api"
WORKER_APPLICATION_NAME = "nc-restart-worker"

# 기동/정리 대기 상한. 정책값이 아니라 무한 대기 대신 실패로 끝내는 장치다.
STARTUP_TIMEOUT_SECONDS = 60.0
SETTLE_TIMEOUT_SECONDS = 30.0
REQUEST_TIMEOUT_SECONDS = 30.0
_POLL_INTERVAL_SECONDS = 0.1

# worker loop를 새 인터프리터에서 돌리는 진입점. `scripts/run_worker.py`와 같은 loop와
# runner를 쓰고 provider 자리에만 test double을 넣는다 --- 실제 진입점은 `LLM_PROVIDER`와
# 키를 요구하고, 그 경로로 띄우면 pending job이 있을 때 실제 provider에 요청이 나간다.
# double은 응답을 하나도 들고 있지 않으므로 호출되면 그 job은 실패로 끝날 뿐 바깥으로
# 아무것도 보내지 않는다.
_WORKER_PROBE = """
from app.config import get_config
from app.db import new_session
from app.jobs.runner import run_job
from app.jobs.worker import ShutdownSignal, install_signal_handlers, run_worker
from tests.provider_double import RecordingProvider

shutdown = ShutdownSignal()
install_signal_handlers(shutdown)
run_worker(
    session_factory=new_session,
    provider=RecordingProvider(),
    run_job=run_job,
    cfg=get_config(),
    shutdown=shutdown,
)
"""


# --------------------------------------------------------------------------
# 프로세스
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Runtime:
    """두 프로세스가 똑같이 받는 것. 재시작은 이것을 바꾸지 않는다."""

    database_url: URL
    config_path: Path
    logs: Path

    def env(self, *, application_name: str) -> dict[str, str]:
        dsn = self.database_url.update_query_dict({"application_name": application_name})
        return {
            "PATH": "/usr/bin:/bin",
            "PYTHONPATH": str(BACKEND_ROOT),
            "DATABASE_URL": dsn.render_as_string(hide_password=False),
            "CORS_ALLOW_ORIGINS": ORIGIN,
            "NC_CONFIG_PATH": str(self.config_path),
        }


def _free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as probe:
        probe.bind((HOST, 0))
        return int(probe.getsockname()[1])


def _poll[T](probe: Callable[[], T | None], *, what: str, timeout: float) -> T:
    deadline = time.monotonic() + timeout
    while True:
        value = probe()
        if value is not None:
            return value
        if time.monotonic() >= deadline:
            raise AssertionError(f"{timeout}s 안에 {what}")
        time.sleep(_POLL_INTERVAL_SECONDS)


@dataclass
class Spawned:
    process: subprocess.Popen[bytes]
    log: Path

    def output(self) -> str:
        return self.log.read_text(encoding="utf-8", errors="replace")

    def assert_alive(self) -> None:
        code = self.process.poll()
        assert code is None, f"프로세스가 죽었다(exit {code}):\n{self.output()}"

    def kill(self) -> None:
        """SIGKILL. 응답 전에 commit하지 않은 구현은 여기서 데이터를 잃는다."""
        if self.process.poll() is None:
            self.process.send_signal(signal.SIGKILL)
        self.process.wait(timeout=SETTLE_TIMEOUT_SECONDS)


def _spawn(argv: list[str], *, env: dict[str, str], log: Path) -> Spawned:
    handle = log.open("wb")
    try:
        process = subprocess.Popen(  # noqa: S603  (인자를 우리가 만든다. 셸을 거치지 않는다)
            argv, cwd=REPO_ROOT, env=env, stdout=handle, stderr=subprocess.STDOUT
        )
    finally:
        handle.close()
    return Spawned(process=process, log=log)


@dataclass
class ApiProcess(Spawned):
    base_url: str


def start_api(runtime: Runtime, *, label: str) -> ApiProcess:
    """`make run`과 같은 uvicorn 진입점. health의 DB가 ok일 때까지 기다린다."""
    port = _free_port()
    spawned = _spawn(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--app-dir",
            str(BACKEND_ROOT),
            "--host",
            HOST,
            "--port",
            str(port),
        ],
        env=runtime.env(application_name=API_APPLICATION_NAME),
        log=runtime.logs / f"api-{label}.log",
    )
    api = ApiProcess(process=spawned.process, log=spawned.log, base_url=f"http://{HOST}:{port}")

    def ready() -> bool | None:
        api.assert_alive()
        try:
            response = httpx2.get(f"{api.base_url}/api/health", timeout=REQUEST_TIMEOUT_SECONDS)
        except httpx2.TransportError:
            return None
        if response.status_code != 200:
            return None
        return True if response.json()["components"]["database"]["status"] == "ok" else None

    try:
        _poll(ready, what=f"API {label}가 뜨지 않았다", timeout=STARTUP_TIMEOUT_SECONDS)
    except BaseException:
        api.kill()
        raise
    return api


def start_worker(runtime: Runtime, *, label: str, heartbeat_after: datetime, db: Engine) -> Spawned:
    """worker loop를 띄우고 **이 프로세스가 쓴** heartbeat가 보일 때까지 기다린다."""
    script = runtime.logs / "worker_probe.py"
    script.write_text(_WORKER_PROBE, encoding="utf-8")
    worker = _spawn(
        [sys.executable, str(script)],
        env=runtime.env(application_name=WORKER_APPLICATION_NAME),
        log=runtime.logs / f"worker-{label}.log",
    )

    def beating() -> datetime | None:
        worker.assert_alive()
        with db.connect() as connection:
            latest = connection.execute(sa.select(sa.func.max(WorkerHeartbeat.last_heartbeat_at)))
            value = latest.scalar_one()
        return value if value is not None and value > heartbeat_after else None

    try:
        _poll(
            beating,
            what=f"worker {label}의 heartbeat가 오지 않았다",
            timeout=STARTUP_TIMEOUT_SECONDS,
        )
    except BaseException:
        worker.kill()
        raise
    return worker


# --------------------------------------------------------------------------
# DB backend 관찰
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Backend:
    pid: int
    application_name: str
    backend_start: datetime


def backends(db: Engine, *names: str) -> list[Backend]:
    """이 DB에 붙어 있는, 이 테스트가 띄운 프로세스의 커넥션."""
    with db.connect() as connection:
        rows = connection.execute(
            sa.text(
                "SELECT pid, application_name, backend_start FROM pg_stat_activity "
                "WHERE datname = current_database() AND application_name = ANY(:names)"
            ),
            {"names": list(names)},
        ).all()
    return [
        Backend(pid=row.pid, application_name=row.application_name, backend_start=row[2])
        for row in rows
    ]


def db_now(db: Engine) -> datetime:
    with db.connect() as connection:
        value = connection.execute(sa.text("SELECT clock_timestamp()")).scalar_one()
    assert isinstance(value, datetime)
    return value


def wait_until_gone(db: Engine, gone: list[Backend]) -> None:
    pids = {backend.pid for backend in gone}

    def cleared() -> bool | None:
        alive = [
            b for b in backends(db, API_APPLICATION_NAME, WORKER_APPLICATION_NAME) if b.pid in pids
        ]
        return True if not alive else None

    _poll(
        cleared, what="죽인 프로세스의 DB backend가 사라지지 않았다", timeout=SETTLE_TIMEOUT_SECONDS
    )


# --------------------------------------------------------------------------
# HTTP (cookie는 손으로 싣는다)
#
# `__Host-` cookie는 `Secure`라서 http base_url의 cookie jar가 저장하지 않는다. 그리고
# 재시작 뒤에 "같은 cookie"를 쓴다는 것을 명시하려면 jar에 맡기지 않는 편이 낫다 ---
# 요청마다 새 client를 만들고 재시작 전에 받은 값을 그대로 헤더에 싣는다.
# --------------------------------------------------------------------------


def call(
    api: ApiProcess,
    method: str,
    path: str,
    *,
    cookie: str | None = None,
    body: dict[str, Any] | None = None,
) -> httpx2.Response:
    headers = {"Origin": ORIGIN}
    if cookie is not None:
        headers["Cookie"] = f"{SESSION_COOKIE_NAME}={cookie}"
    with httpx2.Client(base_url=api.base_url, timeout=REQUEST_TIMEOUT_SECONDS) as client:
        return client.request(method, path, headers=headers, json=body)


def ok(response: httpx2.Response, status: int = 200) -> dict[str, Any]:
    assert response.status_code == status, response.text
    if status == 204:
        return {}
    payload = response.json()
    assert isinstance(payload, dict)
    return payload


def session_cookie(response: httpx2.Response) -> str:
    jar: SimpleCookie = SimpleCookie()
    for header in response.headers.get_list("set-cookie"):
        jar.load(header)
    morsel = jar.get(SESSION_COOKIE_NAME)
    assert morsel is not None and morsel.value, "login이 session cookie를 주지 않았다"
    return morsel.value


# --------------------------------------------------------------------------
# 시나리오
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Learner:
    user_id: int
    login_id: str


@dataclass(frozen=True)
class BeforeRestart:
    cookie: str
    session_id: int
    history_sessions: dict[str, Any]
    history_items: dict[str, Any]
    last_activity: float


def prepare(sessions: sessionmaker[Session]) -> Learner:
    """seed + 사용자 + active prompt 행(worker 기동 조건). **커밋한다.**"""
    with sessions() as db:
        load_seed(db, SEED_DIR, now=datetime.now(UTC))
        for task_type, version in (
            (LlmTaskType.GENERATE_SENTENCE_BATCH, sentence_gen.VERSION),
            (LlmTaskType.GENERATE_REVIEW_CONTEXT, review_context.VERSION),
            (LlmTaskType.EXPLAIN_ITEM, explain_item.VERSION),
        ):
            factories.make_prompt_version(db, task_type=task_type, version=version)
        user = factories.make_user(db)
        user.password_hash = hash_password(PASSWORD)
        db.commit()
        return Learner(user_id=user.id, login_id=user.login_id)


def build_state(
    api: ApiProcess, learner: Learner, sessions: sessionmaker[Session]
) -> BeforeRestart:
    """login -> session -> 문장 -> self-report -> 완료. session은 **열어 둔다.**"""
    login = call(
        api, "POST", "/api/auth/login", body={"login_id": learner.login_id, "password": PASSWORD}
    )
    ok(login)
    cookie = session_cookie(login)
    started = ok(call(api, "POST", "/api/study/session", cookie=cookie))
    assert started["resumed"] is False
    session_id = started["session"]["session_id"]

    presentation = ok(call(api, "POST", f"/api/study/session/{session_id}/next", cookie=cookie))[
        "presentation"
    ]
    assert presentation is not None, "seed에서 Ready Pool이 만들어지지 않았다"
    presentation_id = presentation["presentation_id"]

    # target item에 신호를 준다. 그래야 같은 item에 exposure와 mastery가 함께 남는다.
    with sessions() as db:
        candidate_id = db.execute(
            sa.select(StudyPresentation.candidate_id).where(StudyPresentation.id == presentation_id)
        ).scalar_one()
        targets = set(
            db.execute(
                sa.select(UserSentenceCandidateTarget.learning_item_id).where(
                    UserSentenceCandidateTarget.candidate_id == candidate_id
                )
            ).scalars()
        )
    tappable = [t for t in presentation["tappable_items"] if t["learning_item_id"] in targets]
    assert tappable, f"target item을 누를 수 없다: {presentation['tappable_items']}"

    ok(
        call(
            api,
            "POST",
            f"/api/study/presentations/{presentation_id}/self-report",
            cookie=cookie,
            body={
                "client_event_id": str(uuid.uuid4()),
                "sentence_item_id": tappable[0]["sentence_item_id"],
                "value": ExplicitSignal.UNKNOWN.value,
            },
        ),
        status=204,
    )
    ok(call(api, "POST", f"/api/study/presentations/{presentation_id}/complete", cookie=cookie))
    last_activity = time.monotonic()

    history_sessions = ok(call(api, "GET", "/api/history/sessions", cookie=cookie))
    history_items = ok(call(api, "GET", "/api/history/items", cookie=cookie))
    # 빈 것끼리 같다는 비교는 아무것도 증명하지 않는다.
    assert [s["session_id"] for s in history_sessions["sessions"]] == [session_id]
    assert history_sessions["sessions"][0]["ended_at"] is None
    assert any(
        item["exposure_count"] > 0 and item["comprehension_mastery"] is not None
        for item in history_items["items"]
    ), history_items
    return BeforeRestart(
        cookie=cookie,
        session_id=session_id,
        history_sessions=history_sessions,
        history_items=history_items,
        last_activity=last_activity,
    )


def _rows(
    db: Session, model: type[ItemExposure] | type[UserMastery], user_id: int
) -> list[dict[str, Any]]:
    columns = [column.key for column in model.__table__.columns]
    rows = db.execute(sa.select(model).where(model.user_id == user_id).order_by(model.id)).scalars()
    return [{name: getattr(row, name) for name in columns} for row in rows]


@dataclass(frozen=True)
class LearningRows:
    exposures: list[dict[str, Any]]
    mastery: list[dict[str, Any]]


def learning_rows(sessions: sessionmaker[Session], learner: Learner) -> LearningRows:
    with sessions() as db:
        rows = LearningRows(
            exposures=_rows(db, ItemExposure, learner.user_id),
            mastery=_rows(db, UserMastery, learner.user_id),
        )
    return rows


def assert_state_survived(
    api: ApiProcess,
    before: BeforeRestart,
    rows_before: LearningRows,
    sessions: sessionmaker[Session],
    learner: Learner,
    cfg: AppConfig,
) -> None:
    """재시작 전에 받은 cookie 하나로 전부 확인한다. 순서: 읽기 전용 확인 -> resume."""
    me = ok(call(api, "GET", "/api/auth/me", cookie=before.cookie))
    assert me["user_id"] == learner.user_id

    assert rows_before.exposures, "재시작 전에 exposure가 없다(비교가 비어 있다)"
    assert rows_before.mastery, "재시작 전에 mastery가 없다(비교가 비어 있다)"
    assert learning_rows(sessions, learner) == rows_before

    # history는 조회라서 session을 건드리지 않는다. resume(`touch()`)보다 먼저 본다.
    assert (
        ok(call(api, "GET", "/api/history/sessions", cookie=before.cookie))
        == before.history_sessions
    )
    assert ok(call(api, "GET", "/api/history/items", cookie=before.cookie)) == before.history_items

    open_session = ok(call(api, "GET", "/api/study/session", cookie=before.cookie))["session"]
    assert open_session is not None and open_session["session_id"] == before.session_id

    # 전제: 아직 idle timeout 이내다. 넘었다면 아래 resume 단언은 이 기준을 보지 않는다.
    idle_timeout = cfg.session.study_session_idle_timeout_minutes * 60
    assert time.monotonic() - before.last_activity < idle_timeout

    resumed = ok(call(api, "POST", "/api/study/session", cookie=before.cookie))
    assert resumed["resumed"] is True
    assert resumed["session"]["session_id"] == before.session_id
    assert resumed["timed_out_session_id"] is None


# --------------------------------------------------------------------------
# fixture
# --------------------------------------------------------------------------


def _write_config(path: Path) -> tuple[AppConfig, Path]:
    """테스트가 쥔 config를 두 프로세스에 똑같이 넣는다. 재시작 전후로 정책이 같다."""
    cfg = get_config()
    path.write_text(
        yaml.safe_dump(cfg.model_dump(mode="json"), allow_unicode=True), encoding="utf-8"
    )
    return cfg, path


@contextmanager
def _processes() -> Iterator[list[Spawned]]:
    """테스트가 어디서 실패하든 띄운 프로세스를 전부 죽인다.

    살아남은 프로세스가 커넥션을 쥐고 있으면 `committed_db`의 TRUNCATE가 잠금을 기다린다.
    """
    spawned: list[Spawned] = []
    try:
        yield spawned
    finally:
        for process in spawned:
            process.kill()


# --------------------------------------------------------------------------
# (a) API와 worker 프로세스 재시작
# --------------------------------------------------------------------------


def test_state_survives_restarting_the_api_and_worker_processes(
    committed_db: sessionmaker[Session], db_engine: Engine, database_url: URL, tmp_path: Path
) -> None:
    cfg, config_path = _write_config(tmp_path / "config.yaml")
    runtime = Runtime(database_url=database_url, config_path=config_path, logs=tmp_path)
    learner = prepare(committed_db)

    with _processes() as spawned:
        # ------------------------------------------------------------- A
        worker_a = start_worker(runtime, label="a", heartbeat_after=db_now(db_engine), db=db_engine)
        spawned.append(worker_a)
        api_a = start_api(runtime, label="a")
        spawned.append(api_a)

        before = build_state(api_a, learner, committed_db)
        rows_before = learning_rows(committed_db, learner)

        backends_a = backends(db_engine, API_APPLICATION_NAME, WORKER_APPLICATION_NAME)
        assert {b.application_name for b in backends_a} == {
            API_APPLICATION_NAME,
            WORKER_APPLICATION_NAME,
        }, backends_a

        # ------------------------------------------------------------- restart
        pids_a = {api_a.process.pid, worker_a.process.pid}
        api_a.kill()
        worker_a.kill()
        wait_until_gone(db_engine, backends_a)
        restarted_at = db_now(db_engine)

        # ------------------------------------------------------------- B
        worker_b = start_worker(runtime, label="b", heartbeat_after=restarted_at, db=db_engine)
        spawned.append(worker_b)
        api_b = start_api(runtime, label="b")
        spawned.append(api_b)
        assert {api_b.process.pid, worker_b.process.pid}.isdisjoint(pids_a)
        assert api_a.process.returncode is not None and worker_a.process.returncode is not None

        assert_state_survived(api_b, before, rows_before, committed_db, learner, cfg)

        # B가 본 것은 A가 사라진 뒤에 연 커넥션으로만 읽은 것이다.
        backends_b = backends(db_engine, API_APPLICATION_NAME, WORKER_APPLICATION_NAME)
        assert {b.application_name for b in backends_b} == {
            API_APPLICATION_NAME,
            WORKER_APPLICATION_NAME,
        }, backends_b
        assert all(b.backend_start > restarted_at for b in backends_b), (restarted_at, backends_b)


# --------------------------------------------------------------------------
# (b) Postgres 재시작
# --------------------------------------------------------------------------


@dataclass
class PrivatePostgres:
    """이 테스트만 쓰는 pgserver. 공유 서버(`data/pgtest`)와 data 디렉터리가 다르다."""

    pgdata: Path
    server: Any = None

    def start(self) -> URL:
        # 테스트 전용 의존성. 모듈 최상단으로 올리지 않는다(db_support와 같은 이유).
        import pgserver

        self.server = pgserver.get_server(self.pgdata, cleanup_mode="stop")  # type: ignore[attr-defined]
        return db_support._normalize(self.server.get_uri())

    def postmaster_pid(self) -> int:
        pid = self.server.get_pid()
        assert isinstance(pid, int)
        return pid

    def stop(self) -> None:
        if self.server is not None:
            self.server.cleanup()
            self.server = None


def _postmaster_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


@pytest.fixture
def private_postgres(postgres_admin_dsn: URL, tmp_path: Path) -> Iterator[PrivatePostgres]:
    """`postgres_admin_dsn`을 요구하는 이유: 이 테스트도 "PostgreSQL이 필요한" integration이다.

    공유 서버는 쓰지 않는다. 그 fixture가 기동 실패를 error로 드러내는 곳이라 같은 전제
    (pgserver 바이너리가 이 머신에서 뜬다)를 한 번 확인하고 들어온다. 마커 규칙
    (`test_marker_hygiene.py`)도 이 폐포로 판정한다.
    """
    del postgres_admin_dsn
    instance = PrivatePostgres(pgdata=tmp_path / "pgdata")
    try:
        yield instance
    finally:
        instance.stop()
        shutil.rmtree(instance.pgdata, ignore_errors=True)


def test_state_survives_restarting_postgres_on_the_same_data_directory(
    private_postgres: PrivatePostgres, tmp_path: Path
) -> None:
    cfg, config_path = _write_config(tmp_path / "config.yaml")
    database = "nc_restart"

    admin = private_postgres.start()
    dsn = db_support.recreate_database(admin, database)
    db_support.alembic_upgrade(dsn)

    engine = sa.create_engine(dsn)
    try:
        sessions = sessionmaker(bind=engine, expire_on_commit=False)
        learner = prepare(sessions)
        runtime = Runtime(database_url=dsn, config_path=config_path, logs=tmp_path)
        with _processes() as spawned:
            api_a = start_api(runtime, label="before-pg-restart")
            spawned.append(api_a)
            before = build_state(api_a, learner, sessions)
            api_a.kill()
        rows_before = learning_rows(sessions, learner)
    finally:
        engine.dispose()

    # ----------------------------------------------------------------- stop
    old_postmaster = private_postgres.postmaster_pid()
    private_postgres.stop()
    assert not _postmaster_running(old_postmaster), "Postgres가 멈추지 않았다"
    probe = sa.create_engine(dsn)
    try:
        with pytest.raises(sa.exc.OperationalError), probe.connect():
            pass
    finally:
        probe.dispose()

    # ----------------------------------------------------------------- start (같은 data 디렉터리)
    admin = private_postgres.start()
    assert private_postgres.postmaster_pid() != old_postmaster
    dsn = db_support.database_dsn(admin, database)

    engine = sa.create_engine(dsn)
    try:
        sessions = sessionmaker(bind=engine, expire_on_commit=False)
        runtime = Runtime(database_url=dsn, config_path=config_path, logs=tmp_path)
        with _processes() as spawned:
            api_b = start_api(runtime, label="after-pg-restart")
            spawned.append(api_b)
            assert_state_survived(api_b, before, rows_before, sessions, learner, cfg)
    finally:
        engine.dispose()
