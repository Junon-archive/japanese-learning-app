"""installable PWA (spec/02_ARCHITECTURE.md) + 모바일 탭 타깃.

`index.html`은 **service worker 없이** manifest와 아이콘만으로 설치 가능하다고 적고
있다(MVP는 offline을 지원하지 않고, SW가 있으면 저장 실패를 성공처럼 보이게 만드는
경로가 열린다 --- 10_ERROR_HANDLING.md). 그 주장은 브라우저가 판정하는 것이므로
여기서 Chrome에게 직접 묻는다.

이 파일의 대부분은 **backend를 요구하지 않는다**(`frontend` fixture만 쓴다). 설치
가능성은 정적 산출물의 성질이다. 모바일 스모크만 학습 화면이 필요해서 stack을 쓴다.
"""

from __future__ import annotations

import json
import struct
from datetime import timedelta
from typing import Any

import pytest
from playwright.sync_api import Browser, BrowserContext, Locator, Page, Playwright

from app.config import get_config
from app.models import StudySession
from tests.conftest import override_config
from tests.e2e import study_flow as flow
from tests.e2e.conftest import E2EStack, Frontend

pytestmark = pytest.mark.e2e

# manifest가 있어야 하는 아이콘 크기. PWA 설치 요건이며 학습 정책값이 아니다.
REQUIRED_ICON_SIZES = (192, 512)

# 손가락 하나가 누를 수 있는 최소 크기(px). Apple HIG / WCAG 2.5.5의 목표치이며
# 학습 정책값이 아니다. 03_UI_UX_SPEC.md의 모바일 우선 요구를 숫자로 옮긴 것이다.
MIN_TAP_TARGET_PX = 44

# 레이아웃 좌표의 부동소수 오차. 44px로 선언한 요소가 device scale factor 3에서
# 43.999998px로 측정된다. 1px보다 훨씬 작으므로 실제로 작은 요소를 통과시키지 않는다.
_SUBPIXEL_TOLERANCE_PX = 0.01

# 설치 가능한 PWA가 가질 수 있는 display 값. `browser`는 설치 대상이 아니다.
INSTALLABLE_DISPLAYS = frozenset({"standalone", "fullscreen", "minimal-ui"})

# 브라우저가 manifest를 읽고 installability를 판정할 시간. 정책값이 아니다.
_SETTLE_MS = 3000

# 모바일 스모크가 주입하는 세션 길이. 기본값과 **다르게** 둔다 --- 기본값을 쓰면 config를
# 읽지 않는 구현도 통과한다. 짧게 두는 이유는 시계를 한 번만 옮겨 목표에 닿기 위해서이고,
# 기대값(목표 초, idle gap 상한)은 전부 이 값에서 유도한다.
PHONE_SESSION_MINUTES = 1

# `오늘 학습 완료` 버튼 문구. `frontend/src/ui/session-end.ts`와 같아야 한다 --- 사용자가
# 실제로 누르는 것이 이 글자다.
FINISH_LABEL = "오늘 학습 완료"

# **API를 부르지 않는 경로로 들어간다.** 설치 가능성은 정적 산출물의 성질이고, 이
# 파일은 backend fixture를 요구하지 않는다. MVP-02에서 부팅은 어떤 경로에서도 API를 부르지
# 않으므로(불변식 14) 설치한 앱의 시작 주소(`start_url: "/"`)인 루트가 곧 그 경로다
# (ADR-022의 `PWA start_url`).
_NO_API_ROUTE = "/"


def _manifest(page: Page, context: BrowserContext) -> dict[str, Any]:
    """`Page.getAppManifest`의 원본 JSON.

    CDP의 `parsed`는 이 Chrome에서 `scope`만 담고 있어서 쓸 수 없다. `data`(원문)를
    직접 파싱한다 --- 우리가 배포하는 파일 그대로를 보는 것이므로 오히려 정확하다.
    """
    cdp = context.new_cdp_session(page)
    cdp.send("Page.enable")
    result = cdp.send("Page.getAppManifest")
    assert result.get("errors") == [], f"manifest 파싱 오류: {result.get('errors')}"
    raw = result.get("data")
    assert raw, "manifest가 비어 있다"
    parsed = json.loads(raw)
    assert isinstance(parsed, dict)
    return parsed


def _undersized(locator: Locator, selector: str) -> list[str]:
    """화면에 있는 그 selector의 요소 중 탭 타깃 최소 크기에 못 미치는 것."""
    found: list[str] = []
    assert locator.count() > 0, f"{selector}가 화면에 없다"
    for index in range(locator.count()):
        box = locator.nth(index).bounding_box()
        assert box is not None, f"{selector}[{index}]가 화면에 없다"
        limit = MIN_TAP_TARGET_PX - _SUBPIXEL_TOLERANCE_PX
        if box["width"] < limit or box["height"] < limit:
            found.append(f"{selector}[{index}]={box['width']}x{box['height']}")
    return found


def _finished_session(stack: E2EStack, learner: flow.Learner) -> StudySession | None:
    session = flow.study_session(stack, learner)
    return session if session.ended_at is not None else None


def _png_size(payload: bytes) -> tuple[int, int]:
    """PNG의 IHDR에서 실제 픽셀 크기를 읽는다.

    manifest의 `sizes`는 **선언**일 뿐이다. 192로 적고 32px 파일을 올리면 설치
    아이콘이 흐려지는데 그 결함은 manifest만 봐서는 보이지 않는다.
    """
    assert payload[:8] == b"\x89PNG\r\n\x1a\n", "PNG 파일이 아니다"
    width, height = struct.unpack(">II", payload[16:24])
    return width, height


def test_chrome_reports_no_installability_errors(
    frontend: Frontend, installable_context: BrowserContext
) -> None:
    """persistent context에서 Chrome이 "설치 가능"이라고 답한다. service worker는 없다."""
    page = installable_context.new_page()
    page.goto(f"{frontend.url}{_NO_API_ROUTE}")
    page.wait_for_timeout(_SETTLE_MS)

    cdp = installable_context.new_cdp_session(page)
    cdp.send("Page.enable")
    verdict = cdp.send("Page.getInstallabilityErrors")
    assert verdict["installabilityErrors"] == [], verdict

    # SW가 없는 상태에서의 판정임을 함께 못박는다. 나중에 누가 SW를 등록하면
    # 이 단언이 깨지고, 그때 10_ERROR_HANDLING.md의 결정을 다시 읽게 된다.
    assert page.evaluate("navigator.serviceWorker.controller") is None


def test_the_default_incognito_context_cannot_judge_installability(
    frontend: Frontend, browser: Browser
) -> None:
    """기본 context로는 판정이 안 된다 --- `installable_context` fixture가 있는 이유다.

    이 단언이 없으면 누군가 persistent context를 걷어내고 기본 context로 바꾸면서
    "여전히 초록"이라고 믿게 된다. 그때 실제로 보고 있는 것은 `in-incognito`다.
    """
    context = browser.new_context()
    try:
        page = context.new_page()
        page.goto(f"{frontend.url}{_NO_API_ROUTE}")
        page.wait_for_timeout(_SETTLE_MS)
        cdp = context.new_cdp_session(page)
        cdp.send("Page.enable")
        errors = cdp.send("Page.getInstallabilityErrors")["installabilityErrors"]
        assert errors != [], "incognito context가 설치 가능으로 판정됐다(전제가 바뀌었다)"
    finally:
        context.close()


def test_the_manifest_declares_what_an_installable_app_needs(
    frontend: Frontend, installable_context: BrowserContext
) -> None:
    page = installable_context.new_page()
    page.goto(f"{frontend.url}{_NO_API_ROUTE}")
    page.wait_for_timeout(_SETTLE_MS)
    manifest = _manifest(page, installable_context)

    assert manifest.get("name"), manifest
    assert manifest.get("start_url"), manifest
    assert manifest.get("display") in INSTALLABLE_DISPLAYS, manifest

    icons = manifest.get("icons")
    assert isinstance(icons, list) and icons, manifest
    declared = {size for icon in icons for size in str(icon.get("sizes", "")).split()}
    for required in REQUIRED_ICON_SIZES:
        assert f"{required}x{required}" in declared, f"{required}px 아이콘 선언이 없다: {declared}"

    purposes = {purpose for icon in icons for purpose in str(icon.get("purpose", "")).split()}
    assert "maskable" in purposes, f"maskable 아이콘이 없다: {icons}"


def test_every_declared_icon_is_actually_that_many_pixels(
    frontend: Frontend, installable_context: BrowserContext
) -> None:
    """선언한 크기와 파일의 실제 픽셀이 같다. 빌드 산출물을 HTTP로 받아 확인한다."""
    page = installable_context.new_page()
    page.goto(f"{frontend.url}{_NO_API_ROUTE}")
    page.wait_for_timeout(_SETTLE_MS)
    icons = _manifest(page, installable_context)["icons"]

    checked = 0
    for icon in icons:
        source = str(icon["src"])
        response = page.request.get(f"{frontend.url}{source}" if source.startswith("/") else source)
        assert response.status == 200, f"{source}: {response.status}"
        assert response.headers["content-type"] == "image/png", source
        actual = _png_size(response.body())
        for size in str(icon.get("sizes", "")).split():
            expected = (int(size.split("x")[0]), int(size.split("x")[1]))
            assert actual == expected, f"{source}: 선언 {expected}, 실제 {actual}"
            checked += 1
    assert checked >= len(REQUIRED_ICON_SIZES), f"검사한 아이콘이 {checked}개뿐이다"


def test_the_install_prompt_event_fires(
    frontend: Frontend, installable_context: BrowserContext
) -> None:
    """`beforeinstallprompt`가 실제로 발화한다. 설치 UI가 뜰 수 있다는 브라우저의 신호다."""
    installable_context.add_init_script(
        """
        window.__installPrompt = null;
        window.addEventListener('beforeinstallprompt', (event) => {
            event.preventDefault();
            window.__installPrompt = event.type;
        });
        """
    )
    page = installable_context.new_page()
    page.goto(f"{frontend.url}{_NO_API_ROUTE}")
    page.wait_for_timeout(_SETTLE_MS)
    assert page.evaluate("window.__installPrompt") == "beforeinstallprompt"


@pytest.mark.integration
def test_the_study_screen_works_on_a_phone_viewport(
    e2e_stack: E2EStack, browser: Browser, playwright_driver: Playwright
) -> None:
    """iPhone descriptor로 선택 홈 -> 상단바 `로그인` -> 학습 화면을 시작부터 **세션 종료까지** 밟고
    탭 타깃 크기를 본다.

    03_UI_UX_SPEC.md는 모바일 우선이다. 데스크톱에서만 눌리는 화면은 그 요구를
    만족하지 않고, 크기 미달은 기능 테스트로는 절대 드러나지 않는다. 종료 버튼도 같다 ---
    폰에서 `오늘 학습 완료`를 누를 수 없으면 세션은 idle timeout으로만 닫힌다.

    목표 도달을 실제로 기다리지 않는다. 짧은 세션을 주입하고 `stack.clock`을 목표만큼
    한 번 옮긴다. 그 한 번의 gap이 전부 active time이 되도록 idle gap 상한도 같은 값에서
    유도해 주입한다(`study_session.touch()`는 상한을 넘는 gap에 0을 더한다).
    """
    stack = e2e_stack
    goal = timedelta(minutes=PHONE_SESSION_MINUTES)
    stack.use_config(
        override_config(
            get_config(),
            learning={"default_session_minutes": PHONE_SESSION_MINUTES},
            session={"active_time_idle_gap_seconds": int(goal.total_seconds())},
        )
    )

    device = playwright_driver.devices["iPhone 13"]
    context = browser.new_context(**device)
    try:
        page = context.new_page()
        learner = flow.seed_and_create_user(stack)

        # 선택 홈. 설치한 앱을 열면 여기이고 계정 사용자는 상단바 `로그인`을 한 번 누른다.
        page.goto(stack.frontend_url)
        page.locator(".screen.home").wait_for(state="visible")
        home_targets = _undersized(page.locator(".topbar-login"), ".topbar-login")
        home_targets += _undersized(page.locator(".home-card"), ".home-card")
        assert home_targets == [], f"탭 타깃이 {MIN_TAP_TARGET_PX}px 미만이다: {home_targets}"

        flow.sign_in(page, stack, learner)

        # 문장과 주 동작이 화면에 있다.
        assert flow.tokens(page).count() > 0
        opened = flow.open_presentation(stack, learner)
        assert opened is not None
        assert flow.study_session(stack, learner).target_minutes == PHONE_SESSION_MINUTES

        # 설명 패널까지 열어 self-report 버튼도 측정 대상에 넣는다.
        flow.tap(page, 0)

        undersized: list[str] = []
        for selector in (
            "button.next",
            ".explain .self-report",
            ".sheet-close",
            ".reveal-translation",
            ".topbar .history-link",
            ".topbar .logout",
        ):
            undersized += _undersized(page.locator(selector), selector)
        assert undersized == [], f"탭 타깃이 {MIN_TAP_TARGET_PX}px 미만이다: {undersized}"

        # 가로 스크롤이 생기지 않는다. 모바일에서 문장이 잘리는 가장 흔한 형태다.
        overflow = page.evaluate(
            "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
        )
        assert overflow <= 0, f"가로 overflow {overflow}px"

        # 목표 도달 전에는 종료 선택지가 없다. 처음부터 떠 있는 버튼이면 아래 단언이
        # "도달해서 떴다"를 증명하지 못한다.
        assert page.locator(".session-end").count() == 0

        # 문장 완료(Next). 목표만큼 시계를 옮긴 뒤 누르므로 `/complete`가 목표를 채우고,
        # 이어지는 `GET /session`이 도달을 화면에 알린다.
        stack.clock.advance(goal)
        flow.press_next(page, stack, learner)
        completed = [row for row in flow.presentations(stack, learner) if row.completed_at]
        assert [row.id for row in completed] == [opened.id]

        reached = flow.study_session(stack, learner)
        assert reached.active_seconds >= reached.target_minutes * 60, reached.active_seconds
        # 도달은 종료가 아니다(05_API_SPEC.md). 누르기 전에는 열려 있어야 한다.
        assert reached.ended_at is None

        choice = page.locator(".session-end")
        choice.wait_for(state="visible", timeout=flow.SETTLE_TIMEOUT_SECONDS * 1000)
        end_buttons = _undersized(choice.locator("button"), ".session-end button")
        assert end_buttons == [], f"종료 버튼이 {MIN_TAP_TARGET_PX}px 미만이다: {end_buttons}"

        choice.locator("button", has_text=FINISH_LABEL).tap()
        page.locator(".session-finished").wait_for(
            state="visible", timeout=flow.SETTLE_TIMEOUT_SECONDS * 1000
        )
        # 끝난 화면에는 문장도 Next도 남지 않는다.
        assert page.locator(".sentence").count() == 0
        assert page.locator("button.next").count() == 0

        finished = flow._poll(lambda: _finished_session(stack, learner), what="세션의 ended_at")
        assert finished.id == reached.id
        assert finished.ended_at is not None
    finally:
        context.close()
