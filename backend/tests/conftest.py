from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.engine import URL, Engine
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.config import get_config
from app.db import _build_engine, get_engine
from app.main import create_app
from app.settings import get_settings
from tests import db_support

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
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as test_client:
        yield test_client


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
    db_session: Session, database_url: URL, monkeypatch: pytest.MonkeyPatch
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


# auth fixture(로그인한 사용자, 인증된 client)는 auth 구현이 끝난 뒤
# 이 자리에 추가한다. 지금 추측으로 만들지 않는다.
