"""Probe 대상 선정과 pacing (02_LEARNING_POLICY.md, 06_LEARNING_ENGINE.md의 Probe Pacing).

정책 숫자를 이 파일에 적지 않는다. gap / 상한 / cooldown / passive 임계값은 전부
`get_config()`에서 읽는다 --- 숫자를 베껴 두면 config를 바꿨을 때 테스트가 옛 정책을
지키게 된다.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.config import AppConfig, get_config
from app.learning.probe import ProbePriority, ProbeTarget, choose_probe
from app.learning.progression import bump_no_signal, record_probe_outcome
from app.models import (
    LearningEvent,
    LearningItem,
    ReviewState,
    StudyPresentation,
    StudySession,
    UserItemLearningState,
    UserMastery,
)
from app.models import User as UserModel
from app.models.enums import CandidateStatus, EventType
from tests import factories
from tests.clock import MutableClock

pytestmark = pytest.mark.integration

FSRS_PARAMS_VERSION_FILLER = "test"
FSRS_STATE_FILLER = 1
MASTERY_ALGORITHM_FILLER = "test"

# `애매함`(0.4)과 `알고 있었음`(0.8)의 observation. 여기에 새 임계값을 두지 않고
# 02_LEARNING_POLICY.md가 고정한 값을 그대로 쓴다.
UNCERTAIN_MASTERY = 0.4
KNOWN_MASTERY = 0.8


@pytest.fixture
def config() -> AppConfig:
    return get_config()


def _session(db: Session, user: UserModel, config: AppConfig) -> StudySession:
    return factories.make_study_session(
        db, user, target_minutes=config.learning.default_session_minutes
    )


def _learning_state(
    db: Session, user: UserModel, item: LearningItem, clock: MutableClock
) -> UserItemLearningState:
    """`user_item_learning_state` 행을 만드는 경로는 progression 하나다.

    무신호 카운터는 각 테스트가 필요한 값으로 직접 세팅하므로 여기서 0으로 되돌린다.
    """
    bump_no_signal(db, user_id=user.id, learning_item_id=item.id, now=clock.now())
    state = db.execute(
        sa.select(UserItemLearningState).where(
            UserItemLearningState.user_id == user.id,
            UserItemLearningState.learning_item_id == item.id,
        )
    ).scalar_one()
    state.passive_no_signal_count = 0
    db.flush()
    return state


def _set_passive_count(
    db: Session, user: UserModel, item: LearningItem, clock: MutableClock, *, count: int
) -> UserItemLearningState:
    """무신호 카운터를 정확히 `count`로 맞춘다. 임계값은 호출부가 config에서 읽는다."""
    state = _learning_state(db, user, item, clock)
    state.passive_no_signal_count = count
    db.flush()
    return state


def _presentation(db: Session, user: UserModel, study_session: StudySession) -> StudyPresentation:
    """presentation 하나 = 문장 하나 + candidate 하나. 문장을 매번 새로 만드는 이유는
    `uq_user_sentence_candidates_active`가 (user, sentence, role, stage)에 걸려 있기
    때문이다."""
    sentence = factories.make_sentence(db)
    candidate = factories.make_candidate(db, user, sentence, status=CandidateStatus.READY)
    return factories.make_presentation(db, user, study_session, candidate, sentence)


def _presentations(
    db: Session, user: UserModel, study_session: StudySession, count: int
) -> list[StudyPresentation]:
    return [_presentation(db, user, study_session) for _ in range(count)]


def _event(
    db: Session,
    user: UserModel,
    study_session: StudySession,
    *,
    event_type: EventType,
    presentation: StudyPresentation | None = None,
    item: LearningItem | None = None,
) -> LearningEvent:
    event = LearningEvent(
        user_id=user.id,
        study_session_id=study_session.id,
        study_presentation_id=None if presentation is None else presentation.id,
        learning_item_id=None if item is None else item.id,
        event_type=event_type,
        client_event_id=uuid.uuid4(),
        created_at=factories.NOW,
    )
    db.add(event)
    db.flush()
    return event


def _ready_session(
    db: Session, config: AppConfig
) -> tuple[UserModel, StudySession, StudyPresentation, LearningItem]:
    """간격 조건을 이미 만족한 세션. 현재 presentation은 목록의 마지막이다."""
    user = factories.make_user(db)
    study_session = _session(db, user, config)
    presentations = _presentations(
        db, user, study_session, config.learning.probe_min_gap_presentations + 1
    )
    return user, study_session, presentations[-1], factories.make_learning_item(db)


def _choose(
    db: Session,
    user: UserModel,
    study_session: StudySession,
    presentation: StudyPresentation,
    items: list[LearningItem],
    *,
    now: datetime,
    config: AppConfig,
) -> ProbeTarget | None:
    return choose_probe(
        db,
        user_id=user.id,
        study_session_id=study_session.id,
        presentation_id=presentation.id,
        target_item_ids=[item.id for item in items],
        now=now,
        config=config,
    )


# --------------------------------------------------------------------------
# Pacing --- 조건 1(상한)과 조건 2(간격)
# --------------------------------------------------------------------------


def test_the_first_presentations_of_a_session_carry_no_probe(
    db_session: Session, config: AppConfig
) -> None:
    """조건 2: 세션의 첫 probe도 gap개 뒤로 미뤄진다. 첫 문장부터 묻지 않는다."""
    clock = MutableClock()
    user = factories.make_user(db_session)
    study_session = _session(db_session, user, config)
    item = factories.make_learning_item(db_session)

    for index in range(config.learning.probe_min_gap_presentations):
        presentation = _presentation(db_session, user, study_session)
        chosen = _choose(
            db_session,
            user,
            study_session,
            presentation,
            [item],
            now=clock.now(),
            config=config,
        )
        assert chosen is None, f"presentation {index + 1}에 probe가 실렸다"


def test_a_probe_appears_once_the_gap_is_satisfied(db_session: Session, config: AppConfig) -> None:
    clock = MutableClock()
    user, study_session, presentation, item = _ready_session(db_session, config)

    chosen = _choose(
        db_session, user, study_session, presentation, [item], now=clock.now(), config=config
    )

    assert chosen is not None
    assert chosen.learning_item_id == item.id


def test_the_next_probe_waits_for_the_gap_again(db_session: Session, config: AppConfig) -> None:
    """조건 2의 둘째 갈래: 마지막 probe 이후 제시된 presentation 수 >= gap."""
    clock = MutableClock()
    user, study_session, probed, item = _ready_session(db_session, config)
    _event(
        db_session,
        user,
        study_session,
        event_type=EventType.MASTERY_PROBE_SHOWN,
        presentation=probed,
        item=factories.make_learning_item(db_session),
    )

    # 마지막 probe와 다음 probe 사이에는 gap개의 presentation이 실제로 놓인다.
    for _ in range(config.learning.probe_min_gap_presentations):
        presentation = _presentation(db_session, user, study_session)
        assert (
            _choose(
                db_session,
                user,
                study_session,
                presentation,
                [item],
                now=clock.now(),
                config=config,
            )
            is None
        )

    presentation = _presentation(db_session, user, study_session)
    assert (
        _choose(
            db_session, user, study_session, presentation, [item], now=clock.now(), config=config
        )
        is not None
    )


def test_the_session_budget_is_an_upper_bound(db_session: Session, config: AppConfig) -> None:
    """조건 1: 이번 세션의 probe 수가 상한에 닿으면 간격이 아무리 벌어져도 묻지 않는다."""
    clock = MutableClock()
    user = factories.make_user(db_session)
    study_session = _session(db_session, user, config)
    item = factories.make_learning_item(db_session)
    budget = config.learning.mastery_probe_target_per_session_max

    shown = 0
    probes: list[int] = []
    while shown < budget:
        presentations = _presentations(
            db_session, user, study_session, config.learning.probe_min_gap_presentations + 1
        )
        target = _choose(
            db_session,
            user,
            study_session,
            presentations[-1],
            [item],
            now=clock.now(),
            config=config,
        )
        assert target is not None
        probes.append(target.learning_item_id)
        # 실제 경로에서 event를 남기는 것은 services다. 여기서는 그 결과만 흉내낸다.
        _event(
            db_session,
            user,
            study_session,
            event_type=EventType.MASTERY_PROBE_SHOWN,
            presentation=presentations[-1],
            item=factories.make_learning_item(db_session),
        )
        shown += 1

    assert len(probes) == budget
    presentations = _presentations(
        db_session, user, study_session, config.learning.probe_min_gap_presentations + 1
    )
    assert (
        _choose(
            db_session,
            user,
            study_session,
            presentations[-1],
            [item],
            now=clock.now(),
            config=config,
        )
        is None
    )


def test_a_presentation_without_targets_carries_no_probe(
    db_session: Session, config: AppConfig
) -> None:
    clock = MutableClock()
    user, study_session, presentation, _ = _ready_session(db_session, config)

    assert (
        _choose(db_session, user, study_session, presentation, [], now=clock.now(), config=config)
        is None
    )


# --------------------------------------------------------------------------
# 대상 우선순위
# --------------------------------------------------------------------------


def test_an_item_without_mastery_evidence_comes_first(
    db_session: Session, config: AppConfig
) -> None:
    """우선순위 1. `user_mastery` 행이 아예 없는 경우다."""
    clock = MutableClock()
    user, study_session, presentation, uncertain_item = _ready_session(db_session, config)
    factories.make_mastery(
        db_session,
        user,
        uncertain_item,
        comprehension_mastery=UNCERTAIN_MASTERY,
        algorithm_version=MASTERY_ALGORITHM_FILLER,
    )
    unknown_item = factories.make_learning_item(db_session)

    # id가 더 큰 쪽이 우선순위 1이다. tie-break가 아니라 우선순위가 이겨야 한다.
    assert unknown_item.id > uncertain_item.id
    chosen = _choose(
        db_session,
        user,
        study_session,
        presentation,
        [uncertain_item, unknown_item],
        now=clock.now(),
        config=config,
    )

    assert chosen is not None
    assert chosen.learning_item_id == unknown_item.id
    assert chosen.priority is ProbePriority.NO_EXPLICIT_EVIDENCE


def test_a_null_mastery_row_counts_as_no_evidence(db_session: Session, config: AppConfig) -> None:
    """NULL은 "능력 0"이 아니라 "아직 evidence 없음"이다(02_LEARNING_POLICY.md)."""
    clock = MutableClock()
    user, study_session, presentation, item = _ready_session(db_session, config)
    factories.make_mastery(
        db_session,
        user,
        item,
        comprehension_mastery=None,
        algorithm_version=MASTERY_ALGORITHM_FILLER,
    )

    chosen = _choose(
        db_session, user, study_session, presentation, [item], now=clock.now(), config=config
    )

    assert chosen is not None
    assert chosen.priority is ProbePriority.NO_EXPLICIT_EVIDENCE


def test_passive_exposure_orders_first_within_the_same_priority(
    db_session: Session, config: AppConfig
) -> None:
    """ADR-011: passive 노출은 독립 순위가 아니라 1번 **안**의 정렬 기준이다.

    반복해서 스쳐 지나갔는데 한 번도 말하지 않은 item이 확인 가치가 가장 크다.
    passive 쪽 id를 일부러 더 크게 잡아 `learning_item_id` tie-break가 아니라 이
    정렬 기준이 이겼음을 고정한다.
    """
    clock = MutableClock()
    user, study_session, presentation, silent_item = _ready_session(db_session, config)
    passive_item = factories.make_learning_item(db_session)
    assert passive_item.id > silent_item.id
    _set_passive_count(
        db_session,
        user,
        passive_item,
        clock,
        count=config.learning.passive_exposures_before_probe,
    )

    chosen = _choose(
        db_session,
        user,
        study_session,
        presentation,
        [silent_item, passive_item],
        now=clock.now(),
        config=config,
    )

    assert chosen is not None
    assert chosen.learning_item_id == passive_item.id
    assert chosen.priority is ProbePriority.NO_EXPLICIT_EVIDENCE


def test_the_passive_ordering_threshold_is_inclusive(
    db_session: Session, config: AppConfig
) -> None:
    """경계는 포함이다. 임계값에서 1 모자라면 다시 `learning_item_id` 순서로 돌아간다."""
    clock = MutableClock()
    user, study_session, presentation, silent_item = _ready_session(db_session, config)
    passive_item = factories.make_learning_item(db_session)
    threshold = config.learning.passive_exposures_before_probe
    state = _set_passive_count(db_session, user, passive_item, clock, count=threshold)

    def chosen_id() -> int | None:
        chosen = _choose(
            db_session,
            user,
            study_session,
            presentation,
            [silent_item, passive_item],
            now=clock.now(),
            config=config,
        )
        return None if chosen is None else chosen.learning_item_id

    assert chosen_id() == passive_item.id, "임계값에 정확히 닿은 순간"

    state.passive_no_signal_count = threshold - 1
    db_session.flush()
    assert chosen_id() == silent_item.id, "임계값 1 미만"


def test_passive_exposure_does_not_probe_an_item_that_has_explicit_evidence(
    db_session: Session, config: AppConfig
) -> None:
    """passive 노출은 정렬 기준일 뿐 순위가 아니다(ADR-011).

    이미 `알고 있었음` 수준의 evidence가 있는 item은 아무리 스쳐 지나가도 묻지 않는다.
    """
    clock = MutableClock()
    user, study_session, presentation, item = _ready_session(db_session, config)
    factories.make_mastery(
        db_session,
        user,
        item,
        comprehension_mastery=KNOWN_MASTERY,
        algorithm_version=MASTERY_ALGORITHM_FILLER,
    )
    _set_passive_count(
        db_session, user, item, clock, count=config.learning.passive_exposures_before_probe
    )

    assert (
        _choose(
            db_session, user, study_session, presentation, [item], now=clock.now(), config=config
        )
        is None
    )


def test_an_uncertain_item_is_probed_but_a_known_one_is_not(
    db_session: Session, config: AppConfig
) -> None:
    """우선순위 4. `알고 있었음` 수준의 item은 묻지 않는다."""
    clock = MutableClock()
    user, study_session, presentation, uncertain_item = _ready_session(db_session, config)
    known_item = factories.make_learning_item(db_session)
    for item, mastery in ((uncertain_item, UNCERTAIN_MASTERY), (known_item, KNOWN_MASTERY)):
        factories.make_mastery(
            db_session,
            user,
            item,
            comprehension_mastery=mastery,
            algorithm_version=MASTERY_ALGORITHM_FILLER,
        )

    chosen = _choose(
        db_session,
        user,
        study_session,
        presentation,
        [known_item, uncertain_item],
        now=clock.now(),
        config=config,
    )

    assert chosen is not None
    assert chosen.learning_item_id == uncertain_item.id
    assert chosen.priority is ProbePriority.UNCERTAIN


def test_ties_break_on_learning_item_id(db_session: Session, config: AppConfig) -> None:
    """같은 우선순위면 항상 같은 답이 나온다."""
    clock = MutableClock()
    user, study_session, presentation, first = _ready_session(db_session, config)
    second = factories.make_learning_item(db_session)
    assert second.id > first.id

    for order in ([first, second], [second, first]):
        chosen = _choose(
            db_session, user, study_session, presentation, order, now=clock.now(), config=config
        )
        assert chosen is not None
        assert chosen.learning_item_id == first.id


# --------------------------------------------------------------------------
# 제외
# --------------------------------------------------------------------------


def test_an_item_with_an_explicit_self_report_this_session_is_not_probed(
    db_session: Session, config: AppConfig
) -> None:
    """제외 1: 방금 explicit feedback을 받은 item. 방금 답한 것을 다시 묻지 않는다."""
    clock = MutableClock()
    user, study_session, presentation, item = _ready_session(db_session, config)
    _event(
        db_session,
        user,
        study_session,
        event_type=EventType.SELF_REPORT_UNKNOWN,
        presentation=presentation,
        item=item,
    )

    assert (
        _choose(
            db_session, user, study_session, presentation, [item], now=clock.now(), config=config
        )
        is None
    )


def test_a_self_report_for_another_item_does_not_exclude_this_one(
    db_session: Session, config: AppConfig
) -> None:
    clock = MutableClock()
    user, study_session, presentation, item = _ready_session(db_session, config)
    _event(
        db_session,
        user,
        study_session,
        event_type=EventType.SELF_REPORT_UNKNOWN,
        presentation=presentation,
        item=factories.make_learning_item(db_session),
    )

    assert (
        _choose(
            db_session, user, study_session, presentation, [item], now=clock.now(), config=config
        )
        is not None
    )


def test_an_item_already_probed_in_this_session_is_not_probed_again(
    db_session: Session, config: AppConfig
) -> None:
    """응답하지 않은 probe는 `last_probe_at`을 남기지 않으므로 cooldown이 잡지 못한다."""
    clock = MutableClock()
    user, study_session, first, item = _ready_session(db_session, config)
    _event(
        db_session,
        user,
        study_session,
        event_type=EventType.MASTERY_PROBE_SHOWN,
        presentation=first,
        item=item,
    )
    later = _presentations(
        db_session, user, study_session, config.learning.probe_min_gap_presentations
    )[-1]

    assert (
        _choose(db_session, user, study_session, later, [item], now=clock.now(), config=config)
        is None
    )


def test_cooldown_blocks_the_item_until_it_expires(db_session: Session, config: AppConfig) -> None:
    """제외 2. 경계는 포함이다: cooldown이 정확히 지난 순간부터 다시 묻는다."""
    clock = MutableClock()
    user, study_session, presentation, item = _ready_session(db_session, config)
    state = _learning_state(db_session, user, item, clock)
    state.last_probe_at = clock.now()
    db_session.flush()

    cooldown = timedelta(days=config.learning.probe_skip_cooldown_days)
    clock.advance(cooldown - timedelta(seconds=1))
    assert (
        _choose(
            db_session, user, study_session, presentation, [item], now=clock.now(), config=config
        )
        is None
    ), "cooldown 만료 1초 전"

    clock.advance(timedelta(seconds=1))
    assert (
        _choose(
            db_session, user, study_session, presentation, [item], now=clock.now(), config=config
        )
        is not None
    ), "cooldown이 정확히 지난 순간"


def test_a_cooldown_on_one_item_does_not_block_another(
    db_session: Session, config: AppConfig
) -> None:
    clock = MutableClock()
    user, study_session, presentation, blocked = _ready_session(db_session, config)
    free = factories.make_learning_item(db_session)
    state = _learning_state(db_session, user, blocked, clock)
    state.last_probe_at = clock.now()
    db_session.flush()

    chosen = _choose(
        db_session,
        user,
        study_session,
        presentation,
        [blocked, free],
        now=clock.now(),
        config=config,
    )

    assert chosen is not None
    assert chosen.learning_item_id == free.id


# --------------------------------------------------------------------------
# Skip
# --------------------------------------------------------------------------


def test_a_skipped_probe_creates_no_mastery_and_no_fsrs_state(
    db_session: Session, config: AppConfig
) -> None:
    """skip은 mastery evidence도 FSRS grade도 아니다(02_LEARNING_POLICY.md의 Skip).

    기록은 `progression.record_probe_outcome`이 하고 이 모듈은 그 결과를 읽기만 한다.
    """
    clock = MutableClock()
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    review_state = factories.make_review_state(
        db_session, user, item, state=FSRS_STATE_FILLER, params_version=FSRS_PARAMS_VERSION_FILLER
    )
    scheduled_at = review_state.next_review_at

    record_probe_outcome(
        db_session, user_id=user.id, learning_item_id=item.id, response=None, now=clock.now()
    )

    mastery_rows = db_session.execute(
        sa.select(sa.func.count()).select_from(UserMastery).where(UserMastery.user_id == user.id)
    ).scalar_one()
    assert mastery_rows == 0
    refreshed = db_session.execute(
        sa.select(ReviewState).where(ReviewState.id == review_state.id)
    ).scalar_one()
    assert refreshed.next_review_at == scheduled_at
    assert refreshed.deferred_until is None


def test_a_skipped_item_is_not_asked_again_immediately(
    db_session: Session, config: AppConfig
) -> None:
    """`skip 후 같은 item을 즉시 다시 묻지 않는다`는 `probe_skip_cooldown_days`가 지킨다."""
    clock = MutableClock()
    user, study_session, presentation, item = _ready_session(db_session, config)
    record_probe_outcome(
        db_session, user_id=user.id, learning_item_id=item.id, response=None, now=clock.now()
    )

    clock.advance(timedelta(days=config.learning.probe_skip_cooldown_days) - timedelta(seconds=1))
    assert (
        _choose(
            db_session, user, study_session, presentation, [item], now=clock.now(), config=config
        )
        is None
    )
