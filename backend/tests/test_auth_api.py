"""auth endpoint 통합 테스트 (05_API_SPEC.md, ADR-004).

`conftest.py`의 `db_client`를 쓰지 않는다. base_url이 http라서 `Secure` cookie가
httpx cookie jar에 저장되지 않고, 그러면 login은 200인데 이어지는 /me가 401이 되는
형태로 조용히 실패한다.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import httpx2
import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.main import create_app
from app.models.user import AuthSession, User
from app.services.auth import (
    SESSION_COOKIE_NAME,
    create_session,
    hash_password,
    hash_token,
)
from app.settings import Settings, get_settings
from tests import factories

# 이 모듈의 모든 테스트는 `db_session`을 통해 PostgreSQL을 쓴다. 마크가 없으면
# `make test-unit`이 DB 없는 환경에서 23건 error로 끝난다.
pytestmark = pytest.mark.integration

ORIGIN = "https://app.test"
OTHER_ORIGIN = "https://evil.test"
PASSWORD = "correct horse battery staple"

# `Settings`의 기본값과 **다른** 값을 주입한다. 같으면 "설정을 읽는가"와 "기본값을
# 하드코딩했는가"를 구분할 수 없다(test_the_injected_ttl_is_not_the_default).
TTL_DAYS = 7

SECONDS_PER_DAY = 24 * 60 * 60


@contextmanager
def _configured_client(
    db_session: Session, monkeypatch: pytest.MonkeyPatch, ttl_days: int
) -> Iterator[TestClient]:
    """https base_url이어야 `Secure` cookie가 저장된다."""
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", ORIGIN)
    monkeypatch.setenv("AUTH_SESSION_TTL_DAYS", str(ttl_days))
    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        with TestClient(app, base_url="https://testserver") as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


@pytest.fixture
def auth_client(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    with _configured_client(db_session, monkeypatch, TTL_DAYS) as test_client:
        yield test_client


@pytest.fixture
def user(db_session: Session) -> User:
    account = factories.make_user(db_session, login_id="junon")
    account.password_hash = hash_password(PASSWORD)
    db_session.flush()
    return account


def _login(
    client: TestClient, login_id: str = "junon", password: str = PASSWORD
) -> httpx2.Response:
    return client.post(
        "/api/auth/login",
        json={"login_id": login_id, "password": password},
        headers={"Origin": ORIGIN},
    )


def test_login_returns_the_user_and_sets_the_session_cookie(
    auth_client: TestClient, user: User
) -> None:
    response = _login(auth_client)

    assert response.status_code == 200
    assert response.json() == {
        "user_id": user.id,
        "login_id": "junon",
        "timezone": user.timezone,
        "starting_level": "beginner",
    }
    assert isinstance(response.json()["user_id"], int)  # ADR-005


def test_login_response_never_leaks_secrets(auth_client: TestClient, user: User) -> None:
    body = _login(auth_client).json()

    assert "password" not in str(body).lower()
    assert "hash" not in str(body).lower()


def test_session_cookie_attributes_follow_adr_004(auth_client: TestClient, user: User) -> None:
    # 주입한 TTL이 `Settings` 기본값과 같으면 아래 Max-Age 단언이 "설정을 읽는가"와
    # "기본값을 하드코딩했는가"를 구분하지 못한다. 기본값을 바꾸는 변경이 여기서
    # 걸리고, 그때 TTL_DAYS를 다시 다른 값으로 옮기게 된다.
    assert Settings.model_fields["auth_session_ttl_days"].default != TTL_DAYS

    set_cookie = _login(auth_client).headers["set-cookie"]

    assert set_cookie.startswith(f"{SESSION_COOKIE_NAME}=")
    assert "; HttpOnly" in set_cookie
    assert "; Secure" in set_cookie
    assert "; SameSite=strict" in set_cookie
    assert "; Path=/" in set_cookie
    assert "Domain=" not in set_cookie
    assert f"; Max-Age={TTL_DAYS * SECONDS_PER_DAY}" in set_cookie


def test_only_the_token_hash_is_stored(
    auth_client: TestClient, user: User, db_session: Session
) -> None:
    token = _login(auth_client).cookies[SESSION_COOKIE_NAME]

    stored = db_session.scalars(sa.select(AuthSession.token_hash)).all()
    assert stored == [hash_token(token)]
    assert token not in stored


def test_login_normalizes_the_login_id(auth_client: TestClient, user: User) -> None:
    assert _login(auth_client, login_id="  JuNon  ").status_code == 200


def test_login_with_a_wrong_password_is_401_without_a_cookie(
    auth_client: TestClient, user: User
) -> None:
    response = _login(auth_client, password="wrong")

    assert response.status_code == 401
    assert "set-cookie" not in response.headers


def test_login_failures_are_indistinguishable(
    auth_client: TestClient, user: User, db_session: Session
) -> None:
    wrong_password = _login(auth_client, password="wrong")
    unknown_user = _login(auth_client, login_id="nobody")

    user.is_active = False
    db_session.flush()
    inactive = _login(auth_client)

    assert wrong_password.status_code == unknown_user.status_code == inactive.status_code == 401
    assert wrong_password.json() == unknown_user.json() == inactive.json()


def test_me_returns_the_logged_in_user(auth_client: TestClient, user: User) -> None:
    _login(auth_client)

    response = auth_client.get("/api/auth/me")

    assert response.status_code == 200
    assert response.json()["login_id"] == "junon"


def test_me_without_a_cookie_is_401(auth_client: TestClient, user: User) -> None:
    response = auth_client.get("/api/auth/me")

    assert response.status_code == 401
    # 브라우저 기본 인증 팝업을 띄우지 않는다.
    assert "www-authenticate" not in response.headers


def test_me_with_an_unknown_token_is_401(auth_client: TestClient, user: User) -> None:
    response = auth_client.get(
        "/api/auth/me", headers={"Cookie": f"{SESSION_COOKIE_NAME}=not-a-real-token"}
    )

    assert response.status_code == 401


def test_me_with_an_expired_session_is_401(
    auth_client: TestClient, user: User, db_session: Session
) -> None:
    _login(auth_client)
    db_session.execute(
        sa.update(AuthSession).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    db_session.flush()

    assert auth_client.get("/api/auth/me").status_code == 401


def test_me_with_an_inactive_user_is_401(
    auth_client: TestClient, user: User, db_session: Session
) -> None:
    _login(auth_client)
    user.is_active = False
    db_session.flush()

    assert auth_client.get("/api/auth/me").status_code == 401


def test_request_touches_last_used_at_without_extending_expiry(
    auth_client: TestClient, user: User, db_session: Session
) -> None:
    _login(auth_client)
    session_row = db_session.scalars(sa.select(AuthSession)).one()
    created_expiry = session_row.expires_at
    db_session.execute(
        sa.update(AuthSession).values(last_used_at=datetime.now(UTC) - timedelta(days=1))
    )
    db_session.expire_all()

    auth_client.get("/api/auth/me")

    session_row = db_session.scalars(sa.select(AuthSession)).one()
    assert session_row.last_used_at > datetime.now(UTC) - timedelta(minutes=1)
    # absolute expiry만 쓴다. 사용이 만료를 연장하지 않는다.
    assert session_row.expires_at == created_expiry


def test_logout_revokes_the_session_and_clears_the_cookie(
    auth_client: TestClient, user: User, db_session: Session
) -> None:
    token = _login(auth_client).cookies[SESSION_COOKIE_NAME]

    response = auth_client.post("/api/auth/logout", headers={"Origin": ORIGIN})

    assert response.status_code == 204
    # 값을 비우고 Max-Age=0으로, 설정할 때와 같은 속성으로 덮어쓴다.
    assert response.headers["set-cookie"] == (
        '__Host-nc_session=""; HttpOnly; Max-Age=0; Path=/; SameSite=strict; Secure'
    )
    # cookie를 손으로 다시 붙여도 DB가 canonical이라 401이다.
    replayed = auth_client.get("/api/auth/me", headers={"Cookie": f"{SESSION_COOKIE_NAME}={token}"})
    assert replayed.status_code == 401


def test_logout_without_a_session_is_401(auth_client: TestClient) -> None:
    assert auth_client.post("/api/auth/logout", headers={"Origin": ORIGIN}).status_code == 401


def test_login_without_an_origin_header_is_403(auth_client: TestClient, user: User) -> None:
    response = auth_client.post("/api/auth/login", json={"login_id": "junon", "password": PASSWORD})

    assert response.status_code == 403
    assert "set-cookie" not in response.headers


def test_login_from_an_untrusted_origin_is_403(auth_client: TestClient, user: User) -> None:
    response = auth_client.post(
        "/api/auth/login",
        json={"login_id": "junon", "password": PASSWORD},
        headers={"Origin": OTHER_ORIGIN},
    )

    assert response.status_code == 403


def test_logout_without_an_origin_header_is_403(auth_client: TestClient, user: User) -> None:
    _login(auth_client)

    assert auth_client.post("/api/auth/logout").status_code == 403


def test_get_me_does_not_require_an_origin_header(auth_client: TestClient, user: User) -> None:
    """GET은 상태를 바꾸지 않는다. Origin을 요구하면 정상 탐색이 막힌다."""
    _login(auth_client)

    assert auth_client.get("/api/auth/me").status_code == 200


# --------------------------------------------------------------------------
# AUTH_SESSION_TTL_DAYS (ADR-004). 설정값이 cookie와 DB 양쪽에 실제로 반영되는지.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("ttl_days", [3, 11])
def test_session_lifetime_comes_from_the_configured_ttl(
    db_session: Session, monkeypatch: pytest.MonkeyPatch, user: User, ttl_days: int
) -> None:
    """cookie `Max-Age`와 `auth_sessions.expires_at`이 **둘 다** 주입값을 따른다.

    서로 다른 두 값으로 돌린다. 한 값만 쓰면 그 값을 리터럴로 박은 구현이 통과한다.
    cookie만 보면 DB 만료가 어긋나도(= 브라우저는 지웠는데 서버는 살아 있음) 모르고,
    DB만 보면 브라우저가 쿠키를 너무 오래/짧게 들고 있는 것을 모른다.
    """
    with _configured_client(db_session, monkeypatch, ttl_days) as client:
        before = datetime.now(UTC)
        response = _login(client)
        after = datetime.now(UTC)

    assert response.status_code == 200
    assert f"; Max-Age={ttl_days * SECONDS_PER_DAY}" in response.headers["set-cookie"]

    expires_at = db_session.scalars(sa.select(AuthSession.expires_at)).one()
    assert before + timedelta(days=ttl_days) <= expires_at <= after + timedelta(days=ttl_days)


# --------------------------------------------------------------------------
# 401 응답의 동일성 (04_SECURITY_AND_DATA.md). 실패 사유를 구분하면 그 자체가 oracle이다.
# --------------------------------------------------------------------------


def test_every_unauthenticated_request_gets_the_same_401(
    auth_client: TestClient, user: User, db_session: Session
) -> None:
    """cookie 없음 / 미지 토큰 / 만료 / revoked / 비활성 사용자.

    status뿐 아니라 **body까지** 같아야 한다. "Session expired" 같은 문구를 UX
    명목으로 넣는 순간 공격자는 토큰의 존재 여부를 알게 된다.
    """
    no_cookie = auth_client.get("/api/auth/me")
    unknown_token = auth_client.get(
        "/api/auth/me", headers={"Cookie": f"{SESSION_COOKIE_NAME}=not-a-real-token"}
    )

    _login(auth_client)
    db_session.execute(
        sa.update(AuthSession).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    expired = auth_client.get("/api/auth/me")

    db_session.execute(
        sa.update(AuthSession).values(
            expires_at=datetime.now(UTC) + timedelta(days=TTL_DAYS),
            revoked_at=datetime.now(UTC),
        )
    )
    revoked = auth_client.get("/api/auth/me")

    db_session.execute(sa.update(AuthSession).values(revoked_at=None))
    user.is_active = False
    db_session.flush()
    inactive = auth_client.get("/api/auth/me")

    responses = [no_cookie, unknown_token, expired, revoked, inactive]
    assert {response.status_code for response in responses} == {401}
    bodies = {json.dumps(response.json(), sort_keys=True) for response in responses}
    assert len(bodies) == 1, bodies
    # 브라우저 기본 인증 팝업을 띄우지 않는다.
    assert all("www-authenticate" not in response.headers for response in responses)


def test_a_revoked_session_is_401(auth_client: TestClient, user: User, db_session: Session) -> None:
    """logout을 거치지 않고 `revoked_at`만 채워도 거부된다.

    DB가 canonical이다. revoke 경로가 logout 하나뿐이라고 가정하면 (Future의 admin
    revoke, 침해 대응) 그 경로들이 동작하지 않는다.
    """
    _login(auth_client)
    db_session.execute(sa.update(AuthSession).values(revoked_at=datetime.now(UTC)))
    db_session.flush()

    assert auth_client.get("/api/auth/me").status_code == 401


# --------------------------------------------------------------------------
# logout의 revoke 범위.
# --------------------------------------------------------------------------


def test_logout_revokes_only_the_calling_session(
    auth_client: TestClient, user: User, db_session: Session
) -> None:
    """같은 사용자의 다른 세션(다른 기기)은 살아 있어야 한다.

    `revoke_session`의 `token_hash` 조건이 사라져도 세션이 하나뿐인 테스트에서는
    아무것도 깨지지 않는다. 그래서 두 개를 만든다.
    """
    logged_out = _login(auth_client).cookies[SESSION_COOKIE_NAME]
    other_device = create_session(db_session, user_id=user.id, ttl_days=TTL_DAYS)
    db_session.flush()

    assert auth_client.post("/api/auth/logout", headers={"Origin": ORIGIN}).status_code == 204

    revoked = {
        row.token_hash
        for row in db_session.scalars(sa.select(AuthSession)).all()
        if row.revoked_at is not None
    }
    assert revoked == {hash_token(logged_out)}

    # 살아 있음을 DB 상태가 아니라 실제 요청으로 확인한다.
    still_valid = auth_client.get(
        "/api/auth/me", headers={"Cookie": f"{SESSION_COOKIE_NAME}={other_device}"}
    )
    assert still_valid.status_code == 200
    assert still_valid.json()["login_id"] == "junon"
