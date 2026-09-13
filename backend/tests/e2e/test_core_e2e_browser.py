"""Core E2E Scenario 13단계를 **실제 브라우저**로 주파한다 (12_TEST_PLAN.md).

`test_core_e2e.py`(in-process, TestClient)와 같은 시나리오를 다른 층에서 본다.
그쪽은 HTTP 계약을 밟고, 이쪽은 **사용자가 실제로 누르는 것**을 밟는다. 두 층이
갈리는 결함이 이 시나리오의 표적이다.

-   서버는 맞는데 버튼이 그 요청을 보내지 않는다 (DOM만 보면 안 보인다).
-   화면은 맞는데 저장이 두 번 됐다 (브라우저만 보면 안 보인다).

그래서 단계마다 **DOM과 DB를 함께** 단언한다. 시계는 `MutableClock`이 유일한
수단이고(ADR-007), 정책값은 `use_config()`로 주입한 값에서만 유도한다
(13_ACCEPTANCE_CRITERIA.md의 `수치 취급 원칙`).
"""

from __future__ import annotations

from datetime import timedelta

import pytest
import sqlalchemy as sa
from fsrs import Card, Rating, Scheduler
from playwright.sync_api import Page, expect

from app.config import AppConfig, get_config
from app.learning.exposure import count_valid_exposures
from app.learning.mastery import OBSERVATION, ema
from app.learning.progression import stage_rank
from app.models import (
    Sentence,
    SentenceItem,
    SentenceItemExplanation,
    SentenceItemSpan,
    StudyPresentation,
    UserSentenceCandidate,
)
from app.models.enums import (
    CandidateStatus,
    ContextStage,
    EventType,
    ExplicitSignal,
    PresentationRole,
    ReviewReason,
)
from tests.conftest import no_provider_module_import, override_config
from tests.e2e import study_flow as flow
from tests.e2e.conftest import E2EStack

pytestmark = [pytest.mark.e2e, pytest.mark.integration]

# 이 시나리오가 쓰는 최소 노출 회수. **기본값이 아니라 주입값**이다 --- 엔진이
# config를 읽는지 보기 위한 것이므로 기본값과 달라야 의미가 있다.
MINIMUM_EXPOSURES = 3

# 12_TEST_PLAN.md 13단계("최소 5회 노출 이후에도 FSRS due라면 계속 복습")를 확인하기
# 위해 도는 복습 라운드의 상한. 정책값이 아니라 무한 루프 대신 실패로 끝내는 장치다.
MAX_REVIEW_ROUNDS = 6

# 라운드가 쓸 새 문맥의 수. Wave 3 worker의 대역이며 정책값이 아니다
# (`study_flow.supply_sentences`의 설명).
SUPPLIED_CONTEXTS = 3


def test_core_e2e_13_steps_in_a_real_browser(e2e_stack: E2EStack, page: Page) -> None:
    stack = e2e_stack
    cfg: AppConfig = override_config(
        get_config(), learning={"minimum_meaningful_exposures": MINIMUM_EXPOSURES}
    )
    stack.use_config(cfg)
    clock = stack.clock

    # ------------------------------------------------------------------ 1
    # seed 기반 cold start. 로그인 직후 화면 마운트가 `POST /session`을 부르고,
    # 그 안의 Candidate Materialization이 Ready Pool을 만든다. worker는 없다.
    learner = flow.seed_and_create_user(stack)

    with flow.read_db(stack) as db:
        assert db.execute(_count_ready(learner.user_id)).scalar_one() == 0, (
            "로그인 전에 이미 Ready Pool이 있다 --- 이 단계가 무엇을 만드는지 볼 수 없다"
        )

    # provider 모듈이 **새로** 적재되면 실패한다. request 경로에서 LLM을 부르는
    # 구현은 여기에 걸린다(불변식 #1). 절대 집합이 아니라 증가분을 보므로 같은
    # 세션의 다른 테스트가 무엇을 적재해 뒀든 결과가 달라지지 않는다.
    with no_provider_module_import():
        flow.sign_in(page, stack, learner)

    with flow.read_db(stack) as db:
        ready = db.execute(_count_ready(learner.user_id)).scalar_one()
    assert ready > 0, "세션 시작이 seed에서 Ready Pool을 만들지 못했다"

    # ------------------------------------------------------------------ 2
    # `任せる`가 포함된 문장 노출. 화면에 tappable span이 실제로 그려져 있어야 한다.
    focus = flow.focus_item(stack)
    with no_provider_module_import():
        presentation = flow.advance_to_item(page, stack, learner, item_id=focus.id)
    anchor_sentence_id = presentation.sentence_id
    assert presentation.context_stage is ContextStage.ANCHOR

    index = flow.token_index(stack, presentation, learning_item_id=focus.id)
    assert index >= 0
    token = flow.tokens(page).nth(index)
    expect(token).to_be_visible()
    # 화면의 문장과 서버의 문장이 같은 것인지 본다. DOM만 보면 옛 문장이 남아 있어도
    # 통과한다.
    with flow.read_db(stack) as db:
        japanese = db.execute(_sentence_text(presentation.sentence_id)).scalar_one()
    assert flow.sentence_text(page).replace("\n", "") == japanese

    # ------------------------------------------------------------------ 3, 4
    # item 클릭 -> precomputed 설명. live LLM 호출이 0이다.
    with no_provider_module_import():
        flow.tap(page, index)

    with flow.read_db(stack) as db:
        stored = db.execute(_explanation_of(presentation.sentence_id, focus.id)).scalar_one()
    panel = flow.open_sheet(page).locator(".explain")
    # 화면에 뜬 문구가 **DB에 미리 있던 그 문구**다. 생성된 것이 아니다. 머리는 문장 속 표면형과
    # 그 읽기의 짝이다(03_UI_UX_SPEC.md의 `Explanation`) --- 표면형은 span이 가리키는 원문 조각이다.
    expect(panel.locator(".jp-word")).to_have_text(
        _surface(stack, presentation.sentence_id, focus.id)
    )
    expect(panel.locator(".reading")).to_have_text(stored.reading)
    expect(panel.locator(".meaning")).to_have_text(stored.core_meaning)
    expect(panel.locator(".meaning-context")).to_have_text(stored.meaning_in_context)
    expect(panel.locator(".nuance")).to_have_text(stored.nuance)

    clicked = flow.events(stack, learner, event_type=EventType.ITEM_CLICKED)
    revealed = flow.events(stack, learner, event_type=EventType.EXPLANATION_REVEALED)
    assert [row.learning_item_id for row in clicked] == [focus.id]
    assert [row.learning_item_id for row in revealed] == [focus.id]

    # ------------------------------------------------------------------ 5, 6
    # `몰랐음` 선택 -> event 저장.
    reported_at = clock.advance(timedelta(seconds=20))
    with no_provider_module_import():
        flow.self_report(page, flow.UNKNOWN)
    expect(panel.locator(".feedback-done")).to_have_text(f"{flow.RECORDED_PREFIX}{flow.UNKNOWN}")

    signals = flow.events(stack, learner, event_type=EventType.SELF_REPORT_UNKNOWN)
    assert len(signals) == 1
    event = signals[0]
    assert event.study_presentation_id == presentation.id
    assert event.learning_item_id == focus.id
    # 서버가 본 시각이 테스트가 옮긴 시각이다. 실클록이 아니다.
    assert flow.utc(event.created_at) == reported_at

    # ------------------------------------------------------------------ 7
    # mastery(observation 0.0, EMA) / review state(Again) 생성.
    mastery = flow.mastery(stack, learner, item_id=focus.id)
    assert mastery is not None
    assert mastery.comprehension_mastery == pytest.approx(
        ema(None, OBSERVATION[ExplicitSignal.UNKNOWN], cfg.learning.mastery_ema_alpha)
    )
    assert mastery.evidence_count == 1
    assert mastery.listening_mastery is None

    state = flow.review_state(stack, learner, item_id=focus.id)
    expected, _log = Scheduler(enable_fuzzing=cfg.srs.fsrs_enable_fuzzing).review_card(
        Card(card_id=None, due=reported_at), Rating.Again, reported_at
    )
    assert (state.reps, state.lapses) == (1, 1)
    assert state.stability == expected.stability
    assert state.difficulty == expected.difficulty
    assert flow.utc(state.next_review_at) == expected.due

    # ------------------------------------------------------------------ 8
    # `item_exposures` 생성. exposure는 candidate target 단위이고(ADR-013), 같은
    # presentation의 같은 item은 최대 1건이다(07_SRS_SPEC.md의 `중복 집계 금지`).
    flow.press_next(page, stack, learner)

    made = [
        row
        for row in flow.exposures(stack, learner)
        if row.study_presentation_id == presentation.id
    ]
    assert made, "정상 완료한 문장이 exposure를 하나도 남기지 않았다"
    item_ids = [row.learning_item_id for row in made]
    assert len(item_ids) == len(set(item_ids)), f"같은 presentation에 중복 exposure: {item_ids}"
    assert {row.context_stage for row in made} == {ContextStage.ANCHOR}
    assert all(row.invalidated_at is None for row in made)

    completed = [
        row
        for row in flow.events(stack, learner, event_type=EventType.SENTENCE_COMPLETED)
        if row.study_presentation_id == presentation.id
    ]
    assert len(completed) == 1

    # ------------------------------------------------------------------ 9, 10, 11
    # due 시점으로 시계 이동 -> 재노출 -> exposure 누적.
    #
    # 5단계의 `몰랐음`이 이 item을 학습 대상으로 승격시켰다. 그 **첫 제시는 `new`**이고
    # 문장은 승격 시점에 기록된 anchor다(ADR-013) --- 사용자가 실제로 물어본 그 문장.
    clock.set(flow.utc(state.next_review_at))
    assert flow.reopen(page, stack, learner) is not None, "due 시점에 보여줄 문장이 없다"
    first_target = flow.advance_to_item(page, stack, learner, item_id=focus.id)
    assert first_target.presentation_role is PresentationRole.NEW
    assert first_target.sentence_id == anchor_sentence_id
    assert first_target.context_stage is ContextStage.ANCHOR

    before = _valid_exposures(stack, learner, focus.id)
    _report_known(page, stack, first_target, item_id=focus.id)
    flow.press_next(page, stack, learner)
    assert _valid_exposures(stack, learner, focus.id) == before + 1

    # 이 fixture(`study_flow.SEED_DIR`)에는 이 표현을 담은 문장이 둘뿐이다. ladder가
    # `varied` 이상으로 올라가면 아직 보지 않은 문장이 필요하고 그것을 **생성**하는 것은 Wave 3 worker의 일이므로
    # (06_LEARNING_ENGINE.md) 여기서 콘텐츠를 공급해 그 상황을 흉내 낸다. candidate는
    # 여전히 엔진이 만든다.
    flow.supply_sentences(stack, item_id=focus.id, count=SUPPLIED_CONTEXTS)

    # 그 다음부터가 `review`다. 라운드를 돌며 11단계(노출 누적)와 12단계(anchor 이후
    # 새 문맥)를 함께 본다. stage를 손으로 올리지 않는다 --- 실패 없는 노출이 ladder를
    # 밀어 올리고, `varied` 이상은 아직 보지 않은 문장을 요구하므로 문맥이 실제로 바뀐다.
    #
    # **reason을 여기서 `fsrs_due`로 못박지 않는다.** item이 실제로 due인 것은 매
    # 라운드 DB로 확인하지만, reason 선택은 `reinforcement_min_share_of_review`가
    # `fsrs_due`보다 앞선다(06_LEARNING_ENGINE.md의 5단 절차) --- 최소 노출을 채우지
    # 못한 item에는 reinforcement 지분이 먼저 배정된다. 같은 문장·같은 stage의 두
    # candidate가 함께 존재하고, 어느 쪽이 제시되든 스케줄과 exposure 기록은 같다.
    beyond_anchor: StudyPresentation | None = None
    for _ in range(MAX_REVIEW_ROUNDS):
        state = flow.review_state(stack, learner, item_id=focus.id)
        clock.set(flow.utc(state.next_review_at))
        assert flow.reopen(page, stack, learner) is not None, "due 시점에 보여줄 문장이 없다"
        view = flow.advance_to_item(
            page,
            stack,
            learner,
            item_id=focus.id,
            where=lambda row: flow.is_target_review(stack, row, item_id=focus.id),
        )

        assert view.presentation_role is PresentationRole.REVIEW
        assert view.review_reason in {ReviewReason.FSRS_DUE, ReviewReason.REINFORCEMENT}
        assert flow.utc(state.next_review_at) <= clock.now(), "복습으로 제시됐는데 due가 아니다"

        # 11단계: 노출이 정확히 1건 쌓인다. 2건이면 중복 집계다(07_SRS_SPEC.md).
        before = _valid_exposures(stack, learner, focus.id)
        _report_known(page, stack, view, item_id=focus.id)
        flow.press_next(page, stack, learner)
        assert _valid_exposures(stack, learner, focus.id) == before + 1

        if view.sentence_id != anchor_sentence_id:
            beyond_anchor = view
            break

    # ------------------------------------------------------------------ 12
    # 초기 원문(anchor) 후 새로운 문맥으로 재노출.
    assert beyond_anchor is not None, "복습이 anchor 문장에 고정돼 새 문맥이 나오지 않았다"
    # ladder가 anchor 위로 올라갔다. 순서 판정은 앱의 `stage_rank`를 쓴다 --- 테스트가
    # 자기 순서표를 들고 있으면 앱이 순서를 바꿔도 초록으로 남는다.
    assert stage_rank(beyond_anchor.context_stage) > stage_rank(ContextStage.ANCHOR)

    with flow.read_db(stack) as db:
        anchor_text = db.execute(_sentence_text(anchor_sentence_id)).scalar_one()
        shown_text = db.execute(_sentence_text(beyond_anchor.sentence_id)).scalar_one()
    assert shown_text != anchor_text

    learning_state = flow.learning_state(stack, learner, item_id=focus.id)
    # anchor는 승격 시점의 문장으로 **고정**돼 있다. 문맥이 바뀌어도 원문은 남는다.
    assert learning_state.anchor_sentence_id == anchor_sentence_id
    assert stage_rank(learning_state.context_stage) >= stage_rank(ContextStage.VARIED)

    # ------------------------------------------------------------------ 13
    # 최소 노출을 넘긴 뒤에도 FSRS due라면 계속 복습할 수 있다. "N회 성공 후 졸업"
    # 같은 규칙이 없다는 것이 07_SRS_SPEC.md의 요구다.
    exposures_now = _valid_exposures(stack, learner, focus.id)
    assert exposures_now >= MINIMUM_EXPOSURES, (
        f"최소 노출({MINIMUM_EXPOSURES})을 채우기 전에 라운드가 끝났다: {exposures_now}"
    )

    # 다음 문맥으로 쓸 문장을 한 번 더 공급한다(위와 같은 이유).
    flow.supply_sentences(stack, item_id=focus.id, count=1)

    state = flow.review_state(stack, learner, item_id=focus.id)
    clock.set(flow.utc(state.next_review_at))
    assert flow.reopen(page, stack, learner) is not None, "due 시점에 보여줄 문장이 없다"
    final = flow.advance_to_item(
        page,
        stack,
        learner,
        item_id=focus.id,
        where=lambda row: flow.is_target_review(stack, row, item_id=focus.id),
    )
    assert final.presentation_role is PresentationRole.REVIEW
    assert flow.utc(state.next_review_at) <= clock.now()

    # 화면에 문장이 실제로 떠 있고, 그 노출이 또 한 건 쌓인다. 최소 노출을 채웠다고
    # 복습이 끝나지 않는다.
    flow.wait_for_sentence(page)
    before = _valid_exposures(stack, learner, focus.id)
    _report_known(page, stack, final, item_id=focus.id)
    flow.press_next(page, stack, learner)
    after = _valid_exposures(stack, learner, focus.id)
    assert after == before + 1
    assert after > MINIMUM_EXPOSURES


# --------------------------------------------------------------------------
# 이 시나리오 안에서만 쓰는 동작/조회
# --------------------------------------------------------------------------


def _report_known(
    page: Page, stack: E2EStack, presentation: StudyPresentation, *, item_id: int
) -> None:
    """화면에서 그 item을 눌러 `알고 있었음`을 기록한다."""
    index = flow.token_index(stack, presentation, learning_item_id=item_id)
    assert index >= 0
    flow.tap(page, index)
    flow.self_report(page, flow.KNOWN)


def _valid_exposures(stack: E2EStack, learner: flow.Learner, item_id: int) -> int:
    with flow.read_db(stack) as db:
        return count_valid_exposures(db, user_id=learner.user_id, learning_item_id=item_id)


def _count_ready(user_id: int) -> sa.Select[tuple[int]]:
    return sa.select(sa.func.count(UserSentenceCandidate.id)).where(
        UserSentenceCandidate.user_id == user_id,
        UserSentenceCandidate.status == CandidateStatus.READY,
    )


def _surface(stack: E2EStack, sentence_id: int, learning_item_id: int) -> str:
    """그 문장에서 그 item의 tappable span이 가리키는 원문 조각. offset은 code point다."""
    with flow.read_db(stack) as db:
        japanese = db.execute(_sentence_text(sentence_id)).scalar_one()
        spans = db.execute(
            sa.select(SentenceItemSpan.start_codepoint, SentenceItemSpan.end_codepoint)
            .join(SentenceItem, SentenceItem.id == SentenceItemSpan.sentence_item_id)
            .where(
                SentenceItem.sentence_id == sentence_id,
                SentenceItem.learning_item_id == learning_item_id,
            )
            .order_by(SentenceItemSpan.start_codepoint)
        ).all()
    assert spans, "그 item의 span이 없다"
    return "".join(japanese[row.start_codepoint : row.end_codepoint] for row in spans)


def _sentence_text(sentence_id: int) -> sa.Select[tuple[str]]:
    return sa.select(Sentence.japanese).where(Sentence.id == sentence_id)


def _explanation_of(
    sentence_id: int, learning_item_id: int
) -> sa.Select[tuple[SentenceItemExplanation]]:
    return (
        sa.select(SentenceItemExplanation)
        .join(SentenceItem, SentenceItem.id == SentenceItemExplanation.sentence_item_id)
        .where(
            SentenceItem.sentence_id == sentence_id,
            SentenceItem.learning_item_id == learning_item_id,
        )
    )
