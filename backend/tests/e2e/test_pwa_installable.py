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
from typing import Any

import pytest
from playwright.sync_api import Browser, BrowserContext, Page, Playwright

from tests.e2e import study_flow as flow
from tests.e2e.conftest import E2EStack, Frontend

pytestmark = pytest.mark.e2e

# manifest가 있어야 하는 아이콘 크기. PWA 설치 요건이며 학습 정책값이 아니다.
REQUIRED_ICON_SIZES = (192, 512)

# 손가락 하나가 누를 수 있는 최소 크기(px). Apple HIG / WCAG 2.5.5의 목표치이며
# 학습 정책값이 아니다. 03_UI_UX_SPEC.md의 모바일 우선 요구를 숫자로 옮긴 것이다.
MIN_TAP_TARGET_PX = 44

# 설치 가능한 PWA가 가질 수 있는 display 값. `browser`는 설치 대상이 아니다.
INSTALLABLE_DISPLAYS = frozenset({"standalone", "fullscreen", "minimal-ui"})

# 브라우저가 manifest를 읽고 installability를 판정할 시간. 정책값이 아니다.
_SETTLE_MS = 3000

# **API를 부르지 않는 경로로 들어간다.** 설치 가능성은 정적 산출물의 성질이고, 이
# 파일은 backend fixture를 요구하지 않는다. 루트(`/`)로 들어가면 boot이
# `GET /api/auth/me`를 부르므로 backend 유무에 결과가 얽히고, 같은 pytest 세션에서
# 다른 테스트가 띄워 둔 서버에 설정 없는 요청을 던져 서버 로그를 오염시킨다.
_NO_API_ROUTE = "#/demo"


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
    """iPhone descriptor로 학습 화면을 밟고 주 동작의 탭 타깃 크기를 본다.

    03_UI_UX_SPEC.md는 모바일 우선이다. 데스크톱에서만 눌리는 화면은 그 요구를
    만족하지 않고, 크기 미달은 기능 테스트로는 절대 드러나지 않는다.
    """
    device = playwright_driver.devices["iPhone 13"]
    context = browser.new_context(**device)
    try:
        page = context.new_page()
        learner = flow.seed_and_create_user(e2e_stack)
        flow.sign_in(page, e2e_stack, learner)

        # 문장과 주 동작이 화면에 있다.
        assert flow.tokens(page).count() > 0
        opened = flow.open_presentation(e2e_stack, learner)
        assert opened is not None

        # 설명 패널까지 열어 self-report 버튼도 측정 대상에 넣는다.
        flow.tap(page, 0)

        undersized: list[str] = []
        for selector in ("button.next", ".explain .self-report", ".reveal-translation"):
            locator = page.locator(selector)
            for index in range(locator.count()):
                box = locator.nth(index).bounding_box()
                assert box is not None, f"{selector}[{index}]가 화면에 없다"
                if box["width"] < MIN_TAP_TARGET_PX or box["height"] < MIN_TAP_TARGET_PX:
                    undersized.append(f"{selector}[{index}]={box['width']}x{box['height']}")
        assert undersized == [], f"탭 타깃이 {MIN_TAP_TARGET_PX}px 미만이다: {undersized}"

        # 가로 스크롤이 생기지 않는다. 모바일에서 문장이 잘리는 가장 흔한 형태다.
        overflow = page.evaluate(
            "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
        )
        assert overflow <= 0, f"가로 overflow {overflow}px"
    finally:
        context.close()
