"""Demo E2E (12_TEST_PLAN.md의 `Demo E2E`, mvp-02-onboarding/12_TEST_PLAN.md의 `Browser E2E`).

명세가 demo에 요구하는 것은 기능보다 **경계**다: anonymous visitor가 로그인 없이
체험하고, private user data가 노출되지 않고, paid LLM이 발생하지 않고, **화면이
backend로 네트워크 요청을 하지 않는다**(static fixture).

그래서 이 파일의 기본 구성은 **backend를 띄우지 않는 것**이다. `frontend` fixture만
요구하므로 이 모듈만 단독 실행하면 uvicorn도 pgserver도 뜨지 않고, 번들에 박힌
API origin 포트에는 아무도 listen하지 않는다. 그 구성에서 demo가 열린다는 것이
"공개 화면은 로그인 상태를 확인하지 않는다"(불변식 14)의 실질적 증명이다 --- backend가 죽어도
demo는 열려야 한다.

요청 0건은 두 겹으로 본다(`study_flow.watch_traffic`).

1.  `page.route`로 frontend origin 밖의 요청을 **전부 abort**한다. 흐름이 그대로
    완주하면 "요청을 안 했다"가 아니라 **"요청이 필요 없다"**가 증명된다.
2.  `page.on("request")`로 전수 수집해 frontend origin 밖이 0건임을 단언한다.

마지막에 backend가 떠 있는 구성으로 같은 것을 한 번 더 본다(맨 아래 테스트).

**Wave 2의 demo는 MVP-01의 3문장 fixture 그대로다.** 진입(선택 홈 카드), 설명 시트, 번역 인라인
펼침, 문구는 MVP-02 기준으로 단정한다. 진행 규칙(같은 문장 다시 보기, 본 문장 수 진행, 완료 화면,
localStorage 진도)은 Wave 3 demo 레인이 만들고 이 파일의 해당 단정도 그때 바꾼다.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from playwright.sync_api import Page, expect
from sqlalchemy.orm import DeclarativeBase, Session

from app.models import ItemExposure, LearningEvent, StudySession
from tests.conftest import no_provider_module_import
from tests.e2e import study_flow as flow
from tests.e2e.conftest import E2EStack, Frontend

pytestmark = pytest.mark.e2e

DEMO_ROUTE = "#/demo"

# demo fixture의 모양(`frontend/src/demo/fixture.ts`). 학습 정책값이 아니라 "체험에
# 무엇이 들어 있어야 하는가"이며, 12_TEST_PLAN.md의 Demo E2E 항목을 숫자로 옮긴 것이다.
DEMO_SENTENCE_COUNT = 3
DEMO_TAPPABLE_COUNT = 5
DEMO_PROBE_COUNT = 1

# 화면 문구(03_UI_UX_SPEC.md의 `화면 문구 표`). 사용자가 실제로 읽고 누르는 글자다.
DEMO_CARD_TITLE = "표현 학습 체험해 보기"
DEMO_TITLE = "표현 학습 체험"
DEMO_BANNER = "체험 중이에요. 기록은 이 브라우저에만 남아요."
SHEET_TITLE = "표현 설명"
SHEET_CLOSE = "닫기"
FIELD_LABELS = ["뜻", "이 문장에서", "느낌", "예문"]
SELF_REPORT_QUESTION = "이 표현, 알고 있었나요?"
SELF_REPORT_OPTIONAL = "고르지 않아도 괜찮아요."
TRANSLATION_BUTTON = "문장 뜻 보기"
NEXT_LABEL = "다음 문장"
HINT_TEXT = "모르는 표현을 눌러 보세요."
# Wave 2의 마지막 문장 안내. Wave 3 demo 레인이 `완료 화면`으로 바꾼다.
LAST_SENTENCE_NOTICE = "데모 문장을 모두 보았습니다"

_SETTLE_MS = 300


def _watch(page: Page, frontend: Frontend) -> flow.Traffic:
    return flow.watch_traffic(page, frontend_url=frontend.url, api_url=frontend.api_url, block=True)


def _open_demo_from_home(page: Page, frontend_url: str) -> None:
    """선택 홈의 카드 1로 들어간다(03_UI_UX_SPEC.md의 Demo `진입과 로딩`)."""
    page.goto(frontend_url)
    page.locator(".screen.home").wait_for(state="visible")
    page.locator(".home-card", has_text=DEMO_CARD_TITLE).click()
    page.locator(".demo-banner").wait_for(state="visible")
    page.locator(".sentence").wait_for(state="visible")
    assert page.url.endswith(DEMO_ROUTE), page.url


def _next_sentence(page: Page) -> None:
    flow.close_sheet(page)
    page.locator("button.next").click()
    page.wait_for_timeout(_SETTLE_MS)


def _tap(page: Page, index: int) -> None:
    flow.close_sheet(page)
    page.locator(".sentence .token").nth(index).click()
    flow.open_sheet(page).locator(".explain").wait_for(state="visible")


def _panel_text(page: Page, selector: str) -> str:
    return flow.open_sheet(page).locator(f".explain {selector}").inner_text()


# --------------------------------------------------------------------------
# backend를 띄우지 않은 구성 (기본)
# --------------------------------------------------------------------------


def test_demo_opens_with_no_backend_running(frontend: Frontend, page: Page) -> None:
    """API origin에 아무도 listen하지 않는 상태에서 `#/demo`로 바로 열린다.

    공개 화면을 열 때 `GET /api/auth/me`를 부르지 않는다(불변식 14). 부르면 여기서 막힌 요청이
    `blocked`에 남는다.
    """
    traffic = _watch(page, frontend)
    page.goto(f"{frontend.url}/{DEMO_ROUTE}")
    page.locator(".demo-banner").wait_for(state="visible")
    page.locator(".sentence").wait_for(state="visible")

    assert page.locator(".screen.demo").count() == 1
    assert page.locator(".login-form").count() == 0, "demo가 로그인 화면으로 떨어졌다"
    assert page.locator(".notice-slot .notice").count() == 0, "demo가 오류 안내를 띄웠다"
    traffic.assert_none_outside()


def test_the_demo_screen_says_what_the_copy_table_says(frontend: Frontend, page: Page) -> None:
    """카드로 들어간 demo의 상단바·제목·안내·버튼 문구가 `화면 문구 표`와 같다."""
    traffic = _watch(page, frontend)
    _open_demo_from_home(page, frontend.url)

    screen = page.locator(".screen.demo")
    expect(screen.locator(".topbar .topbar-brand")).to_have_text("Nihongo Context")
    # Demo 오른쪽은 `로그인`이다. 후리가나 토글은 Wave 3 furigana-fe가 더한다.
    expect(screen.locator(".topbar .topbar-actions button").last).to_have_text(flow.LOGIN_LABEL)
    expect(screen.locator("h1")).to_have_text(DEMO_TITLE)
    expect(screen.locator(".demo-banner")).to_contain_text(DEMO_BANNER)
    expect(screen.locator("button.next")).to_have_text(NEXT_LABEL)
    expect(screen.locator(".reveal-translation")).to_have_text(TRANSLATION_BUTTON)
    # 문장 아래 힌트. Demo의 화면 문구는 Study Screen과 같다(03_UI_UX_SPEC.md의 Demo `체험 요소`).
    expect(screen.locator(".sentence-box")).to_contain_text(HINT_TEXT)
    traffic.assert_none_outside()


def test_an_explanation_opens_in_a_sheet_and_the_translation_inline(
    frontend: Frontend, page: Page
) -> None:
    """설명은 아래에서 올라오는 시트이고, 번역은 시트가 아니라 문장 아래 인라인이다.

    -   시트: `role="dialog"`, `aria-modal`, 제목 `표현 설명`, 칸 이름, 자기평가 질문과 안내, `닫기`.
    -   닫으면 연 표현으로 포커스가 돌아온다(03_UI_UX_SPEC.md의 `설명 시트`).
    -   번역 노드는 누르기 전에 없고, 누른 뒤 시트 밖 `.translation-area`에 생긴다.
    """
    traffic = _watch(page, frontend)
    _open_demo_from_home(page, frontend.url)

    token = page.locator(".sentence .token").first
    token.click()
    sheet = flow.open_sheet(page)
    sheet.locator(".explain").wait_for(state="visible")

    assert sheet.get_attribute("role") == "dialog"
    assert sheet.get_attribute("aria-modal") == "true"
    title_id = sheet.get_attribute("aria-labelledby")
    assert title_id, "시트 제목이 연결되지 않았다"
    expect(page.locator(f"#{title_id}")).to_have_text(SHEET_TITLE)
    expect(sheet.locator(".explain-label")).to_have_text(FIELD_LABELS)
    expect(sheet.locator(".feedback-question")).to_have_text(SELF_REPORT_QUESTION)
    expect(sheet.locator(".feedback-optional")).to_have_text(SELF_REPORT_OPTIONAL)
    expect(sheet.locator(".self-report")).to_have_text([flow.KNOWN, flow.UNCERTAIN, flow.UNKNOWN])
    # 머리는 문장 속 표면형이다.
    expect(sheet.locator(".jp-word")).to_have_text(token.inner_text())

    sheet.locator(".sheet-close", has_text=SHEET_CLOSE).click()
    flow.open_sheet(page).wait_for(state="detached")
    assert page.evaluate("() => document.activeElement?.classList.contains('token')") is True, (
        "시트를 닫았는데 포커스가 연 표현으로 돌아오지 않았다"
    )

    # 번역: 누르기 전에는 노드도 문자열도 없다.
    assert page.locator(".translation").count() == 0
    before = page.content()
    page.locator(".reveal-translation").click()
    translation = page.locator(".translation-area .translation")
    translation.wait_for(state="visible")
    assert translation.inner_text().strip() != ""
    assert translation.inner_text() not in before, "번역이 reveal 전에 이미 문서에 있었다"
    assert page.locator(".sheet .translation").count() == 0, "번역이 시트로 떴다"
    assert page.locator(".sheet-scrim:not(.is-closing)").count() == 0
    traffic.assert_none_outside()


def test_the_demo_flow_runs_end_to_end_without_any_request(frontend: Frontend, page: Page) -> None:
    """설명 / 번역 / probe를 전부 체험하고 요청은 0건이다.

    같은 표현이 두 문장에서 다른 문맥 뜻으로 나오는 단정은 **Wave 2의 3문장 fixture 현재 동작**이다.
    MVP-02의 demo는 새 문맥 재등장을 약속하지 않고 `같은 문장 다시 보기`를 체험시킨다
    (03_UI_UX_SPEC.md의 Demo `체험 요소`). Wave 3 demo 레인이 fixture와 진행 규칙을 바꿀 때 이
    단정을 같은 문장 다시 보기로 바꾼다.
    """
    traffic = _watch(page, frontend)
    _open_demo_from_home(page, frontend.url)

    sentences: list[str] = []
    taps = 0
    probes = 0
    explanations: list[tuple[str, str]] = []

    for _ in range(DEMO_SENTENCE_COUNT):
        page.locator(".sentence").wait_for(state="visible")
        sentences.append(page.locator(".sentence").inner_text())

        tokens = page.locator(".sentence .token")
        for index in range(tokens.count()):
            _tap(page, index)
            # 내용이 실제로 있다. 빈 패널이 뜨는 것은 fixture 결함이다.
            assert _panel_text(page, ".jp-word").strip() != ""
            assert _panel_text(page, ".meaning").strip() != ""
            explanations.append(
                (_panel_text(page, ".canonical-form"), _panel_text(page, ".meaning-context"))
            )
            taps += 1
        flow.close_sheet(page)

        # 번역은 **누른 뒤에** 온다. 누르기 전 문서에 그 문자열이 없어야 한다.
        before = page.content()
        assert page.locator(".translation").count() == 0
        page.locator(".reveal-translation").click()
        page.locator(".translation").wait_for(state="visible")
        translation = page.locator(".translation").inner_text()
        assert translation.strip() != ""
        assert translation not in before, "번역이 reveal 전에 이미 문서에 있었다"

        if page.locator(".probe").count() > 0:
            page.locator(".probe .probe-option").first.click()
            page.locator(".probe-answered").wait_for(state="visible")
            probes += 1

        _next_sentence(page)

    assert len(set(sentences)) == DEMO_SENTENCE_COUNT, f"문장이 겹친다: {sentences}"
    assert taps == DEMO_TAPPABLE_COUNT, f"tappable {taps}개(설명 {taps}개)"
    assert probes == DEMO_PROBE_COUNT

    # Wave 2 fixture 현재 동작: 같은 표현(기본형)이 두 문장에서 다른 문맥 뜻으로 나온다.
    forms = [form for form, _ in explanations]
    repeated = [form for form in forms if forms.count(form) > 1]
    assert repeated, f"같은 표현이 다시 나오지 않았다: {forms}"
    contexts = {meaning for form, meaning in explanations if form == repeated[0]}
    assert len(contexts) > 1, f"같은 표현이 같은 문맥 뜻으로만 나왔다: {contexts}"

    # 마지막 문장 뒤에는 안내와 다시 보기가 남는다(무한 spinner도 오류도 아니다).
    assert page.locator(".notice", has_text=LAST_SENTENCE_NOTICE).count() == 1
    traffic.assert_none_outside()


def test_the_demo_stores_nothing(frontend: Frontend, page: Page) -> None:
    """localStorage / sessionStorage / cookie가 끝까지 0이다. 상태는 메모리에만 있다.

    Wave 2 현재 동작이다. Wave 3 demo 레인이 `nc.demo.v1` 진도 저장을 더하면서 이 단정을 바꾼다.
    """
    traffic = _watch(page, frontend)
    _open_demo_from_home(page, frontend.url)
    for _ in range(DEMO_SENTENCE_COUNT):
        if page.locator(".sentence .token").count() > 0:
            _tap(page, 0)
        _next_sentence(page)

    storage = page.evaluate("() => [localStorage.length, sessionStorage.length, document.cookie]")
    assert storage == [0, 0, ""], f"demo가 저장소를 썼다: {storage}"
    assert page.context.cookies() == [], page.context.cookies()
    traffic.assert_none_outside()


def test_the_demo_has_no_path_to_private_data(frontend: Frontend, page: Page) -> None:
    """demo 화면에는 학습 기록도 계정 데이터로 가는 길이 없다.

    나가는 길은 상단바다. 앱 이름을 누르면 선택 홈이고 요청이 나가지 않는다. `로그인`은 로그인
    진입이라 누를 때만 요청이 나간다(`test_frontend_invariants.py`와 `test_home_browser.py`가 본다).
    """
    traffic = _watch(page, frontend)
    _open_demo_from_home(page, frontend.url)

    assert page.locator(".history-link").count() == 0, "demo에 학습 기록 진입점이 있다"
    assert page.locator(".logout").count() == 0, "demo에 로그아웃이 있다"
    assert page.locator(".screen.history").count() == 0
    assert page.locator(".login-form").count() == 0, "demo 화면 안에 로그인 폼이 있다"

    page.locator(".topbar .topbar-brand").click()
    page.locator(".screen.home").wait_for(state="visible")
    page.wait_for_timeout(_SETTLE_MS)

    assert page.locator(".sentence").count() == 0
    traffic.assert_none_outside()


# --------------------------------------------------------------------------
# backend가 떠 있는 구성
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_the_demo_makes_no_request_even_when_the_backend_is_up(
    e2e_stack: E2EStack, page: Page
) -> None:
    """backend가 살아 있어도 요청은 0건이다.

    죽은 포트에서만 확인하면 "연결이 안 돼서 조용했다"와 "부르지 않았다"를 구분할 수
    없다. 여기서는 **부를 수 있는데도** 부르지 않는 것을 본다. 같은 이유로 abort도
    걸어 둔다 --- 시도 자체가 있으면 `blocked`에 남는다.
    """
    traffic = flow.watch_traffic(
        page, frontend_url=e2e_stack.frontend_url, api_url=e2e_stack.api_url, block=True
    )

    with no_provider_module_import():
        _open_demo_from_home(page, e2e_stack.frontend_url)
        for _ in range(DEMO_SENTENCE_COUNT):
            if page.locator(".sentence .token").count() > 0:
                _tap(page, 0)
                flow.close_sheet(page)
                page.locator(".reveal-translation").click()
                page.locator(".translation").wait_for(state="visible")
            _next_sentence(page)

    traffic.assert_none_outside()
    # 서버 쪽에도 흔적이 없다. demo는 session도 event도 만들지 않는다.
    with e2e_stack.sessions() as db:
        assert _count(db, StudySession) == 0
        assert _count(db, LearningEvent) == 0
        assert _count(db, ItemExposure) == 0


def _count(db: Session, model: type[DeclarativeBase]) -> int:
    return int(db.execute(sa.select(sa.func.count()).select_from(model)).scalar_one())
