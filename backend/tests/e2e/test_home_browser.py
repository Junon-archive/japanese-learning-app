"""홈 셋과 로그인 진입 (mvp-02-onboarding/12_TEST_PLAN.md의 `Browser E2E`, 13_ACCEPTANCE_CRITERIA.md 1~10,
mvp-03-english/12_TEST_PLAN.md의 `E2E (browser)`, MVP-03 합격 기준 20·21).

휴대폰 viewport로 돈다. "서버 요청"은 API origin으로 나간 요청이다(정적 자산 제외).

MVP-03에서 홈이 **2단**이 되었다(ADR-025 결정 2). `#/`는 언어 선택 홈(카드 둘: 일본어·영어)이고,
MVP-02의 체험·글자 카드는 언어별 홈(`#/ja` 둘, `#/en` 하나)으로 내려갔다.

-   hash 없이 열면 방문자가 무슨 앱인지 바로 안다: 앱 이름, `학습하러 가기`, 한 줄 소개, 언어 카드 2개.
    카드에 숫자가 없다. API 요청 0건이다. 언어별 홈의 문구와 카드 수도 `화면 문구 표`와 같다.
-   `학습하러 가기`를 누를 때만 `GET /api/auth/me`가 1건 나간다. 401이면 Login, 로그인하면 Study Screen.
    로그인 영역에는 hash가 없으므로 새로고침하면 언어 선택 홈이고, 다시 `학습하러 가기`를 누르면 곧바로
    Study Screen이다. 로그아웃하면 언어 선택 홈이다.
-   공개 화면 사이에서 뒤로 가기가 동작하고, 모르는 hash는 언어 선택 홈(`#/`)이다. `#/ja/kana`는 가나
    학습이다(카드로 들어가도, 직접 열어도). 옛 경로 `#/demo`는 `#/ja/demo`로 바뀐다. 가나 학습 자체의
    흐름은 `test_kana_browser.py`가, 영어 demo는 `test_english_demo_browser.py`가 본다.
-   **도달 전에 세션을 끝내면 언어를 다시 고를 수 있다**(MVP-03 합격 기준 32). 시계를 옮기지 않는다.
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

# 화면 문구(03_UI_UX_SPEC.md의 `화면 문구 표`의 `상단바와 홈`, `Login과 로그아웃`).
APP_NAME = "Nihongo Context"

# 카드 하나: (제목, 설명, 칩 목록).
Card = tuple[str, str, list[str]]

# 언어 선택 홈(`#/`). 언어를 특정하지 않고, 커버리지 퍼센트도 적지 않는다.
HOME_INTRO = "실제 문장 속에서 표현을 익히는 앱이에요."
HOME_CARDS: list[Card] = [
    ("일본어", "문장 속 표현과 한자 읽기를 익혀요.", []),
    ("영어", "드라마와 대화에서 실제로 쓰는 표현을 익혀요.", []),
]

# 언어별 홈. 체험 카드는 두 언어 공통이고 글자 카드는 일본어 홈에만 있다.
DEMO_CARD: Card = ("표현 학습 체험해 보기", "모르는 표현을 눌러 뜻을 확인해요.", ["로그인 없이"])
KANA_CARD: Card = (
    "글자부터 배우기",
    "히라가나와 가타카나를 표와 퀴즈로 익혀요.",
    ["히라가나", "가타카나"],
)
JA_INTRO = "일본어 표현을 실제 문장 속에서 익히는 앱이에요."
JA_CARDS: list[Card] = [DEMO_CARD, KANA_CARD]
EN_INTRO = "아는 단어인데 안 들리는 표현을 문장 속에서 익혀요."
EN_CARDS: list[Card] = [DEMO_CARD]

LOGGED_OUT_TOAST = "로그아웃했어요."
LOGOUT_LABEL = "로그아웃"
# 언어 선택 화면(로그인 영역, MVP-03). `frontend/src/ui/notice.ts`의 `MESSAGES`가 canonical이다.
LANGUAGE_SELECT_TITLE = "무엇을 공부할까요?"
LANGUAGE_LABELS = ["일본어", "영어"]
HOME_HASH = "#/"
JA_HOME_ROUTE = "#/ja"
EN_HOME_ROUTE = "#/en"
DEMO_ROUTE = "#/ja/demo"
EN_DEMO_ROUTE = "#/en/demo"
KANA_ROUTE = "#/ja/kana"
LEGACY_DEMO_ROUTE = "#/demo"

# 언어 선택 홈의 URL. hash 없음(`''`)과 `#/` 둘 다 이 화면이다(03_UI_UX_SPEC.md의 route 표).
_HOME_URL = re.compile(r"/(#/)?$")

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


def _kana(page: Page) -> None:
    page.locator(".screen.kana").wait_for(
        state="visible", timeout=flow.SETTLE_TIMEOUT_SECONDS * 1000
    )


def _topbar_right(page: Page) -> list[str]:
    return page.locator(".screen .topbar .topbar-actions button").all_inner_texts()


def _expect_home(page: Page, intro: str, cards: list[Card]) -> None:
    """홈 한 곳의 상단바·한 줄 소개·카드가 `화면 문구 표`와 같다. 카드에 숫자가 없다."""
    _home(page)
    screen = page.locator(".screen.home")
    expect(screen.locator(".topbar .topbar-brand")).to_have_text(APP_NAME)
    assert _topbar_right(page) == [flow.LOGIN_LABEL]
    expect(screen.locator("h1")).to_have_text(intro)

    rendered = screen.locator(".home-card")
    expect(rendered).to_have_count(len(cards))
    for index, (title, description, pills) in enumerate(cards):
        card = rendered.nth(index)
        expect(card.locator(".home-card-title")).to_have_text(title)
        expect(card.locator(".home-card-desc")).to_have_text(description)
        if pills:
            expect(card.locator(".pill")).to_have_text(pills)
        else:
            expect(card.locator(".pill")).to_have_count(0)
        # 카드에 문장 수·커버리지 숫자를 적지 않는다.
        assert re.search(r"\d", card.inner_text()) is None, card.inner_text()


# --------------------------------------------------------------------------
# backend를 띄우지 않은 구성
# --------------------------------------------------------------------------


def test_the_home_says_what_the_app_is_without_any_request(frontend: Frontend, phone: Page) -> None:
    """hash 없이 열면 앱 이름, `학습하러 가기`, 한 줄 소개, 언어 카드 2개가 있고 요청은 0건이다."""
    traffic = flow.watch_traffic(
        phone, frontend_url=frontend.url, api_url=frontend.api_url, block=True
    )
    phone.goto(frontend.url)
    _expect_home(phone, HOME_INTRO, HOME_CARDS)

    phone.wait_for_timeout(_LATE_REQUEST_WINDOW_MS)
    traffic.assert_none_outside()
    assert traffic.api_calls == []


def test_the_language_homes_have_the_cards_the_copy_table_says(
    frontend: Frontend, phone: Page
) -> None:
    """언어 선택 홈 -> `#/ja`(카드 둘) / `#/en`(카드 하나). 요청 0건이다 (MVP-03 합격 기준 20).

    영어 홈의 카드가 하나인 것이 단언 대상이다 --- 가나 학습에 대응하는 영어 보조 화면을 만들지
    않기로 했다(ADR-025 결정 2). 카드 하나를 채우려고 없는 기능이 생기면 여기서 빨개진다.
    """
    traffic = flow.watch_traffic(
        phone, frontend_url=frontend.url, api_url=frontend.api_url, block=True
    )
    phone.goto(frontend.url)
    _expect_home(phone, HOME_INTRO, HOME_CARDS)

    flow.press_home_card(phone, HOME_CARDS[0][0])
    expect(phone).to_have_url(re.compile(f"{re.escape(JA_HOME_ROUTE)}$"))
    _expect_home(phone, JA_INTRO, JA_CARDS)

    # 언어 선택 홈으로 돌아가는 길은 상단바 앱 이름이다(언어별 홈이 아니다).
    phone.locator(".topbar .topbar-brand").click()
    expect(phone).to_have_url(re.compile(f"{re.escape(HOME_HASH)}$"))
    _expect_home(phone, HOME_INTRO, HOME_CARDS)

    flow.press_home_card(phone, HOME_CARDS[1][0])
    expect(phone).to_have_url(re.compile(f"{re.escape(EN_HOME_ROUTE)}$"))
    _expect_home(phone, EN_INTRO, EN_CARDS)

    flow.press_home_card(phone, DEMO_CARD[0])
    phone.locator(".screen.demo .sentence").wait_for(state="visible")
    expect(phone).to_have_url(re.compile(f"{re.escape(EN_DEMO_ROUTE)}$"))

    phone.wait_for_timeout(_LATE_REQUEST_WINDOW_MS)
    traffic.assert_none_outside()
    assert traffic.api_calls == []


def test_back_returns_home_from_the_public_screens(frontend: Frontend, phone: Page) -> None:
    """뒤로 가기가 2단 홈을 한 단씩 거슬러 간다. 모르는 hash는 `#/`, 옛 경로는 `#/ja/...`다."""
    traffic = flow.watch_traffic(
        phone, frontend_url=frontend.url, api_url=frontend.api_url, block=True
    )
    phone.goto(frontend.url)
    _home(phone)

    # `#/` -> `#/ja` -> demo -> 뒤로 -> `#/ja` -> 뒤로 -> `#/`.
    flow.press_home_card(phone, HOME_CARDS[0][0])
    expect(phone).to_have_url(re.compile(f"{re.escape(JA_HOME_ROUTE)}$"))
    flow.press_home_card(phone, DEMO_CARD[0])
    phone.locator(".screen.demo .sentence").wait_for(state="visible")
    assert phone.url.endswith(DEMO_ROUTE), phone.url
    phone.go_back()
    _home(phone)
    expect(phone).to_have_url(re.compile(f"{re.escape(JA_HOME_ROUTE)}$"))
    assert phone.locator(".screen.demo").count() == 0

    # `#/ja` -> 가나 -> 뒤로 -> `#/ja` -> 뒤로 -> `#/`.
    flow.press_home_card(phone, KANA_CARD[0])
    _kana(phone)
    expect(phone).to_have_url(re.compile(f"{re.escape(KANA_ROUTE)}$"))
    assert _topbar_right(phone) == [flow.LOGIN_LABEL]
    phone.go_back()
    _home(phone)
    assert phone.locator(".screen.kana").count() == 0
    phone.go_back()
    _home(phone)
    # 처음 열 때 hash가 없었으므로 거슬러 간 끝은 hash 없는 URL이다. 둘 다 언어 선택 홈이다(route 표).
    expect(phone).to_have_url(_HOME_URL)

    # `#/` -> `#/en` -> 영어 demo -> 뒤로 -> `#/en`.
    flow.press_home_card(phone, HOME_CARDS[1][0])
    expect(phone).to_have_url(re.compile(f"{re.escape(EN_HOME_ROUTE)}$"))
    flow.press_home_card(phone, DEMO_CARD[0])
    phone.locator(".screen.demo .sentence").wait_for(state="visible")
    phone.go_back()
    _home(phone)
    expect(phone).to_have_url(re.compile(f"{re.escape(EN_HOME_ROUTE)}$"))

    phone.goto(f"{frontend.url}/#/unknown")
    expect(phone).to_have_url(re.compile(f"{re.escape(HOME_HASH)}$"))
    _home(phone)

    phone.goto(f"{frontend.url}/{KANA_ROUTE}")
    _kana(phone)
    expect(phone).to_have_url(re.compile(f"{re.escape(KANA_ROUTE)}$"))
    assert phone.locator(".screen.home").count() == 0

    # 옛 평면 경로는 중첩 경로로 바뀐다(ADR-025 결정 1). 북마크·PWA 바로가기가 남아 있을 수 있다.
    phone.goto(f"{frontend.url}/{LEGACY_DEMO_ROUTE}")
    phone.locator(".screen.demo .sentence").wait_for(state="visible")
    expect(phone).to_have_url(re.compile(f"{re.escape(DEMO_ROUTE)}$"))

    traffic.assert_none_outside()
    assert traffic.api_calls == []


# --------------------------------------------------------------------------
# backend가 떠 있는 구성
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_login_is_checked_only_from_the_topbar_and_the_login_area_has_no_hash(
    e2e_stack: E2EStack, phone: Page
) -> None:
    """`학습하러 가기` -> 401 Login -> 로그인 -> 언어 선택 -> Study, 새로고침 -> 홈, 다시 -> 곧바로 Study, 로그아웃 -> 홈.

    MVP-03: 열린 study session이 없는 첫 로그인은 **언어 선택 화면**을 지난다(ADR-025 결정 2).
    그 화면에도 hash가 없다. 두 번째 `학습하러 가기`는 열린 session이 있으므로 언어를 다시 묻지 않는다
    --- 그것이 "선택 결과를 저장해 두지 않아도 다시 묻지 않는다"의 e2e 쪽 증거다(합격 기준 11).
    """
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

    # 열린 session이 없으므로 언어 선택 화면이다. 고른 언어로 Study Screen에 들어간다.
    select = phone.locator(".screen.language-select")
    select.wait_for(state="visible", timeout=flow.SETTLE_TIMEOUT_SECONDS * 1000)
    expect(select.locator("h1")).to_have_text(LANGUAGE_SELECT_TITLE)
    expect(select.locator(".home-card")).to_have_text(LANGUAGE_LABELS)
    assert "#" not in phone.url, f"언어 선택 화면에 hash가 생겼다: {phone.url}"
    select.locator(".home-card", has_text=re.compile(f"^{re.escape(LANGUAGE_LABELS[0])}$")).click()

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


@pytest.mark.integration
def test_finishing_before_the_goal_lets_the_user_switch_language(
    e2e_stack: E2EStack, phone: Page
) -> None:
    """도달 **전** 종료 -> 언어 바꾸기 경로 전체 (MVP-03 합격 기준 32, `12_TEST_PLAN.md`의 7단계).

    ``` text
    1  로그인 진입 -> 언어 선택 화면 -> 영어 -> 영어 Study Screen
    2  문장을 하나 넘겨 도달 전 상태를 유지한다
    3  `오늘 목표한 시간을 채웠어요.`와 `더 학습하기`가 없고 `오늘 학습 완료`가 있다
    4  `오늘 학습 완료` -> 완료 화면 (`ended_at`이 채워진다)
    5  상단바 앱 이름 -> 언어 선택 홈
    6  `학습하러 가기` -> **언어 선택 화면**
    7  일본어 -> 일본어 Study Screen (옛 세션의 언어가 아니다)
    ```

    **시계를 옮기지 않는다.** 방금 시작한 세션에서 성립해야 한다는 것이 이 테스트의 요점이다
    --- 옛 결함은 (a) 도달 전에 끝낼 UI가 없고 (b) 언어를 다시 묻는 조건이 "이어서 할 수 있는
    세션이 없을 때"뿐이고 (c) 학습 화면 진입만으로 resume이 idle timeout을 되돌리는 것이
    겹쳐서, **탈출 시도가 탈출 조건을 지우는** 고리였다. 6에서 영어 Study Screen이 나오면 재발이다.

    분 수를 테스트에 적지 않는다. 도달 전은 DB의 `active_seconds`와 세션의 분모로 확인한다.
    """
    stack = e2e_stack
    learner = flow.seed_and_create_user(stack)
    # 영어 콘텐츠는 이 테스트가 준비한다(일본어 seed만으로는 영어 세션에 문장이 없다).
    flow.seed_english_items(stack, count=3)

    # 1. 로그인 -> 언어 선택 -> 영어.
    flow.sign_in(phone, stack, learner, language=flow.LANGUAGE_EN)
    english_session = flow.study_session(stack, learner)
    assert english_session.language.value == "en"

    # 2. 문장 하나를 넘긴다. `/complete` 뒤 `GET /session`으로 진행이 갱신되는 경로도 함께 지난다.
    assert flow.press_next(phone, stack, learner) is not None

    # 3. 도달 전이다(시계를 옮기지 않았다). 안내 문구와 연장 버튼이 없고 종료 버튼이 하나 있다.
    progressed = flow.study_session(stack, learner)
    assert (
        progressed.active_seconds < (progressed.target_minutes + progressed.extended_minutes) * 60
    )
    study = phone.locator(".screen.study")
    assert study.locator(".session-end").count() == 0
    assert study.get_by_text(flow.REACHED_TEXT).count() == 0
    assert study.get_by_text(flow.EXTEND_LABEL).count() == 0
    finish = study.locator(".finish-slot button.session-finish")
    expect(finish).to_have_text(flow.FINISH_LABEL)

    # 4. 끝낸다. 서버는 도달을 이유로 거부하지 않는다(05_API_SPEC.md).
    finish.click()
    phone.locator(".session-finished").wait_for(
        state="visible", timeout=flow.SETTLE_TIMEOUT_SECONDS * 1000
    )
    ended = flow.study_session(stack, learner)
    assert ended.id == english_session.id
    assert ended.ended_at is not None

    # 5. 상단바 앱 이름 -> 언어 선택 홈.
    phone.locator(".topbar .topbar-brand").click()
    _expect_home(phone, HOME_INTRO, HOME_CARDS)

    # 6. 재발 지점. 이어서 할 세션이 없으므로 언어를 **다시 묻는다.**
    flow.press_topbar_login(phone)
    select = phone.locator(flow.LANGUAGE_SELECT_SCREEN)
    select.wait_for(state="visible", timeout=flow.SETTLE_TIMEOUT_SECONDS * 1000)
    expect(select.locator(".home-card")).to_have_text(LANGUAGE_LABELS)
    assert phone.locator(".screen.study").count() == 0, "언어를 묻지 않고 학습 화면으로 갔다(재발)"

    # 7. 일본어를 고르면 **고른 언어로** 새 세션이 시작된다.
    select.locator(".home-card", has_text=re.compile(f"^{re.escape(flow.LANGUAGE_JA)}$")).click()
    flow.wait_for_sentence(phone)
    started = flow.study_session(stack, learner)
    assert started.id != english_session.id
    assert started.language.value == "ja"
