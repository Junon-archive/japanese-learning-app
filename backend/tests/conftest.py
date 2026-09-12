from __future__ import annotations

import socket
import sys
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.engine import URL, Engine
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_now
from app.config import AppConfig, get_config
from app.db import _build_engine, get_engine
from app.main import create_app
from app.models.user import User
from app.services.auth import hash_password
from app.settings import get_settings
from tests import db_support, factories
from tests.clock import MutableClock

# `app.settings.Settings`의 모든 필드가 여기에 있어야 한다. 하나라도 빠지면 셸에
# 그 변수가 있을 때 테스트로 샌다. test_env_isolation.py가 어긋남을 감시한다.
_ENV_VARS = (
    "APP_ENV",
    "DATABASE_URL",
    "CORS_ALLOW_ORIGINS",
    "NC_CONFIG_PATH",
    "AUTH_SESSION_TTL_DAYS",
)

REPO_ROOT = Path(__file__).resolve().parents[2]


# 수집된 테스트 전부. `-m` 필터가 걸리기 **전에** 가로채므로 deselect될 것까지 들어온다.
# `test_marker_hygiene.py`가 "DB fixture를 쓰는데 integration 마크가 없는" 테스트를
# 여기서 찾는다. 마크를 자동으로 붙이지 않는 이유: 자동으로 붙이면 누락이 영영
# 드러나지 않고, `make test-unit`의 의미가 조용히 바뀐다.
COLLECTED_ITEMS: list[pytest.Item] = []


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    COLLECTED_ITEMS[:] = items


def _clear_caches() -> None:
    get_settings.cache_clear()
    get_config.cache_clear()
    _build_engine.cache_clear()


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """설정은 환경변수로만 주입한다. 주변 환경이 테스트에 새지 않게 한다."""
    for name in _ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    _clear_caches()
    yield
    _clear_caches()


@pytest.fixture
def study_clock() -> MutableClock:
    """이 테스트가 보는 시각 (ADR-007).

    `client` / `db_client`가 `app.dependency_overrides[get_now]`로 이 시계를 앱에
    꽂는다. 같은 테스트가 `study_clock`을 함께 요청하면 **같은 인스턴스**이므로
    `advance()` 한 번으로 다음 요청의 시각이 움직인다. freezegun을 쓰지 않는다.
    """
    return MutableClock()


@pytest.fixture
def client(study_clock: MutableClock) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_now] = study_clock.now
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


# --------------------------------------------------------------------------
# PostgreSQL (ADR-002)
#
# pgserver는 pytest 세션당 1회, 고정 data 디렉터리(data/pgtest)에서 기동한다.
# 스키마는 세션당 1회 `alembic upgrade head`로만 만든다 --- create_all()을 쓰면
# migration과 모델이 어긋나도 테스트가 통과해버려 "빈 DB에서 migration" 경로가
# 아무에게도 검증되지 않는다.
# --------------------------------------------------------------------------


@pytest.fixture(scope="session")
def postgres_admin_dsn() -> URL:
    """maintenance DB DSN. 기동 실패는 skip이 아니라 error로 드러난다."""
    return db_support.start_postgres()


@pytest.fixture(scope="session")
def database_url(postgres_admin_dsn: URL) -> Iterator[URL]:
    """빈 DB를 만들고 migration을 올린다. 세션당 1회."""
    name = db_support.session_database_name()
    dsn = db_support.recreate_database(postgres_admin_dsn, name)
    db_support.alembic_upgrade(dsn)
    yield dsn
    # 실행마다 DB가 하나씩 쌓이지 않게 치운다. data 디렉터리는 남긴다(다음 세션의 initdb 회피).
    db_support.drop_database(postgres_admin_dsn, name)


@pytest.fixture(scope="session")
def db_engine(database_url: URL) -> Iterator[Engine]:
    engine = sa.create_engine(database_url)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def db_session(db_engine: Engine) -> Iterator[Session]:
    """테스트마다 바깥 트랜잭션을 열고 끝에서 롤백한다.

    TRUNCATE(테이블 목록을 손으로 유지해야 하고 느리다)나 DB 재생성(수백 ms)
    대신 이 방식을 쓴다. SQLAlchemy 2.0의 `join_transaction_mode="create_savepoint"`
    덕분에 서비스 코드가 `session.commit()`을 호출해도 SAVEPOINT release로 바뀌므로
    **애플리케이션 코드를 테스트용으로 왜곡하지 않아도 된다.**

    한계: 모든 작업이 커넥션 하나 안에서 일어나므로 다중 커넥션 동시성
    (Wave 3 worker claim의 `FOR UPDATE SKIP LOCKED`)은 이 fixture로 검증할 수 없다.
    그때 별도 fixture를 추가한다. 지금은 만들지 않는다.

    주의: 롤백은 시퀀스를 되돌리지 않는다. 테스트가 `id == 1`을 가정하면
    실행 순서에 따라 깨진다. 항상 flush 후 객체의 id를 읽어라.
    """
    connection = db_engine.connect()
    outer = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        outer.rollback()
        connection.close()


@pytest.fixture
def db_client(
    db_session: Session,
    database_url: URL,
    monkeypatch: pytest.MonkeyPatch,
    study_clock: MutableClock,
) -> Iterator[TestClient]:
    """요청 핸들러가 테스트와 같은 트랜잭션을 보게 만든다.

    DATABASE_URL도 함께 주입한다. `get_db`를 거치지 않는 경로(health check의
    `get_engine()`)가 실제 DB를 보아야 하기 때문이다.

    `Secure` 쿠키가 필요한 테스트에는 쓸 수 없다. base_url이 `http://testserver`라
    httpx 쿠키 jar가 Secure 쿠키를 저장하지 않는다 --- 로그인은 200인데 이후 요청이
    401이 되는 형태로 조용히 실패한다. auth 테스트는 `https://` base_url을 쓰는
    자체 client fixture를 둔다(test_auth_api.py).
    """
    monkeypatch.setenv("DATABASE_URL", database_url.render_as_string(hide_password=False))
    _clear_caches()
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_now] = study_clock.now
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        # 캐시만 비우면(_clear_caches) 엔진이 커넥션을 연 채로 GC되고, psycopg의
        # ResourceWarning이 filterwarnings=["error"] 때문에 세션 종료 시 에러가 된다.
        engine = get_engine()
        if engine is not None:
            engine.dispose()


# --------------------------------------------------------------------------
# 정책 주입 (13_ACCEPTANCE_CRITERIA.md의 `수치 취급 원칙`)
#
# 시나리오/E2E는 "엔진이 configured 값을 따르는가"를 본다. 기본값에 기대어
# 숫자를 단정하면 config를 아예 읽지 않는 구현도 통과한다.
# --------------------------------------------------------------------------


def override_config(cfg: AppConfig, **sections: Mapping[str, Any]) -> AppConfig:
    """섹션 단위로 정책값을 갈아 끼운 새 `AppConfig`.

    `model_copy`가 아니라 `model_validate`로 다시 만든다 --- copy는 검증기를 건너뛰어
    비율 합 같은 규칙을 우회한 config가 테스트에만 존재하게 된다.
    """
    data = cfg.model_dump()
    for name, values in sections.items():
        section = data[name]
        if not isinstance(section, dict):  # pragma: no cover - 섹션 이름 오타
            raise KeyError(f"{name} is not a config section")
        data[name] = {**section, **values}
    return AppConfig.model_validate(data)


# --------------------------------------------------------------------------
# provider 호출 감시 (불변식 #1)
#
# import 정적 검사(`test_module_boundaries.py`의 G4)와 방향이 다르다. 이쪽은
# "지금 이 요청이 실제로 무엇을 했는가"를 본다.
# --------------------------------------------------------------------------

PROVIDER_MODULES = ("openai", "anthropic")


@contextmanager
def no_outbound_network() -> Iterator[None]:
    """이 블록 안에서 바깥으로 소켓을 열면 실패한다.

    DB 커넥션은 `db_session`이 이미 열어 둔 것을 재사용하므로 request 경로에 새
    소켓이 필요할 이유가 없다. provider를 동기 호출하는 구현은 여기에 걸린다.
    """

    def _refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("request 경로가 바깥으로 연결을 열었다")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(socket.socket, "connect", _refuse)
        patch.setattr(socket, "create_connection", _refuse)
        yield


def assert_no_provider_import() -> None:
    """provider SDK가 요청 처리 중에 끌려 들어오지 않았는지 본다."""
    loaded = [name for name in PROVIDER_MODULES if name in sys.modules]
    assert loaded == [], f"provider SDK가 import됐다: {loaded}"


# --------------------------------------------------------------------------
# 인증된 HTTP client
#
# `db_client`는 base_url이 http라서 `Secure` 쿠키가 httpx jar에 저장되지 않는다 ---
# 로그인은 200인데 이후 요청이 401이 되는 형태로 조용히 실패한다(그 fixture의
# docstring). 시나리오/E2E는 HTTP 계약까지 함께 밟아야 하므로 https client를 둔다.
# --------------------------------------------------------------------------

STUDY_ORIGIN = "https://app.test"
STUDY_PASSWORD = "correct horse battery staple"


@dataclass(frozen=True)
class StudyApi:
    """로그인된 client + 그 app + 이 테스트의 시계."""

    client: TestClient
    app: FastAPI
    clock: MutableClock
    user: User

    def use_config(self, cfg: AppConfig) -> None:
        """이 app이 보는 정책값을 바꾼다. 요청 경로는 `Depends(get_config)`로만 읽는다."""
        self.app.dependency_overrides[get_config] = lambda: cfg


@pytest.fixture
def study_api(
    db_session: Session, monkeypatch: pytest.MonkeyPatch, study_clock: MutableClock
) -> Iterator[StudyApi]:
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", STUDY_ORIGIN)
    _clear_caches()
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_now] = study_clock.now

    user = factories.make_user(db_session)
    user.password_hash = hash_password(STUDY_PASSWORD)
    db_session.flush()

    try:
        with TestClient(
            app, base_url="https://testserver", headers={"Origin": STUDY_ORIGIN}
        ) as client:
            response = client.post(
                "/api/auth/login",
                json={"login_id": user.login_id, "password": STUDY_PASSWORD},
            )
            assert response.status_code == 200, response.text
            yield StudyApi(client=client, app=app, clock=study_clock, user=user)
    finally:
        app.dependency_overrides.clear()
