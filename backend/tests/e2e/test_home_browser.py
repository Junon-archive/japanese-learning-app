"""선택 홈과 로그인 진입 (mvp-02-onboarding/12_TEST_PLAN.md의 `Browser E2E`, 13_ACCEPTANCE_CRITERIA.md 1~10).

휴대폰 viewport로 돈다. "서버 요청"은 API origin으로 나간 요청이다(정적 자산 제외).

-   hash 없이 열면 방문자가 무슨 앱인지 바로 안다: 앱 이름, `로그인`, 한 줄 소개, 카드 2개. 카드에 문장
    수 숫자가 없다. API 요청 0건이다.
-   `로그인`을 누를 때만 `GET /api/auth/me`가 1건 나간다. 401이면 Login, 로그인하면 Study Screen.
    로그인 영역에는 hash가 없으므로 새로고침하면 선택 홈이고, 다시 `로그인`을 누르면 곧바로 Study Screen이다.
    로그아웃하면 선택 홈이다.
-   공개 화면 사이에서 뒤로 가기가 동작하고, 모르는 hash는 선택 홈(`#/`)이다.

**Wave 2에는 가나 학습 화면이 없다.** `#/kana`는 route 표에 없어 선택 홈(`#/`)으로 떨어진다. Wave 3
kana-ui 레인이 화면을 더하면서 가나 경로의 단정을 바꾼다.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

import pytest
from playwright.sync_api import Browser, Page, Playwright, expect

from tests.e2e import study_flow as flow
from tests.e2e.conftest import E2EStack, Frontend

pytestmark = pytest.mark.e2e

PHONE = "iPhone 13"

# 화면 문구(03_UI_UX_SPEC.md의 `화면 문구 표`의 `상단바와 선택 홈`, `Login과 로그아웃`).
APP_NAME = "Nihongo Context"
INTRO = "일본어 표현을 실제 문장 속에서 익히는 앱이에요."
CARDS = [
    ("표현 학습 체험해 보기", "모르는 표현을 눌러 뜻을 확인해요.", ["로그인 없이"]),
    ("글자부터 배우기", "히라가나와 가타카나를 표와 퀴즈로 익혀요.", ["히라가나", "가타카나"]),
]
LOGGED_OUT_TOAST = "로그아웃했어요."
LOGOUT_LABEL = "로그아웃"
HOME_HASH = "#/"
DEMO_ROUTE = "#/demo"
KANA_ROUTE = "#/kana"

# 늦게 나가는 요청이 드러날 때까지 기다리는 시간. 정책값이 아니다.
_LATE_REQUEST_WINDOW_MS = 2000


@pytest.fixture
def phone(browser: Browser, playwright_driver: Playwright) -> Iterator[Page]:
    context = browser.new_context(**playwright_driver.devices[PHONE])
    try:
        yield context.new_page()
    finally:
        context.close()


def _home(page: Page) -> None:
    page.locator(".screen.home").wait_for(
        state="visible", timeout=flow.SETTLE_TIMEOUT_SECONDS * 1000
    )


def _topbar_right(page: Page) -> list[str]:
    return page.locator(".screen .topbar .topbar-actions button").all_inner_texts()


# --------------------------------------------------------------------------
# backend를 띄우지 않은 구성
# --------------------------------------------------------------------------


def test_the_home_says_what_the_app_is_without_any_request(frontend: Frontend, phone: Page) -> None:
    """hash 없이 열면 앱 이름, `로그인`, 한 줄 소개, 카드 2개가 있고 요청은 0건이다."""
    traffic = flow.watch_traffic(
        phone, frontend_url=frontend.url, api_url=frontend.api_url, block=True
    )
    phone.goto(frontend.url)
    _home(phone)

    screen = phone.locator(".screen.home")
    expect(screen.locator(".topbar .topbar-brand")).to_have_text(APP_NAME)
    assert _topbar_right(phone) == [flow.LOGIN_LABEL]
    expect(screen.locator("h1")).to_have_text(INTRO)

    cards = screen.locator(".home-card")
    assert cards.count() == len(CARDS)
    for index, (title, description, pills) in enumerate(CARDS):
        card = cards.nth(index)
        expect(card.locator(".home-card-title")).to_have_text(title)
        expect(card.locator(".home-card-desc")).to_have_text(description)
        expect(card.locator(".pill")).to_have_text(pills)
        # 카드에 문장 수 숫자를 적지 않는다.
        assert re.search(r"\d", card.inner_text()) is None, card.inner_text()

    phone.wait_for_timeout(_LATE_REQUEST_WINDOW_MS)
    traffic.assert_none_outside()
    assert traffic.api_calls == []


def test_back_returns_home_from_the_public_screens(frontend: Frontend, phone: Page) -> None:
    """선택 홈 -> Demo -> 뒤로 -> 선택 홈, 선택 홈 -> 가나 -> 뒤로 -> 선택 홈. 모르는 hash는 `#/`다."""
    traffic = flow.watch_traffic(
        phone, frontend_url=frontend.url, api_url=frontend.api_url, block=True
    )
    phone.goto(frontend.url)
    _home(phone)

    phone.locator(".home-card", has_text=CARDS[0][0]).click()
    phone.locator(".screen.demo .sentence").wait_for(state="visible")
    assert phone.url.endswith(DEMO_ROUTE), phone.url
    phone.go_back()
    _home(phone)
    assert phone.locator(".screen.demo").count() == 0

    phone.locator(".home-card", has_text=CARDS[1][0]).click()
    # Wave 2: 가나 학습 route가 없어 선택 홈(`#/`)이다. Wave 3 kana-ui가 가나 화면 단정으로 바꾼다.
    expect(phone).to_have_url(re.compile(f"{re.escape(HOME_HASH)}$"))
    _home(phone)
    phone.go_back()
    _home(phone)

    phone.goto(f"{frontend.url}/#/unknown")
    expect(phone).to_have_url(re.compile(f"{re.escape(HOME_HASH)}$"))
    _home(phone)

    phone.goto(f"{frontend.url}/{KANA_ROUTE}")
    expect(phone).to_have_url(re.compile(f"{re.escape(HOME_HASH)}$"))
    _home(phone)

    traffic.assert_none_outside()
    assert traffic.api_calls == []


# --------------------------------------------------------------------------
# backend가 떠 있는 구성
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_login_is_checked_only_from_the_topbar_and_the_login_area_has_no_hash(
    e2e_stack: E2EStack, phone: Page
) -> None:
    """`로그인` -> 401 Login -> 로그인 -> Study, 새로고침 -> 선택 홈, `로그인` -> 곧바로 Study, 로그아웃 -> 선택 홈."""
    stack = e2e_stack
    learner = flow.seed_and_create_user(stack)
    traffic = flow.watch_traffic(
        phone, frontend_url=stack.frontend_url, api_url=stack.api_url, block=False
    )

    phone.goto(stack.frontend_url)
    _home(phone)
    phone.wait_for_timeout(_LATE_REQUEST_WINDOW_MS)
    assert traffic.api_calls == [], f"선택 홈이 API를 불렀다: {traffic.api_calls}"

    # 쿠키가 없다 -> 401 -> Login. 확인은 정확히 1건이다.
    flow.press_topbar_login(phone)
    phone.locator(".login-form").wait_for(
        state="visible", timeout=flow.SETTLE_TIMEOUT_SECONDS * 1000
    )
    phone.wait_for_timeout(_LATE_REQUEST_WINDOW_MS)
    assert traffic.api_calls == ["GET /api/auth/me"]
    assert _topbar_right(phone) == [], "Login 화면의 상단바 오른쪽은 비어 있다"
    assert "#" not in phone.url, f"로그인 영역에 hash가 생겼다: {phone.url}"

    phone.locator("#login-id").fill(learner.login_id)
    phone.locator("#password").fill(flow.PASSWORD)
    phone.locator(".login-form button[type=submit]").click()
    flow.wait_for_sentence(phone)
    assert "#" not in phone.url, f"로그인 영역에 hash가 생겼다: {phone.url}"

    # 새로고침 -> 선택 홈. 부팅은 API를 부르지 않는다.
    calls_before_reload = len(traffic.api_calls)
    phone.reload()
    _home(phone)
    phone.wait_for_timeout(_LATE_REQUEST_WINDOW_MS)
    assert traffic.api_calls[calls_before_reload:] == [], "새로고침한 선택 홈이 API를 불렀다"

    # 다시 `로그인` -> 쿠키가 유효하므로 곧바로 Study Screen. 로그인 폼을 거치지 않는다.
    flow.press_topbar_login(phone)
    flow.wait_for_sentence(phone)
    assert phone.locator(".login-form").count() == 0
    after_login = traffic.api_calls[calls_before_reload:]
    assert after_login[0] == "GET /api/auth/me", after_login
    assert after_login.count("GET /api/auth/me") == 1, after_login

    # 로그아웃 -> 선택 홈과 한 번 사라지는 안내.
    phone.locator(".topbar .logout", has_text=LOGOUT_LABEL).click()
    _home(phone)
    expect(phone.locator(".toast")).to_have_text(LOGGED_OUT_TOAST)
    assert _topbar_right(phone) == [flow.LOGIN_LABEL]
