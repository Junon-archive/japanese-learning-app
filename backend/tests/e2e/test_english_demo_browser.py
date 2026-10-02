"""영어 Demo E2E (mvp-03-english/12_TEST_PLAN.md의 `E2E (browser)`, 합격 기준 22~27).

일본어 쪽은 `test_demo_e2e_browser.py`가 본다. 여기서는 **영어 demo에서만 갈리는 것**을 본다.
구조와 하네스(backend를 띄우지 않는 기본 구성, `watch_traffic` 두 겹)는 그 파일과 같고, 화면을
미는 도우미는 `study_flow`를 공유한다.

갈리는 지점:

1.  **재생 버튼을 눌러도 frontend origin 밖 요청이 0건이다**(불변식 24의 e2e backstop). 소스
    필터(`ui/speech.ts`가 `localService === true`만 고른다)는 "코드가 그렇게 쓰여 있다"까지만
    말한다. 네트워크 음성을 쓰면 브라우저가 제3자 서버로 합성 요청을 보내고, 그것은 DOM에
    아무 흔적을 남기지 않는다 --- **결과로 받칠 곳이 여기뿐이다.**
2.  **로컬 영어 음성이 없는 브라우저에서는 버튼이 없다.** 그때 skip하지 않는다 --- "버튼이
    없다"를 단언하고 **어느 분기로 통과했는지 출력에 남긴다**(`--capture=tee-sys`). 두 분기를
    서로 묶어 둔다: 음성이 있는데 버튼이 없거나 음성이 없는데 버튼이 있으면 실패다.
3.  **설명 시트에 reading 줄이 없다**(합격 기준 24). 빈 줄이나 `-`가 아니라 **줄 자체가 없다.**
    양성 대조군으로 같은 측정을 일본어 demo에 해서 그 줄이 거기엔 있는 것을 본다 --- 없으면 이
    단언은 선택자 오타만으로도 초록이 된다.
4.  **상단바에 후리가나 토글이 없고**(영어 fixture의 ruby가 비어 있다) 완료 화면에 `글자 배우기`가
    없다(가나 학습에 대응하는 영어 화면이 없다, ADR-025 결정 2).
5.  **두 demo의 진도가 섞이지 않는다**(불변식 18, ADR-025 결정 3). 영어를 끝까지 보고 새로고침해도
    일본어 demo는 처음부터다.

문장 수와 fixture 식별자는 커밋된 생성 파일에서 읽는다(`demo_fixture.py`). 숫자를 테스트에
복사하지 않는다.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from playwright.sync_api import Browser, Page, Playwright, expect

from tests.e2e import study_flow as flow
from tests.e2e.conftest import Frontend
from tests.e2e.demo_fixture import DEMO_KEYS, read_fixture

pytestmark = pytest.mark.e2e

PHONE = "iPhone 13"

EN_DEMO_ROUTE = "#/en/demo"
JA_DEMO_ROUTE = "#/ja/demo"

EN_KEY = DEMO_KEYS["en"]
JA_KEY = DEMO_KEYS["ja"]

EN_FIXTURE_ID, EN_SENTENCES = read_fixture("en")
JA_FIXTURE_ID, JA_SENTENCES = read_fixture("ja")
EN_TOTAL = len(EN_SENTENCES)
JA_TOTAL = len(JA_SENTENCES)

# 화면 문구(03_UI_UX_SPEC.md의 `화면 문구 표`). 사용자가 실제로 읽고 누르는 글자다.
DEMO_TITLE = "표현 학습 체험"
FURIGANA_LABEL = "후리가나"
FIELD_LABELS = ["뜻", "이 문장에서", "느낌", "예문"]
LEARN_KANA = "글자 배우기"
RESTART = "처음부터 다시"
COMPLETE_TITLE = f"{EN_TOTAL}문장을 모두 봤어요."

# 늦게 나가는 요청(타이머, 늦게 온 `voiceschanged`)이 드러날 때까지 기다리는 시간. 정책값이 아니다.
_LATE_REQUEST_WINDOW_MS = 2000

# 문장 옆과 설명 시트 예문 옆. 재생 버튼이 있을 수 있는 자리 전부다(상단바·번역에는 없다).
_SENTENCE_SPEAK = ".screen.demo .sentence-box"
_EXAMPLE_SPEAK = ".screen.demo .sheet .explain"

_LOCAL_ENGLISH_VOICES = """() => {
    if (typeof speechSynthesis === 'undefined') return [];
    return speechSynthesis
        .getVoices()
        .filter((voice) => voice.localService && voice.lang.startsWith('en'))
        .map((voice) => voice.lang);
}"""


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


def _sentence_text(sentences: list[dict[str, Any]], index: int) -> str:
    text = sentences[index]["presentation"]["text"]
    assert isinstance(text, str)
    return text


# 두 fixture의 첫 문장. 어느 언어의 화면이 떠 있는지 가르는 값이다.
EN_FIRST = _sentence_text(EN_SENTENCES, 0)
JA_FIRST = _sentence_text(JA_SENTENCES, 0)


def _open_demo(page: Page, frontend: Frontend, route: str, expected_sentence: str) -> None:
    """demo route를 열고 **그 문장이 그 화면에 하나만 있을 때까지** 기다린다.

    hash만 다른 주소로 `goto`하면 같은 문서 안에서의 이동이라, 떠나는 화면이 전환이 끝날 때까지
    DOM에 남고 들어오는 화면은 동적 import를 기다린다. 그 사이에는 `.screen.demo`가 **앞 화면
    하나뿐**이라서 "화면이 하나다"와 "문장이 보인다"만으로는 앞 화면을 보고 통과한다
    (영어 화면을 일본어 화면으로 착각한다). 그래서 문장 자체로 기다린다.
    """
    page.goto(f"{frontend.url}/{route}")
    expect(page.locator(".screen.demo .sentence")).to_have_attribute(
        "aria-label", expected_sentence, timeout=int(flow.SETTLE_TIMEOUT_SECONDS * 1000)
    )
    expect(page.locator(".screen.demo")).to_have_count(1)


def _local_english_voices(page: Page) -> list[str]:
    """이 브라우저가 쓸 수 있는 로컬 영어 음성의 `lang` 목록(`ui/speech.ts`의 `pickVoice`와 같은 조건)."""
    voices: list[str] = page.evaluate(_LOCAL_ENGLISH_VOICES)
    return voices


def _press_speak(page: Page, container: str, where: str) -> bool:
    """`container`의 재생 버튼을 누르고 어느 분기였는지 출력한다.

    두 분기를 음성 목록과 묶어 둔다. 음성이 있는데 버튼이 없으면 버튼을 그리지 않는 회귀이고,
    음성이 없는데 버튼이 있으면 `localService` 필터가 빠진 것이다(변이 검증 24).
    """
    pressed = flow.press_speak_if_available(page, container)
    voices = _local_english_voices(page)
    # 어느 분기로 통과했는지 출력에 남긴다(`--capture=tee-sys`). skip하지 않으므로 이것이 유일한 기록이다.
    button = "있음" if pressed else "없음"
    found = ", ".join(voices) or "없음"
    print(f"[speech] {where}: 버튼 {button}, 로컬 영어 음성 {found}")  # noqa: T201
    if pressed:
        assert voices != [], f"{where}: 재생 버튼이 있는데 쓸 수 있는 로컬 영어 음성이 없다"
    else:
        assert voices == [], f"{where}: 로컬 영어 음성이 있는데 재생 버튼이 없다: {voices}"
    return pressed


def _local_storage(page: Page) -> dict[str, str]:
    entries: dict[str, str] = page.evaluate(
        "() => Object.fromEntries(Object.keys(localStorage).map((k) => [k, localStorage.getItem(k)]))"
    )
    return entries


def _progress(page: Page) -> str:
    return page.locator(".screen.demo .demo-progress").inner_text()


def _topbar_right(page: Page) -> list[str]:
    return page.locator(".screen.demo .topbar .topbar-actions button").all_inner_texts()


# --------------------------------------------------------------------------
# 열림과 기본 흐름
# --------------------------------------------------------------------------


def test_the_english_demo_opens_with_no_backend_running(frontend: Frontend, page: Page) -> None:
    """API origin에 아무도 listen하지 않는 상태에서 `#/en/demo`가 열리고 상단바에 후리가나 토글이 없다.

    영어 fixture의 `render_segments[].ruby`는 전부 비어 있으므로(ADR-023 결정 6) 토글이 할 일이
    없다. 토글을 공유 engine이 무조건 그리면 여기서 빨개진다(합격 기준 24).
    """
    traffic = _watch(page, frontend)
    _open_demo(page, frontend, EN_DEMO_ROUTE, EN_FIRST)

    screen = page.locator(".screen.demo")
    expect(screen.locator("h1")).to_have_text(DEMO_TITLE)
    assert _topbar_right(page) == [flow.LOGIN_LABEL], _topbar_right(page)
    assert FURIGANA_LABEL not in _topbar_right(page)
    assert screen.locator(".sentence rt").count() == 0, "영어 문장에 ruby가 그려졌다"
    assert page.locator(".login-form").count() == 0, "demo가 로그인 화면으로 떨어졌다"
    assert page.locator(".notice-slot .notice").count() == 0, "demo가 오류 안내를 띄웠다"

    page.wait_for_timeout(_LATE_REQUEST_WINDOW_MS)
    traffic.assert_none_outside()
    assert traffic.api_calls == []


def test_the_english_demo_runs_a_sentence_without_any_request(
    frontend: Frontend, page: Page
) -> None:
    """탭 -> 설명 시트 -> 인라인 번역 -> 다음 문장. 요청은 0건이고 저장은 영어 진도 key 하나다."""
    traffic = _watch(page, frontend)
    _open_demo(page, frontend, EN_DEMO_ROUTE, EN_FIRST)

    first = EN_SENTENCES[0]
    expect(page.locator(".screen.demo .sentence")).to_have_attribute(
        "aria-label", str(first["presentation"]["text"])
    )
    expect(page.locator(".screen.demo .demo-progress")).to_have_text(f"1 / {EN_TOTAL}")

    flow.tap(page, 0)
    sheet = flow.open_sheet(page)
    expect(sheet.locator(".explain-label")).to_have_text(FIELD_LABELS)
    flow.close_sheet(page)

    # 번역은 시트가 아니라 문장 아래 인라인이다.
    assert page.locator(".translation").count() == 0
    page.locator(".reveal-translation").click()
    expect(page.locator(".translation-area .translation")).to_have_text(
        str(first["korean_translation"])
    )

    page.locator("button.next").click()
    expect(page.locator(".screen.demo .sentence")).to_have_attribute(
        "aria-label", str(EN_SENTENCES[1]["presentation"]["text"])
    )
    expect(page.locator(".screen.demo .demo-progress")).to_have_text(f"2 / {EN_TOTAL}")

    stored = _local_storage(page)
    assert list(stored) == [EN_KEY], stored
    assert json.loads(stored[EN_KEY])["fixtureId"] == EN_FIXTURE_ID

    page.wait_for_timeout(_LATE_REQUEST_WINDOW_MS)
    traffic.assert_none_outside()
    assert traffic.api_calls == []


def test_the_english_explanation_sheet_has_no_reading_line(frontend: Frontend, page: Page) -> None:
    """영어 설명 시트에 `reading` 줄이 **없다**(합격 기준 24). 양성 대조군은 일본어 demo다.

    대조군이 없으면 선택자 오타 하나로 이 단언이 영원히 초록이 된다. 같은 선택자가 일본어 쪽에서
    1건을 세는 것까지 함께 본다. 재생 버튼도 같다 --- 일본어 화면에는 자리조차 없다(합격 기준 27).
    """
    traffic = _watch(page, frontend)

    _open_demo(page, frontend, EN_DEMO_ROUTE, EN_FIRST)
    flow.tap(page, 0)
    explain = flow.open_sheet(page).locator(".explain")
    assert explain.locator(".reading").count() == 0, "영어 설명에 reading 줄이 있다"
    expect(explain.locator(".canonical-form")).to_have_count(1)
    # 머리는 문장 속 표면형이다. 읽기 줄만 빠진다.
    expect(explain.locator(".jp-word")).to_have_text(
        page.locator(".screen.demo .sentence .token").first.inner_text()
    )

    # 양성 대조군: 같은 선택자가 일본어 설명에서는 읽기를 센다.
    _open_demo(page, frontend, JA_DEMO_ROUTE, JA_FIRST)
    assert page.locator(f"{_SENTENCE_SPEAK} .speak-slot").count() == 0, (
        "일본어 문장 옆에 재생 자리가 있다"
    )
    flow.tap(page, 0)
    ja_explain = flow.open_sheet(page).locator(".explain")
    expect(ja_explain.locator(".reading")).to_have_count(1)
    assert ja_explain.locator(".speak-slot").count() == 0, "일본어 예문 옆에 재생 자리가 있다"

    page.wait_for_timeout(_LATE_REQUEST_WINDOW_MS)
    traffic.assert_none_outside()
    assert traffic.api_calls == []


# --------------------------------------------------------------------------
# 재생 (불변식 24·25, 합격 기준 25~27)
# --------------------------------------------------------------------------


def test_pressing_play_sends_nothing_outside_the_frontend_origin(
    frontend: Frontend, page: Page
) -> None:
    """문장 옆과 설명 시트 예문 옆의 재생 버튼을 눌러도 frontend origin 밖 요청이 0건이다.

    쓸 수 있는 로컬 영어 음성이 없는 브라우저에는 버튼이 없다. 그때도 **skip하지 않는다** --- 자리는
    남아 있고 버튼만 없다는 것을 단언하고, 어느 분기였는지 출력에 남긴다
    (`mvp-03-english/12_TEST_PLAN.md`의 `E2E (browser)`).

    마지막의 양성 대조군이 "이 페이지의 밖으로 나가는 요청은 정말로 잡힌다"를 보인다. 없으면
    "요청 0건"이 측정 실패와 구별되지 않는다.
    """
    traffic = _watch(page, frontend)
    _open_demo(page, frontend, EN_DEMO_ROUTE, EN_FIRST)

    pressed_sentence = _press_speak(page, _SENTENCE_SPEAK, "문장")
    flow.tap(page, 0)
    pressed_example = _press_speak(page, _EXAMPLE_SPEAK, "설명 시트 예문")
    assert pressed_sentence == pressed_example, (
        "두 자리의 판정이 갈렸다 --- 같은 음성 목록을 쓰므로 같아야 한다"
    )

    # 같은 버튼을 다시 누르면 멈춤이다. 멈춤도 요청을 내지 않는다.
    if pressed_example:
        _press_speak(page, _EXAMPLE_SPEAK, "설명 시트 예문(다시 누름)")

    flow.close_sheet(page)
    page.locator("button.next").click()
    page.locator(".screen.demo .sentence").wait_for(state="visible")

    page.wait_for_timeout(_LATE_REQUEST_WINDOW_MS)
    traffic.assert_none_outside()
    assert traffic.api_calls == []
    # 재생은 학습 신호가 아니다(불변식 25). 재생에 관한 값을 브라우저에도 남기지 않는다.
    assert set(_local_storage(page)) <= {EN_KEY}, _local_storage(page)

    # 양성 대조군: 이 페이지가 밖으로 내는 요청은 `watch_traffic`에 잡힌다.
    page.evaluate("() => { void fetch('https://nc-e2e-control.invalid/probe').catch(() => {}); }")
    page.wait_for_timeout(_LATE_REQUEST_WINDOW_MS)
    assert traffic.blocked != [] or traffic.foreign != [], (
        "일부러 낸 외부 요청이 기록되지 않았다 --- 위의 `0건`은 측정 실패일 수 있다"
    )


# 로컬 영어 음성 하나를 가진 브라우저를 흉내낸다. `localService: true`이므로 `ui/speech.ts`가 고른다.
# 재생 요청을 받아 적기만 하고 소리를 내지 않는다.
_STUB_LOCAL_VOICE = """(() => {
    const voice = {name: 'Stub', lang: 'en-US', localService: true, default: true, voiceURI: 'stub'};
    const synth = {
        getVoices: () => [voice],
        speak: (utterance) => {
            window.__spoken = (window.__spoken ?? []).concat([utterance.text]);
            synth.speaking = true;
        },
        cancel: () => {
            window.__cancels = (window.__cancels ?? 0) + 1;
            synth.speaking = false;
        },
        addEventListener: () => {},
        removeEventListener: () => {},
        speaking: false,
        pending: false,
    };
    for (const target of [window, Window.prototype]) {
        try {
            Object.defineProperty(target, 'speechSynthesis', {get: () => synth, configurable: true});
        } catch (error) {
            // 이미 설정 불가한 쪽은 넘어간다. 아래 양성 대조군이 스텁이 실제로 걸렸는지 본다.
        }
    }
    window.SpeechSynthesisUtterance = function (text) { this.text = text; };
})();"""


def test_the_play_button_appears_and_stays_silent_when_a_local_voice_exists(
    frontend: Frontend, browser: Browser, playwright_driver: Playwright
) -> None:
    """로컬 영어 음성이 하나 있는 브라우저에서 버튼이 **생기고**, 눌러도 요청이 0건이다.

    위 테스트는 이 환경의 Chrome에 음성이 있는지에 따라 분기가 갈린다. 그래서 "버튼 있음" 쪽을
    여기서 고정한다 --- 음성 목록을 스텁으로 심어 **항상** 그 분기를 돈다.

    **이 테스트가 증명하지 못하는 것:** 스텁은 소리를 내지 않으므로 "진짜 합성이 네트워크로 나가지
    않는다"는 보이지 못한다. 그것은 `localService` 필터(unit `speech.test.ts`)와 음성이 실제로 있는
    기기에서 도는 위 테스트가 맡는다. 여기서 보는 것은 **우리 코드**가 재생을 계기로 아무 요청도
    보내지 않고 아무것도 저장하지 않는다는 것이다(불변식 25).
    """
    context = browser.new_context(**playwright_driver.devices[PHONE])
    try:
        context.add_init_script(_STUB_LOCAL_VOICE)
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        traffic = _watch(page, frontend)

        _open_demo(page, frontend, EN_DEMO_ROUTE, EN_FIRST)
        # 양성 대조군: 스텁이 정말 걸렸다. 걸리지 않았으면 아래는 "음성 없음" 분기를 돈다.
        assert _local_english_voices(page) == ["en-US"], _local_english_voices(page)

        assert _press_speak(page, _SENTENCE_SPEAK, "문장(스텁 음성)") is True
        # 읽는 문자열은 화면에 보이는 문장 하나다. id·설정값이 섞이지 않는다.
        assert page.evaluate("() => window.__spoken") == [EN_FIRST]
        # 새 재생 전에 항상 멈춘다(두 문장이 겹치지 않는다).
        assert page.evaluate("() => window.__cancels") >= 1
        expect(page.locator(f"{_SENTENCE_SPEAK} button.speak")).to_have_attribute(
            "aria-pressed", "true"
        )

        # 읽는 중에 같은 버튼을 다시 누르면 멈춤이다. 새 문자열을 읽지 않는다.
        page.locator(f"{_SENTENCE_SPEAK} button.speak").click()
        expect(page.locator(f"{_SENTENCE_SPEAK} button.speak")).to_have_attribute(
            "aria-pressed", "false"
        )
        assert page.evaluate("() => window.__spoken") == [EN_FIRST]

        # 설명 시트 예문에도 버튼이 있다. 읽는 것은 예문이고 번역이 아니다.
        flow.tap(page, 0)
        assert _press_speak(page, _EXAMPLE_SPEAK, "설명 시트 예문(스텁 음성)") is True
        spoken: list[str] = page.evaluate("() => window.__spoken")
        example = flow.open_sheet(page).locator(".explain .example").inner_text()
        assert spoken[-1] == example, spoken

        # 문장을 넘기면 그 문장의 signal이 abort되어 재생이 멈춘다.
        before = int(page.evaluate("() => window.__cancels"))
        flow.close_sheet(page)
        page.locator("button.next").click()
        expect(page.locator(".screen.demo .sentence")).to_have_attribute(
            "aria-label", _sentence_text(EN_SENTENCES, 1)
        )
        assert int(page.evaluate("() => window.__cancels")) > before, (
            "문장을 떠났는데 `cancel()`이 불리지 않았다"
        )

        page.wait_for_timeout(_LATE_REQUEST_WINDOW_MS)
        assert errors == [], f"잡히지 않은 오류: {errors}"
        traffic.assert_none_outside()
        assert traffic.api_calls == []
        # 재생에 관한 어떤 값도 브라우저에 쓰지 않는다(불변식 25).
        assert set(_local_storage(page)) <= {EN_KEY}, _local_storage(page)
    finally:
        context.close()


# --------------------------------------------------------------------------
# 진도 분리 (불변식 18, 합격 기준 23)
# --------------------------------------------------------------------------


def _progress_value(fixture_id: str, total: int) -> str:
    """마지막 문장을 보고 있는 상태의 저장 형식(`demo/progress.ts`의 `DemoProgress`)."""
    value: dict[str, Any] = {
        "fixtureId": fixture_id,
        "position": total - 1,
        "seen": total,
        "selfReports": {},
        "probed": [],
        "queue": [],
        "reviewed": [],
    }
    return json.dumps(value)


# 영어 진도만 완료 직전으로 심는다. 일본어 key는 건드리지 않는다.
_SEED_EN_PROGRESS = """([key, value]) => {
    if (localStorage.getItem(key) === null) localStorage.setItem(key, value);
}"""


def test_finishing_the_english_demo_leaves_the_japanese_demo_at_the_start(
    frontend: Frontend, page: Page
) -> None:
    """영어를 끝까지 보고 새로고침해도 일본어 demo는 처음부터다. 완료 화면에 `글자 배우기`가 없다.

    진도 key가 언어별로 갈려 있으므로(`nc.demo.ja.v1` / `nc.demo.en.v1`) 한쪽을 끝내도 다른 쪽은
    건드려지지 않는다. 한 key를 공유하면 일본어 demo가 끝난 것처럼 열린다.
    """
    seed = json.dumps([EN_KEY, _progress_value(EN_FIXTURE_ID, EN_TOTAL)])
    page.add_init_script(f"({_SEED_EN_PROGRESS})({seed})")
    traffic = _watch(page, frontend)

    # 심은 진도의 자리는 마지막 문장이다. 한 번 더 누르면 완료다.
    _open_demo(page, frontend, EN_DEMO_ROUTE, _sentence_text(EN_SENTENCES, EN_TOTAL - 1))
    assert _progress(page) == f"{EN_TOTAL} / {EN_TOTAL}"
    page.locator("button.next").click()

    screen = page.locator(".screen.demo")
    expect(screen.locator("h1")).to_have_text(COMPLETE_TITLE)
    # 가나 학습에 대응하는 영어 화면이 없다(ADR-025 결정 2). 완료 화면의 버튼은 `처음부터 다시`뿐이다.
    expect(page.locator(".screen.demo > :not(.topbar) button")).to_have_text([RESTART])
    assert screen.locator("button", has_text=LEARN_KANA).count() == 0

    page.reload()
    expect(page.locator(".screen.demo h1")).to_have_text(COMPLETE_TITLE)

    # 일본어 demo는 처음부터다. 여는 것만으로는 아무것도 저장하지 않으므로 key도 아직 없다.
    _open_demo(page, frontend, JA_DEMO_ROUTE, JA_FIRST)
    assert _progress(page) == f"1 / {JA_TOTAL}"
    assert list(_local_storage(page)) == [EN_KEY], _local_storage(page)

    # 일본어 쪽 한 걸음은 일본어 key에만 쓴다. 영어 진도는 그대로 남는다.
    page.locator("button.next").click()
    expect(page.locator(".screen.demo .demo-progress")).to_have_text(f"2 / {JA_TOTAL}")
    stored = _local_storage(page)
    assert sorted(stored) == sorted([EN_KEY, JA_KEY]), stored
    assert json.loads(stored[EN_KEY])["seen"] == EN_TOTAL
    assert json.loads(stored[EN_KEY])["fixtureId"] == EN_FIXTURE_ID
    assert json.loads(stored[JA_KEY])["seen"] == 2
    assert json.loads(stored[JA_KEY])["fixtureId"] == JA_FIXTURE_ID

    page.wait_for_timeout(_LATE_REQUEST_WINDOW_MS)
    traffic.assert_none_outside()
    assert traffic.api_calls == []
