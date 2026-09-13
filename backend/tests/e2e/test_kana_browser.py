"""가나 학습 (mvp-02-onboarding/12_TEST_PLAN.md의 `Browser E2E`, 13_ACCEPTANCE_CRITERIA.md 29·31·32·34·35).

휴대폰 viewport로 돈다. 가나 학습은 frontend만으로 동작하므로 backend를 띄우지 않는 `frontend` fixture만 쓰고,
모든 테스트가 frontend origin 밖의 요청을 막은 채(`block=True`) 끝까지 간다 --- "요청을 안 했다"가 아니라
"요청이 필요 없다"를 본다.

-   선택 홈 카드로 들어가 두 탭과 범위 칩 7개, 범위 설명, 글자 표와 단어 목록, 히라가나 탭의 외래어 안내를 본다.
-   보고 읽기와 보고 고르기를 각각 한 라운드씩 끝까지 푼다. 첫 문항을 틀리면 라운드 끝에 한 번 더 나오고,
    결과에 바로 맞힌 수와 한 번 더 풀어 본 글자가 나온다. 응답마다(다시 나온 문항 포함) `nc.kana.v1`이 는다.
-   퀴즈 중 진행 표시와 `글자 표로 돌아가기`, 새로고침 뒤 진도 유지, 진도 초기화(인라인 확인) 뒤 key 없음.

기대값의 출처:

-   **글자의 로마자·한글은 `spec/mvp-01-core/03_UI_UX_SPEC.md`의 `정답 표기` 글자 표를 읽어서** 얻는다. 화면
    구현(`frontend/src/kana/data.ts`)을 기대값으로 쓰면 데이터가 틀려도 통과한다. 가타카나는 대응하는 히라가나와
    같은 로마자·한글이다(같은 절).
-   단어의 로마자·한글·뜻은 03에 표가 없다. 형식(소문자 ASCII, 한글, 뜻 있음)을 보고, 퀴즈의 정답이 같은 화면의
    단어 목록과 같은지 본다.
-   라운드 문항 수 상한과 선택지 수는 그 값을 정의한 `frontend/src/kana/quiz.ts`에서 읽는다(숫자를 복사하지
    않는다). 화면 문구는 03 `화면 문구 표`의 리터럴이다. 표에 아직 없는 표기(범위 `히라가나 · 청음`, 진행
    `{현재} / {전체}`, 퀴즈 제목 = 방식 이름, 가타카나 탭의 작은 글자)는 Wave 3 메인 결정 W3-2·W3-5를 따른다.
-   `nc.kana.v1`의 값 형식은 `frontend/src/kana/progress.ts`가 정한다(03 `진도 저장`). 이 파일은 그 형식으로
    글자·단어별 맞음/틀림 수와 마지막 학습 시각을 읽는다.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any

import pytest
from playwright.sync_api import Browser, Locator, Page, Playwright, expect

from tests.conftest import REPO_ROOT
from tests.e2e import study_flow as flow
from tests.e2e.conftest import Frontend

pytestmark = pytest.mark.e2e

PHONE = "iPhone 13"

UI_SPEC = REPO_ROOT / "spec" / "mvp-01-core" / "03_UI_UX_SPEC.md"
QUIZ_TS = REPO_ROOT / "frontend" / "src" / "kana" / "quiz.ts"

KANA_KEY = "nc.kana.v1"
FURIGANA_KEY = "nc.furigana.v1"
KANA_ROUTE = "#/kana"
KANA_CARD_TITLE = "글자부터 배우기"

# 03 `화면 문구 표`의 `가나 학습`.
TITLE = "글자 배우기"
SCRIPTS = ("히라가나", "가타카나")
RANGES = ("청음", "탁음", "반탁음", "요음", "촉음", "장음", "외래어")
CHAR_RANGES = ("청음", "탁음", "반탁음", "요음")
RANGE_DESCRIPTIONS = {
    "히라가나": {
        "청음": "기본 글자예요.",
        "탁음": "점 두 개(゛)가 붙으면 흐린 소리가 나요.",
        "반탁음": "작은 동그라미(゜)가 붙으면 ㅍ 소리가 나요.",
        "요음": "작은 ゃ·ゅ·ょ가 붙으면 한 소리로 읽어요.",
        "촉음": "작은 っ 자리에서 한 박자 쉬어요.",
        "장음": "あ·い·う 같은 모음 글자만큼 길게 읽어요.",
    },
    # 요음·촉음의 작은 글자는 W3-2 (6)의 가타카나 표기다.
    "가타카나": {
        "청음": "기본 글자예요.",
        "탁음": "점 두 개(゛)가 붙으면 흐린 소리가 나요.",
        "반탁음": "작은 동그라미(゜)가 붙으면 ㅍ 소리가 나요.",
        "요음": "작은 ャ·ュ·ョ가 붙으면 한 소리로 읽어요.",
        "촉음": "작은 ッ 자리에서 한 박자 쉬어요.",
        "장음": "ー 표시만큼 길게 읽어요.",
        "외래어": "다른 나라 말을 가타카나로 적어요. ティ, ファ처럼 작은 글자를 붙인 표기도 있어요.",
    },
}
GAIRAIGO_NOTE = ["외래어는 가타카나로 적어요.", "가타카나에서 볼 수 있어요."]
SHOW_KATAKANA = "가타카나로 보기"
QUIZ_CARD_TITLE = "퀴즈로 연습해요"
MODES = {
    "보고 읽기": "읽어 본 뒤 정답을 확인해요.",
    "보고 고르기": "알맞은 읽기를 4개 중에서 골라요.",
}
READ = "보고 읽기"
CHOOSE = "보고 고르기"
SAVE_NOTE = "푼 기록은 이 브라우저에만 남아요."
RESET = "진도 초기화"
RESET_QUESTION = "진도를 초기화할까요?"
RESET_DETAIL = "이 브라우저에 남은 퀴즈 기록이 지워져요."
RESET_CONFIRM = "초기화하기"
RESET_CANCEL = "취소"
RESET_DONE = "진도를 초기화했어요."
READ_INSTRUCTION = "소리 내어 읽어 보세요."
SHOW_ANSWER = "정답 보기"
WRONG = "틀렸어요"
RIGHT = "맞았어요"
RETRY_MARK = "한 번 더 볼게요."
WILL_RETRY = "이번 라운드에서 한 번 더 나와요."
CHOOSE_RIGHT = "맞았어요."
NEXT_QUESTION = "다음 문제"
SHOW_RESULT = "결과 보기"
RESULT_TITLE = "이번 라운드를 마쳤어요."
RESULT_RETRIED = "한 번 더 풀어 본 글자예요."
AGAIN = "한 번 더 풀기"
BACK_TO_TABLE = "글자 표로 돌아가기"


def _choose_wrong(romaji: str) -> str:
    return f"정답은 {romaji}예요."


def _result_some(total: int, correct: int) -> str:
    return f"{total}문제 중 {correct}문제를 바로 맞혔어요."


def _quiz_scope(script: str, range_label: str) -> str:
    return f"지금 고른 {script} · {range_label}에서 문제를 내요."


ROMAJI = re.compile(r"[a-z]+")
HANGUL = re.compile(r"[가-힣]+")
HIRAGANA_WORD = re.compile(r"[ぁ-ゖ]+")
KATAKANA_WORD = re.compile(r"[ァ-ヺー]+")

# 늦게 나가는 요청이 드러날 때까지 기다리는 시간. 정책값이 아니다.
_LATE_REQUEST_WINDOW_MS = 2000


# --------------------------------------------------------------------------
# 기대값: 03의 글자 표와 quiz.ts의 상수
# --------------------------------------------------------------------------

Entry = tuple[str, str, str]  # (가나, 로마자, 한글)


def _spec_char_table() -> dict[str, list[Entry]]:
    """03 `정답 표기`의 글자 표. 범위 이름 -> 표 순서의 (히라가나, 로마자, 한글)."""
    text = UI_SPEC.read_text(encoding="utf-8")
    blocks = re.findall(r"``` text\n(.*?)```", text, flags=re.DOTALL)
    table_blocks = [block for block in blocks if block.lstrip().startswith("청음    あ a")]
    assert len(table_blocks) == 1, "03의 `정답 표기` 글자 표를 찾지 못했다"

    table: dict[str, list[Entry]] = {label: [] for label in CHAR_RANGES}
    current: str | None = None
    for line in table_blocks[0].splitlines():
        tokens = line.split()
        if not tokens:
            continue
        if tokens[0] in table:
            current = tokens.pop(0)
        assert current is not None and len(tokens) % 3 == 0, line
        for index in range(0, len(tokens), 3):
            kana, romaji, hangul = tokens[index : index + 3]
            table[current].append((kana, romaji, hangul))
    for label, entries in table.items():
        assert entries, f"03 글자 표에 {label}이 비어 있다"
    return table


def _katakana(hiragana: str) -> str:
    """가타카나 탭은 대응하는 히라가나와 같은 로마자·한글이다(03 `정답 표기`)."""
    return "".join(chr(ord(char) + 0x60) if "ぁ" <= char <= "ゖ" else char for char in hiragana)


def _expected_chars(script: str, range_label: str) -> list[Entry]:
    entries = SPEC_CHARS[range_label]
    if script == "히라가나":
        return entries
    return [(_katakana(kana), romaji, hangul) for kana, romaji, hangul in entries]


def _quiz_constant(name: str) -> int:
    match = re.search(rf"export const {name} = (\d+)", QUIZ_TS.read_text(encoding="utf-8"))
    assert match is not None, f"{QUIZ_TS}에서 {name}을 찾지 못했다"
    return int(match.group(1))


SPEC_CHARS = _spec_char_table()
ROUND_MAX = _quiz_constant("KANA_ROUND_MAX_QUESTIONS")
CHOICE_COUNT = _quiz_constant("KANA_CHOICE_COUNT")


# --------------------------------------------------------------------------
# 화면 조작
# --------------------------------------------------------------------------


@pytest.fixture
def phone(browser: Browser, playwright_driver: Playwright) -> Iterator[Page]:
    context = browser.new_context(**playwright_driver.devices[PHONE])
    try:
        yield context.new_page()
    finally:
        context.close()


def _watch(page: Page, frontend: Frontend) -> flow.Traffic:
    return flow.watch_traffic(page, frontend_url=frontend.url, api_url=frontend.api_url, block=True)


def _assert_no_requests(page: Page, traffic: flow.Traffic) -> None:
    page.wait_for_timeout(_LATE_REQUEST_WINDOW_MS)
    traffic.assert_none_outside()
    assert traffic.api_calls == []


def _table_screen(page: Page) -> Locator:
    screen = page.locator(".screen.kana.kana-home")
    screen.wait_for(state="visible", timeout=flow.SETTLE_TIMEOUT_SECONDS * 1000)
    return screen


def _enter_from_home(page: Page, frontend: Frontend) -> Locator:
    page.goto(frontend.url)
    page.locator(".screen.home").wait_for(state="visible")
    page.locator(".home-card", has_text=KANA_CARD_TITLE).click()
    screen = _table_screen(page)
    expect(page).to_have_url(re.compile(f"{re.escape(KANA_ROUTE)}$"))
    return screen


def _exact(text: str) -> re.Pattern[str]:
    # has_text는 부분 일치다(`탁음`이 `반탁음`에도 맞는다).
    return re.compile(f"^{re.escape(text)}$")


def _tab(page: Page, label: str) -> Locator:
    return page.locator(".kana-tabs .kana-tabs-button", has_text=_exact(label))


def _chip(page: Page, label: str) -> Locator:
    return page.locator(".kana-chips .kana-chips-button", has_text=_exact(label))


def _select(page: Page, script: str, range_label: str) -> None:
    _tab(page, script).click()
    _chip(page, range_label).click()
    _assert_selected(page, script, range_label)


def _assert_selected(page: Page, script: str, range_label: str) -> None:
    for label in SCRIPTS:
        expect(_tab(page, label)).to_have_attribute("aria-pressed", str(label == script).lower())
    for label in RANGES:
        expect(_chip(page, label)).to_have_attribute(
            "aria-pressed", str(label == range_label).lower()
        )


def _cells(page: Page) -> list[Entry]:
    return [
        tuple(row)
        for row in page.evaluate(
            """() => Array.from(document.querySelectorAll('.kana-table .kana-cell:not(.is-empty)'))
                .map((cell) => ['.kana-cell-text', '.kana-cell-romaji', '.kana-cell-hangul']
                    .map((selector) => cell.querySelector(selector).textContent))"""
        )
    ]


def _words(page: Page) -> list[tuple[str, str, str, str]]:
    return [
        tuple(row)
        for row in page.evaluate(
            """() => Array.from(document.querySelectorAll('.kana-words .kana-word'))
                .map((word) => ['.kana-word-text', '.kana-word-romaji', '.kana-word-hangul',
                                '.kana-word-meaning']
                    .map((selector) => word.querySelector(selector).textContent))"""
        )
    ]


def _start_round(page: Page, mode: str) -> Locator:
    page.locator(".kana-quiz-card .kana-mode", has_text=mode).click()
    screen = page.locator(".screen.kana.kana-quiz")
    screen.wait_for(state="visible")
    expect(screen.locator("h1")).to_have_text(mode)
    return screen


def _progress(page: Page) -> Locator:
    return page.locator(".screen.kana-quiz .kana-progress")


def _question_text(page: Page) -> str:
    text = page.locator(".kana-question-text").text_content()
    assert text is not None
    return text


def _stored(page: Page, key: str) -> str | None:
    value = page.evaluate("(key) => window.localStorage.getItem(key)", key)
    assert value is None or isinstance(value, str)
    return value


def _stored_keys(page: Page) -> set[str]:
    return set(page.evaluate("() => Object.keys(window.localStorage)"))


def _kana_progress(page: Page) -> dict[str, Any]:
    raw = _stored(page, KANA_KEY)
    assert raw is not None, f"{KANA_KEY}에 진도가 없다"
    parsed = json.loads(raw)
    assert isinstance(parsed, dict)
    return parsed


def _now_ms(page: Page) -> float:
    return float(page.evaluate("() => Date.now()"))


def _history_length(page: Page) -> int:
    return int(page.evaluate("() => history.length"))


def _assert_still_on_kana(page: Page, history_length: int) -> None:
    """라운드 진행 상태는 hash·history에 없다(03 `가나 학습`)."""
    expect(page).to_have_url(re.compile(f"{re.escape(KANA_ROUTE)}$"))
    assert _history_length(page) == history_length, "가나 화면 안의 이동이 history를 쌓았다"


def _assert_no_sound_or_stroke_media(page: Page) -> None:
    """소리·획순이 없다(AC 35). 재생·그리기 요소가 화면에 없다."""
    assert page.locator("audio, video, canvas").count() == 0


# --------------------------------------------------------------------------
# 글자 표: 탭, 범위 칩, 표와 단어 목록, 히라가나 탭의 외래어
# --------------------------------------------------------------------------


def test_tabs_and_range_chips_show_the_spec_tables_and_word_lists(
    frontend: Frontend, phone: Page
) -> None:
    """카드로 들어가 두 탭 x 범위 칩 7개를 모두 누른다. 글자 표는 03 `정답 표기`와 칸 순서까지 같다."""
    traffic = _watch(phone, frontend)
    screen = _enter_from_home(phone, frontend)
    history_length = _history_length(phone)

    expect(screen.locator("h1")).to_have_text(TITLE)
    assert screen.locator(".topbar .topbar-actions button").all_inner_texts() == [flow.LOGIN_LABEL]
    expect(screen.locator(".kana-tabs .kana-tabs-button")).to_have_text(list(SCRIPTS))
    expect(screen.locator(".kana-chips .kana-chips-button")).to_have_text(list(RANGES))
    # 처음은 히라가나 · 청음이다.
    _assert_selected(phone, "히라가나", "청음")
    expect(screen.locator(".kana-save .kana-save-text")).to_have_text(SAVE_NOTE)
    expect(screen.locator(".kana-save .kana-reset-open")).to_have_text(RESET)

    for script in SCRIPTS:
        for range_label in RANGES:
            if script == "히라가나" and range_label == "외래어":
                continue
            _select(phone, script, range_label)
            expect(screen.locator(".kana-range-desc")).to_have_text(
                RANGE_DESCRIPTIONS[script][range_label]
            )
            card = screen.locator(".kana-quiz-card")
            expect(card.locator(".kana-quiz-title")).to_have_text(QUIZ_CARD_TITLE)
            expect(card.locator(".kana-quiz-scope")).to_have_text(_quiz_scope(script, range_label))
            expect(card.locator(".kana-mode .kana-mode-name")).to_have_text(list(MODES))
            expect(card.locator(".kana-mode .kana-mode-desc")).to_have_text(list(MODES.values()))

            if range_label in CHAR_RANGES:
                assert _cells(phone) == _expected_chars(script, range_label), (
                    f"{script} {range_label} 표가 03 `정답 표기`와 다르다"
                )
                assert screen.locator(".kana-words").count() == 0
                continue

            words = _words(phone)
            assert words, f"{script} {range_label} 단어 목록이 비어 있다"
            assert screen.locator(".kana-table").count() == 0
            script_pattern = HIRAGANA_WORD if script == "히라가나" else KATAKANA_WORD
            for text, romaji, hangul, meaning in words:
                assert script_pattern.fullmatch(text), (script, text)
                assert ROMAJI.fullmatch(romaji), (text, romaji)
                assert HANGUL.fullmatch(hangul), (text, hangul)
                assert meaning.strip(), f"{text}에 뜻이 없다"
            assert len({text for text, *_ in words}) == len(words), words

    # 히라가나 탭의 외래어: 안내와 가타카나 이동 버튼. 문항이 없으므로 퀴즈 카드를 숨긴다(W3-2 (1)).
    _select(phone, "히라가나", "외래어")
    expect(screen.locator(".kana-gairaigo-note .kana-note-text")).to_have_text(GAIRAIGO_NOTE)
    assert screen.locator(".kana-quiz-card").count() == 0
    assert screen.locator(".kana-words, .kana-table").count() == 0
    screen.locator(".kana-show-katakana", has_text=SHOW_KATAKANA).click()
    _assert_selected(phone, "가타카나", "외래어")
    assert _words(phone), "가타카나로 옮겼는데 외래어 목록이 없다"
    expect(screen.locator(".kana-quiz-scope")).to_have_text(_quiz_scope("가타카나", "외래어"))

    _assert_no_sound_or_stroke_media(phone)
    _assert_still_on_kana(phone, history_length)
    _assert_no_requests(phone, traffic)


# --------------------------------------------------------------------------
# 보고 읽기 한 라운드
# --------------------------------------------------------------------------


def test_a_see_and_read_round_retries_the_missed_question_and_records_every_answer(
    frontend: Frontend, phone: Page
) -> None:
    """히라가나 · 청음 보고 읽기. 첫 문항을 `틀렸어요`로 답하고 나머지는 `맞았어요`.

    -   정답은 누른 뒤에 생기고 `{로마자} {한글}`이 03 글자 표와 같다.
    -   틀리면 토스트가 뜨고 진행 표시의 전체 수가 하나 늘며, 라운드 끝에 `한 번 더 볼게요.`와 함께 다시 나온다.
    -   결과: 바로 맞힌 수, 한 번 더 풀어 본 글자(로마자와 함께), 두 행동.
    -   `nc.kana.v1`: 다시 나온 문항의 응답까지 센다.
    """
    traffic = _watch(phone, frontend)
    _enter_from_home(phone, frontend)
    history_length = _history_length(phone)
    _assert_selected(phone, "히라가나", "청음")
    expected = {
        kana: (romaji, hangul) for kana, romaji, hangul in _expected_chars("히라가나", "청음")
    }
    total = min(len(expected), ROUND_MAX)
    started_at = _now_ms(phone)

    quiz = _start_round(phone, READ)
    assert quiz.locator(".topbar .topbar-actions button").all_inner_texts() == [flow.LOGIN_LABEL]
    expect(quiz.locator(".kana-back")).to_have_text(BACK_TO_TABLE)

    asked: list[str] = []
    length = total
    position = 1
    while position <= length:
        expect(_progress(phone)).to_have_text(f"{position} / {length}")
        text = _question_text(phone)
        retry = position > total
        if retry:
            expect(quiz.locator(".kana-retry")).to_have_text(RETRY_MARK)
            assert text == asked[0], "라운드 끝에 다시 나온 문항이 틀린 문항이 아니다"
        else:
            assert quiz.locator(".kana-retry").count() == 0
            assert text in expected, f"청음 밖의 문항: {text}"
            asked.append(text)
        expect(quiz.locator(".kana-instruction")).to_have_text(READ_INSTRUCTION)
        assert quiz.locator(".kana-answer").count() == 0, "정답 보기 전에 정답이 문서에 있다"

        quiz.locator(".kana-show-answer", has_text=SHOW_ANSWER).click()
        romaji, hangul = expected[text]
        assert ROMAJI.fullmatch(romaji)
        expect(quiz.locator(".kana-answer")).to_have_text(f"{romaji} {hangul}")

        if position == 1:
            quiz.locator(".kana-wrong", has_text=WRONG).click()
            expect(phone.locator(".toast")).to_have_text(WILL_RETRY)
            length += 1
        else:
            quiz.locator(".kana-right", has_text=RIGHT).click()
        position += 1

    assert len(set(asked)) == total, f"한 라운드에 같은 문항이 두 번 처음 나왔다: {asked}"
    result = phone.locator(".screen.kana.kana-result")
    result.wait_for(state="visible")
    expect(result.locator("h1")).to_have_text(RESULT_TITLE)
    expect(result.locator(".kana-result-summary")).to_have_text(_result_some(total, total - 1))
    expect(result.locator(".kana-retried-title")).to_have_text(RESULT_RETRIED)
    expect(result.locator(".kana-retried-item .kana-retried-text")).to_have_text([asked[0]])
    expect(result.locator(".kana-retried-item .kana-retried-romaji")).to_have_text(
        [expected[asked[0]][0]]
    )
    expect(result.locator(".kana-result-actions button")).to_have_text([AGAIN, BACK_TO_TABLE])

    progress = _kana_progress(phone)
    assert progress["items"] == {
        text: {"correct": 1, "wrong": 1} if text == asked[0] else {"correct": 1, "wrong": 0}
        for text in asked
    }
    assert started_at <= progress["lastStudiedAt"] <= _now_ms(phone)

    # `한 번 더 풀기`는 같은 범위의 새 라운드다. `글자 표로 돌아가기`는 고른 탭·범위 그대로다.
    result.locator(".kana-again").click()
    expect(_progress(phone)).to_have_text(f"1 / {total}")
    expect(phone.locator(".screen.kana-quiz h1")).to_have_text(READ)
    phone.locator(".screen.kana-quiz .kana-back").click()
    _table_screen(phone)
    _assert_selected(phone, "히라가나", "청음")

    _assert_no_sound_or_stroke_media(phone)
    _assert_still_on_kana(phone, history_length)
    _assert_no_requests(phone, traffic)


# --------------------------------------------------------------------------
# 보고 고르기 한 라운드
# --------------------------------------------------------------------------


def test_a_see_and_choose_round_offers_same_range_romaji_and_retries_the_missed_question(
    frontend: Frontend, phone: Page
) -> None:
    """가타카나 · 탁음 보고 고르기. 첫 문항과 그 재출제를 틀리고 나머지는 맞힌다.

    -   선택지는 로마자이고 서로 겹치지 않으며 정답이 정확히 하나, 모두 같은 범위(03 탁음 표)의 로마자다.
    -   틀리면 `정답은 {로마자}예요. 이번 라운드에서 한 번 더 나와요.`이고 토스트는 없다(W3-5).
    -   다시 나온 문항을 또 틀리면 `정답은 {로마자}예요.`만 보인다(G6).
    """
    traffic = _watch(phone, frontend)
    screen = _enter_from_home(phone, frontend)
    history_length = _history_length(phone)
    _select(phone, "가타카나", "탁음")
    expect(screen.locator(".kana-quiz-scope")).to_have_text(_quiz_scope("가타카나", "탁음"))
    entries = _expected_chars("가타카나", "탁음")
    expected = {kana: romaji for kana, romaji, _ in entries}
    same_range = {romaji for _, romaji, _ in entries}
    total = min(len(expected), ROUND_MAX)
    started_at = _now_ms(phone)

    quiz = _start_round(phone, CHOOSE)

    asked: list[str] = []
    length = total
    position = 1
    while position <= length:
        expect(_progress(phone)).to_have_text(f"{position} / {length}")
        text = _question_text(phone)
        retry = position > total
        if retry:
            expect(quiz.locator(".kana-retry")).to_have_text(RETRY_MARK)
            assert text == asked[0]
        else:
            assert text in expected, f"가타카나 탁음 밖의 문항: {text}"
            asked.append(text)
        romaji = expected[text]

        options = quiz.locator(".kana-option")
        expect(options).to_have_count(CHOICE_COUNT)
        labels = options.all_text_contents()
        assert len(set(labels)) == len(labels), f"선택지가 겹친다: {labels}"
        assert all(ROMAJI.fullmatch(label) for label in labels), labels
        assert labels.count(romaji) == 1, f"정답 {romaji}가 정확히 하나가 아니다: {labels}"
        assert set(labels) <= same_range, f"같은 범위 밖의 선택지: {set(labels) - same_range}"
        assert quiz.locator(".kana-feedback").count() == 0

        missed = position == 1 or retry
        picked = next(label for label in labels if label != romaji) if missed else romaji
        quiz.locator(".kana-option", has_text=_exact(picked)).click()

        if position == 1:
            feedback = f"{_choose_wrong(romaji)} {WILL_RETRY}"
            length += 1
        elif retry:
            feedback = _choose_wrong(romaji)
        else:
            feedback = CHOOSE_RIGHT
        expect(quiz.locator(".kana-feedback")).to_have_text(feedback)
        for index in range(CHOICE_COUNT):
            expect(options.nth(index)).to_be_disabled()
        expect(quiz.locator(".kana-option.is-correct")).to_have_text(romaji)
        expect(quiz.locator(".kana-option.is-wrong")).to_have_count(1 if missed else 0)
        assert phone.locator(".toast").count() == 0, "보고 고르기에서 토스트가 떴다"

        last = position == length
        expect(quiz.locator(".kana-next")).to_have_text(SHOW_RESULT if last else NEXT_QUESTION)
        quiz.locator(".kana-next").click()
        position += 1

    result = phone.locator(".screen.kana.kana-result")
    result.wait_for(state="visible")
    expect(result.locator(".kana-result-summary")).to_have_text(_result_some(total, total - 1))
    expect(result.locator(".kana-retried-item .kana-retried-text")).to_have_text([asked[0]])
    expect(result.locator(".kana-retried-item .kana-retried-romaji")).to_have_text(
        [expected[asked[0]]]
    )

    progress = _kana_progress(phone)
    assert progress["items"] == {
        text: {"correct": 0, "wrong": 2} if text == asked[0] else {"correct": 1, "wrong": 0}
        for text in asked
    }
    assert started_at <= progress["lastStudiedAt"] <= _now_ms(phone)

    result.locator(".kana-back").click()
    _table_screen(phone)
    _assert_selected(phone, "가타카나", "탁음")

    _assert_still_on_kana(phone, history_length)
    _assert_no_requests(phone, traffic)


# --------------------------------------------------------------------------
# 퀴즈 중 표로 돌아가기, 새로고침 뒤 진도, 진도 초기화
# --------------------------------------------------------------------------


def test_progress_survives_a_reload_and_reset_removes_only_the_kana_key(
    frontend: Frontend, phone: Page
) -> None:
    """가타카나 · 촉음 보고 읽기 한 문항 -> 퀴즈 중 `글자 표로 돌아가기` -> 새로고침 -> 진도 초기화.

    -   단어 문항의 정답은 `{로마자} {한글} ({뜻})`이고 같은 화면의 단어 목록과 같다.
    -   퀴즈 중 돌아가면 라운드는 버리고 고른 탭·범위의 표로 간다. 이미 한 응답은 저장돼 있다(W3-2 (2)).
    -   `#/kana`를 직접 열어도 가나 화면이고, 새로고침 뒤에도 `nc.kana.v1`이 그대로다.
    -   `진도 초기화`는 인라인 확인을 거친다. 취소하면 그대로, 확인하면 `nc.kana.v1`만 없어지고
        `nc.furigana.v1`은 남는다.
    """
    traffic = _watch(phone, frontend)
    phone.goto(f"{frontend.url}/{KANA_ROUTE}")
    screen = _table_screen(phone)
    expect(screen.locator("h1")).to_have_text(TITLE)
    furigana = json.dumps({"on": True})
    phone.evaluate(
        "([key, value]) => window.localStorage.setItem(key, value)", [FURIGANA_KEY, furigana]
    )
    history_length = _history_length(phone)

    _select(phone, "가타카나", "촉음")
    words = {text: (romaji, hangul, meaning) for text, romaji, hangul, meaning in _words(phone)}
    total = min(len(words), ROUND_MAX)
    assert total > 1, (
        "라운드 중간에 돌아가려면 문항이 둘 이상이어야 한다 --- 전제가 성립하지 않는다"
    )

    quiz = _start_round(phone, READ)
    expect(_progress(phone)).to_have_text(f"1 / {total}")
    text = _question_text(phone)
    assert text in words, f"촉음 단어 목록 밖의 문항: {text}"
    quiz.locator(".kana-show-answer").click()
    romaji, hangul, meaning = words[text]
    expect(quiz.locator(".kana-answer")).to_have_text(f"{romaji} {hangul} ({meaning})")
    quiz.locator(".kana-right").click()
    expect(_progress(phone)).to_have_text(f"2 / {total}")
    quiz.locator(".kana-back", has_text=BACK_TO_TABLE).click()
    _table_screen(phone)
    _assert_selected(phone, "가타카나", "촉음")
    _assert_still_on_kana(phone, history_length)

    assert _kana_progress(phone)["items"] == {text: {"correct": 1, "wrong": 0}}
    stored = _stored(phone, KANA_KEY)
    assert _stored_keys(phone) == {KANA_KEY, FURIGANA_KEY}

    phone.reload()
    screen = _table_screen(phone)
    expect(phone).to_have_url(re.compile(f"{re.escape(KANA_ROUTE)}$"))
    assert _stored(phone, KANA_KEY) == stored, "새로고침 뒤 가나 진도가 달라졌다"

    save = screen.locator(".kana-save")
    save.locator(".kana-reset-open", has_text=RESET).click()
    expect(save.locator(".kana-confirm-question")).to_have_text(RESET_QUESTION)
    expect(save.locator(".kana-confirm-detail")).to_have_text(RESET_DETAIL)
    expect(save.locator(".kana-confirm-actions button")).to_have_text([RESET_CONFIRM, RESET_CANCEL])
    # 확인은 시트가 아니다.
    assert phone.locator(".sheet, [role=dialog]").count() == 0
    save.locator(".kana-reset-cancel").click()
    expect(save.locator(".kana-save-text")).to_have_text(SAVE_NOTE)
    assert _stored(phone, KANA_KEY) == stored, "취소했는데 진도가 바뀌었다"

    save.locator(".kana-reset-open").click()
    save.locator(".kana-reset-confirm").click()
    expect(phone.locator(".toast")).to_have_text(RESET_DONE)
    expect(save.locator(".kana-save-text")).to_have_text(SAVE_NOTE)
    assert _stored(phone, KANA_KEY) is None, "진도 초기화 뒤에도 nc.kana.v1이 있다"
    assert _stored_keys(phone) == {FURIGANA_KEY}
    assert _stored(phone, FURIGANA_KEY) == furigana, "진도 초기화가 가나 밖의 설정을 건드렸다"

    phone.reload()
    _table_screen(phone)
    assert _stored(phone, KANA_KEY) is None

    _assert_no_requests(phone, traffic)
