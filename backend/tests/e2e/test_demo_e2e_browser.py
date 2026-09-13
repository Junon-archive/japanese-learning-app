"""Demo E2E (12_TEST_PLAN.md의 `Demo E2E`, mvp-02-onboarding/12_TEST_PLAN.md의 `Browser E2E`, 합격 기준 12·39~42).

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

진행 규칙(`03_UI_UX_SPEC.md`의 `Demo` > `진행 규칙`): demo는 새 문맥 재등장이 아니라 **같은 문장 다시
보기**를 체험시킨다. 진도는 `nc.demo.v1`에 남아 새로고침 뒤에도 이어진다. 문장 수는 커밋된 fixture에서,
간격은 `constants.ts`에서 읽는다(`demo_fixture.py`). 휴대폰 viewport로 돈다.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
import sqlalchemy as sa
from playwright.sync_api import Browser, Page, Playwright, expect
from sqlalchemy.orm import DeclarativeBase, Session

from app.models import ItemExposure, LearningEvent, StudySession
from tests.conftest import no_provider_module_import
from tests.e2e import study_flow as flow
from tests.e2e.conftest import E2EStack, Frontend
from tests.e2e.demo_fixture import (
    DEMO_KEY,
    FURIGANA_KEY,
    demo_constant,
    expression_of,
    read_fixture,
)

pytestmark = pytest.mark.e2e

PHONE = "iPhone 13"
DEMO_ROUTE = "#/demo"

FIXTURE_ID, SENTENCES = read_fixture()
TOTAL = len(SENTENCES)
REVIEW_AFTER = demo_constant("DEMO_REVIEW_AFTER_SENTENCES")
PROBE_EVERY = demo_constant("DEMO_PROBE_EVERY_SENTENCES")

# 화면 문구(03_UI_UX_SPEC.md의 `화면 문구 표`). 사용자가 실제로 읽고 누르는 글자다.
DEMO_CARD_TITLE = "표현 학습 체험해 보기"
DEMO_TITLE = "표현 학습 체험"
DEMO_BANNER = "체험 중이에요. 기록은 이 브라우저에만 남아요."
RESET_LABEL = "진도 초기화"
FURIGANA_LABEL = "후리가나"
SHEET_TITLE = "표현 설명"
SHEET_CLOSE = "닫기"
FIELD_LABELS = ["뜻", "이 문장에서", "느낌", "예문"]
SELF_REPORT_QUESTION = "이 표현, 알고 있었나요?"
SELF_REPORT_OPTIONAL = "고르지 않아도 괜찮아요."
TRANSLATION_BUTTON = "문장 뜻 보기"
NEXT_LABEL = "다음 문장"
HINT_TEXT = "모르는 표현을 눌러 보세요."
PROBE_PROMPT = "이 표현을 알고 계세요?"
PROBE_OPTIONS = [flow.KNOWN, flow.UNCERTAIN, flow.UNKNOWN, "건너뛰기"]
COMPLETE_TITLE = f"{TOTAL}문장을 모두 봤어요."
COMPLETE_THANKS = "끝까지 둘러봐 주셔서 고마워요."
LEARN_KANA = "글자 배우기"
RESTART = "처음부터 다시"
RESTART_NOTE = "처음부터 다시 하면 체험 기록이 지워져요."
KANA_HASH = "#/kana"

_SETTLE_MS = 300


@pytest.fixture
def page(browser: Browser, playwright_driver: Playwright) -> Iterator[Page]:
    """휴대폰 context의 페이지. context마다 쿠키·localStorage가 따로다."""
    context = browser.new_context(**playwright_driver.devices[PHONE])
    try:
        yield context.new_page()
    finally:
        context.close()


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


def _japanese(index: int) -> str:
    japanese = SENTENCES[index]["presentation"]["japanese"]
    assert isinstance(japanese, str)
    return japanese


def _expect_sentence(page: Page, index: int) -> None:
    expect(page.locator(".screen.demo .sentence")).to_have_attribute("aria-label", _japanese(index))


def _expect_progress(page: Page, seen: int) -> None:
    expect(page.locator(".screen.demo .demo-progress")).to_have_text(f"{seen} / {TOTAL}")


def _next_sentence(page: Page) -> None:
    flow.close_sheet(page)
    page.locator("button.next").click()


def _tap(page: Page, index: int) -> None:
    flow.close_sheet(page)
    page.locator(".sentence .token").nth(index).click()
    flow.open_sheet(page).locator(".explain").wait_for(state="visible")


def _self_report(page: Page, label: str) -> None:
    """열린 설명 시트의 자기평가. 닫히는 중인 앞 시트의 버튼과 섞이지 않게 열린 시트 안에서만 찾는다."""
    sheet = flow.open_sheet(page)
    sheet.locator(".self-report", has_text=label).click()
    sheet.locator(".feedback-done").wait_for(state="visible")


def _local_storage(page: Page) -> dict[str, str]:
    entries: dict[str, str] = page.evaluate(
        "() => Object.fromEntries(Object.keys(localStorage).map((k) => [k, localStorage.getItem(k)]))"
    )
    return entries


def _first_probe_item(self_reported: int) -> tuple[int, int]:
    """체크포인트에서 물을 표현과 그 표현이 처음 나온 문장. 먼저 본 순서, 자기평가한 표현은 뺀다."""
    for index in range(PROBE_EVERY - 1):
        for item in SENTENCES[index]["presentation"]["tappable_items"]:
            learning_item_id = item["learning_item_id"]
            assert isinstance(learning_item_id, int)
            if learning_item_id != self_reported:
                return learning_item_id, index
    raise AssertionError("체크포인트 앞 문장에 물을 표현이 없다(전제)")


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
    """카드로 들어간 demo의 상단바·제목·안내·진행·버튼 문구가 `화면 문구 표`와 같다."""
    traffic = _watch(page, frontend)
    _open_demo_from_home(page, frontend.url)

    screen = page.locator(".screen.demo")
    expect(screen.locator(".topbar .topbar-brand")).to_have_text("Nihongo Context")
    expect(screen.locator(".topbar .topbar-actions button")).to_have_text(
        [FURIGANA_LABEL, flow.LOGIN_LABEL]
    )
    expect(screen.locator("h1")).to_have_text(DEMO_TITLE)
    expect(screen.locator(".demo-banner")).to_contain_text(DEMO_BANNER)
    expect(screen.locator(".demo-banner button")).to_have_text([RESET_LABEL])
    # 진행 표시는 `본 문장 수 / 전체 문장 수` 하나다. 12분 진행바가 없다.
    _expect_progress(page, 1)
    assert screen.locator(".progress-bar").count() == 0
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


def test_the_demo_reviews_the_same_sentence_and_asks_a_probe_without_any_request(
    frontend: Frontend, page: Page
) -> None:
    """카드 -> 설명 시트 -> 인라인 번역 -> 몰랐음 -> 새 문장 `DEMO_REVIEW_AFTER_SENTENCES`개 -> 같은 문장 -> probe.

    새로고침해도 같은 문장과 진행 표시다. 저장은 `nc.demo.v1`(토글을 켜면 `nc.furigana.v1`)뿐이고
    sessionStorage와 cookie는 비어 있다. 요청은 0건이다.
    """
    assert REVIEW_AFTER + 1 < PROBE_EVERY, (
        "이 시나리오는 다시 보기가 첫 probe 체크포인트보다 먼저 온다(전제)"
    )
    traffic = _watch(page, frontend)
    _open_demo_from_home(page, frontend.url)
    first = SENTENCES[0]
    _expect_sentence(page, 0)
    _expect_progress(page, 1)

    # 설명 시트에서 몰랐음. 이 문장이 다시 보기 대기열에 들어간다.
    _tap(page, 0)
    _self_report(page, flow.UNKNOWN)
    self_reported = first["presentation"]["tappable_items"][0]["learning_item_id"]

    # 번역은 시트가 아니라 문장 아래 인라인이다.
    flow.close_sheet(page)
    assert page.locator(".translation").count() == 0
    page.locator(".reveal-translation").click()
    expect(page.locator(".translation-area .translation")).to_have_text(first["korean_translation"])

    for index in range(1, REVIEW_AFTER + 1):
        _next_sentence(page)
        _expect_sentence(page, index)
        _expect_progress(page, index + 1)
        assert page.locator(".probe").count() == 0

    # 같은 문장 다시 보기. 본 문장 수는 그대로다.
    _next_sentence(page)
    _expect_sentence(page, 0)
    _expect_progress(page, REVIEW_AFTER + 1)

    # 새로고침 뒤 같은 위치.
    page.reload()
    page.locator(".screen.demo .sentence").wait_for(state="visible")
    _expect_sentence(page, 0)
    _expect_progress(page, REVIEW_AFTER + 1)
    assert list(_local_storage(page)) == [DEMO_KEY]
    stored = json.loads(_local_storage(page)[DEMO_KEY])
    assert stored["fixtureId"] == FIXTURE_ID
    assert page.evaluate("() => [sessionStorage.length, document.cookie]") == [0, ""]
    assert page.context.cookies() == []

    # 다음 체크포인트까지. 새 문장이 fixture 순서로 이어진다.
    for seen in range(REVIEW_AFTER + 2, PROBE_EVERY + 1):
        assert page.locator(".probe").count() == 0
        _next_sentence(page)
        _expect_sentence(page, seen - 1)
        _expect_progress(page, seen)

    item, item_sentence = _first_probe_item(self_reported)
    probe = page.locator(".probe")
    expect(probe.locator(".probe-prompt")).to_have_text(PROBE_PROMPT)
    expect(probe.locator(".probe-expression")).to_have_text(
        expression_of(SENTENCES[item_sentence], item)
    )
    expect(probe.locator(".probe-option")).to_have_text(PROBE_OPTIONS)
    probe.locator(".probe-option", has_text=flow.UNKNOWN).click()
    probe.locator(".probe-answered").wait_for(state="visible")
    assert [record["item"] for record in json.loads(_local_storage(page)[DEMO_KEY])["probed"]] == [
        item
    ]

    # 후리가나를 켜면 그 설정 key 하나가 더해진다.
    page.locator(".screen.demo .topbar .furigana-toggle").click()
    expect(page.locator(".screen.demo .topbar .furigana-toggle")).to_have_attribute(
        "aria-pressed", "true"
    )
    assert sorted(_local_storage(page)) == sorted([DEMO_KEY, FURIGANA_KEY])
    assert page.evaluate("() => [sessionStorage.length, document.cookie]") == [0, ""]
    assert page.context.cookies() == []

    page.wait_for_timeout(_SETTLE_MS)
    traffic.assert_none_outside()
    assert traffic.api_calls == []


_COMPLETION_INIT = """(value) => {
    window.__ncHashChanges = [];
    window.addEventListener('hashchange', (event) => { window.__ncHashChanges.push(event.newURL); });
    if (localStorage.getItem('nc.demo.v1') === null) localStorage.setItem('nc.demo.v1', value);
}"""


def test_the_completion_screen_leads_to_kana_without_any_request(
    frontend: Frontend, page: Page
) -> None:
    """완료 직전 진도(저장 형식에 맞춘 값)를 넣고 마지막 `다음 문장`을 누르면 완료 화면이다.

    `글자 배우기`는 `#/kana`로 간다. 가나 route가 아직 없는 브랜치에서는 router가 곧바로 `#/`로 바꾸므로
    URL이 아니라 기록한 `hashchange`의 newURL로 단정한다.
    """
    before_end: dict[str, Any] = {
        "fixtureId": FIXTURE_ID,
        "position": TOTAL - 1,
        "seen": TOTAL,
        "selfReports": {},
        "probed": [],
        "queue": [],
        "reviewed": [],
    }
    page.add_init_script(f"({_COMPLETION_INIT})({json.dumps(json.dumps(before_end))})")
    traffic = _watch(page, frontend)

    page.goto(f"{frontend.url}/{DEMO_ROUTE}")
    page.locator(".screen.demo .sentence").wait_for(state="visible")
    _expect_sentence(page, TOTAL - 1)
    _expect_progress(page, TOTAL)

    _next_sentence(page)

    screen = page.locator(".screen.demo")
    expect(screen.locator("h1")).to_have_text(COMPLETE_TITLE)
    expect(screen).to_contain_text(COMPLETE_THANKS)
    expect(screen).to_contain_text(RESTART_NOTE)
    assert screen.locator(".sentence").count() == 0
    expect(page.locator(".screen.demo > :not(.topbar) button")).to_have_text([LEARN_KANA, RESTART])
    # 완료 화면에는 문장이 없으므로 상단바 오른쪽은 `로그인`뿐이다(W3-6).
    expect(screen.locator(".topbar .topbar-actions button")).to_have_text([flow.LOGIN_LABEL])

    screen.locator("button", has_text=LEARN_KANA).click()
    page.wait_for_function("() => window.__ncHashChanges.length > 0")
    changes: list[str] = page.evaluate("() => window.__ncHashChanges")
    assert changes[-1].endswith(KANA_HASH), changes

    page.wait_for_timeout(_SETTLE_MS)
    traffic.assert_none_outside()
    assert traffic.api_calls == []


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
        _tap(page, 0)
        _self_report(page, flow.UNKNOWN)
        flow.close_sheet(page)
        page.locator(".reveal-translation").click()
        page.locator(".translation").wait_for(state="visible")
        # 새 문장들을 지나 같은 문장 다시 보기까지.
        for _ in range(REVIEW_AFTER + 1):
            _next_sentence(page)
        _expect_sentence(page, 0)
        page.wait_for_timeout(_SETTLE_MS)

    traffic.assert_none_outside()
    # 서버 쪽에도 흔적이 없다. demo는 session도 event도 만들지 않는다.
    with e2e_stack.sessions() as db:
        assert _count(db, StudySession) == 0
        assert _count(db, LearningEvent) == 0
        assert _count(db, ItemExposure) == 0


def _count(db: Session, model: type[DeclarativeBase]) -> int:
    return int(db.execute(sa.select(sa.func.count()).select_from(model)).scalar_one())
