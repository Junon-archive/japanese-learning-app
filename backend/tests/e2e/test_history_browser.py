"""학습 기록 화면 (03_UI_UX_SPEC.md의 `History`, 05_API_SPEC.md의 history endpoint 2개).

Core E2E의 연장이다 --- 같은 로그인 흐름 위에서 조회 화면을 본다. 여기서 노리는
결함은 두 가지이고 둘 다 화면만 보면 정상이다.

-   **행 수로 잘림을 추측하는 구현.** 행이 정확히 상한만큼인 사용자에게 "오래된
    기록은 표시하지 않았습니다"라고 거짓을 말한다. 그 사용자는 있지도 않은 손실을
    믿게 된다.
-   **조회가 학습 시간을 만드는 구현.** history를 열어 둔 시간이 `active_seconds`로
    누적되면 진행바가 사용자가 공부하지 않은 시간을 채운다.

`HISTORY_LIMIT`을 테스트에 적지 않고 서버 모듈에서 가져온다. 숫자를 베끼면 상한이
바뀐 날 이 테스트가 조용히 무의미해진다.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
import sqlalchemy as sa
from playwright.sync_api import Page

from app.models import StudySession, User, UserMastery
from app.services.history import HISTORY_LIMIT
from tests import factories
from tests.e2e import study_flow as flow
from tests.e2e.conftest import E2EStack

pytestmark = [pytest.mark.e2e, pytest.mark.integration]

SESSIONS_HEADING = "최근 세션"
ITEMS_HEADING = "학습한 표현"
TRUNCATED_TEXT = "오래된 기록은 표시하지 않았습니다"
NO_MASTERY_TEXT = "아직 평가 없음"

# history를 두 번 읽는 사이에 흘리는 시간. `active_time_idle_gap_seconds`보다 **작게**
# 둔다 --- 그보다 크면 서버가 gap을 0으로 처리하므로 "조회가 시간을 만들었는가"를
# 구분할 수 없다. 정책값이 아니라 이 테스트의 관측 창이다.
READ_GAP = timedelta(seconds=30)


def _open_history(page: Page) -> None:
    page.locator(".history-link").click()
    page.locator(".screen.history").wait_for(state="visible")
    page.locator(".history-section").first.wait_for(state="visible")


def _back_to_study(page: Page) -> None:
    page.locator(".history-back").click()
    flow.wait_for_sentence(page)


def _finished_sessions(stack: E2EStack, learner: flow.Learner, count: int) -> None:
    """종료된 세션 `count`개. 상한 경계를 만들기 위한 것이므로 factory로 심는다.

    `ended_at`을 채우는 이유: 열린 채 두면 다음 `POST /session`이 그 중 하나를
    **resume**해 버려서 화면이 엉뚱한 세션을 보게 된다.
    """
    with flow.read_db(stack) as db:
        user = db.get(User, learner.user_id)
        assert user is not None
        for _ in range(count):
            session = factories.make_study_session(db, user, target_minutes=1)
            session.ended_at = session.started_at
        db.commit()


def test_history_renders_both_lists(e2e_stack: E2EStack, page: Page) -> None:
    """두 목록이 렌더된다. 진행 중인 세션은 종료 시각 자리에 `진행 중`이 온다."""
    stack = e2e_stack
    learner = flow.seed_and_create_user(stack)
    flow.sign_in(page, stack, learner)
    # 한 문장을 완료해 `학습한 표현`에 행이 생기게 한다(target item의 learning state).
    flow.press_next(page, stack, learner)

    _open_history(page)

    sections = page.locator(".history-section")
    assert sections.count() == 2, f"section이 {sections.count()}개다"
    assert page.locator(".history-heading").nth(0).inner_text() == SESSIONS_HEADING
    assert page.locator(".history-heading").nth(1).inner_text() == ITEMS_HEADING

    session_rows = page.locator(".history-section").nth(0).locator(".history-row")
    assert session_rows.count() == 1
    # 진행 중인 세션이다. 종료 시각을 꾸며 내지 않는다.
    assert "진행 중" in session_rows.first.inner_text()

    item_rows = page.locator(".history-section").nth(1).locator(".history-row")
    assert item_rows.count() > 0, "완료한 문장의 target item이 목록에 없다"

    # 읽기 전용 화면이다. 학습으로 이어지는 버튼을 두지 않는다(돌아가기 하나뿐).
    assert page.locator(".screen.history button").count() == 1
    _back_to_study(page)


def test_rows_exactly_at_the_limit_are_not_reported_as_truncated(
    e2e_stack: E2EStack, page: Page
) -> None:
    """행이 상한과 같을 때 잘림 문구가 **없다**. 상한을 넘으면 나타난다.

    행 수로 추측하는 구현(`len(rows) == LIMIT`)은 앞쪽에서 빨개지고, 문구를 아예
    만들지 않는 구현은 뒤쪽에서 빨개진다.
    """
    stack = e2e_stack
    learner = flow.seed_and_create_user(stack)
    flow.sign_in(page, stack, learner)

    # 로그인이 만든 진행 중 세션 1개 + 심은 것들 = 정확히 상한.
    _finished_sessions(stack, learner, HISTORY_LIMIT - 1)
    with flow.read_db(stack) as db:
        total = int(
            db.execute(
                sa.select(sa.func.count(StudySession.id)).where(
                    StudySession.user_id == learner.user_id
                )
            ).scalar_one()
        )
    assert total == HISTORY_LIMIT, total

    _open_history(page)
    rows = page.locator(".history-section").nth(0).locator(".history-row")
    assert rows.count() == HISTORY_LIMIT
    assert page.locator(".history-truncated").count() == 0, (
        "행이 상한과 같을 뿐인데 잘렸다고 표시했다 --- 행 수로 추측하고 있다"
    )

    # 한 개 더. 이제는 진짜로 잘렸고 그 사실을 적어야 한다.
    _back_to_study(page)
    _finished_sessions(stack, learner, 1)
    _open_history(page)

    rows = page.locator(".history-section").nth(0).locator(".history-row")
    assert rows.count() == HISTORY_LIMIT
    truncated = page.locator(".history-truncated")
    assert truncated.count() == 1, "상한을 넘었는데 잘림을 알리지 않았다"
    assert TRUNCATED_TEXT in truncated.first.inner_text()


def test_reading_history_does_not_accrue_active_time(e2e_stack: E2EStack, page: Page) -> None:
    """진행 중 session을 history로 두 번 읽어도 `active_seconds`가 그대로다.

    조회 사이에 시계를 흘린다 --- 흘리지 않으면 서버가 `touch()`를 해도 더할 gap이
    0이어서 이 단언이 아무것도 보지 않는다.
    """
    stack = e2e_stack
    learner = flow.seed_and_create_user(stack)
    flow.sign_in(page, stack, learner)

    _open_history(page)
    before = flow.study_session(stack, learner)

    # 화면을 떠나지 않고 두 번 더 읽는다. 돌아가기는 `POST /session`을 부르므로
    # (그쪽은 touch()가 정당하다) 이 관측에 섞지 않는다.
    for _ in range(2):
        stack.clock.advance(READ_GAP)
        for path in ("/api/history/sessions", "/api/history/items"):
            status = page.evaluate(
                """async (url) => (await fetch(url, {credentials: 'include'})).status""",
                f"{stack.api_url}{path}",
            )
            assert status == 200, (path, status)

    after = flow.study_session(stack, learner)
    assert after.id == before.id
    assert after.active_seconds == before.active_seconds, "조회가 학습 시간을 만들었다"
    assert after.last_activity_at == before.last_activity_at, "조회가 마지막 활동 시각을 옮겼다"
    assert after.ended_at is None


def test_an_item_without_evidence_is_not_shown_as_zero_percent(
    e2e_stack: E2EStack, page: Page
) -> None:
    """`comprehension_mastery`가 null인 item은 `0%`가 아니라 `아직 평가 없음`이다.

    0%는 "능력이 0"으로 읽힌다. 아직 아무 evidence가 없는 것과 뜻이 다르다
    (02_LEARNING_POLICY.md).
    """
    stack = e2e_stack
    learner = flow.seed_and_create_user(stack)
    flow.sign_in(page, stack, learner)
    # 신호를 주지 않고 완료한다 --- learning state는 생기고 mastery 행은 생기지 않는다.
    flow.press_next(page, stack, learner)

    with flow.read_db(stack) as db:
        masteries = int(
            db.execute(
                sa.select(sa.func.count(UserMastery.id)).where(
                    UserMastery.user_id == learner.user_id
                )
            ).scalar_one()
        )
    assert masteries == 0, "전제가 깨졌다: evidence 없이 mastery 행이 생겼다"

    _open_history(page)
    items = page.locator(".history-section").nth(1).locator(".history-row")
    assert items.count() > 0
    text = items.first.inner_text()
    assert NO_MASTERY_TEXT in text, text
    assert "0%" not in text, f"evidence가 없는 item을 0%로 표시했다: {text}"
