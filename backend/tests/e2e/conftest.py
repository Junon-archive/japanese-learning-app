"""브라우저 E2E 하네스 (12_TEST_PLAN.md의 `Core E2E Scenario` / `Demo E2E`).

## 왜 앱을 테스트 프로세스 안에서 띄우는가

Core E2E 13단계 중 9번이 **due 시점으로 시계를 옮기는 것**이다. 서버가 별도
프로세스면 그 시계를 옮길 방법이 없고, `/test/clock` 같은 훅을 앱에 붙이는 것은
불가능하다 --- `app/api/router.py`의 `assert_fail_closed()`가 익명 허용 목록 밖의
무인증 라우트를 발견하면 **부팅을 실패시킨다**. 테스트 전용 무인증 HTTP 표면을
만드는 대신, 앱을 이 프로세스의 데몬 스레드에 띄우고
`dependency_overrides[get_now]`로 시계를 직접 쥔다.

그 결과가 이 하네스의 존재 이유다: HTTP 표면은 운영과 **완전히 같은데**
(`get_now` / `get_config` 말고는 override가 없다) 테스트가 시계를 옮길 수 있고,
같은 프로세스라 **DB를 직접 단언할 수 있다.** "화면은 맞는데 `item_exposures`가
2건" 같은 결함은 DOM만 보는 E2E로는 잡히지 않는다.

## 구성

-   frontend: `npm run build`로 매 세션 새로 빌드해 `ThreadingHTTPServer`로 서빙.
-   backend: `create_app()` + uvicorn 데몬 스레드. DB는 부모 conftest의 pgserver.
-   브라우저: 시스템 Chrome(`channel="chrome"`). 바이너리를 내려받지 않는다.

## 지키는 규칙

-   host는 **`localhost` 하나로 고정한다.** `127.0.0.1`과 섞으면 쿠키가 조용히
    실리지 않아 401만 남는다. `crypto.randomUUID`도 secure context(=localhost)에서만
    존재한다.
-   `CORS_ALLOW_ORIGINS`에 frontend origin이 반드시 들어간다. 빠지면
    `require_trusted_origin`이 상태 변경 요청을 403으로 막는다.
-   Chrome이나 node가 없을 때 `NC_E2E_REQUIRED=1`이면 **skip이 아니라 실패**다.
    skip이 초록으로 위장하는 것을 막는다(`make test-e2e`가 이 변수를 세운다).
"""

from __future__ import annotations

import http.server
import os
import shutil
import socket
import subprocess
import threading
import time
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import NoReturn

import pytest
import uvicorn
from fastapi import FastAPI
from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright
from playwright.sync_api import Error as PlaywrightError
from sqlalchemy.engine import URL, Engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.deps import get_now
from app.config import AppConfig, get_config
from app.db import get_engine
from app.main import create_app
from tests.clock import MutableClock
from tests.conftest import REPO_ROOT, _clear_caches, truncate_all_tables

FRONTEND_DIR = REPO_ROOT / "frontend"
FRONTEND_DIST = FRONTEND_DIR / "dist"

# make 타깃이 세운다. 세워져 있으면 "환경이 없어서 못 돌았다"는 skip을 허용하지 않는다.
E2E_REQUIRED_ENV = "NC_E2E_REQUIRED"

# 127.0.0.1과 섞지 않는다. 위 모듈 docstring의 `지키는 규칙` 참고.
HOST = "localhost"

_SERVER_START_TIMEOUT_SECONDS = 30.0
_BUILD_TIMEOUT_SECONDS = 300.0


def _unavailable(reason: str) -> NoReturn:
    """실행 환경이 없다. `NC_E2E_REQUIRED=1`이면 실패, 아니면 skip.

    빌드 **실패**는 여기로 오지 않는다. 그것은 환경 부재가 아니라 결함이므로
    항상 실패다.
    """
    if os.environ.get(E2E_REQUIRED_ENV) == "1":
        raise RuntimeError(f"{reason} ({E2E_REQUIRED_ENV}=1이므로 skip하지 않는다)")
    pytest.skip(f"{reason} — {E2E_REQUIRED_ENV}=1로 돌리면 실패로 드러난다")


def _free_port() -> int:
    """빈 포트 하나를 잡아 번호만 돌려준다.

    잡았다 놓는 사이에 다른 프로세스가 가져갈 수 있다. 고정 포트를 쓰면 같은
    머신의 다른 pytest 실행과 **항상** 충돌하므로 이쪽이 낫다.
    """
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as probe:
        probe.bind((HOST, 0))
        return int(probe.getsockname()[1])


@contextmanager
def _environment(**values: str) -> Iterator[None]:
    """세션 동안 유지할 환경변수. monkeypatch(함수 스코프)로는 세션 fixture를 못 덮는다."""
    previous = {name: os.environ.get(name) for name in values}
    os.environ.update(values)
    _clear_caches()
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        _clear_caches()


# --------------------------------------------------------------------------
# frontend
# --------------------------------------------------------------------------


def _build_frontend(api_base_url: str) -> Path:
    """매 세션 새로 빌드한다. 옛 `dist`를 검증하고 초록이 되는 것을 막는다.

    빌드 실패는 곧 테스트 실패다(skip이 아니다). `npm ci`는 여기서 하지 않는다 ---
    의존성 설치는 `make test-e2e`의 몫이고, 여기서는 포트가 정해진 뒤에야 알 수 있는
    `VITE_API_BASE_URL`을 넣어 빌드하는 것만 한다.
    """
    npm = shutil.which("npm")
    if npm is None:
        _unavailable("npm이 PATH에 없다")
    if not (FRONTEND_DIR / "node_modules").is_dir():
        _unavailable("frontend/node_modules가 없다 (`cd frontend && npm ci`)")

    if FRONTEND_DIST.exists():
        shutil.rmtree(FRONTEND_DIST)

    completed = subprocess.run(  # noqa: S603  (인자를 우리가 만든다. 셸을 거치지 않는다)
        [npm, "run", "build"],
        cwd=FRONTEND_DIR,
        env={**os.environ, "VITE_API_BASE_URL": api_base_url},
        capture_output=True,
        text=True,
        timeout=_BUILD_TIMEOUT_SECONDS,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "frontend 빌드가 실패했다 (E2E는 이 산출물을 검증한다)\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    if not (FRONTEND_DIST / "index.html").is_file():
        raise RuntimeError(f"빌드는 성공했는데 {FRONTEND_DIST}/index.html이 없다")
    return FRONTEND_DIST


class _DistHandler(http.server.SimpleHTTPRequestHandler):
    """`frontend/dist`를 서빙한다. 로그는 버린다(테스트 출력에 섞이면 시끄럽다)."""

    # `.webmanifest`가 빠지면 브라우저가 manifest를 무시하고 installability 판정이
    # **조용히** 실패한다. mimetypes의 시스템 테이블에 기대지 않고 여기서 못박는다.
    # RUF012는 ClassVar 선언을 요구하지만 typeshed가 이 속성을 instance variable로
    # 선언해 두었기 때문에 ClassVar로 좁히면 mypy가 override를 거부한다. stdlib
    # 자신이 class 속성으로 두는 값이므로 여기서도 class 속성이 맞다.
    extensions_map = {  # noqa: RUF012
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".webmanifest": "application/manifest+json",
        ".js": "text/javascript",
        ".mjs": "text/javascript",
        ".json": "application/json",
    }

    def log_message(self, format: str, *args: object) -> None:
        del format, args


@contextmanager
def _serve_dist(dist: Path, port: int) -> Iterator[str]:
    handler = partial(_DistHandler, directory=str(dist))
    server = http.server.ThreadingHTTPServer((HOST, port), handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, name="e2e-frontend", daemon=True)
    thread.start()
    try:
        yield f"http://{HOST}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


# --------------------------------------------------------------------------
# backend (in-process uvicorn)
# --------------------------------------------------------------------------


@contextmanager
def _serve_app(app: FastAPI, port: int) -> Iterator[str]:
    """uvicorn을 데몬 스레드로 띄운다. 앱 객체는 테스트가 그대로 들고 있다."""
    config = uvicorn.Config(app, host=HOST, port=port, log_level="warning", access_log=False)
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="e2e-backend", daemon=True)
    thread.start()

    waited = 0.0
    while not server.started:
        if not thread.is_alive():
            raise RuntimeError("uvicorn 스레드가 기동 중에 죽었다")
        if waited >= _SERVER_START_TIMEOUT_SECONDS:
            raise RuntimeError(f"uvicorn이 {_SERVER_START_TIMEOUT_SECONDS}s 안에 뜨지 않았다")
        time.sleep(0.05)
        waited += 0.05
    try:
        yield f"http://{HOST}:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


# --------------------------------------------------------------------------
# 하네스
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class E2EStack:
    """E2E 테스트가 잡는 손잡이 전부.

    `clock`은 그 테스트의 `study_clock`과 **같은 객체**다. `advance()` 한 번이면
    다음 HTTP 요청이 새 시각을 본다 --- 브라우저가 보낸 요청이든 아니든.
    """

    frontend_url: str
    api_url: str
    clock: MutableClock
    sessions: sessionmaker[Session]
    app: FastAPI

    def use_config(self, cfg: AppConfig) -> None:
        """이 앱이 보는 정책값을 바꾼다 (`tests.conftest.override_config`와 함께 쓴다).

        13_ACCEPTANCE_CRITERIA.md의 `수치 취급 원칙`: E2E는 "엔진이 configured 값을
        따르는가"를 본다. 기본값에 기대면 config를 읽지 않는 구현도 통과한다.
        """
        self.app.dependency_overrides[get_config] = lambda: cfg


@dataclass(frozen=True)
class Frontend:
    """빌드된 frontend와 그것을 서빙하는 정적 서버. **backend와 무관하다.**

    `api_url`은 번들에 박힌 `VITE_API_BASE_URL`이다. 이 fixture만 요구한 테스트에서는
    그 포트에 **아무도 listen하지 않는다** --- Public Demo가 정말로 static fixture인지
    (`#/demo`가 `fetchMe()`보다 먼저 갈리는지) 보려면 그 구성이 필요하다.
    """

    url: str
    api_url: str
    dist: Path


@pytest.fixture(scope="session")
def frontend(request: pytest.FixtureRequest) -> Iterator[Frontend]:
    """세션당 한 번 빌드하고 한 번 서빙한다.

    빌드가 세션당 1회인 이유: `frontend/dist` 하나를 공유하므로 두 번 빌드하면 먼저
    띄운 정적 서버의 발밑에서 파일이 사라진다. backend를 띄우는 것은 별도 fixture
    (`_e2e_stack_session`)이고 이 fixture는 그것을 요구하지 않는다.
    """
    del request
    api_port = _free_port()
    front_port = _free_port()
    dist = _build_frontend(f"http://{HOST}:{api_port}")
    with _serve_dist(dist, front_port) as frontend_url:
        yield Frontend(url=frontend_url, api_url=f"http://{HOST}:{api_port}", dist=dist)


@dataclass(frozen=True)
class _RunningStack:
    """세션 내내 살아 있는 부분. 시계만 테스트마다 갈아 끼운다."""

    frontend_url: str
    api_url: str
    app: FastAPI
    clock_slot: list[MutableClock]


@pytest.fixture(scope="session")
def _e2e_stack_session(frontend: Frontend, database_url: URL) -> Iterator[_RunningStack]:
    api_port = int(frontend.api_url.rsplit(":", 1)[1])

    # CORS_ALLOW_ORIGINS가 빠지면 require_trusted_origin이 POST를 전부 403으로 막는다.
    with _environment(
        DATABASE_URL=database_url.render_as_string(hide_password=False),
        CORS_ALLOW_ORIGINS=frontend.url,
    ):
        app = create_app()
        # 슬롯 하나를 두고 테스트마다 그 안의 시계를 바꾼다. app은 세션 스코프인데
        # `study_clock`은 함수 스코프이므로 override를 매번 다시 걸 수는 없다
        # (요청 스레드가 도중에 override 딕셔너리를 읽는다).
        clock_slot = [MutableClock()]
        app.dependency_overrides[get_now] = lambda: clock_slot[0].now()

        with _serve_app(app, api_port) as api_url:
            yield _RunningStack(
                frontend_url=frontend.url,
                api_url=api_url,
                app=app,
                clock_slot=clock_slot,
            )
        app.dependency_overrides.clear()


@pytest.fixture
def e2e_stack(
    _e2e_stack_session: _RunningStack,
    db_engine: Engine,
    study_clock: MutableClock,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[E2EStack]:
    """테스트 하나가 쓰는 하네스. 시계는 이 테스트의 `study_clock`이다.

    autouse `clean_env`가 테스트마다 환경변수를 지우므로 여기서 다시 세운다 ---
    `require_trusted_origin`과 `get_engine()`은 **요청 시점에** 그 값을 읽으므로
    비어 있으면 403/DB 미연결로 조용히 어긋난다.
    """
    frontend_origin = _e2e_stack_session.frontend_url
    monkeypatch.setenv("DATABASE_URL", str(db_engine.url.render_as_string(hide_password=False)))
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", frontend_origin)
    _clear_caches()

    _e2e_stack_session.clock_slot[0] = study_clock
    _e2e_stack_session.app.dependency_overrides.pop(get_config, None)

    try:
        yield E2EStack(
            frontend_url=_e2e_stack_session.frontend_url,
            api_url=_e2e_stack_session.api_url,
            clock=study_clock,
            sessions=sessionmaker(bind=db_engine, expire_on_commit=False),
            app=_e2e_stack_session.app,
        )
    finally:
        _e2e_stack_session.app.dependency_overrides.pop(get_config, None)
        # 요청 경로가 진짜로 commit한다(`db_session`의 롤백 격리가 없다). 다음
        # 테스트가 남은 행 위에서 오염되지 않도록 지운다.
        truncate_all_tables(db_engine)
        # 캐시만 비우면 엔진이 커넥션을 연 채 GC되고 psycopg의 ResourceWarning이
        # filterwarnings=["error"] 때문에 에러가 된다(부모 conftest의 db_client와 같다).
        engine = get_engine()
        if engine is not None:
            engine.dispose()


# --------------------------------------------------------------------------
# 브라우저
#
# 시스템 Chrome을 채널로 쓴다(`/opt/google/chrome/chrome`). Playwright 번들
# 브라우저를 내려받지 않고, WebKit은 host dependency가 없어 쓸 수 없다.
# --------------------------------------------------------------------------


@pytest.fixture(scope="session")
def playwright_driver() -> Iterator[Playwright]:
    with sync_playwright() as driver:
        yield driver


@pytest.fixture(scope="session")
def browser(playwright_driver: Playwright) -> Iterator[Browser]:
    """일반 브라우저. context는 테스트마다 새로 만든다(쿠키/스토리지 격리)."""
    try:
        launched = playwright_driver.chromium.launch(channel="chrome")
    except PlaywrightError as exc:
        _unavailable(f"Chrome을 띄울 수 없다: {exc.message.splitlines()[0]}")
    try:
        yield launched
    finally:
        launched.close()


@pytest.fixture
def page(browser: Browser) -> Iterator[Page]:
    context = browser.new_context()
    try:
        yield context.new_page()
    finally:
        context.close()


@pytest.fixture
def installable_context(playwright_driver: Playwright, tmp_path: Path) -> Iterator[BrowserContext]:
    """PWA installability 판정용 persistent context.

    기본 context는 incognito라 Chrome이 installability를 `in-incognito`로만
    보고한다. 그 판정을 보려면 사용자 데이터 디렉터리가 실재해야 한다.
    """
    user_data_dir = tmp_path / "chrome-profile"
    user_data_dir.mkdir()
    try:
        context = playwright_driver.chromium.launch_persistent_context(
            str(user_data_dir), channel="chrome"
        )
    except PlaywrightError as exc:
        _unavailable(f"Chrome persistent context를 띄울 수 없다: {exc.message.splitlines()[0]}")
    try:
        yield context
    finally:
        context.close()
