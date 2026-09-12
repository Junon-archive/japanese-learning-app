"""Demo E2E (12_TEST_PLAN.md의 `Demo E2E`).

명세가 demo에 요구하는 것은 기능보다 **경계**다: anonymous visitor가 로그인 없이
체험하고, private user data가 노출되지 않고, paid LLM이 발생하지 않고, **화면이
backend로 네트워크 요청을 하지 않는다**(static fixture).

그래서 이 파일의 기본 구성은 **backend를 띄우지 않는 것**이다. `frontend` fixture만
요구하므로 이 모듈만 단독 실행하면 uvicorn도 pgserver도 뜨지 않고, 번들에 박힌
API origin 포트에는 아무도 listen하지 않는다. 그 구성에서 demo가 열린다는 것이
"`#/demo`가 `fetchMe()`보다 먼저 갈린다"의 실질적 증명이다 --- backend가 죽어도
demo는 열려야 한다.

요청 0건은 두 겹으로 본다.

1.  `page.route`로 frontend origin 밖의 요청을 **전부 abort**한다. 흐름이 그대로
    완주하면 "요청을 안 했다"가 아니라 **"요청이 필요 없다"**가 증명된다.
2.  `page.on("request")`로 전수 수집해 `/api/` 경로가 0건임을 단언한다.

마지막에 backend가 떠 있는 구성으로 같은 것을 한 번 더 본다(맨 아래 테스트).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
import sqlalchemy as sa
from playwright.sync_api import Page, Route
from sqlalchemy.orm import DeclarativeBase, Session

from app.models import ItemExposure, LearningEvent, StudySession
from tests.conftest import no_provider_module_import
from tests.e2e.conftest import E2EStack, Frontend

pytestmark = pytest.mark.e2e

DEMO_ROUTE = "#/demo"

# demo fixture의 모양(`frontend/src/demo/fixture.ts`). 학습 정책값이 아니라 "체험에
# 무엇이 들어 있어야 하는가"이며, 12_TEST_PLAN.md의 Demo E2E 항목을 숫자로 옮긴 것이다.
DEMO_SENTENCE_COUNT = 3
DEMO_TAPPABLE_COUNT = 5
DEMO_PROBE_COUNT = 1

_SETTLE_MS = 300


@dataclass
class Traffic:
    """이 페이지가 낸 요청 전부. demo에서는 frontend origin 안쪽만 있어야 한다."""

    frontend_url: str
    seen: list[str] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)

    @property
    def api_calls(self) -> list[str]:
        return [url for url in self.seen if "/api/" in url]

    @property
    def foreign(self) -> list[str]:
        return [
            url
            for url in self.seen
            if not url.startswith(self.frontend_url) and not url.startswith("data:")
        ]


def _watch(page: Page, frontend_url: str) -> Traffic:
    """frontend origin 밖으로 나가는 요청을 막고 전부 기록한다."""
    traffic = Traffic(frontend_url=frontend_url)

    def handler(route: Route) -> None:
        url = route.request.url
        if url.startswith(frontend_url) or url.startswith("data:"):
            route.continue_()
            return
        traffic.blocked.append(url)
        route.abort()

    page.on("request", lambda request: traffic.seen.append(request.url))
    page.route("**/*", handler)
    return traffic


def _open_demo(page: Page, frontend_url: str) -> Traffic:
    traffic = _watch(page, frontend_url)
    page.goto(f"{frontend_url}{DEMO_ROUTE}")
    page.locator(".demo-banner").wait_for(state="visible")
    page.locator(".sentence").wait_for(state="visible")
    return traffic


def _next_sentence(page: Page) -> None:
    page.locator("button.next").click()
    page.wait_for_timeout(_SETTLE_MS)


def _tap(page: Page, index: int) -> None:
    page.locator(".sentence .token").nth(index).click()
    page.locator(".explain").wait_for(state="visible")


def _panel_text(page: Page, selector: str) -> str:
    return page.locator(f".explain {selector}").inner_text()


def _assert_no_traffic(traffic: Traffic) -> None:
    assert traffic.api_calls == [], f"demo가 backend를 호출했다: {traffic.api_calls}"
    assert traffic.foreign == [], f"demo가 frontend origin 밖으로 나갔다: {traffic.foreign}"
    assert traffic.blocked == [], f"막힌 외부 요청이 있다(즉 시도했다): {traffic.blocked}"


# --------------------------------------------------------------------------
# backend를 띄우지 않은 구성 (기본)
# --------------------------------------------------------------------------


def test_demo_opens_with_no_backend_running(frontend: Frontend, page: Page) -> None:
    """API origin에 아무도 listen하지 않는 상태에서 demo가 열린다.

    이 테스트가 통과한다는 것은 `#/demo`가 `GET /api/auth/me`보다 **먼저** 갈린다는
    뜻이다. 뒤에 두면 여기서 로그인 화면이나 오류 안내가 뜬다.
    """
    traffic = _open_demo(page, frontend.url)

    assert page.locator(".screen.demo").count() == 1
    assert page.locator(".login-form").count() == 0, "demo가 로그인 화면으로 떨어졌다"
    assert page.locator(".notice-slot .notice").count() == 0, "demo가 오류 안내를 띄웠다"
    _assert_no_traffic(traffic)


def test_the_demo_flow_runs_end_to_end_without_any_request(frontend: Frontend, page: Page) -> None:
    """설명 / 번역 / probe / contextual review를 전부 체험하고 요청은 0건이다."""
    traffic = _open_demo(page, frontend.url)

    sentences: list[str] = []
    taps = 0
    probes = 0
    # 같은 item이 anchor -> new_context로 다시 나오는지 보기 위해 설명을 모은다.
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
                (_panel_text(page, ".jp-word"), _panel_text(page, ".meaning-context"))
            )
            taps += 1

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

    # contextual review: 같은 표현이 두 문장에서 **다른 문맥 뜻**으로 나왔다.
    repeated = [word for word, _ in explanations if [w for w, _ in explanations].count(word) > 1]
    assert repeated, f"같은 표현이 다시 나오지 않았다: {[w for w, _ in explanations]}"
    contexts = {meaning for word, meaning in explanations if word == repeated[0]}
    assert len(contexts) > 1, f"같은 표현이 같은 문맥 뜻으로만 나왔다: {contexts}"

    # 마지막 문장 뒤에는 안내와 다시 보기가 남는다(무한 spinner도 오류도 아니다).
    assert page.locator(".notice", has_text="데모 문장을 모두 보았습니다").count() == 1
    _assert_no_traffic(traffic)


def test_the_demo_stores_nothing(frontend: Frontend, page: Page) -> None:
    """localStorage / sessionStorage / cookie가 끝까지 0이다. 상태는 메모리에만 있다."""
    traffic = _open_demo(page, frontend.url)
    for _ in range(DEMO_SENTENCE_COUNT):
        if page.locator(".sentence .token").count() > 0:
            _tap(page, 0)
        _next_sentence(page)

    storage = page.evaluate("() => [localStorage.length, sessionStorage.length, document.cookie]")
    assert storage == [0, 0, ""], f"demo가 저장소를 썼다: {storage}"
    assert page.context.cookies() == [], page.context.cookies()
    _assert_no_traffic(traffic)


def test_the_demo_has_no_path_to_private_data(frontend: Frontend, page: Page) -> None:
    """demo 화면에는 학습 기록도 계정 데이터로 가는 길이 없다.

    나가는 길은 `로그인 화면으로` 하나이며, 그것을 눌러도 요청이 나가지 않는다
    (로그인 화면은 제출 전에는 아무것도 부르지 않는다).
    """
    traffic = _open_demo(page, frontend.url)

    assert page.locator(".history-link").count() == 0, "demo에 학습 기록 진입점이 있다"
    assert page.locator(".screen.history").count() == 0

    page.locator(".demo-exit").click()
    page.locator(".login-form").wait_for(state="visible")
    page.wait_for_timeout(_SETTLE_MS)

    assert page.locator(".sentence").count() == 0
    _assert_no_traffic(traffic)


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
    traffic = _watch(page, e2e_stack.frontend_url)

    with no_provider_module_import():
        page.goto(f"{e2e_stack.frontend_url}{DEMO_ROUTE}")
        page.locator(".demo-banner").wait_for(state="visible")
        page.locator(".sentence").wait_for(state="visible")
        for _ in range(DEMO_SENTENCE_COUNT):
            if page.locator(".sentence .token").count() > 0:
                _tap(page, 0)
                page.locator(".reveal-translation").click()
                page.locator(".translation").wait_for(state="visible")
            _next_sentence(page)

    _assert_no_traffic(traffic)
    # 서버 쪽에도 흔적이 없다. demo는 session도 event도 만들지 않는다.
    with e2e_stack.sessions() as db:
        assert _count(db, StudySession) == 0
        assert _count(db, LearningEvent) == 0
        assert _count(db, ItemExposure) == 0


def _count(db: Session, model: type[DeclarativeBase]) -> int:
    return int(db.execute(sa.select(sa.func.count()).select_from(model)).scalar_one())
