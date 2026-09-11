"""실제 요청 스코프 DB 세션 (12_TEST_PLAN.md Integration: FastAPI ↔ Postgres).

다른 모든 API 테스트는 `get_db`를 override하고, CLI 테스트는 `new_session`을
monkeypatch한다. 그래서 **아무도 진짜 요청 세션을 실행하지 않는다.** 그 맹점에서는
`get_current_user`의 `db.commit()`을 지워도 테스트가 전부 초록이다 --- savepoint
fixture가 미커밋을 가리기 때문이다.

여기서는 override를 하나도 걸지 않는다. 대신:

-   전용 일회용 DB를 만든다. 공유 테스트 DB에 진짜로 commit하면 롤백 격리에
    의존하는 다른 테스트가 실행 순서에 따라 깨진다.
-   검증은 항상 **별도 커넥션**에서 한다. 같은 세션에서 읽으면 flush만 되고
    commit되지 않은 변경도 보인다(autoflush).

Wave 2의 event/mastery 쓰기 경로가 같은 맹점을 물려받으므로, 그 경로가 생기면
이 파일에 같은 형태의 테스트를 추가한다.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

from app.db import get_engine
from app.main import create_app
from app.models.enums import StartingLevel
from app.models.user import AuthSession, User
from app.services.auth import hash_password
from app.settings import get_settings
from tests import db_support

pytestmark = pytest.mark.integration

ORIGIN = "https://app.test"
LOGIN_ID = "request.scope"
PASSWORD = "correct horse battery staple"

# 호출 사이의 시간차보다 훨씬 큰 값이어야 "갱신됐다"와 "원래 그 값이었다"가 구분된다.
STALE_AGE = timedelta(days=1)


@pytest.fixture
def live_database_url(postgres_admin_dsn: URL) -> Iterator[URL]:
    """이 테스트만 쓰는 일회용 DB. 여기서 일어나는 commit은 진짜 commit이다."""
    name = f"nc_request_scope_{uuid.uuid4().hex[:12]}"
    dsn = db_support.recreate_database(postgres_admin_dsn, name)
    db_support.alembic_upgrade(dsn)
    try:
        yield dsn
    finally:
        db_support.drop_database(postgres_admin_dsn, name)


@pytest.fixture
def live_client(live_database_url: URL, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """`get_db` override가 **없는** client. 요청마다 진짜 세션이 열린다."""
    monkeypatch.setenv("DATABASE_URL", live_database_url.render_as_string(hide_password=False))
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", ORIGIN)
    get_settings.cache_clear()
    app = create_app()
    assert app.dependency_overrides == {}, "이 테스트의 목적이 override를 쓰지 않는 것이다"
    try:
        with TestClient(app, base_url="https://testserver") as test_client:
            yield test_client
    finally:
        # 캐시만 비우면 커넥션을 연 채로 엔진이 GC되고, psycopg의 ResourceWarning이
        # filterwarnings=["error"] 때문에 세션 종료 시 에러가 된다.
        engine = get_engine()
        if engine is not None:
            engine.dispose()


@pytest.fixture
def observer(live_database_url: URL) -> Iterator[sa.Engine]:
    """요청이 쓰는 것과 **다른** 커넥션. 커밋된 것만 보인다."""
    engine = sa.create_engine(live_database_url)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def user_id(observer: sa.Engine) -> int:
    with Session(observer) as session:
        account = User(
            login_id=LOGIN_ID,
            password_hash=hash_password(PASSWORD),
            timezone="Asia/Seoul",
            starting_level=StartingLevel.BEGINNER,
            created_at=datetime.now(UTC),
        )
        session.add(account)
        session.commit()
        return account.id


def _login(client: TestClient) -> int:
    response = client.post(
        "/api/auth/login",
        json={"login_id": LOGIN_ID, "password": PASSWORD},
        headers={"Origin": ORIGIN},
    )
    assert response.status_code == 200, response.text
    return response.status_code


def _committed_sessions(observer: sa.Engine) -> list[sa.Row[tuple[int, datetime, datetime | None]]]:
    with observer.connect() as connection:
        return list(
            connection.execute(
                sa.select(AuthSession.id, AuthSession.last_used_at, AuthSession.revoked_at)
            )
        )


def test_login_commits_the_session_row_in_the_request_scope(
    live_client: TestClient, observer: sa.Engine, user_id: int
) -> None:
    """cookie를 내주기 전에 세션이 실제로 저장돼 있어야 한다.

    commit이 없으면 브라우저는 cookie를 받았는데 서버에는 세션이 없는 상태가 된다
    --- 로그인은 성공처럼 보이고 다음 요청이 401이다.
    """
    assert _committed_sessions(observer) == []

    _login(live_client)

    assert len(_committed_sessions(observer)) == 1


def test_a_request_commits_last_used_at(
    live_client: TestClient, observer: sa.Engine, user_id: int
) -> None:
    """`get_current_user`의 `db.commit()`이 없으면 여기서 빨개진다(M11).

    override된 세션에서는 savepoint와 autoflush가 미커밋을 가려서 이 차이가
    보이지 않는다. 별도 커넥션에서만 드러난다.
    """
    _login(live_client)
    stale = datetime.now(UTC) - STALE_AGE
    with observer.begin() as connection:
        connection.execute(sa.update(AuthSession).values(last_used_at=stale))

    assert live_client.get("/api/auth/me").status_code == 200

    rows = _committed_sessions(observer)
    assert len(rows) == 1
    assert rows[0].last_used_at > stale, "last_used_at 갱신이 커밋되지 않았다"


def test_logout_commits_the_revocation(
    live_client: TestClient, observer: sa.Engine, user_id: int
) -> None:
    _login(live_client)

    assert live_client.post("/api/auth/logout", headers={"Origin": ORIGIN}).status_code == 204

    rows = _committed_sessions(observer)
    assert len(rows) == 1
    assert rows[0].revoked_at is not None


def test_a_rejected_request_leaves_nothing_behind(
    live_client: TestClient, observer: sa.Engine, user_id: int
) -> None:
    """인증 실패가 세션 row를 만들지 않는다. 실패 경로에도 실제 세션이 열린다."""
    response = live_client.post(
        "/api/auth/login",
        json={"login_id": LOGIN_ID, "password": "wrong"},
        headers={"Origin": ORIGIN},
    )

    assert response.status_code == 401
    assert _committed_sessions(observer) == []


def test_each_request_gets_its_own_session_and_returns_the_connection(
    live_client: TestClient, observer: sa.Engine, user_id: int
) -> None:
    """요청 세션이 닫히지 않으면 pool이 고갈되어 나중 요청이 멈춘다.

    기본 pool_size(5) + max_overflow(10)보다 많이 보낸다. 커넥션을 돌려주지 않으면
    여기서 timeout으로 드러난다.
    """
    _login(live_client)

    for _ in range(20):
        assert live_client.get("/api/auth/me").status_code == 200
