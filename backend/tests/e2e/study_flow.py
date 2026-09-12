"""브라우저로 학습 화면을 미는 helper + 그 결과를 DB에서 읽는 조회.

두 가지가 한 모듈에 있는 이유가 이 하네스의 요점이다: **화면을 밀고 DB를
단언한다.** DOM만 보는 E2E는 "화면은 맞는데 `item_exposures`가 2건"을 잡지 못하고,
서비스만 부르는 테스트는 "버튼이 실제로 그 요청을 보내는가"를 잡지 못한다.

`test_core_e2e_browser.py`와 `test_frontend_invariants.py`가 함께 쓴다.

## DOM을 기다리는 방식

`time.sleep`으로 기다리지 않는다. 두 축을 쓴다.

-   DOM: Playwright의 auto-wait (`locator.wait_for`, `expect`).
-   DB: `_poll()`로 **커밋된 상태**가 바뀔 때까지 기다린다. 화면 갱신과 서버 저장은
    같은 순간이 아니므로, 저장을 단언하려면 저장 쪽을 봐야 한다.

정책값을 여기에 적지 않는다. 숫자가 필요한 곳은 테스트가 `use_config()`로 주입한
값에서 유도한다(13_ACCEPTANCE_CRITERIA.md의 `수치 취급 원칙`).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime

import sqlalchemy as sa
from playwright.sync_api import Locator, Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from sqlalchemy.orm import Session

from app.models import (
    ItemExposure,
    LearningEvent,
    LearningItem,
    ReviewState,
    SentenceItem,
    SentenceItemSpan,
    StudyPresentation,
    StudySession,
    UserItemLearningState,
    UserMastery,
    UserSentenceCandidateTarget,
)
from app.models.enums import EventType, PresentationRole
from app.services.auth import hash_password
from app.services.seed_loader import load_seed
from tests import factories
from tests.conftest import REPO_ROOT
from tests.e2e.conftest import E2EStack

SEED_DIR = REPO_ROOT / "seed"

# 12_TEST_PLAN.md의 Core E2E 2단계가 지목한 표현.
FOCUS_LEMMA = "任せる"

PASSWORD = "correct horse battery staple"

# self-report 버튼 문구. `frontend/src/ui/explanation.ts`의 `SELF_REPORT_CHOICES`와
# 같아야 한다 --- 사용자가 실제로 누르는 것이 이 글자다.
KNOWN = "알고 있었음"
UNCERTAIN = "애매함"
UNKNOWN = "몰랐음"

# DOM/DB가 정착할 때까지의 상한. 정책값이 아니라 무한 대기 대신 실패로 끝내는 장치다.
SETTLE_TIMEOUT_SECONDS = 15.0
_POLL_INTERVAL_SECONDS = 0.05

# 한 라운드에서 찾는 item이 나올 때까지 넘겨볼 문장 수. 위와 같은 이유의 안전장치다.
MAX_PRESENTATIONS_PER_ROUND = 6


@dataclass(frozen=True)
class Learner:
    user_id: int
    login_id: str


# --------------------------------------------------------------------------
# 전제
# --------------------------------------------------------------------------


def seed_and_create_user(stack: E2EStack) -> Learner:
    """seed 적재 + 사용자 1명. cold start의 출발점이다 (Core E2E 1단계).

    `db_session`의 롤백 격리가 없으므로 **커밋한다** --- uvicorn 스레드는 다른
    커넥션에서 이것을 보아야 한다.
    """
    with stack.sessions() as db:
        load_seed(db, SEED_DIR, now=stack.clock.now())
        user = factories.make_user(db)
        user.password_hash = hash_password(PASSWORD)
        db.commit()
        return Learner(user_id=user.id, login_id=user.login_id)


@contextmanager
def read_db(stack: E2EStack) -> Iterator[Session]:
    """커밋된 상태를 읽는 짧은 세션. 캐시를 남기지 않도록 매번 새로 연다."""
    with stack.sessions() as db:
        yield db


# --------------------------------------------------------------------------
# 화면
# --------------------------------------------------------------------------


def sign_in(page: Page, stack: E2EStack, learner: Learner) -> None:
    """로그인 화면의 두 필드를 실제로 채우고 제출한다.

    boot이 `GET /api/auth/me`로 401을 받아 로그인 화면을 띄운 뒤다. 제출이 성공하면
    학습 화면이 뜨고 그 마운트가 `POST /api/study/session`을 부른다.
    """
    page.goto(stack.frontend_url)
    page.locator("#login-id").fill(learner.login_id)
    page.locator("#password").fill(PASSWORD)
    page.locator(".login-form button[type=submit]").click()
    wait_for_sentence(page)


def wait_for_sentence(page: Page) -> None:
    """문장이 뜰 때까지 기다린다. 안 뜨면 **화면에 남은 것을 함께** 실패 메시지에 싣는다.

    Playwright의 기본 timeout 메시지는 "locator(.sentence)를 기다렸다"까지만 말한다.
    그런데 이 화면에서 문장이 안 뜨는 이유는 거의 항상 그 자리에 **안내나 오류가
    대신 떠 있기** 때문이다. 그것을 찍지 않으면 매번 브라우저를 다시 띄워 들여다봐야
    한다.
    """
    try:
        page.locator(".sentence").wait_for(state="visible", timeout=SETTLE_TIMEOUT_SECONDS * 1000)
    except PlaywrightTimeoutError as exc:
        raise AssertionError(f"문장이 뜨지 않았다. {screen_digest(page)}") from exc


def screen_digest(page: Page) -> str:
    """실패 메시지에 넣을 화면 요약."""
    notices = page.locator(".notice").all_inner_texts()
    body = page.locator("body").inner_text()
    return f"notice={notices!r} body={body[:400]!r}"


def tokens(page: Page) -> Locator:
    """tappable span. DOM 순서가 span의 (start, end) 순서다 (`app/render.py`)."""
    return page.locator(".sentence .token")


def sentence_text(page: Page) -> str:
    return page.locator(".sentence").inner_text()


def tap(page: Page, index: int) -> None:
    """tappable span 하나를 누른다. 설명 패널이 뜰 때까지 기다린다."""
    tokens(page).nth(index).click()
    page.locator(".explain").wait_for(state="visible", timeout=SETTLE_TIMEOUT_SECONDS * 1000)


def self_report(page: Page, label: str) -> None:
    """설명 패널의 self-report 버튼 하나를 누르고 잠김(기록됨)까지 기다린다."""
    page.locator(".explain .self-report", has_text=label).click()
    page.locator(".explain .feedback-done").wait_for(
        state="visible", timeout=SETTLE_TIMEOUT_SECONDS * 1000
    )


def reveal_translation(page: Page) -> None:
    page.locator(".reveal-translation").click()
    page.locator(".translation").wait_for(state="visible", timeout=SETTLE_TIMEOUT_SECONDS * 1000)


def press_next(page: Page, stack: E2EStack, learner: Learner) -> StudyPresentation | None:
    """`다음 문장`을 누르고 서버가 정착할 때까지 기다린다.

    화면만 보고 기다리지 않는다. UI는 `/complete` -> `GET /session` -> `/next`를
    순서대로 밟으므로, "다음 문장이 떴다"는 **새 열린 presentation이 커밋됐다**는
    뜻이다. pool이 비면 `presentation: null`이고 화면에는 안내가 남는다.
    """
    previous = open_presentation(stack, learner)
    assert previous is not None, "열린 presentation이 없으면 Next를 누를 수 없다"
    page.locator("button.next").click()
    return _wait_for_next_presentation(page, stack, learner, previous_id=previous.id)


def _wait_for_next_presentation(
    page: Page, stack: E2EStack, learner: Learner, *, previous_id: int
) -> StudyPresentation | None:
    def settled() -> tuple[StudyPresentation | None] | None:
        row = open_presentation(stack, learner)
        if row is not None and row.id != previous_id:
            return (row,)
        if row is None and _empty_pool_notice(page):
            # Ready Pool이 비었다. 오류가 아니다(05_API_SPEC.md).
            return (None,)
        return None

    result = _poll(settled, what="다음 presentation 또는 빈 pool 안내")
    if result[0] is not None:
        wait_for_sentence(page)
    return result[0]


def _empty_pool_notice(page: Page) -> bool:
    return page.locator(".notice", has_text="준비된 문장이 없습니다").count() > 0


def reopen(page: Page, stack: E2EStack, learner: Learner) -> StudyPresentation | None:
    """페이지를 다시 띄운다. boot이 `POST /session`으로 세션을 얻고 `/next`를 부른다.

    시계를 옮긴 뒤에 쓴다 --- idle timeout을 넘겼으면 이전 세션이 종료되고 새 세션이
    시작된다. 그 판정은 서버가 하고 화면은 안내 한 줄을 띄운다.

    Ready Pool이 비어 있으면 `None`이다. 그것은 오류가 아니라 상태이므로
    `wait_for_sentence`로 15초를 태우지 않고 호출부가 단언할 수 있게 돌려준다.
    """
    page.reload()

    def settled() -> tuple[StudyPresentation | None] | None:
        row = open_presentation(stack, learner)
        if row is not None and page.locator(".sentence").count() > 0:
            return (row,)
        if row is None and _empty_pool_notice(page):
            return (None,)
        return None

    return _poll(settled, what="새 세션의 첫 문장 또는 빈 pool 안내")[0]


# --------------------------------------------------------------------------
# DB 조회
# --------------------------------------------------------------------------


def open_presentation(stack: E2EStack, learner: Learner) -> StudyPresentation | None:
    """화면에 떠 있는 문장. **최신 세션의** 아직 완료되지 않은 presentation이다.

    세션 범위를 좁히는 이유: idle timeout으로 종료된 세션에 열린 presentation이
    **그대로 남는다**(사용자가 보지 않은 문장을 완료로 확정하지 않는다, 불변식 #2).
    그 행을 화면의 문장으로 착각하면 옛 문장의 span을 누르게 된다.
    """
    with read_db(stack) as db:
        latest = (
            sa.select(sa.func.max(StudySession.id))
            .where(StudySession.user_id == learner.user_id)
            .scalar_subquery()
        )
        return db.execute(
            sa.select(StudyPresentation)
            .where(
                StudyPresentation.user_id == learner.user_id,
                StudyPresentation.study_session_id == latest,
                StudyPresentation.completed_at.is_(None),
            )
            .order_by(StudyPresentation.id.desc())
            .limit(1)
        ).scalar_one_or_none()


def supply_sentences(stack: E2EStack, *, item_id: int, count: int) -> list[int]:
    """그 표현을 담은 ready 문장을 `count`개 공급하고 sentence id를 돌려준다.

    **Wave 3의 대역이다.** 문맥 ladder가 `varied` 이상으로 올라가면 아직 보지 않은
    문장이 필요한데 그것을 **생성**하는 것은 worker의 일이다
    (06_LEARNING_ENGINE.md의 `Wave 3이 추가하는 것`). seed에는 표현당 문장이 두 개뿐이라
    Wave 3 없이는 두 라운드 만에 pool이 마른다. candidate는 여전히 엔진이 만든다 ---
    여기서 공급하는 것은 콘텐츠(문장 + span + 설명)뿐이다.
    """
    with read_db(stack) as db:
        item = db.get(LearningItem, item_id)
        assert item is not None
        ids = [
            factories.make_ready_sentence(db, [item], surfaces=[item.lemma]).id
            for _ in range(count)
        ]
        db.commit()
        return ids


def wait_for_open_presentation_change(
    stack: E2EStack, learner: Learner, *, previous_id: int
) -> StudyPresentation:
    """열린 presentation이 바뀔 때까지 기다린다.

    화면을 보지 않고 **커밋된 상태**를 본다. "진행했는가"의 답은 DB에 있다.
    """

    def changed() -> StudyPresentation | None:
        row = open_presentation(stack, learner)
        return row if row is not None and row.id != previous_id else None

    return _poll(changed, what="다음 presentation")


def sentence_item_id(
    stack: E2EStack, presentation: StudyPresentation, *, learning_item_id: int
) -> int:
    """그 문장에서 이 learning item을 가리키는 `sentence_items.id`."""
    with read_db(stack) as db:
        return int(
            db.execute(
                sa.select(SentenceItem.id).where(
                    SentenceItem.sentence_id == presentation.sentence_id,
                    SentenceItem.learning_item_id == learning_item_id,
                )
            ).scalar_one()
        )


def token_index(stack: E2EStack, presentation: StudyPresentation, *, learning_item_id: int) -> int:
    """그 item의 tappable span이 DOM에서 몇 번째인가. 없으면 -1.

    `build_render_segments()`가 tappable span을 `(start, end)`로 정렬해 segment를
    만들므로 이 순서가 곧 `.token` 버튼의 순서다. `sentence_item_id`를 DOM 속성으로
    내지 않는 구현이므로(`ui/segments.ts`) 위치로 찾는다.
    """
    with read_db(stack) as db:
        rows = db.execute(
            sa.select(
                SentenceItemSpan.start_codepoint,
                SentenceItemSpan.end_codepoint,
                SentenceItem.learning_item_id,
            )
            .join(SentenceItem, SentenceItem.id == SentenceItemSpan.sentence_item_id)
            .where(
                SentenceItem.sentence_id == presentation.sentence_id,
                SentenceItem.is_tappable.is_(True),
            )
            .order_by(SentenceItemSpan.start_codepoint, SentenceItemSpan.end_codepoint)
        ).all()
    for index, row in enumerate(rows):
        if row.learning_item_id == learning_item_id:
            return index
    return -1


def target_item_ids(stack: E2EStack, presentation: StudyPresentation) -> set[int]:
    """그 presentation의 candidate target. exposure를 만드는 단위다 (ADR-013)."""
    with read_db(stack) as db:
        return set(
            db.execute(
                sa.select(UserSentenceCandidateTarget.learning_item_id).where(
                    UserSentenceCandidateTarget.candidate_id == presentation.candidate_id
                )
            )
            .scalars()
            .all()
        )


def focus_item(stack: E2EStack) -> LearningItem:
    with read_db(stack) as db:
        return db.execute(
            sa.select(LearningItem).where(LearningItem.lemma == FOCUS_LEMMA)
        ).scalar_one()


def review_state(stack: E2EStack, learner: Learner, *, item_id: int) -> ReviewState:
    with read_db(stack) as db:
        return db.execute(
            sa.select(ReviewState).where(
                ReviewState.user_id == learner.user_id,
                ReviewState.learning_item_id == item_id,
            )
        ).scalar_one()


def mastery(stack: E2EStack, learner: Learner, *, item_id: int) -> UserMastery | None:
    with read_db(stack) as db:
        return db.execute(
            sa.select(UserMastery).where(
                UserMastery.user_id == learner.user_id,
                UserMastery.learning_item_id == item_id,
            )
        ).scalar_one_or_none()


def learning_state(stack: E2EStack, learner: Learner, *, item_id: int) -> UserItemLearningState:
    with read_db(stack) as db:
        return db.execute(
            sa.select(UserItemLearningState).where(
                UserItemLearningState.user_id == learner.user_id,
                UserItemLearningState.learning_item_id == item_id,
            )
        ).scalar_one()


def events(
    stack: E2EStack, learner: Learner, *, event_type: EventType | None = None
) -> list[LearningEvent]:
    with read_db(stack) as db:
        query = sa.select(LearningEvent).where(LearningEvent.user_id == learner.user_id)
        if event_type is not None:
            query = query.where(LearningEvent.event_type == event_type)
        return list(db.execute(query.order_by(LearningEvent.id)).scalars().all())


def exposures(
    stack: E2EStack, learner: Learner, *, item_id: int | None = None
) -> list[ItemExposure]:
    with read_db(stack) as db:
        query = sa.select(ItemExposure).where(ItemExposure.user_id == learner.user_id)
        if item_id is not None:
            query = query.where(ItemExposure.learning_item_id == item_id)
        return list(db.execute(query.order_by(ItemExposure.id)).scalars().all())


def presentations(stack: E2EStack, learner: Learner) -> list[StudyPresentation]:
    with read_db(stack) as db:
        return list(
            db.execute(
                sa.select(StudyPresentation)
                .where(StudyPresentation.user_id == learner.user_id)
                .order_by(StudyPresentation.id)
            )
            .scalars()
            .all()
        )


def study_session(stack: E2EStack, learner: Learner) -> StudySession:
    """가장 최근 세션. 진행 표시의 분모가 여기서 나온다."""
    with read_db(stack) as db:
        return db.execute(
            sa.select(StudySession)
            .where(StudySession.user_id == learner.user_id)
            .order_by(StudySession.id.desc())
            .limit(1)
        ).scalar_one()


def utc(moment: datetime) -> datetime:
    """DB가 돌려주는 시각에는 세션 timezone이 붙어 있다. 시계는 UTC로 움직인다."""
    return moment.astimezone(UTC)


# --------------------------------------------------------------------------
# 라운드
# --------------------------------------------------------------------------


def advance_to_item(
    page: Page,
    stack: E2EStack,
    learner: Learner,
    *,
    item_id: int,
    where: Callable[[StudyPresentation], bool] | None = None,
) -> StudyPresentation:
    """그 item을 누를 수 있는 문장이 나올 때까지 Next를 누른다.

    지나친 문장도 **정상 완료**한다(Next가 그것을 한다). 건너뛰기 경로를 따로
    만들지 않는다 --- 사용자가 할 수 있는 동작만 한다.

    `where`로 presentation 자체에 조건을 더 걸 수 있다. 같은 표현이 exploration
    문장에도 span으로 들어 있을 수 있으므로("그 item이 보인다"와 "그 item이 이
    제시의 target이다"는 다른 이야기다), role/target을 요구하는 쪽은 그것을 명시한다.
    """
    row = open_presentation(stack, learner)
    assert row is not None, "열린 presentation이 없다"
    for _ in range(MAX_PRESENTATIONS_PER_ROUND):
        if token_index(stack, row, learning_item_id=item_id) >= 0 and (where is None or where(row)):
            return row
        nxt = press_next(page, stack, learner)
        assert nxt is not None, "보여줄 문장이 없다"
        row = nxt
    raise AssertionError(f"learning item {item_id}을 담은 문장이 조건에 맞게 나오지 않았다")


def is_target_review(stack: E2EStack, presentation: StudyPresentation, *, item_id: int) -> bool:
    """그 item을 **target으로 삼은 review** 제시인가.

    exposure를 만드는 단위가 candidate target이므로(ADR-013), "복습으로 나왔다"를
    보려면 role과 target을 함께 봐야 한다.
    """
    return presentation.presentation_role is PresentationRole.REVIEW and item_id in target_item_ids(
        stack, presentation
    )


def _poll[T](probe: Callable[[], T | None], *, what: str) -> T:
    deadline = time.monotonic() + SETTLE_TIMEOUT_SECONDS
    while True:
        value = probe()
        if value is not None:
            return value
        if time.monotonic() >= deadline:
            raise AssertionError(f"{SETTLE_TIMEOUT_SECONDS}s 안에 {what}이(가) 오지 않았다")
        time.sleep(_POLL_INTERVAL_SECONDS)
