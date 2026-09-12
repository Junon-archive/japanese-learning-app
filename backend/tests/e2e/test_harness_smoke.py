"""하네스 자체의 스모크 (작업 단위 F0).

여기서 검증하는 것은 **화면이 아니라 하네스**다. 화면 검증(Core E2E 13단계)은
frontend가 생긴 뒤 별도 작업에서 이 fixture들 위에 쓴다.

이 파일이 초록이면 다음이 성립한다.

-   빌드된 frontend가 실제 HTTP로 서빙되고 Chrome이 그것을 연다.
-   브라우저가 API에 닿고, `require_trusted_origin` / `__Host-` + `Secure` 쿠키가
    `http://localhost` 조합에서 실제로 통한다(여기가 조용히 401이 되는 자리다).
-   **테스트가 서버의 시계를 옮길 수 있다.** Core E2E 9단계(due 시점으로 이동)가
    이 능력 하나에 달려 있다.
-   같은 프로세스라 DB를 직접 쓰고 읽을 수 있다.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from playwright.sync_api import BrowserContext, Page

from app.services.auth import SESSION_COOKIE_NAME, hash_password
from tests import factories
from tests.e2e.conftest import FRONTEND_DIST, E2EStack

pytestmark = pytest.mark.e2e

# 정책값이 아니다. "시계가 움직였다"만 보므로 아무 간격이어도 된다 --- 그래서
# config에서 읽지 않는다(13_ACCEPTANCE_CRITERIA.md의 `수치 취급 원칙`은 정책
# 판정에 쓰이는 숫자에 대한 규칙이다).
_ARBITRARY_CLOCK_STEP = timedelta(days=3, hours=7, minutes=11)

_PASSWORD = "correct horse battery staple"


@pytest.mark.integration
def test_the_built_frontend_is_served(e2e_stack: E2EStack, page: Page) -> None:
    """옛 `dist`가 아니라 이 세션이 빌드한 산출물이 200으로 나온다."""
    response = page.goto(e2e_stack.frontend_url)
    assert response is not None
    assert response.status == 200, response.status
    assert page.title() != ""


@pytest.mark.integration
def test_the_browser_reaches_the_api(e2e_stack: E2EStack, page: Page) -> None:
    """브라우저 -> uvicorn 스레드 -> pgserver가 한 줄로 이어진다."""
    response = page.request.get(f"{e2e_stack.api_url}/api/health")
    assert response.status == 200, response.text()
    body = response.json()
    assert body["status"] == "ok", body
    # DB가 실제로 붙어 있어야 한다. unknown이면 DATABASE_URL이 새어 나간 것이고,
    # 그래도 overall status는 ok로 나오므로 여기서 따로 못박는다.
    assert body["components"]["database"]["status"] == "ok", body


@pytest.mark.integration
def test_moving_the_test_clock_moves_the_server_clock(e2e_stack: E2EStack, page: Page) -> None:
    """이 하네스의 핵심 능력. Core E2E 9단계가 여기에 달려 있다.

    `/api/health`의 `checked_at`은 `Depends(get_now)`가 준 값이므로 서버가 이 요청에서
    **실제로 본 시각**이다. 시계를 옮긴 뒤 그 값이 따라 움직이면, 테스트 프로세스의
    시계가 request 경로까지 닿는다는 뜻이다 --- 앱에 테스트용 표면을 하나도 붙이지 않고.
    """
    health = f"{e2e_stack.api_url}/api/health"

    before = _checked_at(page, health)
    assert before == e2e_stack.clock.now(), (before, e2e_stack.clock.now())

    moved = e2e_stack.clock.advance(_ARBITRARY_CLOCK_STEP)

    after = _checked_at(page, health)
    # 실패했을 때 "시계가 안 움직였다"를 로그에서 바로 읽을 수 있어야 한다.
    print(f"[e2e] server-observed now: {before.isoformat()} -> {after.isoformat()}")  # noqa: T201
    assert after == moved
    assert after - before == _ARBITRARY_CLOCK_STEP
    # 실클록이 아니라 주입된 시계다. 실행일과 무관하게 같은 값이 나온다.
    assert after == e2e_stack.clock.now()


@pytest.mark.integration
def test_login_through_the_browser_stores_the_host_cookie(e2e_stack: E2EStack, page: Page) -> None:
    """`__Host-` + `Secure` + `SameSite=Strict` 쿠키가 http://localhost에서 통한다.

    여기가 조용히 깨지는 자리다: host를 `127.0.0.1`과 섞거나
    `CORS_ALLOW_ORIGINS`에서 frontend origin이 빠지면 로그인은 403/401이 되고,
    쿠키가 저장되지 않으면 이후 모든 요청이 401이 된다. 그 실패는 화면만 보면
    "아무것도 안 뜬다"로만 보인다.
    """
    with e2e_stack.sessions() as setup:
        user = factories.make_user(setup)
        user.password_hash = hash_password(_PASSWORD)
        setup.commit()
        login_id = user.login_id

    page.goto(e2e_stack.frontend_url)
    login = page.request.post(
        f"{e2e_stack.api_url}/api/auth/login",
        data={"login_id": login_id, "password": _PASSWORD},
        headers={"Origin": e2e_stack.frontend_url},
    )
    assert login.status == 200, login.text()

    stored = {cookie["name"] for cookie in page.context.cookies()}
    assert SESSION_COOKIE_NAME in stored, stored

    me = page.request.get(f"{e2e_stack.api_url}/api/auth/me")
    assert me.status == 200, me.text()
    assert me.json()["login_id"] == login_id


@pytest.mark.integration
def test_unauthenticated_api_is_rejected(e2e_stack: E2EStack, page: Page) -> None:
    """테스트 전용 무인증 표면이 없다는 것을 브라우저 쪽에서도 확인한다."""
    response = page.request.get(f"{e2e_stack.api_url}/api/study/session")
    assert response.status == 401, response.text()


@pytest.mark.integration
def test_the_static_server_labels_a_webmanifest(e2e_stack: E2EStack, page: Page) -> None:
    """`.webmanifest`의 Content-Type이 맞아야 한다.

    매핑이 빠지면 브라우저가 manifest를 무시하고 installability 판정이 **조용히**
    실패한다. frontend의 실제 manifest 파일명에 기대지 않고 탐침 파일을 쓴다 ---
    검사 대상은 이 정적 서버의 계약이고, 파일명은 frontend 쪽 사정이다.
    """
    probe = FRONTEND_DIST / "harness-probe.webmanifest"
    probe.write_text('{"name":"probe"}', encoding="utf-8")
    try:
        response = page.request.get(f"{e2e_stack.frontend_url}/{probe.name}")
        assert response.status == 200, response.text()
        assert response.headers["content-type"] == "application/manifest+json"
    finally:
        probe.unlink()


def test_the_browser_fixture_runs_system_chrome(page: Page) -> None:
    """어떤 브라우저가 떴는지 출력한다. 다운로드한 번들이 아니라 시스템 Chrome이다."""
    browser = page.context.browser
    assert browser is not None
    print(f"[e2e] browser (launch): Chrome {browser.version}")  # noqa: T201
    assert browser.version != ""


def test_the_persistent_context_fixture_runs_system_chrome(
    installable_context: BrowserContext,
) -> None:
    """installability 판정용 fixture. 기본 context(incognito)로는 판정이 안 된다."""
    browser = installable_context.browser
    assert browser is not None
    print(f"[e2e] browser (persistent context): Chrome {browser.version}")  # noqa: T201
    page = installable_context.new_page()
    page.goto("data:text/html,<title>harness</title>")
    assert page.title() == "harness"


def _checked_at(page: Page, health_url: str) -> datetime:
    response = page.request.get(health_url)
    assert response.status == 200, response.text()
    return datetime.fromisoformat(response.json()["checked_at"])
