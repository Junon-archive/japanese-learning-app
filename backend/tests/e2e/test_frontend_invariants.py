"""frontend가 지켜야 하는 불변식을 브라우저로 확인한다.

여기 모인 것들은 **화면에서는 전부 정상으로 보인다.** 그래서 DOM 단언만으로는
잡히지 않고, 서버·DB까지 함께 보아야 드러난다.

-   no-click을 Known으로 추론하면 mastery가 올라가고 화면은 똑같다.
-   연타가 두 번의 진행이 되면 없던 노출이 생기고 진행은 오히려 잘 되는 것처럼 보인다.
-   재시도가 새 key를 발급하면 자가보고 하나가 EMA를 두 번 돈다.
-   번역을 미리 받아 숨겨 두면 `translation_revealed`가 "봤다"를 뜻하지 못한다.
-   이탈에 `sendBeacon`을 달면 보지 않은 문장이 완료로 확정된다.
-   빈 pool을 폴링하면 서버 `touch()`가 자리를 비운 시간을 학습 시간으로 누적한다.
-   진행바에 정책값을 하드코딩하면 config를 바꾼 배포에서 화면이 거짓을 말한다.
-   공개 화면이 API나 제3자에게 요청을 보내도 화면은 똑같이 뜬다(불변식 13·14).
-   설명 시트를 다시 열 때마다 event를 보내면 raw history가 시트 여닫기 횟수를 센다.
-   떠난 화면에 늦게 온 `/click` 응답으로 `explanation_revealed`를 보내면 보지 않은 설명이 "표시됐다"가 된다.

정책값은 전부 `use_config()`로 주입하고 기대값을 그 주입값에서 유도한다
(13_ACCEPTANCE_CRITERIA.md의 `수치 취급 원칙`).
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

import pytest
import sqlalchemy as sa
from playwright.sync_api import Browser, Page, Request, Route, expect

from app.config import AppConfig, get_config
from app.learning.mastery import OBSERVATION, ema
from app.models import ItemExposure, LearningEvent, ReviewState, Sentence
from app.models.enums import EventType, ExplicitSignal
from tests.conftest import override_config
from tests.e2e import study_flow as flow
from tests.e2e.conftest import E2EStack, Frontend

# DB를 쓰는 테스트에만 `integration`을 단다. 공개 화면 검사는 backend 없이 `frontend` fixture만 쓴다
# (`test_marker_hygiene.py`).
pytestmark = pytest.mark.e2e

# 기본값과 **다른** 값을 주입한다. 기본값을 쓰면 config를 읽지 않는 구현도 통과한다.
DEFERRAL_HOURS = 7
SESSION_MINUTES = 7
MINIMUM_EXPOSURES = 3

# 폴링이 있으면 이 안에 반드시 드러난다. 12_TEST_PLAN.md가 요구한 유지 시간이다.
IDLE_HOLD_SECONDS = 30

# 빈 pool까지 눌러 볼 횟수 상한. 정책값이 아니라 무한 루프 방지다.
MAX_DRAIN_PRESSES = 24

# self-report 3종. `무신호`가 정말 무신호인지 보려면 세 종류 전부를 세어야 한다.
SELF_REPORT_EVENTS = (
    EventType.SELF_REPORT_KNOWN,
    EventType.SELF_REPORT_UNCERTAIN,
    EventType.SELF_REPORT_UNKNOWN,
)

# 무신호 review가 **절대 건드리면 안 되는** 것들. `deferred_until`만 빠져 있다
# (07_SRS_SPEC.md의 `No-signal review`).
UNTOUCHED_BY_NO_SIGNAL = (
    "stability",
    "difficulty",
    "state",
    "step",
    "reps",
    "lapses",
    "next_review_at",
    "last_review_at",
)


def _cfg(**learning: object) -> AppConfig:
    return override_config(get_config(), learning=learning)


@dataclass(frozen=True)
class _Started:
    learner: flow.Learner
    focus_id: int


def _start(stack: E2EStack, page: Page, cfg: AppConfig, *, supply: int = 0) -> _Started:
    """주입한 config로 로그인까지. 모든 불변식 테스트의 공통 전제다."""
    stack.use_config(cfg)
    learner = flow.seed_and_create_user(stack)
    focus = flow.focus_item(stack)
    if supply:
        flow.supply_sentences(stack, item_id=focus.id, count=supply)
    flow.sign_in(page, stack, learner)
    return _Started(learner=learner, focus_id=focus.id)


def _self_report_count(stack: E2EStack, learner: flow.Learner) -> int:
    with flow.read_db(stack) as db:
        return int(
            db.execute(
                sa.select(sa.func.count(LearningEvent.id)).where(
                    LearningEvent.user_id == learner.user_id,
                    LearningEvent.event_type.in_(SELF_REPORT_EVENTS),
                )
            ).scalar_one()
        )


def _snapshot(state: ReviewState) -> dict[str, object]:
    return {name: getattr(state, name) for name in UNTOUCHED_BY_NO_SIGNAL}


# --------------------------------------------------------------------------
# no-click을 Known으로 추론하지 않는다 (불변식 #2)
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_completing_without_a_signal_defers_and_leaves_memory_state_alone(
    e2e_stack: E2EStack, page: Page
) -> None:
    """self-report 없이 `다음 문장`을 누른 review는 **deferral 하나만** 남긴다.

    화면에서는 그냥 문장을 넘긴 것이고, 그것이 요점이다: 넘긴 것을 "알고 있었다"로
    읽으면 mastery가 조용히 올라간다.
    """
    stack = e2e_stack
    started = _start(
        stack,
        page,
        _cfg(
            passive_review_deferral_hours=DEFERRAL_HOURS,
            minimum_meaningful_exposures=MINIMUM_EXPOSURES,
        ),
        supply=2,
    )
    learner, focus_id = started.learner, started.focus_id

    # review_states 행을 만든다. 무신호 deferral은 `review` role에만 적용되고
    # (new/exploration에는 defer할 스케줄이 없다) 그 role에 닿으려면 신호가 한 번
    # 있어야 한다.
    first = flow.advance_to_item(page, stack, learner, item_id=focus_id)
    flow.tap(page, flow.token_index(stack, first, learning_item_id=focus_id))
    flow.self_report(page, flow.UNKNOWN)
    flow.press_next(page, stack, learner)

    state = flow.review_state(stack, learner, item_id=focus_id)
    stack.clock.set(flow.utc(state.next_review_at))
    assert flow.reopen(page, stack, learner) is not None
    review = flow.advance_to_item(
        page,
        stack,
        learner,
        item_id=focus_id,
        where=lambda row: flow.is_target_review(stack, row, item_id=focus_id),
    )
    assert review.presentation_role.value == "review"

    before = _snapshot(flow.review_state(stack, learner, item_id=focus_id))
    signals_before = _self_report_count(stack, learner)
    mastery_before = flow.mastery(stack, learner, item_id=focus_id)
    assert mastery_before is not None
    completed_at = stack.clock.now()

    # **아무 버튼도 누르지 않고** 다음 문장으로 넘긴다.
    flow.press_next(page, stack, learner)

    after = flow.review_state(stack, learner, item_id=focus_id)
    assert _snapshot(after) == before, "무신호 review가 FSRS memory state를 건드렸다"
    assert after.deferred_until is not None, "무신호 review가 deferral을 걸지 않았다"
    # 주입한 값에서 유도한다. 기본값을 적으면 config를 읽지 않는 구현도 통과한다.
    assert flow.utc(after.deferred_until) == completed_at + timedelta(hours=DEFERRAL_HOURS)

    assert _self_report_count(stack, learner) == signals_before, "무신호인데 자가보고가 생겼다"
    mastery_after = flow.mastery(stack, learner, item_id=focus_id)
    assert mastery_after is not None
    assert mastery_after.evidence_count == mastery_before.evidence_count
    assert mastery_after.comprehension_mastery == mastery_before.comprehension_mastery


# --------------------------------------------------------------------------
# 노출은 제시당 item당 1회다 (07_SRS_SPEC.md의 `중복 집계 금지`)
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_hammering_next_advances_exactly_one_presentation(e2e_stack: E2EStack, page: Page) -> None:
    """`다음 문장`을 3연타해도 진행은 1이고 exposure가 중복되지 않는다.

    JS에서 연속으로 세 번 누른다 --- Playwright의 클릭 사이 대기 없이 같은 tick에
    보내야 단일 비행(`busy`)과 in-flight 합치기가 실제로 검사된다.
    """
    stack = e2e_stack
    started = _start(stack, page, _cfg(minimum_meaningful_exposures=MINIMUM_EXPOSURES))
    learner = started.learner

    opened = flow.open_presentation(stack, learner)
    assert opened is not None
    before = len(flow.presentations(stack, learner))

    page.evaluate(
        """() => {
            const button = document.querySelector('button.next');
            button.click();
            button.click();
            button.click();
        }"""
    )

    # 진행이 정착할 때까지 기다린 뒤, 늦게 도착한 두 번째/세 번째 진행이 없는지 본다.
    flow.wait_for_open_presentation_change(stack, learner, previous_id=opened.id)
    page.wait_for_timeout(1000)

    after = flow.presentations(stack, learner)
    assert len(after) == before + 1, (
        f"연타가 presentation을 {len(after) - before}개 만들었다 (1이어야 한다)"
    )

    made = [row for row in flow.exposures(stack, learner) if row.study_presentation_id == opened.id]
    item_ids = [row.learning_item_id for row in made]
    assert len(item_ids) == len(set(item_ids)), f"같은 제시에 중복 exposure: {item_ids}"

    with flow.read_db(stack) as db:
        completions = int(
            db.execute(
                sa.select(sa.func.count(LearningEvent.id)).where(
                    LearningEvent.study_presentation_id == opened.id,
                    LearningEvent.event_type == EventType.SENTENCE_COMPLETED,
                )
            ).scalar_one()
        )
    assert completions == 1


# --------------------------------------------------------------------------
# 재시도는 같은 key를 다시 보낸다 (ADR-008, 불변식 #10)
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_a_retried_self_report_applies_evidence_once(e2e_stack: E2EStack, page: Page) -> None:
    """응답을 잃은 자가보고를 재시도해도 evidence가 한 번만 적용된다.

    첫 시도는 **서버까지 도달시킨 뒤** 응답을 버린다(`route.fetch()` 후 `abort()`).
    그래야 "요청이 도착했는데 응답이 없어서 재시도한" 실제 상황이 된다 --- 단순히
    abort하면 서버는 아무것도 받지 않으므로 중복 적용이 애초에 불가능하다.

    client가 재시도에 새 UUID를 발급하면 서버의 `(user_id, client_event_id)` 중복
    방지가 통하지 않아 EMA가 두 번 돈다. 화면은 어느 쪽이든 `기록했습니다`다.
    """
    stack = e2e_stack
    cfg = _cfg(minimum_meaningful_exposures=MINIMUM_EXPOSURES)
    started = _start(stack, page, cfg)
    learner, focus_id = started.learner, started.focus_id

    attempts: list[str] = []

    def handler(route: Route) -> None:
        attempts.append(route.request.post_data or "")
        if len(attempts) == 1:
            # 서버는 처리한다. 브라우저는 응답을 받지 못한다.
            route.fetch()
            route.abort()
            return
        route.continue_()

    page.route("**/self-report", handler)

    presentation = flow.advance_to_item(page, stack, learner, item_id=focus_id)
    flow.tap(page, flow.token_index(stack, presentation, learning_item_id=focus_id))
    flow.self_report(page, flow.UNKNOWN)
    page.unroute("**/self-report")

    assert len(attempts) >= 2, "재시도가 일어나지 않아 이 테스트는 아무것도 보지 않았다"
    assert len(set(attempts)) == 1, (
        "재시도가 body를 새로 만들었다(client_event_id가 달라졌다). "
        f"서로 다른 body {len(set(attempts))}개: {attempts}"
    )

    events = flow.events(stack, learner, event_type=EventType.SELF_REPORT_UNKNOWN)
    assert len(events) == 1, f"자가보고 event가 {len(events)}건이다"

    mastery = flow.mastery(stack, learner, item_id=focus_id)
    assert mastery is not None
    assert mastery.evidence_count == 1
    # EMA가 **한 번만** 돌았다. 두 번 돌면 값이 0.0에 더 가까워지므로 값으로 잡는다.
    assert mastery.comprehension_mastery == pytest.approx(
        ema(None, OBSERVATION[ExplicitSignal.UNKNOWN], cfg.learning.mastery_ema_alpha)
    )


# --------------------------------------------------------------------------
# 번역은 호출 뒤에 온다 (05_API_SPEC.md)
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_the_translation_exists_only_after_the_reveal_call_succeeds(
    e2e_stack: E2EStack, page: Page
) -> None:
    """reveal 전에는 번역 문자열이 **문서에 아예 없다.**

    DOM 단언만으로는 "미리 받아 숨겨 두고 CSS로 토글하는" 구현이 통과한다. 그래서
    세 겹으로 본다.

    1.  누르기 전: 번역 문자열이 `page.content()`에 없다.
    2.  요청을 막으면: 눌러도 번역이 나타나지 않고 실패 문구가 남는다 --- 화면이
        번역을 **가지고 있지 않다**는 증거다.
    3.  요청을 허용하면: 요청이 먼저 나가고 그 뒤에 번역 노드가 생긴다.
    """
    stack = e2e_stack
    started = _start(stack, page, _cfg(minimum_meaningful_exposures=MINIMUM_EXPOSURES))
    learner = started.learner

    opened = flow.open_presentation(stack, learner)
    assert opened is not None
    with flow.read_db(stack) as db:
        korean = db.execute(
            sa.select(Sentence.korean_translation).where(Sentence.id == opened.sentence_id)
        ).scalar_one()

    assert korean not in page.content(), "reveal 전에 번역이 이미 문서에 있다"
    assert page.locator(".translation").count() == 0

    blocked: list[str] = []

    def block(route: Route) -> None:
        blocked.append(route.request.url)
        route.abort()

    page.route("**/translation/reveal", block)
    page.locator(".reveal-translation").click()
    page.locator(".translation-area .panel-failure").wait_for(
        state="visible", timeout=flow.SETTLE_TIMEOUT_SECONDS * 1000
    )
    assert blocked, "번역 버튼이 요청을 보내지 않았다"
    assert page.locator(".translation").count() == 0
    assert korean not in page.content(), "요청이 막혔는데 번역이 화면에 있다"
    page.unroute("**/translation/reveal")

    requested_at: list[float] = []
    page.on(
        "request",
        lambda request: (
            requested_at.append(time.monotonic()) if "/translation/reveal" in request.url else None
        ),
    )
    page.locator(".reveal-translation").click()
    page.locator(".translation").wait_for(
        state="visible", timeout=flow.SETTLE_TIMEOUT_SECONDS * 1000
    )
    shown_at = time.monotonic()

    assert requested_at, "두 번째 시도에서도 요청이 나가지 않았다"
    assert requested_at[0] < shown_at
    assert page.locator(".translation").inner_text() == korean

    with flow.read_db(stack) as db:
        revealed = int(
            db.execute(
                sa.select(sa.func.count(LearningEvent.id)).where(
                    LearningEvent.user_id == learner.user_id,
                    LearningEvent.event_type == EventType.TRANSLATION_REVEALED,
                )
            ).scalar_one()
        )
    # 막힌 시도는 event를 만들지 않는다. "봤다"는 성공한 reveal 하나뿐이다.
    assert revealed == 1


# --------------------------------------------------------------------------
# 이탈은 아무것도 확정하지 않는다 (불변식 #2)
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_leaving_the_page_mutates_nothing(e2e_stack: E2EStack, page: Page) -> None:
    """탭 숨김 / pagehide / 실제 이탈에서 요청이 하나도 나가지 않는다.

    `sendBeacon`으로 완료를 보내면 사용자가 보지 않은 문장에 exposure가 생긴다.
    beacon도 네트워크 요청이므로 요청 수집으로 함께 잡힌다.
    """
    stack = e2e_stack
    started = _start(stack, page, _cfg(minimum_meaningful_exposures=MINIMUM_EXPOSURES))
    learner = started.learner

    opened = flow.open_presentation(stack, learner)
    assert opened is not None
    events_before = len(flow.events(stack, learner))

    sent: list[str] = []
    page.on("request", lambda request: sent.append(request.url))

    page.evaluate(
        """() => {
            document.dispatchEvent(new Event('visibilitychange'));
            window.dispatchEvent(new Event('blur'));
            window.dispatchEvent(new Event('pagehide'));
            window.dispatchEvent(new Event('beforeunload'));
        }"""
    )
    page.wait_for_timeout(500)
    # 실제 이탈. unload/pagehide가 진짜로 발생한다.
    page.goto("about:blank")
    page.wait_for_timeout(1000)

    api_calls = [url for url in sent if "/api/" in url]
    assert api_calls == [], f"이탈 경로가 요청을 보냈다: {api_calls}"
    assert len(flow.events(stack, learner)) == events_before

    still_open = flow.open_presentation(stack, learner)
    assert still_open is not None
    assert still_open.id == opened.id, "이탈이 presentation을 완료로 확정했다"
    assert still_open.completed_at is None


# --------------------------------------------------------------------------
# 자동 폴링이 없다 (05_API_SPEC.md: `touch()`가 idle을 학습시간으로 만든다)
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_an_empty_pool_does_not_poll_and_does_not_accrue_active_time(
    e2e_stack: E2EStack, page: Page
) -> None:
    """`presentation: null` 상태를 30초 유지해도 요청이 0건이고 학습시간이 늘지 않는다.

    폴링은 **화면상 오히려 잘 도는 것처럼 보인다.** 서버의 `touch()`가 자리를 비운
    시간을 `active_seconds`로 누적하므로 진행바까지 움직인다.
    """
    stack = e2e_stack
    started = _start(stack, page, _cfg(minimum_meaningful_exposures=MINIMUM_EXPOSURES))
    learner = started.learner

    # pool을 비운다. 사용자가 할 수 있는 동작(Next)만 쓴다.
    for _ in range(MAX_DRAIN_PRESSES):
        if flow.press_next(page, stack, learner) is None:
            break
    else:
        raise AssertionError("pool이 비워지지 않았다 --- 이 테스트의 전제가 성립하지 않는다")

    page.locator(".notice", has_text=flow.EMPTY_POOL_TEXT).wait_for(state="visible")
    before = flow.study_session(stack, learner)

    sent: list[str] = []
    page.on("request", lambda request: sent.append(request.url))
    page.wait_for_timeout(IDLE_HOLD_SECONDS * 1000)

    assert sent == [], f"{IDLE_HOLD_SECONDS}초 동안 자동 요청이 나갔다: {sent}"

    after = flow.study_session(stack, learner)
    assert after.active_seconds == before.active_seconds
    assert after.last_activity_at == before.last_activity_at


# --------------------------------------------------------------------------
# 진행 표시는 config를 따른다
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_the_progress_bar_follows_the_configured_session_length(
    e2e_stack: E2EStack, page: Page
) -> None:
    """`default_session_minutes`를 주입한 값이 화면 문구와 `aria-valuemax`에 그대로 온다.

    화면이 12를 적어 두고 있으면 여기서 빨개진다. 기대값은 주입값에서 유도한다.
    """
    stack = e2e_stack
    started = _start(stack, page, _cfg(default_session_minutes=SESSION_MINUTES))
    learner = started.learner

    session = flow.study_session(stack, learner)
    assert session.target_minutes == SESSION_MINUTES, (
        "서버가 주입한 세션 길이를 쓰지 않았다 --- 화면 단언이 무의미해진다"
    )
    assert session.extended_minutes == 0

    bar = page.locator(".progress-bar")
    total_seconds = (session.target_minutes + session.extended_minutes) * 60
    assert bar.get_attribute("aria-valuemax") == str(total_seconds)
    assert bar.get_attribute("aria-valuenow") == str(session.active_seconds)

    assert f"{SESSION_MINUTES}분" in page.locator(".progress-label").inner_text()
    done_minutes = session.active_seconds // 60
    assert (
        page.locator(".progress-readout").inner_text() == f"{done_minutes}분 / {SESSION_MINUTES}분"
    )


# --------------------------------------------------------------------------
# 노출당 evidence 1건 (07_SRS_SPEC.md)
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_the_server_rejects_a_second_evidence_for_the_same_exposure(
    e2e_stack: E2EStack, page: Page
) -> None:
    """UI는 잠그고 **서버도** 막는다.

    두 번째 시도를 만들려면 UI를 우회해야 한다(버튼이 사라지므로). 브라우저 안에서
    직접 POST하고 409와 사유 문구를 확인한다 --- 화면의 잠금이 유일한 방어선이면
    스크립트 한 줄로 evidence가 두 번 적용된다.
    """
    stack = e2e_stack
    cfg = _cfg(minimum_meaningful_exposures=MINIMUM_EXPOSURES)
    started = _start(stack, page, cfg)
    learner, focus_id = started.learner, started.focus_id

    presentation = flow.advance_to_item(page, stack, learner, item_id=focus_id)
    sentence_item_id = flow.sentence_item_id(stack, presentation, learning_item_id=focus_id)
    flow.tap(page, flow.token_index(stack, presentation, learning_item_id=focus_id))
    flow.self_report(page, flow.UNKNOWN)

    # 화면 쪽 잠금: 버튼이 사라지고 기록 문구가 남는다.
    assert page.locator(".explain .self-report").count() == 0
    assert page.locator(".explain .feedback-done").count() == 1

    result = page.evaluate(
        """async ({url, body}) => {
            const response = await fetch(url, {
                method: 'POST',
                credentials: 'include',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(body),
            });
            let detail = '';
            try { detail = (await response.json()).detail ?? ''; } catch { detail = ''; }
            return {status: response.status, detail: String(detail)};
        }""",
        {
            "url": f"{stack.api_url}/api/study/presentations/{presentation.id}/self-report",
            "body": {
                # 새 key다. 재전송이 아니라 **다른** 자가보고 시도다.
                "client_event_id": str(uuid.uuid4()),
                "sentence_item_id": sentence_item_id,
                "value": ExplicitSignal.KNOWN.value,
            },
        },
    )
    assert result["status"] == 409, result
    assert "evidence" in result["detail"].lower(), result

    mastery = flow.mastery(stack, learner, item_id=focus_id)
    assert mastery is not None
    assert mastery.evidence_count == 1
    # 거부된 시도가 값을 바꾸지 않았다. `알고 있었음`이 적용됐다면 값이 올라간다.
    assert mastery.comprehension_mastery == pytest.approx(
        ema(None, OBSERVATION[ExplicitSignal.UNKNOWN], cfg.learning.mastery_ema_alpha)
    )
    assert len(flow.events(stack, learner, event_type=EventType.SELF_REPORT_KNOWN)) == 0

    # exposure도 늘지 않았다(409면 event를 기록하지 않는다).
    with flow.read_db(stack) as db:
        exposures = int(
            db.execute(
                sa.select(sa.func.count(ItemExposure.id)).where(
                    ItemExposure.study_presentation_id == presentation.id,
                    ItemExposure.learning_item_id == focus_id,
                )
            ).scalar_one()
        )
    assert exposures == 0, "완료하지 않은 제시에 exposure가 생겼다"


# --------------------------------------------------------------------------
# 공개 화면은 frontend origin 밖으로 요청을 내지 않는다 (불변식 13·14, 격리 검사 (f))
# --------------------------------------------------------------------------

# 공개 route. `#/kana`는 Wave 2에서 route 표에 없어 선택 홈(`#/`)으로 떨어진다. Wave 3 kana-ui가
# 가나 학습 화면을 더하면 그 조작도 여기서 본다.
PUBLIC_ROUTES = ("", "#/demo", "#/kana")
HOME_HASH = "#/"
DEMO_CARD_TITLE = "표현 학습 체험해 보기"
KANA_CARD_TITLE = "글자부터 배우기"

# 조작 뒤 늦게 나가는 요청(타이머, 토스트 등)이 드러날 때까지 기다리는 시간. 정책값이 아니다.
_LATE_REQUEST_WINDOW_MS = 2000


def _operate_demo(page: Page) -> None:
    """demo에서 사용자가 하는 것: 탭, 시트 닫기, 번역, 다음 문장."""
    page.locator(".screen.demo .sentence").wait_for(state="visible")
    flow.tap(page, 0)
    flow.close_sheet(page)
    page.locator(".reveal-translation").click()
    page.locator(".translation").wait_for(state="visible")
    page.locator("button.next").click()
    page.locator(".screen.demo .sentence").wait_for(state="visible")


def _operate_home(page: Page) -> None:
    """선택 홈에서 두 카드를 누르고 돌아온다."""
    page.locator(".screen.home").wait_for(state="visible")
    page.locator(".home-card", has_text=DEMO_CARD_TITLE).click()
    _operate_demo(page)
    page.locator(".topbar .topbar-brand").click()
    page.locator(".screen.home").wait_for(state="visible")
    page.locator(".home-card", has_text=KANA_CARD_TITLE).click()
    # Wave 2: 가나 학습 route가 아직 없어 선택 홈(`#/`)이다.
    expect(page).to_have_url(re.compile(f"{re.escape(HOME_HASH)}$"))
    page.locator(".screen.home").wait_for(state="visible")
    page.go_back()
    page.locator(".screen.home").wait_for(state="visible")


@pytest.mark.parametrize("route", PUBLIC_ROUTES)
def test_public_screens_send_nothing_outside_the_frontend_origin(
    frontend: Frontend, page: Page, route: str
) -> None:
    """API origin에 아무도 listen하지 않는 구성에서 공개 화면을 열고 조작해도 요청이 0건이다.

    API origin과 제3자 origin을 가리지 않는다. 막아 두고(`block=True`) 흐름이 끝까지 가므로
    "요청이 필요 없다"까지 본다. 로그인은 누르지 않는다 --- 누를 때의 1건은 아래 테스트가 본다.
    """
    traffic = flow.watch_traffic(
        page, frontend_url=frontend.url, api_url=frontend.api_url, block=True
    )
    page.goto(f"{frontend.url}/{route}")

    if route == "#/demo":
        _operate_demo(page)
        page.locator(".topbar .topbar-brand").click()
        _operate_home(page)
    elif route == "#/kana":
        # Wave 2의 #/kana는 선택 홈(#/)이다.
        expect(page).to_have_url(re.compile(f"{re.escape(HOME_HASH)}$"))
        page.locator(".screen.home").wait_for(state="visible")
        _operate_home(page)
    else:
        _operate_home(page)

    page.wait_for_timeout(_LATE_REQUEST_WINDOW_MS)
    traffic.assert_none_outside()
    assert traffic.api_calls == []


@pytest.mark.integration
def test_only_the_topbar_login_checks_the_login_state_once(e2e_stack: E2EStack, page: Page) -> None:
    """공개 화면을 열 때는 요청이 없고, 상단바 `로그인`을 누르면 `GET /api/auth/me`가 정확히 1건이다.

    backend가 떠 있어서 요청이 가면 답이 온다(쿠키가 없으므로 401 -> Login). 죽은 포트에서는
    `api.ts`가 연결 실패를 유한 번 다시 보내므로 "1건"을 볼 수 없다.
    """
    traffic = flow.watch_traffic(
        page, frontend_url=e2e_stack.frontend_url, api_url=e2e_stack.api_url, block=False
    )
    for route in PUBLIC_ROUTES:
        page.goto(f"{e2e_stack.frontend_url}/{route}")
        page.locator(".topbar .topbar-login").wait_for(state="visible")
    page.wait_for_timeout(_LATE_REQUEST_WINDOW_MS)
    assert traffic.api_calls == [], f"공개 화면이 열리면서 API를 불렀다: {traffic.api_calls}"

    flow.press_topbar_login(page)
    page.locator(".login-form").wait_for(
        state="visible", timeout=flow.SETTLE_TIMEOUT_SECONDS * 1000
    )
    page.wait_for_timeout(_LATE_REQUEST_WINDOW_MS)
    assert traffic.api_calls == ["GET /api/auth/me"]


# --------------------------------------------------------------------------
# reduced-motion: 화면 진입과 설명 시트에 이동이 없다 (03_UI_UX_SPEC.md의 `reduced-motion`)
# --------------------------------------------------------------------------

_MOTION_AT_START = """(selector) => {
    const element = document.querySelector(selector);
    if (element === null) return null;
    const animations = element.getAnimations();
    for (const animation of animations) {
        animation.pause();
        animation.currentTime = 0;
    }
    const style = getComputedStyle(element);
    return {animations: animations.length, translate: style.translate, transform: style.transform};
}"""


def _motion_on_entry(
    browser: Browser, frontend: Frontend, reduced_motion: Literal["reduce", "no-preference"]
) -> dict[str, object]:
    """선택 홈 -> demo 화면 진입과 설명 시트가 **시작 순간** 어디에 있는지.

    애니메이션이 끝나면 `getAnimations()`에서 사라지므로 문서 타임라인을 멈춘다(CDP). 멈춘 뒤 새로
    시작한 애니메이션은 시작 프레임에 머문다.
    """
    context = browser.new_context(reduced_motion=reduced_motion)
    try:
        page = context.new_page()
        traffic = flow.watch_traffic(
            page, frontend_url=frontend.url, api_url=frontend.api_url, block=True
        )
        page.goto(frontend.url)
        page.locator(".screen.home").wait_for(state="visible")

        cdp = context.new_cdp_session(page)
        cdp.send("Animation.enable")
        cdp.send("Animation.setPlaybackRate", {"playbackRate": 0})

        page.locator(".home-card", has_text=DEMO_CARD_TITLE).click()
        page.locator(".screen.demo .sentence .token").first.wait_for(state="attached")
        screen = page.evaluate(_MOTION_AT_START, ".screen.demo")

        page.locator(".screen.demo .sentence .token").first.dispatch_event("click")
        page.locator(".sheet .explain").wait_for(state="attached")
        sheet = page.evaluate(_MOTION_AT_START, ".sheet")

        traffic.assert_none_outside()
        return {"screen": screen, "sheet": sheet}
    finally:
        context.close()


def test_reduced_motion_removes_movement_from_screen_entry_and_the_sheet(
    frontend: Frontend, browser: Browser
) -> None:
    """`prefers-reduced-motion: reduce`이면 화면 진입과 시트의 시작 위치가 제자리다(translate/transform 없음).

    양성 대조군: 같은 측정이 기본 설정에서는 이동을 본다. 그렇지 않으면 이 측정은 아무것도 보지 않는다.
    """
    normal = _motion_on_entry(browser, frontend, "no-preference")
    reduced = _motion_on_entry(browser, frontend, "reduce")

    for part in ("screen", "sheet"):
        moving = normal[part]
        assert isinstance(moving, dict), normal
        assert moving["animations"] > 0, f"기본 설정에서 {part} 애니메이션이 없다: {normal}"
        assert _displaced(moving), f"기본 설정에서 {part}이 움직이지 않는다: {normal}"

        still = reduced[part]
        assert isinstance(still, dict), reduced
        assert not _displaced(still), f"reduced-motion인데 {part}이 이동한다: {reduced}"


def _displaced(motion: dict[str, object]) -> bool:
    """시작 순간 제자리에서 벗어나 있는가.

    `translate: none`에서 시작하는 애니메이션의 계산값은 Chrome에서 `0px`다(보간을 위해 0으로 바꾼다).
    그래서 문자열 `none`이 아니라 **이동량이 0인가**를 본다. transform은 `none`이거나 항등 행렬이어야 한다.
    """
    translate = str(motion["translate"])
    moved = translate != "none" and any(
        float(part.rstrip("px%")) != 0 for part in translate.split()
    )
    transform = str(motion["transform"])
    return moved or transform not in ("none", "matrix(1, 0, 0, 1, 0, 0)")


# --------------------------------------------------------------------------
# localStorage 접근이 던져도 공개 화면이 동작한다 (불변식 18)
# --------------------------------------------------------------------------

_THROWING_STORAGE = """(() => {
    const deny = () => { throw new DOMException('storage denied', 'SecurityError'); };
    for (const target of [window, Window.prototype]) {
        try {
            Object.defineProperty(target, 'localStorage', {get: deny, configurable: true});
        } catch (error) {
            // 이미 설정 불가한 쪽은 넘어간다. 아래 양성 대조군이 실제로 던지는지 본다.
        }
    }
})();"""


def test_public_screens_work_when_local_storage_throws(
    frontend: Frontend, browser: Browser
) -> None:
    """localStorage 접근이 던지는 페이지에서 선택 홈과 Demo가 정상 동작하고 잡히지 않은 오류가 없다.

    가나 학습과 후리가나 토글은 Wave 3 레인이 그 화면을 더할 때 여기에 조작을 더한다.
    """
    context = browser.new_context()
    try:
        context.add_init_script(_THROWING_STORAGE)
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        traffic = flow.watch_traffic(
            page, frontend_url=frontend.url, api_url=frontend.api_url, block=True
        )

        page.goto(frontend.url)
        # 양성 대조군: 이 페이지에서는 정말로 던진다.
        probe = "() => { try { void window.localStorage; return 'no-throw'; } catch (e) { return 'threw'; } }"
        assert page.evaluate(probe) == "threw"

        _operate_home(page)
        page.goto(f"{frontend.url}/#/demo")
        _operate_demo(page)

        assert errors == [], f"잡히지 않은 오류: {errors}"
        traffic.assert_none_outside()
    finally:
        context.close()


# --------------------------------------------------------------------------
# 설명 시트 재열기와 떠난 뒤 늦은 /click (05_API_SPEC.md의 `explanation_revealed를 언제 보내는가`)
# --------------------------------------------------------------------------


def _interaction_counts(
    stack: E2EStack, presentation_id: int, item_id: int
) -> dict[EventType, int]:
    with flow.read_db(stack) as db:
        rows = db.execute(
            sa.select(LearningEvent.event_type, sa.func.count(LearningEvent.id))
            .where(
                LearningEvent.study_presentation_id == presentation_id,
                LearningEvent.learning_item_id == item_id,
                LearningEvent.event_type.in_(
                    [EventType.ITEM_CLICKED, EventType.EXPLANATION_REVEALED]
                ),
            )
            .group_by(LearningEvent.event_type)
        ).all()
    counts = {EventType.ITEM_CLICKED: 0, EventType.EXPLANATION_REVEALED: 0}
    counts.update({row[0]: int(row[1]) for row in rows})
    return counts


def _watch_paths(page: Page, *suffixes: str) -> list[str]:
    sent: list[str] = []

    def record(request: Request) -> None:
        if request.method == "POST" and request.url.endswith(suffixes):
            sent.append(request.url.rsplit("/", 1)[1])

    page.on("request", record)
    return sent


@pytest.mark.integration
def test_reopening_an_explanation_sends_click_and_revealed_once(
    e2e_stack: E2EStack, page: Page
) -> None:
    """시트를 닫고 같은 표현을 다시 탭해도 `/click`과 `explanation_revealed`는 presentation + item당 1회다."""
    stack = e2e_stack
    started = _start(stack, page, _cfg(minimum_meaningful_exposures=MINIMUM_EXPOSURES))
    learner, focus_id = started.learner, started.focus_id

    presentation = flow.advance_to_item(page, stack, learner, item_id=focus_id)
    index = flow.token_index(stack, presentation, learning_item_id=focus_id)
    sent = _watch_paths(page, "/click", "/explanation-revealed")

    flow.tap(page, index)
    flow._poll(
        lambda: (
            _interaction_counts(stack, presentation.id, focus_id)[EventType.EXPLANATION_REVEALED]
            or None
        ),
        what="explanation_revealed",
    )

    for _ in range(2):
        flow.close_sheet(page)
        flow.tap(page, index)
        expect_text = flow.open_sheet(page).locator(".explain .meaning").inner_text()
        assert expect_text.strip() != "", "다시 연 시트에 설명이 없다"
    page.wait_for_timeout(_LATE_REQUEST_WINDOW_MS)

    assert sent == ["click", "explanation-revealed"], sent
    assert _interaction_counts(stack, presentation.id, focus_id) == {
        EventType.ITEM_CLICKED: 1,
        EventType.EXPLANATION_REVEALED: 1,
    }


# 학습 화면을 떠나는 상단바 버튼과 떠난 뒤의 화면. 앱 이름은 공개 route(선택 홈)로, `학습 기록`은 로그인
# 영역 안의 콜백 이동(History)으로 떠난다. 두 길 모두 학습 화면의 signal을 abort해야 한다.
LEAVE_STUDY_BY = {
    "app-name": (".topbar .topbar-brand", ".screen.home"),
    "history": (".topbar .history-link", ".screen.history"),
}


@pytest.mark.integration
@pytest.mark.parametrize("leave_by", list(LEAVE_STUDY_BY))
def test_a_late_click_response_after_leaving_reveals_nothing(
    e2e_stack: E2EStack, page: Page, leave_by: str
) -> None:
    """`/click` 응답 전에 화면을 떠나면 늦게 온 응답으로 설명을 그리지 않고 `explanation_revealed`도 없다.

    요청은 서버까지 보낸다(`route.fetch()`) --- 그래야 `item_clicked`만 남는 실제 상황이다. 응답은 상단바
    앱 이름(선택 홈) 또는 `학습 기록`(History)으로 떠난 **뒤에** 브라우저에 건넨다.
    """
    leave_button, left_screen = LEAVE_STUDY_BY[leave_by]
    stack = e2e_stack
    started = _start(stack, page, _cfg(minimum_meaningful_exposures=MINIMUM_EXPOSURES))
    learner, focus_id = started.learner, started.focus_id

    presentation = flow.advance_to_item(page, stack, learner, item_id=focus_id)
    index = flow.token_index(stack, presentation, learning_item_id=focus_id)
    sent = _watch_paths(page, "/explanation-revealed")

    held: list[Route] = []
    page.route("**/click", lambda route: held.append(route))
    flow.tokens(page).nth(index).click()
    # route 처리기는 Playwright 호출 안에서만 돈다. time.sleep으로 기다리면 오지 않는다.
    for _ in range(int(flow.SETTLE_TIMEOUT_SECONDS * 1000 / 50)):
        if held:
            break
        page.wait_for_timeout(50)
    assert held, "/click 요청이 나가지 않았다"

    page.locator(leave_button).click()
    page.locator(left_screen).wait_for(state="visible")

    late = held[0]
    late.fulfill(response=late.fetch())
    page.wait_for_timeout(_LATE_REQUEST_WINDOW_MS)
    page.unroute("**/click")

    assert page.locator(".sheet").count() == 0, "떠난 뒤에 설명 시트가 열렸다"
    assert page.locator(left_screen).count() == 1
    assert sent == [], f"떠난 뒤 explanation_revealed를 보냈다: {sent}"
    assert _interaction_counts(stack, presentation.id, focus_id) == {
        EventType.ITEM_CLICKED: 1,
        EventType.EXPLANATION_REVEALED: 0,
    }
