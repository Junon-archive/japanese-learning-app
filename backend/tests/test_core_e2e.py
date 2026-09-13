"""Core E2E Scenario (`12_TEST_PLAN.md`의 13단계).

seed 적재(시나리오 전용 fixture) -> 첫 세션 -> `任せる` 노출 -> click ->
precomputed 설명 -> `몰랐음` -> event / mastery / review state / exposure -> due 시점으로 시계 이동 -> 복습 ->
anchor에서 새 문맥으로 -> 최소 노출을 넘긴 뒤에도 due면 계속 복습.

**HTTP로 밟는다.** service를 직접 부르면 같은 정책을 확인하면서도 API 계약
(200 + `presentation: null`, 번역 미노출, id가 number)은 아무도 보지 않는다.

시각은 `MutableClock`이 유일한 수단이다(ADR-007). freezegun을 쓰지 않는다 ---
전역 시계를 얼리는 도구는 애플리케이션이 몰래 `datetime.now()`를 읽어도 통과시켜
준다.

정책값은 `override_config`로 주입한다. 최소 노출 회수를 기본값보다 작게 넣는
이유는 시간 절약이 아니라 **엔진이 설정값을 읽는지** 보기 위해서다.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx2
import pytest
import sqlalchemy as sa
from fsrs import Card, Rating, Scheduler
from sqlalchemy.orm import Session

from app.config import AppConfig, get_config
from app.learning.exposure import count_valid_exposures
from app.learning.mastery import OBSERVATION, ema
from app.models import (
    ItemExposure,
    LearningEvent,
    LearningItem,
    ReviewState,
    SentenceItem,
    SentenceItemExplanation,
    UserItemLearningState,
    UserMastery,
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
from app.services.seed_loader import load_seed
from tests import factories
from tests.conftest import (
    StudyApi,
    assert_no_provider_import,
    no_outbound_network,
    override_config,
)

pytestmark = pytest.mark.integration

# repo 루트 `seed/`가 아니라 시나리오 전용 fixture를 적재한다. 2단계가 `任せる`를
# 지목하는데, 그 표현이 몇 문장 안에 나오는지는 적재된 seed의 exploration 순서가
# 정한다 --- 실 seed가 커지거나 순서가 바뀌면 시나리오의 의미와 무관하게 깨진다.
# 이 fixture가 주는 전제는 그 디렉터리의 items.yaml 머리말에 있다. 실 `seed/`의
# cold start는 test_restart_persistence / test_db_backup_restore가 계속 밟는다.
SEED_DIR = Path(__file__).resolve().parent / "data" / "seed_core_e2e"

# 이 시나리오가 따라가는 표현 (12_TEST_PLAN.md의 2단계).
FOCUS_LEMMA = "任せる"

# 한 라운드에서 우리 item이 나올 때까지 넘겨볼 문장 수. 정책값이 아니라 테스트의
# 안전장치다 --- 무한 루프 대신 실패로 끝나게 한다.
MAX_PRESENTATIONS_PER_ROUND = 4
# 최소 노출을 채우는 동안의 라운드 상한. 위와 같은 이유의 안전장치다.
MAX_REVIEW_ROUNDS = 8


def _json(response: httpx2.Response) -> dict[str, Any]:
    assert response.status_code == 200, response.text
    payload = response.json()
    assert isinstance(payload, dict)
    return payload


def _start_session(api: StudyApi) -> int:
    payload = _json(api.client.post("/api/study/session"))
    session_id = payload["session"]["session_id"]
    # ADR-005: id는 문자열로 감싸지 않는다.
    assert isinstance(session_id, int)
    return session_id


def _next(api: StudyApi, session_id: int) -> dict[str, Any] | None:
    payload = _json(api.client.post(f"/api/study/session/{session_id}/next"))
    presentation = payload["presentation"]
    if presentation is None:
        return None
    assert isinstance(presentation, dict)
    # 번역은 reveal endpoint에만 있다. 필드 자체가 없어야 샐 수 없다.
    assert "korean_translation" not in presentation
    return presentation


def _complete(api: StudyApi, presentation_id: int) -> None:
    _json(api.client.post(f"/api/study/presentations/{presentation_id}/complete"))


def _finish(api: StudyApi, session_id: int) -> None:
    _json(api.client.post(f"/api/study/session/{session_id}/finish"))


def _self_report(
    api: StudyApi, presentation_id: int, *, sentence_item_id: int, signal: ExplicitSignal
) -> None:
    response = api.client.post(
        f"/api/study/presentations/{presentation_id}/self-report",
        json={
            "client_event_id": str(uuid.uuid4()),
            "sentence_item_id": sentence_item_id,
            "value": signal.value,
        },
    )
    assert response.status_code == 204, response.text


def _tappable_id(presentation: dict[str, Any], *, learning_item_id: int) -> int | None:
    for tappable in presentation["tappable_items"]:
        if tappable["learning_item_id"] == learning_item_id:
            item_id = tappable["sentence_item_id"]
            assert isinstance(item_id, int)
            return item_id
    return None


def _utc(moment: datetime) -> datetime:
    """DB가 돌려주는 시각에는 세션 timezone이 붙어 있다. 시계는 UTC로 움직인다."""
    return moment.astimezone(UTC)


def _state(db: Session, *, user_id: int, item_id: int) -> ReviewState:
    return db.execute(
        sa.select(ReviewState).where(
            ReviewState.user_id == user_id, ReviewState.learning_item_id == item_id
        )
    ).scalar_one()


def _present_until(
    api: StudyApi, session_id: int, matches: Callable[[dict[str, Any]], bool]
) -> dict[str, Any]:
    """조건에 맞는 presentation이 나올 때까지 넘긴다. 넘긴 문장도 정상 완료한다."""
    for _ in range(MAX_PRESENTATIONS_PER_ROUND):
        presentation = _next(api, session_id)
        assert presentation is not None, "보여줄 문장이 없다"
        if matches(presentation):
            return presentation
        _complete(api, presentation["presentation_id"])
    raise AssertionError("찾는 presentation이 나오지 않았다")


def test_core_e2e_from_seed_cold_start_to_repeated_contextual_review(
    study_api: StudyApi, db_session: Session
) -> None:
    """12_TEST_PLAN.md의 13단계를 순서대로 밟는다."""
    minimum_exposures = 3
    cfg: AppConfig = override_config(
        get_config(), learning={"minimum_meaningful_exposures": minimum_exposures}
    )
    study_api.use_config(cfg)
    api = study_api
    clock = api.clock
    user_id = api.user.id

    # ----------------------------------------------------------------- 1
    # 신규 사용자 / seed 기반 cold start. 세션 시작이 Ready Pool을 만든다.
    # Wave 3 worker 없이 성립해야 한다.
    load_seed(db_session, SEED_DIR, now=clock.now())
    assert db_session.execute(sa.select(sa.func.count(UserSentenceCandidate.id))).scalar_one() == 0

    with no_outbound_network():
        session_id = _start_session(api)
    assert_no_provider_import()

    ready = (
        db_session.execute(
            sa.select(sa.func.count(UserSentenceCandidate.id)).where(
                UserSentenceCandidate.user_id == user_id,
                UserSentenceCandidate.status == CandidateStatus.READY,
            )
        )
    ).scalar_one()
    assert ready > 0, "세션 시작이 seed에서 Ready Pool을 만들지 못했다"

    # ----------------------------------------------------------------- 2
    # `任せる`가 포함된 문장 노출.
    focus = db_session.execute(
        sa.select(LearningItem).where(LearningItem.lemma == FOCUS_LEMMA)
    ).scalar_one()
    with no_outbound_network():
        presentation = _present_until(
            api,
            session_id,
            lambda shown: _tappable_id(shown, learning_item_id=focus.id) is not None,
        )
    assert_no_provider_import()
    presentation_id = presentation["presentation_id"]
    anchor_sentence_id = presentation["sentence_id"]
    assert presentation["context_stage"] == ContextStage.ANCHOR.value
    sentence_item_id = _tappable_id(presentation, learning_item_id=focus.id)
    assert sentence_item_id is not None

    # ----------------------------------------------------------------- 3, 4
    # item 클릭 -> precomputed 설명. live LLM 호출이 0이다.
    with no_outbound_network():
        explanation = _json(
            api.client.post(
                f"/api/study/presentations/{presentation_id}/items/{sentence_item_id}/click",
                json={"client_event_id": str(uuid.uuid4())},
            )
        )
    assert_no_provider_import()

    stored = db_session.execute(
        sa.select(SentenceItemExplanation)
        .join(SentenceItem, SentenceItem.id == SentenceItemExplanation.sentence_item_id)
        .where(SentenceItem.id == sentence_item_id)
    ).scalar_one()
    assert explanation["learning_item_id"] == focus.id
    assert explanation["canonical_form"] == FOCUS_LEMMA
    assert explanation["core_meaning"] == stored.core_meaning
    assert explanation["meaning_in_context"] == stored.meaning_in_context
    assert explanation["nuance"] == stored.nuance

    # ----------------------------------------------------------------- 5, 6
    # `몰랐음` 선택 -> event 저장.
    reported_at = clock.advance(timedelta(seconds=20))
    with no_outbound_network():
        _self_report(
            api, presentation_id, sentence_item_id=sentence_item_id, signal=ExplicitSignal.UNKNOWN
        )
    assert_no_provider_import()

    event = db_session.execute(
        sa.select(LearningEvent).where(
            LearningEvent.user_id == user_id,
            LearningEvent.event_type == EventType.SELF_REPORT_UNKNOWN,
        )
    ).scalar_one()
    assert event.study_presentation_id == presentation_id
    assert event.learning_item_id == focus.id
    assert event.created_at == reported_at

    # ----------------------------------------------------------------- 7
    # mastery(observation 0.0, EMA) / review state(Again) 생성.
    mastery = db_session.execute(
        sa.select(UserMastery).where(
            UserMastery.user_id == user_id, UserMastery.learning_item_id == focus.id
        )
    ).scalar_one()
    assert mastery.comprehension_mastery == pytest.approx(
        ema(None, OBSERVATION[ExplicitSignal.UNKNOWN], cfg.learning.mastery_ema_alpha)
    )
    assert mastery.evidence_count == 1
    assert mastery.listening_mastery is None

    state = _state(db_session, user_id=user_id, item_id=focus.id)
    expected, _log = Scheduler(enable_fuzzing=cfg.srs.fsrs_enable_fuzzing).review_card(
        Card(card_id=None, due=reported_at), Rating.Again, reported_at
    )
    assert (state.reps, state.lapses) == (1, 1)
    assert state.stability == expected.stability
    assert state.difficulty == expected.difficulty
    assert state.next_review_at == expected.due

    # ----------------------------------------------------------------- 8
    # `item_exposures` 생성.
    #
    # 이 구현은 exposure를 **candidate target 기준**으로 남긴다(불변식 #5). `任せる`는
    # 이 문장에서 클릭된 incidental 표현이고 이 candidate의 target은 아니므로, 8단계의
    # "1건"이 곧 `任せる`의 1건은 아니다. 그래서 여기서 고정하는 것은 두 가지다.
    #
    #   - 정상 완료한 문장은 target마다 exposure를 남긴다.
    #   - 같은 presentation의 같은 item은 최대 1건이다(click / explanation / self-report를
    #     각각 세지 않는다, 07_SRS_SPEC.md의 `중복 집계 금지`).
    #
    # `任せる` 자신의 노출 누적은 11단계부터 본다 --- 5단계의 `몰랐음`이 그것을 학습
    # target으로 승격시키므로 다음 presentation부터는 target이다.
    _complete(api, presentation_id)
    exposures = list(
        db_session.execute(
            sa.select(ItemExposure)
            .where(ItemExposure.study_presentation_id == presentation_id)
            .order_by(ItemExposure.id)
        )
        .scalars()
        .all()
    )
    # 재시도가 한 번 더 세지 않는다. `/complete`는 몇 번을 불러도 같은 결과다.
    _complete(api, presentation_id)
    repeated = db_session.execute(
        sa.select(sa.func.count(ItemExposure.id)).where(
            ItemExposure.study_presentation_id == presentation_id
        )
    ).scalar_one()
    assert repeated == len(exposures)
    completed_events = db_session.execute(
        sa.select(sa.func.count(LearningEvent.id)).where(
            LearningEvent.study_presentation_id == presentation_id,
            LearningEvent.event_type == EventType.SENTENCE_COMPLETED,
        )
    ).scalar_one()
    assert completed_events == 1

    assert exposures, "정상 완료한 문장이 exposure를 하나도 남기지 않았다"
    item_ids = [row.learning_item_id for row in exposures]
    assert len(item_ids) == len(set(item_ids))
    assert {row.context_stage for row in exposures} == {ContextStage.ANCHOR}
    assert all(row.invalidated_at is None for row in exposures)
    assert count_valid_exposures(db_session, user_id=user_id, learning_item_id=focus.id) <= 1

    # ----------------------------------------------------------------- 9, 10, 11
    # due 시점으로 테스트 clock 이동 -> 재노출 -> exposure 누적.
    #
    # 5단계의 `몰랐음`이 승격시킨 item의 **첫 제시는 `new`**이고 문장은 승격 시점에
    # 기록된 anchor --- 사용자가 실제로 물어본 그 문장이다(ADR-013). target이 아닌
    # item의 self-report는 exposure를 만들지 않으므로 최초 문맥은 여기서 1회로
    # 계상된다. 시점이 한 presentation 뒤로 밀릴 뿐 사라지지 않는다.
    _finish(api, session_id)
    clock.set(_utc(state.next_review_at))
    first_target_session_id = _start_session(api)
    first_target = _present_until(
        api,
        first_target_session_id,
        lambda shown: _tappable_id(shown, learning_item_id=focus.id) is not None,
    )
    assert first_target["presentation_role"] == PresentationRole.NEW.value
    assert first_target["sentence_id"] == anchor_sentence_id
    assert first_target["context_stage"] == ContextStage.ANCHOR.value

    before = count_valid_exposures(db_session, user_id=user_id, learning_item_id=focus.id)
    _self_report(
        api,
        first_target["presentation_id"],
        sentence_item_id=_tappable_id(first_target, learning_item_id=focus.id) or 0,
        signal=ExplicitSignal.KNOWN,
    )
    _complete(api, first_target["presentation_id"])
    after = count_valid_exposures(db_session, user_id=user_id, learning_item_id=focus.id)
    assert after == before + 1
    _finish(api, first_target_session_id)

    # 그 다음부터가 `review`다. 노출이 1건 이상이므로 이제 review pool에 있다.
    state = _state(db_session, user_id=user_id, item_id=focus.id)
    clock.set(_utc(state.next_review_at))
    review_session_id = _start_session(api)
    review = _present_until(
        api,
        review_session_id,
        lambda shown: _tappable_id(shown, learning_item_id=focus.id) is not None,
    )
    assert review["presentation_role"] == PresentationRole.REVIEW.value
    assert review["review_reason"] == ReviewReason.FSRS_DUE.value
    # 노출 1회가 ladder를 한 칸 올렸다(07_SRS_SPEC.md의 `전이 규칙`).
    assert review["context_stage"] == ContextStage.NEAR_ORIGINAL.value
    _self_report(
        api,
        review["presentation_id"],
        sentence_item_id=_tappable_id(review, learning_item_id=focus.id) or 0,
        signal=ExplicitSignal.KNOWN,
    )
    _complete(api, review["presentation_id"])
    _finish(api, review_session_id)

    # ----------------------------------------------------------------- 12
    # 초기 원문(anchor) 후 새로운 문맥으로 재노출.
    #
    # **stage를 손으로 올리지 않는다.** 실패 없는 노출이 ladder를 한 칸씩 밀어
    # 올리고, `varied` 이상은 아직 보지 않은 문장을 요구하므로 문맥이 실제로
    # 바뀐다. `varied`와 `new_context`의 문장 선택 규칙이 같은 것은 MVP의 한계다
    # (06_LEARNING_ENGINE.md의 `한계`) --- 여기서 고정하는 것은 "anchor에 고정되지
    # 않는다"이다.
    state = _state(db_session, user_id=user_id, item_id=focus.id)
    clock.set(_utc(state.next_review_at))
    new_context_session_id = _start_session(api)
    new_context = _present_until(
        api,
        new_context_session_id,
        lambda shown: _tappable_id(shown, learning_item_id=focus.id) is not None,
    )
    assert new_context["context_stage"] == ContextStage.VARIED.value
    assert new_context["sentence_id"] != anchor_sentence_id
    _self_report(
        api,
        new_context["presentation_id"],
        sentence_item_id=_tappable_id(new_context, learning_item_id=focus.id) or 0,
        signal=ExplicitSignal.KNOWN,
    )
    _complete(api, new_context["presentation_id"])
    _finish(api, new_context_session_id)

    learning_state = db_session.execute(
        sa.select(UserItemLearningState).where(
            UserItemLearningState.user_id == user_id,
            UserItemLearningState.learning_item_id == focus.id,
        )
    ).scalar_one()
    assert learning_state.context_stage is ContextStage.NEW_CONTEXT
    assert learning_state.anchor_sentence_id == anchor_sentence_id

    # ----------------------------------------------------------------- 13
    # 최소 노출 이후에도 FSRS due라면 계속 복습 가능.
    exposures_now = count_valid_exposures(db_session, user_id=user_id, learning_item_id=focus.id)
    assert exposures_now >= minimum_exposures

    # 이 fixture에는 이 표현을 담은 문장이 둘뿐이라 `new_context`가 쓸 문장이 남지
    # 않았다. 그 문맥을 **생성**하는 것은 Wave 3의 일이므로(06_LEARNING_ENGINE.md의
    # `Wave 3이 추가하는 것`) 여기서는 문장 하나를 공급해 그 상황을 흉내 낸다.
    # candidate는 여전히 materialization이 만든다.
    supplied = factories.make_ready_sentence(db_session, [focus], surfaces=[FOCUS_LEMMA])

    state = _state(db_session, user_id=user_id, item_id=focus.id)
    clock.set(_utc(state.next_review_at))
    final_session_id = _start_session(api)
    final_view = _present_until(
        api,
        final_session_id,
        lambda shown: _tappable_id(shown, learning_item_id=focus.id) is not None,
    )
    assert final_view["presentation_role"] == PresentationRole.REVIEW.value
    assert final_view["review_reason"] == ReviewReason.FSRS_DUE.value
    assert final_view["context_stage"] == ContextStage.NEW_CONTEXT.value
    assert final_view["sentence_id"] == supplied.id
    # 최소 노출을 채웠다고 복습이 끝나지 않는다. "2회 성공 후 종료" 같은 규칙이
    # 없다는 것이 07_SRS_SPEC.md의 요구다.
    assert (
        count_valid_exposures(db_session, user_id=user_id, learning_item_id=focus.id)
        >= minimum_exposures
    )
