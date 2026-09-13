"""후리가나 표시와 토글 (mvp-02-onboarding/12_TEST_PLAN.md의 `Browser E2E`, 13_ACCEPTANCE_CRITERIA.md 16·17·19~21).

휴대폰 viewport로 돈다. Study Screen과 Demo가 같은 설정(`nc.furigana.v1`)을 공유한다.

-   기본은 끔이다. `rt`는 렌더되어 있지만 보이지 않는다.
-   켜면 학습 문장의 `rt`가 보이고, 그 읽기와 밑글자가 DB `sentences.ruby_json`에 저장된 값 그대로다(브라우저가
    계산하지 않는다). `rt`를 뺀 문장 텍스트는 원문이다.
-   설정은 브라우저에 남는다. 새로고침 -> 선택 홈 -> `로그인` -> Study Screen에서도 켜져 있다.
-   토글 자체는 API 요청을 0건 보낸다.
-   켠 상태와 끈 상태에서 같은 흐름(탭·설명·번역·다음 문장)을 밟으면 API 요청 목록과 `learning_events` 종류·건수가
    같다. 후리가나는 학습 신호가 아니다(불변식 16).

Demo 부분은 backend 없이(`frontend` fixture만) 돈다. 읽기의 기준값은 커밋된 demo fixture의 ruby다. Demo에서 켠
설정이 로그인 뒤 Study Screen에서도 켜져 있는지는 backend가 필요하다.

"서버 요청"은 API origin으로 나간 요청이다(정적 자산 제외). 정책값을 단언하지 않으므로 config를 주입하지 않는다.
DB를 쓰는 테스트에만 `integration`을 단다(`test_marker_hygiene.py`).
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Callable, Iterator

import pytest
import sqlalchemy as sa
from playwright.sync_api import Browser, Locator, Page, Playwright, expect

from app.models import ItemExposure, LearningEvent, Sentence
from app.models.enums import EventType
from app.services.auth import hash_password
from tests import factories
from tests.e2e import study_flow as flow
from tests.e2e.conftest import E2EStack, Frontend
from tests.e2e.demo_fixture import DEMO_KEY, read_fixture, ruby_pairs

pytestmark = pytest.mark.e2e

PHONE = "iPhone 13"

# 03_UI_UX_SPEC.md의 `Translation/Furigana` 설정.
FURIGANA_KEY = "nc.furigana.v1"
FURIGANA_ON_CLASS = "furigana-on"

# 늦게 나가는 요청이 드러날 때까지 기다리는 시간. 정책값이 아니다.
_LATE_REQUEST_WINDOW_MS = 2000

# 켬/끔 비교 흐름이 반드시 남기는 event. 이것들이 커밋될 때까지 기다린 뒤 비교한다(fire-and-forget이 있다).
_FLOW_EVENTS = (
    EventType.ITEM_CLICKED,
    EventType.EXPLANATION_REVEALED,
    EventType.TRANSLATION_REVEALED,
    EventType.SENTENCE_COMPLETED,
)

# `rt`를 뺀 문장 텍스트와 `<ruby>`마다 (밑글자, 읽기). DOM 순서다.
_SENTENCE_WITHOUT_RT = """() => {
    const clone = document.querySelector('.sentence').cloneNode(true);
    for (const rt of clone.querySelectorAll('rt')) rt.remove();
    return clone.textContent;
}"""
_RUBY_PAIRS = """() => Array.from(document.querySelectorAll('.sentence ruby')).map((ruby) => {
    const base = Array.from(ruby.childNodes)
        .filter((node) => !(node.nodeType === 1 && node.tagName === 'RT'))
        .map((node) => node.textContent).join('');
    const rt = ruby.querySelector('rt');
    return [base, rt === null ? null : rt.textContent];
})"""


@pytest.fixture
def phone_page(browser: Browser, playwright_driver: Playwright) -> Iterator[Callable[[], Page]]:
    """휴대폰 context의 새 페이지를 만든다. context마다 쿠키·localStorage가 따로다."""
    contexts = []

    def make() -> Page:
        context = browser.new_context(**playwright_driver.devices[PHONE])
        contexts.append(context)
        return context.new_page()

    try:
        yield make
    finally:
        for context in contexts:
            context.close()


def _toggle(page: Page) -> Locator:
    return page.locator(".screen.study .topbar .topbar-actions .furigana-toggle")


def _rts(page: Page) -> Locator:
    return page.locator(".sentence rt")


def _expect_all(rts: Locator, *, visible: bool) -> None:
    count = rts.count()
    assert count > 0, "학습 문장에 rt가 없다 --- 렌더러는 토글과 무관하게 rt를 항상 만든다"
    for index in range(count):
        if visible:
            expect(rts.nth(index)).to_be_visible()
        else:
            expect(rts.nth(index)).to_be_hidden()


def _stored_ruby(stack: E2EStack, learner: flow.Learner) -> tuple[str, list[tuple[str, str]]]:
    """화면에 떠 있는 문장의 원문과 `ruby_json`의 (밑글자, 읽기). code point offset이다."""
    presentation = flow.open_presentation(stack, learner)
    assert presentation is not None
    with flow.read_db(stack) as db:
        sentence = db.get(Sentence, presentation.sentence_id)
        assert sentence is not None
        japanese, ruby_json = sentence.japanese, sentence.ruby_json
    assert ruby_json is not None, "seed 적재가 이 문장의 ruby를 계산하지 않았다(전제)"
    spans = sorted(ruby_json["spans"], key=lambda span: (span[0], span[1]))
    assert spans, "이 문장에 저장된 읽기가 없다(전제) --- 한자가 있는 fixture 문장이어야 한다"
    return japanese, [(japanese[start:end], reading) for start, end, reading in spans]


def _local_storage(page: Page) -> dict[str, str]:
    entries: dict[str, str] = page.evaluate(
        "() => Object.fromEntries(Object.keys(localStorage).map((k) => [k, localStorage.getItem(k)]))"
    )
    return entries


def _add_learner(stack: E2EStack) -> flow.Learner:
    """seed가 이미 적재된 DB에 사용자 한 명을 더한다."""
    with stack.sessions() as db:
        user = factories.make_user(db)
        user.password_hash = hash_password(flow.PASSWORD)
        db.commit()
        return flow.Learner(user_id=user.id, login_id=user.login_id)


# --------------------------------------------------------------------------
# 기본 끔, 켜면 저장된 읽기, 토글 요청 0
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_furigana_is_off_by_default_and_shows_the_stored_reading_when_on(
    e2e_stack: E2EStack, phone_page: Callable[[], Page]
) -> None:
    stack = e2e_stack
    learner = flow.seed_and_create_user(stack)
    page = phone_page()
    traffic = flow.watch_traffic(
        page, frontend_url=stack.frontend_url, api_url=stack.api_url, block=False
    )
    flow.sign_in(page, stack, learner)
    japanese, stored = _stored_ruby(stack, learner)

    # 기본 끔: 저장값이 없고 토글이 눌리지 않았고 rt는 있지만 보이지 않는다.
    toggle = _toggle(page)
    expect(toggle).to_have_attribute("aria-pressed", "false")
    assert FURIGANA_KEY not in _local_storage(page)
    _expect_all(_rts(page), visible=False)
    sentence = page.locator(".sentence")

    # 켬. 요청 0건. 로그인 흐름의 늦은 요청이 섞이지 않도록 먼저 잦아들기를 기다린다.
    page.wait_for_timeout(_LATE_REQUEST_WINDOW_MS)
    calls_before = list(traffic.api_calls)
    page.evaluate("() => { window.__ncSentence = document.querySelector('.sentence'); }")
    toggle.click()
    expect(toggle).to_have_attribute("aria-pressed", "true")
    _expect_all(_rts(page), visible=True)

    # 화면이 읽기를 계산하지 않는다: 밑글자와 읽기가 DB의 ruby_json 그대로다.
    assert [tuple(pair) for pair in page.evaluate(_RUBY_PAIRS)] == stored
    assert page.evaluate(_SENTENCE_WITHOUT_RT) == japanese
    expect(sentence).to_have_attribute("aria-label", japanese)
    # 문서 class 전환이지 문장 재렌더가 아니다.
    assert page.evaluate(
        f"() => document.documentElement.classList.contains('{FURIGANA_ON_CLASS}')"
    )
    assert page.evaluate("() => window.__ncSentence === document.querySelector('.sentence')")

    # 끔으로 되돌린다. 역시 요청 0건.
    toggle.click()
    expect(toggle).to_have_attribute("aria-pressed", "false")
    _expect_all(_rts(page), visible=False)

    page.wait_for_timeout(_LATE_REQUEST_WINDOW_MS)
    assert traffic.api_calls == calls_before, (
        f"토글이 API를 불렀다: {traffic.api_calls[len(calls_before) :]}"
    )


# --------------------------------------------------------------------------
# 설정 유지: 새로고침 -> 선택 홈 -> 로그인 -> Study
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_the_setting_survives_reload_and_login(
    e2e_stack: E2EStack, phone_page: Callable[[], Page]
) -> None:
    stack = e2e_stack
    learner = flow.seed_and_create_user(stack)
    page = phone_page()
    flow.sign_in(page, stack, learner)

    _toggle(page).click()
    expect(_toggle(page)).to_have_attribute("aria-pressed", "true")

    # 로그인 영역에는 hash가 없어 새로고침하면 선택 홈이다. `로그인`을 누르면 곧바로 Study Screen이다.
    assert flow.reopen(page, stack, learner) is not None
    flow.wait_for_sentence(page)
    expect(_toggle(page)).to_have_attribute("aria-pressed", "true")
    _expect_all(_rts(page), visible=True)

    # 설정은 이 key 하나에만 있다.
    stored = _local_storage(page)
    assert list(stored) == [FURIGANA_KEY], stored
    assert json.loads(stored[FURIGANA_KEY]) == {"on": True}


# --------------------------------------------------------------------------
# 켬/끔 같은 흐름 -> 같은 요청, 같은 event (불변식 16, AC 21)
# --------------------------------------------------------------------------


def _run_flow(
    page: Page, stack: E2EStack, learner: flow.Learner, *, furigana_on: bool
) -> list[str]:
    """로그인 -> (켬이면 토글) -> 탭·설명 -> 번역 -> 다음 문장. API 요청을 `METHOD /path{id}` 모양으로 돌려준다."""
    traffic = flow.watch_traffic(
        page, frontend_url=stack.frontend_url, api_url=stack.api_url, block=False
    )
    flow.sign_in(page, stack, learner)
    if furigana_on:
        _toggle(page).click()
        _expect_all(_rts(page), visible=True)
    expect(_toggle(page)).to_have_attribute("aria-pressed", "true" if furigana_on else "false")

    flow.tap(page, 0)
    flow.reveal_translation(page)
    assert flow.press_next(page, stack, learner) is not None, "다음 문장이 없다(전제)"

    _wait_for_flow_events(stack, learner)
    page.wait_for_timeout(_LATE_REQUEST_WINDOW_MS)
    return [re.sub(r"/\d+(?=/|$|\?)", "/{id}", call) for call in traffic.api_calls]


def _event_counts(stack: E2EStack, learner: flow.Learner) -> Counter[EventType]:
    with flow.read_db(stack) as db:
        rows = db.execute(
            sa.select(LearningEvent.event_type).where(LearningEvent.user_id == learner.user_id)
        ).scalars()
        return Counter(rows)


def _exposure_count(stack: E2EStack, learner: flow.Learner) -> int:
    with flow.read_db(stack) as db:
        return int(
            db.execute(
                sa.select(sa.func.count(ItemExposure.id)).where(
                    ItemExposure.user_id == learner.user_id
                )
            ).scalar_one()
        )


def _wait_for_flow_events(stack: E2EStack, learner: flow.Learner) -> None:
    flow._poll(
        lambda: True if all(_event_counts(stack, learner)[kind] for kind in _FLOW_EVENTS) else None,
        what=f"흐름 event {[kind.value for kind in _FLOW_EVENTS]}",
    )


@pytest.mark.integration
def test_the_same_flow_sends_the_same_requests_and_events_with_furigana_on_or_off(
    e2e_stack: E2EStack, phone_page: Callable[[], Page]
) -> None:
    stack = e2e_stack
    off_learner = flow.seed_and_create_user(stack)
    on_learner = _add_learner(stack)

    off_calls = _run_flow(phone_page(), stack, off_learner, furigana_on=False)
    on_calls = _run_flow(phone_page(), stack, on_learner, furigana_on=True)

    # 흐름이 실제로 서버를 밟았다(빈 목록끼리 같아서 통과하는 것을 막는다).
    assert any(call.endswith("/click") for call in off_calls), off_calls
    assert any(call.endswith("/translation/reveal") for call in off_calls), off_calls

    assert on_calls == off_calls
    off_events = _event_counts(stack, off_learner)
    on_events = _event_counts(stack, on_learner)
    assert on_events == off_events, {"off": off_events, "on": on_events}
    assert _exposure_count(stack, on_learner) == _exposure_count(stack, off_learner)


# --------------------------------------------------------------------------
# Demo: 기본 끔, 켜면 fixture의 읽기, 새로고침 유지, 토글 요청 0 (backend 없음)
# --------------------------------------------------------------------------

DEMO_URL_HASH = "#/demo"
DEMO_CARD_TITLE = "표현 학습 체험해 보기"


def _demo_toggle(page: Page) -> Locator:
    return page.locator(".screen.demo .topbar .topbar-actions .furigana-toggle")


def test_demo_furigana_is_off_by_default_and_shows_the_fixture_reading_when_on(
    frontend: Frontend, phone_page: Callable[[], Page]
) -> None:
    """Demo도 Study Screen과 같은 규칙이다. 읽기는 fixture에 저장된 ruby 그대로이고 브라우저가 계산하지 않는다."""
    _, sentences = read_fixture()
    first = sentences[0]["presentation"]
    stored = ruby_pairs(sentences[0])
    assert stored, "첫 demo 문장에 읽기가 없다(전제)"

    page = phone_page()
    traffic = flow.watch_traffic(
        page, frontend_url=frontend.url, api_url=frontend.api_url, block=True
    )
    page.goto(f"{frontend.url}/{DEMO_URL_HASH}")
    page.locator(".screen.demo .sentence").wait_for(state="visible")

    # 기본 끔.
    toggle = _demo_toggle(page)
    expect(toggle).to_have_attribute("aria-pressed", "false")
    assert FURIGANA_KEY not in _local_storage(page)
    _expect_all(_rts(page), visible=False)

    # 켬. 문서 class 전환이지 문장 재렌더가 아니다.
    page.evaluate("() => { window.__ncSentence = document.querySelector('.sentence'); }")
    toggle.click()
    expect(toggle).to_have_attribute("aria-pressed", "true")
    _expect_all(_rts(page), visible=True)
    assert [tuple(pair) for pair in page.evaluate(_RUBY_PAIRS)] == stored
    assert page.evaluate(_SENTENCE_WITHOUT_RT) == first["japanese"]
    expect(page.locator(".sentence")).to_have_attribute("aria-label", first["japanese"])
    assert page.evaluate("() => window.__ncSentence === document.querySelector('.sentence')")
    assert json.loads(_local_storage(page)[FURIGANA_KEY]) == {"on": True}

    # 새로고침해도 켜져 있다.
    page.reload()
    page.locator(".screen.demo .sentence").wait_for(state="visible")
    expect(_demo_toggle(page)).to_have_attribute("aria-pressed", "true")
    _expect_all(_rts(page), visible=True)

    # 끔도 유지된다.
    _demo_toggle(page).click()
    expect(_demo_toggle(page)).to_have_attribute("aria-pressed", "false")
    page.reload()
    page.locator(".screen.demo .sentence").wait_for(state="visible")
    expect(_demo_toggle(page)).to_have_attribute("aria-pressed", "false")
    _expect_all(_rts(page), visible=False)

    # 토글은 진도가 아니다. demo 진도 key가 생기지 않았다.
    assert DEMO_KEY not in _local_storage(page)
    page.wait_for_timeout(_LATE_REQUEST_WINDOW_MS)
    traffic.assert_none_outside()
    assert traffic.api_calls == []


# --------------------------------------------------------------------------
# Demo에서 켠 설정 -> 로그인 -> Study, Study에서 끈 설정 -> Demo
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_the_setting_is_shared_between_the_demo_and_study(
    e2e_stack: E2EStack, phone_page: Callable[[], Page]
) -> None:
    stack = e2e_stack
    learner = flow.seed_and_create_user(stack)
    page = phone_page()
    traffic = flow.watch_traffic(
        page, frontend_url=stack.frontend_url, api_url=stack.api_url, block=False
    )

    page.goto(f"{stack.frontend_url}/{DEMO_URL_HASH}")
    page.locator(".screen.demo .sentence").wait_for(state="visible")
    _demo_toggle(page).click()
    expect(_demo_toggle(page)).to_have_attribute("aria-pressed", "true")
    page.wait_for_timeout(_LATE_REQUEST_WINDOW_MS)
    assert traffic.api_calls == [], f"Demo 토글이 API를 불렀다: {traffic.api_calls}"

    # Demo 상단바의 `로그인`으로 들어간다.
    flow.press_topbar_login(page)
    page.locator(".login-form").wait_for(
        state="visible", timeout=flow.SETTLE_TIMEOUT_SECONDS * 1000
    )
    page.locator("#login-id").fill(learner.login_id)
    page.locator("#password").fill(flow.PASSWORD)
    page.locator(".login-form button[type=submit]").click()
    flow.wait_for_sentence(page)
    assert page.locator(".screen.demo").count() == 0

    expect(_toggle(page)).to_have_attribute("aria-pressed", "true")
    _expect_all(_rts(page), visible=True)

    # Study에서 끄면 Demo에서도 꺼져 있다.
    _toggle(page).click()
    expect(_toggle(page)).to_have_attribute("aria-pressed", "false")
    page.locator(".topbar .topbar-brand").click()
    page.locator(".screen.home").wait_for(state="visible")
    page.locator(".home-card", has_text=DEMO_CARD_TITLE).click()
    page.locator(".screen.demo .sentence").wait_for(state="visible")
    expect(_demo_toggle(page)).to_have_attribute("aria-pressed", "false")
    _expect_all(_rts(page), visible=False)

    stored = _local_storage(page)
    assert json.loads(stored[FURIGANA_KEY]) == {"on": False}
