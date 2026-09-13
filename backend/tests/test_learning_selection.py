"""Category Mix / Review Reason / Review Ordering / Pool Fallback / Materialization.

선택 규칙 자체(deficit, tie-break, reason 5단 절차)는 DB를 보지 않으므로 순수
함수로 고정한다. 정책값은 하드코딩하지 않고 **인자로 주입**한다 --- 값을 무시하는
구현이 통과하지 못해야 하기 때문이다.

Ready Pool을 만드는 경로(materialization)는 손으로 INSERT하지 않고 실제로
`materialize_candidates`를 호출해서 만든다(06_LEARNING_ENGINE.md의
`테스트에서의 candidate 구성`). 선택 함수만 보는 테스트는 예외이므로 candidate를
직접 구성한다.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.config import get_config
from app.learning.progression import INITIAL_CONTEXT_STAGE, STAGE_LADDER, stage_rank
from app.learning.selection import (
    Selection,
    SessionCounters,
    choose_ratios,
    choose_review_reason,
    count_backlog,
    load_counters,
    materialize_candidates,
    rank_categories,
    select_next,
)
from app.models import (
    ItemExposure,
    LearningEvent,
    LearningItem,
    ReviewState,
    Sentence,
    SentenceItem,
    SentenceItemExplanation,
    StudyPresentation,
    StudySession,
    User,
    UserItemLearningState,
    UserSentenceCandidate,
    UserSentenceCandidateTarget,
)
from app.models.enums import (
    CandidateStatus,
    ContextStage,
    EventType,
    ExplanationStatus,
    ExplicitSignal,
    ExposureModality,
    PresentationRole,
    ReviewReason,
    SentenceStatus,
)
from app.srs.review import record_explicit_review
from tests import factories
from tests.clock import MutableClock
from tests.conftest import override_config

REVIEW = PresentationRole.REVIEW
NEW = PresentationRole.NEW
EXPLORATION = PresentationRole.EXPLORATION
ALL_ROLES = (REVIEW, NEW, EXPLORATION)

FSRS_DUE = ReviewReason.FSRS_DUE
REINFORCEMENT = ReviewReason.REINFORCEMENT
CONTEXT_REPAIR = ReviewReason.CONTEXT_REPAIR

FSRS_PARAMS_VERSION_FILLER = "test"
FSRS_STATE_FILLER = 1
MASTERY_ALGORITHM_FILLER = "test"


def _counters(
    role_counts: dict[PresentationRole, int] | None = None,
    reason_counts: dict[ReviewReason, int] | None = None,
) -> SessionCounters:
    return SessionCounters.from_counts(role_counts or {}, reason_counts or {})


# --------------------------------------------------------------------------
# Category Mix (순수)
# --------------------------------------------------------------------------


def test_the_first_sentence_of_a_session_has_a_non_zero_deficit() -> None:
    """`total_presented`가 이번에 제시할 1을 포함하지 않으면 첫 문장에서 전부 0이 되고
    tie-break만으로 category가 정해진다."""
    ratios = {REVIEW: 0.7, NEW: 0.2, EXPLORATION: 0.1}

    assert rank_categories(ratios, _counters()) == [REVIEW, NEW, EXPLORATION]


def test_ties_fall_back_to_review_then_new_then_exploration() -> None:
    """세 deficit이 정확히 같을 때의 순서는 명세가 정한 상수다."""
    ratios = {EXPLORATION: 1 / 3, NEW: 1 / 3, REVIEW: 1 / 3}

    assert rank_categories(ratios, _counters()) == [REVIEW, NEW, EXPLORATION]


def test_a_category_that_is_ahead_of_its_share_sorts_last() -> None:
    ratios = {REVIEW: 0.7, NEW: 0.2, EXPLORATION: 0.1}
    counters = _counters({REVIEW: 1, NEW: 3, EXPLORATION: 0})

    assert rank_categories(ratios, counters)[-1] == NEW


def _simulate_mix(
    ratios: dict[PresentationRole, float], presentations: int
) -> list[PresentationRole]:
    """매 문장마다 deficit을 다시 계산한다. 세션 시작 시 정수 quota를 고정하지 않는다."""
    counters = _counters()
    chosen: list[PresentationRole] = []
    for _ in range(presentations):
        role = rank_categories(ratios, counters)[0]
        chosen.append(role)
        counts = dict(counters.by_role)
        counts[role] += 1
        counters = SessionCounters.from_counts(counts, counters.by_review_reason)
    return chosen


def test_fifteen_sentences_converge_without_an_exact_integer_quota() -> None:
    """15는 70/20/10으로 나누어떨어지지 않는다(10.5 / 3 / 1.5).

    시퀀스를 통째로 고정하는 이유는, 나누어떨어지지 않는 자리에서 동률이 생기고
    그 자리를 **부동소수점 오차가 아니라 명시된 tie-break**가 정해야 하기 때문이다.
    0.7*12-8 과 0.2*12-2 는 수학적으로 같은 0.4지만 IEEE 754에서는 다르다.
    """
    ratios = {REVIEW: 0.7, NEW: 0.2, EXPLORATION: 0.1}

    sequence = _simulate_mix(ratios, 15)

    assert sequence == [
        REVIEW,
        REVIEW,
        NEW,
        REVIEW,
        REVIEW,
        EXPLORATION,
        REVIEW,
        REVIEW,
        NEW,
        REVIEW,
        REVIEW,
        REVIEW,
        NEW,
        REVIEW,
        REVIEW,
    ]
    assert sequence.count(REVIEW) == 11
    assert sequence.count(NEW) == 3
    assert sequence.count(EXPLORATION) == 1


def test_a_long_session_stays_within_one_presentation_of_each_share() -> None:
    ratios = {REVIEW: 0.7, NEW: 0.2, EXPLORATION: 0.1}

    sequence = _simulate_mix(ratios, 100)

    for role, ratio in ratios.items():
        assert abs(sequence.count(role) - ratio * 100) <= 1


# --------------------------------------------------------------------------
# Backlog (순수)
# --------------------------------------------------------------------------


def test_below_the_threshold_the_configured_ratios_are_used() -> None:
    cfg = get_config().learning

    assert choose_ratios(cfg.backlog_threshold - 1, cfg) == {
        REVIEW: cfg.review_ratio,
        NEW: cfg.new_ratio,
        EXPLORATION: cfg.exploration_ratio,
    }


def test_at_the_threshold_the_whole_backlog_set_replaces_the_ratios() -> None:
    """일부 키만 바꾸지 않는다. 섞으면 합이 1.0이라는 config 검증이 의미를 잃는다."""
    cfg = get_config().learning.model_copy(
        update={
            "backlog_review_ratio": 0.85,
            "backlog_new_ratio": 0.0,
            "backlog_exploration_ratio": 0.15,
        }
    )

    assert choose_ratios(cfg.backlog_threshold, cfg) == {
        REVIEW: 0.85,
        NEW: 0.0,
        EXPLORATION: 0.15,
    }


# --------------------------------------------------------------------------
# Review Reason (순수)
# --------------------------------------------------------------------------


def _simulate_reasons(
    available: set[ReviewReason], share: float, presentations: int
) -> list[ReviewReason]:
    counters = _counters()
    chosen: list[ReviewReason] = []
    for _ in range(presentations):
        reason = choose_review_reason(available, counters, share)
        assert reason is not None
        chosen.append(reason)
        reasons = dict(counters.by_review_reason)
        reasons[reason] += 1
        roles = dict(counters.by_role)
        roles[REVIEW] += 1
        counters = SessionCounters.from_counts(roles, reasons)
    return chosen


def test_the_minimum_share_is_repaid_at_the_front_of_the_session() -> None:
    """06_LEARNING_ENGINE.md의 예시 그대로다. share는 주입값이지 config 읽기가 아니다."""
    sequence = _simulate_reasons({FSRS_DUE, REINFORCEMENT}, share=0.2, presentations=6)

    assert sequence == [REINFORCEMENT, FSRS_DUE, FSRS_DUE, FSRS_DUE, FSRS_DUE, REINFORCEMENT]


def test_the_cumulative_reinforcement_share_converges_to_the_setting() -> None:
    sequence = _simulate_reasons({FSRS_DUE, REINFORCEMENT}, share=0.2, presentations=50)

    assert sequence.count(REINFORCEMENT) == 10


def test_a_zero_share_turns_the_rule_off_and_leaves_pure_priority() -> None:
    sequence = _simulate_reasons({FSRS_DUE, REINFORCEMENT}, share=0.0, presentations=5)

    assert sequence == [FSRS_DUE] * 5


def test_context_repair_outranks_the_minimum_share() -> None:
    """직전 실패를 방치하면 오답이 굳는다. 최소 지분은 fsrs_due보다만 앞선다."""
    reason = choose_review_reason({CONTEXT_REPAIR, FSRS_DUE, REINFORCEMENT}, _counters(), 1.0)

    assert reason is CONTEXT_REPAIR


def test_reinforcement_is_still_used_when_the_share_is_already_met() -> None:
    """4단계. fsrs_due가 없으면 지분과 무관하게 reinforcement를 쓴다."""
    counters = _counters({REVIEW: 4}, {REINFORCEMENT: 4})

    assert choose_review_reason({REINFORCEMENT}, counters, 0.2) is REINFORCEMENT


def test_no_available_reason_means_pool_fallback() -> None:
    assert choose_review_reason(set(), _counters(), 0.2) is None


# --------------------------------------------------------------------------
# context ladder (순수)
# --------------------------------------------------------------------------


def test_the_repair_comparison_and_the_transition_share_one_ladder() -> None:
    """`context_repair`의 `context_stage < S_fail` 비교와 전이가 같은 순서를 본다.

    선언이 둘이면 한쪽만 뒤집혀도 아무도 눈치채지 못한 채 repair가 영영 참이거나
    영영 거짓이 된다. canonical 선언은 `learning/progression.py` 하나다(ADR-012).
    """
    assert STAGE_LADDER == (
        ContextStage.ANCHOR,
        ContextStage.NEAR_ORIGINAL,
        ContextStage.VARIED,
        ContextStage.NEW_CONTEXT,
    )
    assert [stage_rank(stage) for stage in STAGE_LADDER] == [0, 1, 2, 3]


# --------------------------------------------------------------------------
# DB 헬퍼
# --------------------------------------------------------------------------


def _ready_sentence(
    db_session: Session, items: list[LearningItem], *, explained: bool = True
) -> Sentence:
    """Ready invariant를 만족하는 문장. tappable item마다 validated explanation을 둔다."""
    sentence = factories.make_sentence(db_session)
    for item in items:
        sentence_item = SentenceItem(
            sentence_id=sentence.id,
            learning_item_id=item.id,
            surface_form=item.lemma,
            is_tappable=True,
            created_at=factories.NOW,
        )
        db_session.add(sentence_item)
        db_session.flush()
        if explained:
            db_session.add(
                SentenceItemExplanation(
                    sentence_item_id=sentence_item.id,
                    reading="r",
                    core_meaning="c",
                    meaning_in_context="m",
                    nuance="n",
                    example_sentence="e",
                    generated_at=factories.NOW,
                    status=ExplanationStatus.VALIDATED,
                )
            )
    db_session.flush()
    return sentence


def _learning_state(
    db_session: Session,
    user: User,
    item: LearningItem,
    *,
    active: bool = True,
    stage: ContextStage = ContextStage.ANCHOR,
    anchor_sentence_id: int | None = None,
) -> UserItemLearningState:
    state = UserItemLearningState(
        user_id=user.id,
        learning_item_id=item.id,
        context_stage=stage,
        is_active_learning_target=active,
        anchor_sentence_id=anchor_sentence_id,
        updated_at=factories.NOW,
    )
    db_session.add(state)
    db_session.flush()
    return state


def _schedule(
    db_session: Session,
    user: User,
    item: LearningItem,
    *,
    next_review_at: datetime,
    deferred_until: datetime | None = None,
) -> None:
    """FSRS 컬럼을 세팅하는 것은 테스트 fixture의 일이다. 프로덕션 코드에서는
    `app/srs/`만 쓸 수 있다(G5)."""
    state = factories.make_review_state(
        db_session,
        user,
        item,
        state=FSRS_STATE_FILLER,
        params_version=FSRS_PARAMS_VERSION_FILLER,
    )
    state.next_review_at = next_review_at
    state.deferred_until = deferred_until
    db_session.flush()


def _candidate(
    db_session: Session,
    user: User,
    sentence: Sentence,
    *,
    role: PresentationRole,
    targets: list[LearningItem],
    reason: ReviewReason | None = None,
    stage: ContextStage = ContextStage.ANCHOR,
    status: CandidateStatus = CandidateStatus.READY,
) -> UserSentenceCandidate:
    candidate = UserSentenceCandidate(
        user_id=user.id,
        sentence_id=sentence.id,
        presentation_role=role,
        review_reason=reason,
        context_stage=stage,
        status=status,
        created_at=factories.NOW,
        updated_at=factories.NOW,
    )
    db_session.add(candidate)
    db_session.flush()
    for item in targets:
        db_session.add(
            UserSentenceCandidateTarget(
                candidate_id=candidate.id, learning_item_id=item.id, is_new_item=False
            )
        )
    db_session.flush()
    return candidate


def _study_session(db_session: Session, user: User) -> StudySession:
    return factories.make_study_session(
        db_session, user, target_minutes=get_config().learning.default_session_minutes
    )


def _presentation(
    db_session: Session,
    user: User,
    study_session: StudySession,
    candidate: UserSentenceCandidate,
    *,
    role: PresentationRole,
    reason: ReviewReason | None = None,
    stage: ContextStage = ContextStage.ANCHOR,
    now: datetime = factories.NOW,
) -> StudyPresentation:
    presentation = StudyPresentation(
        study_session_id=study_session.id,
        user_id=user.id,
        candidate_id=candidate.id,
        sentence_id=candidate.sentence_id,
        presentation_role=role,
        review_reason=reason,
        context_stage=stage,
        shown_at=now,
        # 세션 이력은 닫힌 행이다. 한 세션에 미완료 행은 하나뿐이므로
        # (`uq_study_presentations_open`) 여러 건을 세우려면 완료돼 있어야 한다.
        # category mix 집계는 `completed_at`을 보지 않는다.
        completed_at=now,
    )
    db_session.add(presentation)
    db_session.flush()
    return presentation


def _expose(db_session: Session, user: User, item: LearningItem, now: datetime) -> None:
    """`item_exposures` 한 건. 조건 3(최근 노출)의 판정 소스이고, **그 item을 `new`
    pool에서 `review` pool로 옮기는 조건**이기도 하다(ADR-013)."""
    sentence = _ready_sentence(db_session, [item])
    study_session = _study_session(db_session, user)
    candidate = _candidate(
        db_session,
        user,
        sentence,
        role=EXPLORATION,
        targets=[item],
        status=CandidateStatus.CONSUMED,
    )
    presentation = _presentation(db_session, user, study_session, candidate, role=EXPLORATION)
    db_session.add(
        ItemExposure(
            user_id=user.id,
            learning_item_id=item.id,
            study_presentation_id=presentation.id,
            sentence_id=sentence.id,
            modality=ExposureModality.READING,
            context_stage=ContextStage.ANCHOR,
            created_at=now,
        )
    )
    db_session.flush()


def _exposure(
    db_session: Session,
    user: User,
    item: LearningItem,
    presentation: StudyPresentation,
    *,
    stage: ContextStage,
    now: datetime,
) -> None:
    """이미 만든 presentation에 유효 exposure 1건을 붙인다.

    `context_repair`의 S_fail은 `study_presentations`가 아니라 이 row에서 읽는다
    (06_LEARNING_ENGINE.md의 조건 1-a).
    """
    db_session.add(
        ItemExposure(
            user_id=user.id,
            learning_item_id=item.id,
            study_presentation_id=presentation.id,
            sentence_id=presentation.sentence_id,
            modality=ExposureModality.READING,
            context_stage=stage,
            created_at=now,
        )
    )
    db_session.flush()


def _utc(moment: datetime) -> datetime:
    """DB가 돌려주는 시각에는 세션 timezone이 붙어 있다. 같은 순간을 UTC로 옮긴다."""
    return moment.astimezone(UTC)


def _candidates_of(
    db_session: Session, user: User, *, role: PresentationRole | None = None
) -> list[UserSentenceCandidate]:
    """Ready Pool 그 자체. 이미 소비된 candidate는 pool이 아니므로 세지 않는다."""
    statement = sa.select(UserSentenceCandidate).where(
        UserSentenceCandidate.user_id == user.id,
        UserSentenceCandidate.status == CandidateStatus.READY,
    )
    if role is not None:
        statement = statement.where(UserSentenceCandidate.presentation_role == role)
    return list(db_session.execute(statement.order_by(UserSentenceCandidate.id)).scalars().all())


def _targets_of(db_session: Session, candidate: UserSentenceCandidate) -> list[int]:
    return list(
        db_session.execute(
            sa.select(UserSentenceCandidateTarget.learning_item_id)
            .where(UserSentenceCandidateTarget.candidate_id == candidate.id)
            .order_by(UserSentenceCandidateTarget.learning_item_id)
        )
        .scalars()
        .all()
    )


# --------------------------------------------------------------------------
# 세션 카운터 (DB)
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_counters_come_from_the_presentations_table(db_session: Session) -> None:
    """in-memory 카운터를 쓰지 않는다. 세션 resume과 서버 재시작에도 비율이 유지되어야 한다."""
    user = factories.make_user(db_session)
    study_session = _study_session(db_session, user)
    item = factories.make_learning_item(db_session)
    sentence = _ready_sentence(db_session, [item])
    review = _candidate(db_session, user, sentence, role=REVIEW, reason=FSRS_DUE, targets=[item])
    exploration = _candidate(db_session, user, sentence, role=EXPLORATION, targets=[item])
    _presentation(db_session, user, study_session, review, role=REVIEW, reason=FSRS_DUE)
    _presentation(db_session, user, study_session, review, role=REVIEW, reason=REINFORCEMENT)
    _presentation(db_session, user, study_session, exploration, role=EXPLORATION)

    counters = load_counters(db_session, study_session_id=study_session.id)

    assert counters.total == 3
    assert counters.by_role[REVIEW] == 2
    assert counters.by_role[EXPLORATION] == 1
    assert counters.by_role[NEW] == 0
    assert counters.by_review_reason[FSRS_DUE] == 1
    assert counters.by_review_reason[REINFORCEMENT] == 1
    assert counters.by_review_reason[CONTEXT_REPAIR] == 0


@pytest.mark.integration
def test_counters_of_an_empty_session_are_all_zero(db_session: Session) -> None:
    user = factories.make_user(db_session)
    study_session = _study_session(db_session, user)

    counters = load_counters(db_session, study_session_id=study_session.id)

    assert counters.total == 0
    assert set(counters.by_role) == set(PresentationRole)
    assert set(counters.by_review_reason) == set(ReviewReason)


@pytest.mark.integration
def test_backlog_counts_only_eligible_due_items(db_session: Session) -> None:
    """deferral 중인 item은 밀린 빚이 아니다. `overdue 93` 부채감 UX를 만들지 않는다."""
    clock = MutableClock()
    user = factories.make_user(db_session)
    due = factories.make_learning_item(db_session)
    later = factories.make_learning_item(db_session)
    deferred = factories.make_learning_item(db_session)
    _schedule(db_session, user, due, next_review_at=clock.now() - timedelta(days=1))
    _schedule(db_session, user, later, next_review_at=clock.now() + timedelta(days=1))
    _schedule(
        db_session,
        user,
        deferred,
        next_review_at=clock.now() - timedelta(days=1),
        deferred_until=clock.now() + timedelta(hours=12),
    )

    assert count_backlog(db_session, user_id=user.id, now=clock.now()) == 1


# --------------------------------------------------------------------------
# Candidate Materialization (DB)
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_a_seed_only_user_gets_exploration_candidates_only(db_session: Session) -> None:
    """Cold start. `user_item_learning_state` 행이 없으므로 new와 review pool은 비고
    exploration만 생긴다. 신규 사용자에게 review 70%를 강제로 만들지 않는다."""
    clock = MutableClock()
    user = factories.make_user(db_session)
    first = factories.make_learning_item(db_session)
    second = factories.make_learning_item(db_session)
    _ready_sentence(db_session, [first])
    _ready_sentence(db_session, [second])

    created = materialize_candidates(
        db_session, user=user, now=clock.now(), cfg=get_config().learning
    )

    candidates = _candidates_of(db_session, user)
    assert created == 2
    assert {candidate.presentation_role for candidate in candidates} == {EXPLORATION}
    assert {candidate.status for candidate in candidates} == {CandidateStatus.READY}
    assert {candidate.context_stage for candidate in candidates} == {ContextStage.ANCHOR}
    assert {candidate.review_reason for candidate in candidates} == {None}
    assert {candidate.created_at for candidate in candidates} == {clock.now()}
    assert sorted(_targets_of(db_session, candidates[0])) == [first.id]


@pytest.mark.integration
def test_the_first_target_of_a_new_item_is_marked_new(db_session: Session) -> None:
    """`review_states` 행이 없는 target은 `is_new_item = true`다 (06)."""
    clock = MutableClock()
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    _ready_sentence(db_session, [item])

    materialize_candidates(db_session, user=user, now=clock.now(), cfg=get_config().learning)

    (candidate,) = _candidates_of(db_session, user)
    target = db_session.execute(
        sa.select(UserSentenceCandidateTarget).where(
            UserSentenceCandidateTarget.candidate_id == candidate.id
        )
    ).scalar_one()
    assert target.is_new_item is True


@pytest.mark.integration
def test_running_materialization_twice_does_not_duplicate_candidates(
    db_session: Session,
) -> None:
    """재실행은 idempotent해야 한다. 세션 생성과 /next가 같은 요청 흐름에서 둘 다 부른다."""
    clock = MutableClock()
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    _ready_sentence(db_session, [item])
    cfg = get_config().learning

    first = materialize_candidates(db_session, user=user, now=clock.now(), cfg=cfg)
    second = materialize_candidates(
        db_session, user=user, now=clock.advance(timedelta(minutes=1)), cfg=cfg
    )

    assert (first, second) == (1, 0)
    assert len(_candidates_of(db_session, user)) == 1


@pytest.mark.integration
def test_a_sentence_without_a_validated_explanation_never_becomes_ready(
    db_session: Session,
) -> None:
    """explanation이 없는 item을 포함한 문장은 candidate가 되지 않는다. 탭했을 때
    보여줄 것이 없는 문장을 ready로 두면 핵심 UI가 빈 화면이 된다."""
    clock = MutableClock()
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    _ready_sentence(db_session, [item], explained=False)

    created = materialize_candidates(
        db_session, user=user, now=clock.now(), cfg=get_config().learning
    )

    assert created == 0
    assert _candidates_of(db_session, user) == []


@pytest.mark.integration
def test_a_quarantined_sentence_never_becomes_ready(db_session: Session) -> None:
    clock = MutableClock()
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    sentence = _ready_sentence(db_session, [item])
    sentence.status = SentenceStatus.QUARANTINED
    db_session.flush()

    created = materialize_candidates(
        db_session, user=user, now=clock.now(), cfg=get_config().learning
    )

    assert created == 0


@pytest.mark.integration
def test_one_run_creates_at_most_the_configured_batch_size(db_session: Session) -> None:
    """상한이 없으면 첫 세션 한 번에 seed 전체가 candidate로 복제된다."""
    clock = MutableClock()
    cfg = get_config().learning
    user = factories.make_user(db_session)
    for _ in range(cfg.candidate_materialization_batch_size + 2):
        _ready_sentence(db_session, [factories.make_learning_item(db_session)])

    created = materialize_candidates(db_session, user=user, now=clock.now(), cfg=cfg)

    assert created == cfg.candidate_materialization_batch_size


@pytest.mark.integration
def test_items_sharing_a_sentence_become_targets_of_one_candidate(
    db_session: Session,
) -> None:
    """문장당 target item 수는 `max_new_items_per_sentence` 이하이고, 넘는 item은 싣지 않는다."""
    clock = MutableClock()
    cfg = get_config().learning
    user = factories.make_user(db_session)
    items = [
        factories.make_learning_item(db_session) for _ in range(cfg.max_new_items_per_sentence + 1)
    ]
    _ready_sentence(db_session, items)

    created = materialize_candidates(db_session, user=user, now=clock.now(), cfg=cfg)

    (candidate,) = _candidates_of(db_session, user)
    assert created == 1
    assert len(_targets_of(db_session, candidate)) == cfg.max_new_items_per_sentence


@pytest.mark.integration
def test_an_active_learning_target_becomes_new_and_not_exploration(
    db_session: Session,
) -> None:
    """new와 exploration은 `is_active_learning_target`으로 배타적으로 갈린다.
    겹치면 같은 item이 두 category에서 동시에 뽑혀 Category Mix가 무의미해진다."""
    clock = MutableClock()
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    _ready_sentence(db_session, [item])
    _learning_state(db_session, user, item, active=True)

    materialize_candidates(db_session, user=user, now=clock.now(), cfg=get_config().learning)

    (candidate,) = _candidates_of(db_session, user)
    assert candidate.presentation_role is NEW
    assert candidate.review_reason is None
    assert candidate.context_stage is ContextStage.ANCHOR


@pytest.mark.integration
def test_a_promoted_item_stays_new_until_it_has_been_shown(db_session: Session) -> None:
    """`new`의 기준은 `review_states` 유무가 아니라 **유효 exposure 0건**이다 (ADR-013).

    `몰랐음 -> Again`이 승격시킨 바로 그 self-report가 스케줄을 만들므로, "아직
    `review_states` 행이 없는 item"이라는 옛 정의의 집합은 항상 공집합이었고
    Category Mix의 new 축이 영구히 굶었다. 문장은 승격 시점에 기록된 anchor다 ---
    사용자가 실제로 물어본 그 문장을 다시 제시한다.
    """
    clock = MutableClock()
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    anchor = _ready_sentence(db_session, [item])
    _ready_sentence(db_session, [item])
    _learning_state(db_session, user, item, active=True, anchor_sentence_id=anchor.id)
    _schedule(db_session, user, item, next_review_at=clock.now() - timedelta(days=1))

    materialize_candidates(db_session, user=user, now=clock.now(), cfg=get_config().learning)

    (candidate,) = _candidates_of(db_session, user)
    assert candidate.presentation_role is NEW
    assert candidate.review_reason is None
    assert candidate.context_stage is ContextStage.ANCHOR
    assert candidate.sentence_id == anchor.id


@pytest.mark.integration
def test_the_first_exposure_moves_an_item_from_new_to_review(db_session: Session) -> None:
    """제시된 적이 있으면 `new`가 아니라 `review`다. 두 pool은 배타적이다 (ADR-013)."""
    clock = MutableClock()
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    anchor = _ready_sentence(db_session, [item])
    _learning_state(db_session, user, item, active=True, anchor_sentence_id=anchor.id)
    _schedule(db_session, user, item, next_review_at=clock.now() - timedelta(days=1))
    _expose(db_session, user, item, clock.now())

    materialize_candidates(db_session, user=user, now=clock.now(), cfg=get_config().learning)

    (candidate,) = _candidates_of(db_session, user)
    assert candidate.presentation_role is REVIEW
    assert candidate.review_reason is FSRS_DUE


@pytest.mark.integration
def test_a_due_item_gets_an_fsrs_due_candidate(db_session: Session) -> None:
    clock = MutableClock()
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    sentence = _ready_sentence(db_session, [item])
    _learning_state(db_session, user, item, anchor_sentence_id=sentence.id)
    _schedule(db_session, user, item, next_review_at=clock.now() - timedelta(days=1))
    # 이미 한 번 제시된 적이 있어야 `review`다. 0건이면 그 item은 `new`의 몫이다.
    _expose(db_session, user, item, clock.now())

    materialize_candidates(db_session, user=user, now=clock.now(), cfg=get_config().learning)

    (candidate,) = _candidates_of(db_session, user)
    assert candidate.presentation_role is REVIEW
    assert candidate.review_reason is FSRS_DUE


@pytest.mark.integration
def test_an_item_below_the_minimum_exposures_gets_a_reinforcement_candidate(
    db_session: Session,
) -> None:
    """불변식 #4: FSRS interval을 cap하지 않는다. 최소 노출은 이 reason으로 채운다."""
    clock = MutableClock()
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    sentence = _ready_sentence(db_session, [item])
    _learning_state(db_session, user, item, anchor_sentence_id=sentence.id)
    _schedule(db_session, user, item, next_review_at=clock.now() + timedelta(days=30))
    _expose(db_session, user, item, clock.now())

    materialize_candidates(db_session, user=user, now=clock.now(), cfg=get_config().learning)

    (candidate,) = _candidates_of(db_session, user)
    assert candidate.review_reason is REINFORCEMENT


@pytest.mark.integration
@pytest.mark.parametrize("headroom", [0, 1])
def test_reinforcement_follows_the_injected_minimum_exposures(
    db_session: Session, headroom: int
) -> None:
    """`minimum_meaningful_exposures`를 **주입해서** 경계 양쪽을 본다.

    노출 수가 주입한 최소치와 같으면 reinforcement를 만들지 않고, 최소치가 하나
    크면 만든다. 위의 두 테스트는 기본값으로만 돌아서, 최소치를 상수로 박은 구현도
    통과했다(변이로 확인). 여기서는 노출 1건에 최소치를 1과 2로 넣으므로 어떤
    상수를 박아도 두 경우 중 하나에서 실패한다.
    """
    exposures = 1
    cfg = override_config(
        get_config(), learning={"minimum_meaningful_exposures": exposures + headroom}
    ).learning
    clock = MutableClock()
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    sentence = _ready_sentence(db_session, [item])
    _learning_state(db_session, user, item, anchor_sentence_id=sentence.id)
    # due가 아니어야 reason이 최소 노출 판정 하나로만 갈린다.
    _schedule(db_session, user, item, next_review_at=clock.now() + timedelta(days=30))
    for _ in range(exposures):
        _expose(db_session, user, item, clock.now())

    materialize_candidates(db_session, user=user, now=clock.now(), cfg=cfg)

    reasons = [
        candidate.review_reason for candidate in _candidates_of(db_session, user, role=REVIEW)
    ]
    assert reasons == ([REINFORCEMENT] if headroom else [])


@pytest.mark.integration
def test_the_anchor_sentence_is_recorded_when_it_was_missing(db_session: Session) -> None:
    """anchor는 "최초 학습 문맥"이므로 한 번 정하면 기록한다."""
    clock = MutableClock()
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    sentence = _ready_sentence(db_session, [item])
    state = _learning_state(db_session, user, item, anchor_sentence_id=None)
    _schedule(db_session, user, item, next_review_at=clock.now() - timedelta(days=1))
    _expose(db_session, user, item, clock.now())

    materialize_candidates(db_session, user=user, now=clock.now(), cfg=get_config().learning)

    assert state.anchor_sentence_id == sentence.id


@pytest.mark.integration
def test_a_quarantined_anchor_is_replaced_and_the_item_keeps_learning(
    db_session: Session,
) -> None:
    """quarantine된 anchor를 그대로 두면 그 item이 학습에서 조용히 빠진다.

    stage progression은 노출을 요구하는데 candidate를 못 받으니 노출이 없고,
    자력으로 빠져나올 수 없다. quarantine 시점에 그 문장의 `item_exposures`는 이미
    무효화되므로 보존할 "최초 학습 문맥" 기록 자체가 없다.
    """
    clock = MutableClock()
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    anchor = _ready_sentence(db_session, [item])
    replacement = _ready_sentence(db_session, [item])
    state = _learning_state(db_session, user, item, anchor_sentence_id=anchor.id)
    _schedule(db_session, user, item, next_review_at=clock.now() - timedelta(days=1))
    _expose(db_session, user, item, clock.now())
    anchor.status = SentenceStatus.QUARANTINED
    db_session.flush()

    materialize_candidates(db_session, user=user, now=clock.now(), cfg=get_config().learning)

    (candidate,) = _candidates_of(db_session, user, role=REVIEW)
    assert state.anchor_sentence_id == replacement.id
    assert candidate.sentence_id == replacement.id
    assert candidate.context_stage is ContextStage.ANCHOR


@pytest.mark.integration
def test_a_quarantined_anchor_is_replaced_at_the_near_original_stage(
    db_session: Session,
) -> None:
    """`near_original`도 anchor 문장이 실제로 필요하므로 같은 재지정을 받는다."""
    clock = MutableClock()
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    anchor = _ready_sentence(db_session, [item])
    replacement = _ready_sentence(db_session, [item])
    state = _learning_state(
        db_session,
        user,
        item,
        stage=ContextStage.NEAR_ORIGINAL,
        anchor_sentence_id=anchor.id,
    )
    _schedule(db_session, user, item, next_review_at=clock.now() - timedelta(days=1))
    _expose(db_session, user, item, clock.now())
    anchor.status = SentenceStatus.QUARANTINED
    db_session.flush()

    materialize_candidates(db_session, user=user, now=clock.now(), cfg=get_config().learning)

    (candidate,) = _candidates_of(db_session, user, role=REVIEW)
    assert state.anchor_sentence_id == replacement.id
    assert candidate.sentence_id == replacement.id
    assert candidate.context_stage is ContextStage.NEAR_ORIGINAL


@pytest.mark.integration
def test_an_anchor_awaiting_explanation_repair_is_not_replaced(db_session: Session) -> None:
    """일시적으로 invariant를 만족하지 못하는 문장 때문에 anchor를 바꾸지 않는다.

    곧 복구될 문장 때문에 재지정하면 같은 item의 학습 문맥이 흔들린다. 이번
    실행에서 그 stage를 건너뛰고 Pool Fallback으로 넘긴다.
    """
    clock = MutableClock()
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    # validated 문장이지만 tappable item에 explanation이 없다(EXPLAIN_ITEM 대기).
    anchor = _ready_sentence(db_session, [item], explained=False)
    _ready_sentence(db_session, [item])
    state = _learning_state(db_session, user, item, anchor_sentence_id=anchor.id)
    _schedule(db_session, user, item, next_review_at=clock.now() - timedelta(days=1))
    _expose(db_session, user, item, clock.now())

    created = materialize_candidates(
        db_session, user=user, now=clock.now(), cfg=get_config().learning
    )

    assert created == 0
    assert state.anchor_sentence_id == anchor.id


@pytest.mark.integration
def test_a_fully_exposed_item_that_is_not_due_gets_no_review_candidate(
    db_session: Session,
) -> None:
    """세 reason 중 어느 것도 만족하지 않으면 그 item의 review candidate를 만들지 않는다."""
    clock = MutableClock()
    cfg = get_config().learning
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    sentence = _ready_sentence(db_session, [item])
    _learning_state(db_session, user, item, anchor_sentence_id=sentence.id)
    _schedule(db_session, user, item, next_review_at=clock.now() + timedelta(days=30))
    study_session = _study_session(db_session, user)
    for _ in range(cfg.minimum_meaningful_exposures):
        candidate = _candidate(
            db_session,
            user,
            _ready_sentence(db_session, [item]),
            role=REVIEW,
            reason=REINFORCEMENT,
            targets=[item],
            status=CandidateStatus.CONSUMED,
        )
        presentation = _presentation(
            db_session, user, study_session, candidate, role=REVIEW, reason=REINFORCEMENT
        )
        db_session.add(
            ItemExposure(
                user_id=user.id,
                learning_item_id=item.id,
                study_presentation_id=presentation.id,
                sentence_id=presentation.sentence_id,
                modality=ExposureModality.READING,
                context_stage=ContextStage.ANCHOR,
                created_at=clock.now(),
            )
        )
    db_session.flush()

    created = materialize_candidates(db_session, user=user, now=clock.now(), cfg=cfg)

    assert created == 0


@pytest.mark.integration
def test_context_repair_follows_a_failure_at_a_higher_stage(db_session: Session) -> None:
    """실패 후 stage가 한 단계 내려갔고 되돌린 문맥의 노출이 아직 없으면 repair다."""
    clock = MutableClock()
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    anchor = _ready_sentence(db_session, [item])
    _learning_state(db_session, user, item, stage=ContextStage.ANCHOR, anchor_sentence_id=anchor.id)
    _schedule(db_session, user, item, next_review_at=clock.now() - timedelta(days=1))
    study_session = _study_session(db_session, user)
    failed_on = _candidate(
        db_session,
        user,
        _ready_sentence(db_session, [item]),
        role=REVIEW,
        reason=FSRS_DUE,
        stage=ContextStage.VARIED,
        targets=[item],
        status=CandidateStatus.CONSUMED,
    )
    presentation = _presentation(
        db_session,
        user,
        study_session,
        failed_on,
        role=REVIEW,
        reason=FSRS_DUE,
        stage=ContextStage.VARIED,
    )
    db_session.add(
        LearningEvent(
            user_id=user.id,
            study_session_id=study_session.id,
            study_presentation_id=presentation.id,
            sentence_id=presentation.sentence_id,
            learning_item_id=item.id,
            event_type=EventType.SELF_REPORT_UNKNOWN,
            client_event_id=uuid.uuid4(),
            created_at=clock.now(),
        )
    )
    # S_fail은 presentation이 아니라 그 (presentation, item)의 유효 exposure에서 읽는다.
    _exposure(db_session, user, item, presentation, stage=ContextStage.VARIED, now=clock.now())
    db_session.flush()

    materialize_candidates(db_session, user=user, now=clock.now(), cfg=get_config().learning)

    (candidate,) = _candidates_of(db_session, user, role=REVIEW)
    assert candidate.review_reason is CONTEXT_REPAIR
    assert candidate.context_stage is ContextStage.ANCHOR
    assert candidate.sentence_id == anchor.id


@pytest.mark.integration
def test_a_repaired_stage_stops_asking_for_context_repair(db_session: Session) -> None:
    """되돌린 문맥의 노출이 실제로 일어나면 조건 c가 자동으로 거짓이 된다. "repair를
    했는가"를 따로 저장할 필요가 없다."""
    clock = MutableClock()
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    anchor = _ready_sentence(db_session, [item])
    _learning_state(db_session, user, item, stage=ContextStage.ANCHOR, anchor_sentence_id=anchor.id)
    _schedule(db_session, user, item, next_review_at=clock.now() + timedelta(days=30))
    study_session = _study_session(db_session, user)
    failed_on = _candidate(
        db_session,
        user,
        _ready_sentence(db_session, [item]),
        role=REVIEW,
        reason=FSRS_DUE,
        stage=ContextStage.VARIED,
        targets=[item],
        status=CandidateStatus.CONSUMED,
    )
    failure = _presentation(
        db_session,
        user,
        study_session,
        failed_on,
        role=REVIEW,
        reason=FSRS_DUE,
        stage=ContextStage.VARIED,
    )
    db_session.add(
        LearningEvent(
            user_id=user.id,
            study_session_id=study_session.id,
            study_presentation_id=failure.id,
            sentence_id=failure.sentence_id,
            learning_item_id=item.id,
            event_type=EventType.SELF_REPORT_UNKNOWN,
            client_event_id=uuid.uuid4(),
            created_at=clock.now(),
        )
    )
    _exposure(db_session, user, item, failure, stage=ContextStage.VARIED, now=clock.now())
    repaired_on = _candidate(
        db_session,
        user,
        anchor,
        role=REVIEW,
        reason=CONTEXT_REPAIR,
        targets=[item],
        status=CandidateStatus.CONSUMED,
    )
    repair = _presentation(
        db_session,
        user,
        study_session,
        repaired_on,
        role=REVIEW,
        reason=CONTEXT_REPAIR,
        now=clock.advance(timedelta(minutes=5)),
    )
    db_session.add(
        ItemExposure(
            user_id=user.id,
            learning_item_id=item.id,
            study_presentation_id=repair.id,
            sentence_id=repair.sentence_id,
            modality=ExposureModality.READING,
            context_stage=ContextStage.ANCHOR,
            created_at=clock.now(),
        )
    )
    db_session.flush()

    materialize_candidates(db_session, user=user, now=clock.now(), cfg=get_config().learning)

    (candidate,) = _candidates_of(db_session, user, role=REVIEW)
    assert candidate.review_reason is REINFORCEMENT


# --------------------------------------------------------------------------
# 선택 (DB)
# --------------------------------------------------------------------------


def _select(
    db_session: Session, user: User, study_session: StudySession, now: datetime
) -> Selection | None:
    return select_next(
        db_session,
        user=user,
        study_session_id=study_session.id,
        now=now,
        cfg=get_config().learning,
    )


@pytest.mark.integration
def test_an_empty_pool_is_materialized_inside_the_request(db_session: Session) -> None:
    """Pool Fallback 0단계. "Ready candidate가 없다"는 대부분 콘텐츠가 없다가 아니라
    아직 이 사용자에게 투영되지 않았다는 뜻이다."""
    clock = MutableClock()
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    _ready_sentence(db_session, [item])
    study_session = _study_session(db_session, user)

    selection = _select(db_session, user, study_session, clock.now())

    assert selection is not None
    assert selection.presentation_role is EXPLORATION
    assert selection.target_item_ids == (item.id,)


@pytest.mark.integration
def test_a_user_with_no_content_at_all_gets_none(db_session: Session) -> None:
    """모든 pool이 비어도 예외가 아니다. None은 Pool Fallback 3단계(job enqueue)를 뜻한다."""
    clock = MutableClock()
    user = factories.make_user(db_session)
    study_session = _study_session(db_session, user)

    assert _select(db_session, user, study_session, clock.now()) is None


@pytest.mark.integration
def test_an_exploration_candidate_whose_target_no_longer_qualifies_is_skipped(
    db_session: Session,
) -> None:
    """Ready Pool에 있는 candidate도 고를 때 후보 조건 1~3을 **다시** 확인한다.

    candidate를 만든 뒤에 그 item이 다른 문장에서 노출됐을 수 있다. 그대로 고르면
    `exploration_recent_days` 안에 같은 item을 두 번 탐색하게 된다.
    """
    clock = MutableClock()
    user = factories.make_user(db_session)
    seen = factories.make_learning_item(db_session)
    untouched = factories.make_learning_item(db_session)
    _ready_sentence(db_session, [seen])
    _ready_sentence(db_session, [untouched])
    study_session = _study_session(db_session, user)
    materialize_candidates(db_session, user=user, now=clock.now(), cfg=get_config().learning)
    _expose(db_session, user, seen, clock.now())

    selection = _select(db_session, user, study_session, clock.now())

    assert selection is not None
    assert selection.presentation_role is EXPLORATION
    assert selection.target_item_ids == (untouched.id,)


@pytest.mark.integration
def test_a_promoted_target_is_no_longer_offered_as_exploration(db_session: Session) -> None:
    """조건 2. 승격된 item은 `new`의 몫이고 exploration이 다시 잡지 않는다."""
    clock = MutableClock()
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    _ready_sentence(db_session, [item])
    study_session = _study_session(db_session, user)
    materialize_candidates(db_session, user=user, now=clock.now(), cfg=get_config().learning)
    # candidate를 만든 뒤에 사용자가 이 item을 클릭해 학습 target으로 승격시켰다.
    _learning_state(db_session, user, item, active=True)

    selection = _select(db_session, user, study_session, clock.now())

    assert selection is not None
    assert selection.presentation_role is NEW


@pytest.mark.integration
def test_an_fsrs_due_candidate_is_not_chosen_before_its_target_is_due(
    db_session: Session,
) -> None:
    """`fsrs_due`의 "사용 가능"은 candidate 존재만으로 부족하고 target이 실제로 due여야 한다."""
    clock = MutableClock()
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    sentence = _ready_sentence(db_session, [item])
    _learning_state(db_session, user, item, anchor_sentence_id=sentence.id)
    _schedule(db_session, user, item, next_review_at=clock.now() + timedelta(days=3))
    _expose(db_session, user, item, clock.now())
    _candidate(db_session, user, sentence, role=REVIEW, reason=FSRS_DUE, targets=[item])
    study_session = _study_session(db_session, user)

    assert _select(db_session, user, study_session, clock.now()) is None

    selection = _select(db_session, user, study_session, clock.advance(timedelta(days=4)))

    assert selection is not None
    assert selection.review_reason is FSRS_DUE


@pytest.mark.integration
def test_a_reinforcement_candidate_is_chosen_even_when_the_target_is_not_due(
    db_session: Session,
) -> None:
    """불변식 #4. reinforcement가 due를 요구하면 최소 5회 노출이 다시 FSRS 일정에만
    의존하게 되고, 그것을 채우려면 interval을 cap해야 한다."""
    clock = MutableClock()
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    sentence = _ready_sentence(db_session, [item])
    _learning_state(db_session, user, item, anchor_sentence_id=sentence.id)
    _schedule(db_session, user, item, next_review_at=clock.now() + timedelta(days=365))
    candidate = _candidate(
        db_session, user, sentence, role=REVIEW, reason=REINFORCEMENT, targets=[item]
    )
    study_session = _study_session(db_session, user)

    selection = _select(db_session, user, study_session, clock.now())

    assert selection is not None
    assert selection.candidate_id == candidate.id
    assert selection.review_reason is REINFORCEMENT


@pytest.mark.integration
def test_a_deferred_target_is_not_chosen(db_session: Session) -> None:
    """무신호 review가 같은 세션에서 무한히 다시 뽑히지 않게 하는 것이 deferral이다."""
    clock = MutableClock()
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    sentence = _ready_sentence(db_session, [item])
    _learning_state(db_session, user, item, anchor_sentence_id=sentence.id)
    _schedule(
        db_session,
        user,
        item,
        next_review_at=clock.now() - timedelta(days=1),
        deferred_until=clock.now() + timedelta(hours=12),
    )
    _expose(db_session, user, item, clock.now())
    _candidate(db_session, user, sentence, role=REVIEW, reason=FSRS_DUE, targets=[item])
    study_session = _study_session(db_session, user)

    assert _select(db_session, user, study_session, clock.now()) is None


@pytest.mark.integration
def test_an_explicit_review_lifts_the_deferral(db_session: Session) -> None:
    """증거가 도착하면 deferral이 풀리고 스케줄이 다시 답이 된다 (07_SRS_SPEC.md의 `deferral 해제`).

    deferral의 존재 이유는 "이 review에 증거가 없었다" 하나뿐이다. 남겨 두면 방금
    `몰랐음`을 받아 몇 분 뒤로 잡힌 due를 12시간 동안 가린다 --- 그것은 스케줄 준수가
    아니라 스케줄 무시다. rating을 기록하는 자리가 그것을 지운다.
    """
    clock = MutableClock()
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    sentence = _ready_sentence(db_session, [item])
    _learning_state(db_session, user, item, anchor_sentence_id=sentence.id)
    _schedule(
        db_session,
        user,
        item,
        next_review_at=clock.now() - timedelta(days=1),
        deferred_until=clock.now() + timedelta(hours=12),
    )
    _expose(db_session, user, item, clock.now())
    _candidate(db_session, user, sentence, role=REVIEW, reason=FSRS_DUE, targets=[item])
    study_session = _study_session(db_session, user)
    assert _select(db_session, user, study_session, clock.now()) is None

    state = record_explicit_review(
        db_session,
        user_id=user.id,
        learning_item_id=item.id,
        signal=ExplicitSignal.UNKNOWN,
        now=clock.now(),
        config=get_config(),
    )

    assert state.deferred_until is None
    selection = _select(db_session, user, study_session, _utc(state.next_review_at))
    assert selection is not None, "deferral이 풀렸는데도 due item을 고르지 못했다"
    assert selection.target_item_ids == (item.id,)


@pytest.mark.integration
@pytest.mark.parametrize("headroom", [0, 1])
def test_anchor_reuse_fallback_follows_the_injected_minimum_exposures(
    db_session: Session, headroom: int
) -> None:
    """Pool Fallback 2(anchor reinforcement 재사용)도 주입한 최소 노출을 따른다.

    `varied`는 아직 보지 않은 문장을 요구하는데 anchor 하나뿐이라 0단계
    materialization은 아무것도 만들지 못한다. 남는 경로는 2단계뿐이고, 그 단계의
    최소 노출 비교는 materialization과 **별도 코드**라 따로 본다(변이로 확인: 이
    비교를 상수로 박아도 다른 테스트는 전부 통과했다).
    """
    exposures = 1
    cfg = override_config(
        get_config(), learning={"minimum_meaningful_exposures": exposures + headroom}
    ).learning
    clock = MutableClock()
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    anchor = _ready_sentence(db_session, [item])
    _learning_state(db_session, user, item, stage=ContextStage.VARIED, anchor_sentence_id=anchor.id)
    _schedule(db_session, user, item, next_review_at=clock.now() + timedelta(days=30))
    history = _study_session(db_session, user)
    shown_on = _candidate(
        db_session,
        user,
        anchor,
        role=REVIEW,
        reason=REINFORCEMENT,
        targets=[item],
        status=CandidateStatus.CONSUMED,
    )
    for _ in range(exposures):
        shown = _presentation(
            db_session, user, history, shown_on, role=REVIEW, reason=REINFORCEMENT
        )
        _exposure(db_session, user, item, shown, stage=ContextStage.ANCHOR, now=clock.now())
    study_session = _study_session(db_session, user)

    selection = select_next(
        db_session, user=user, study_session_id=study_session.id, now=clock.now(), cfg=cfg
    )

    if not headroom:
        assert selection is None
        return
    assert selection is not None
    assert (selection.review_reason, selection.context_stage, selection.sentence_id) == (
        REINFORCEMENT,
        ContextStage.ANCHOR,
        anchor.id,
    )


@pytest.mark.integration
@pytest.mark.parametrize("dominant", [REVIEW, NEW, EXPLORATION])
def test_select_next_follows_the_injected_category_ratios(
    db_session: Session, dominant: PresentationRole
) -> None:
    """세 pool이 모두 ready인 **같은 상태**에서 주입한 ratio가 첫 문장의 category를 정한다.

    위의 Category Mix 테스트는 순수 함수에 기본값과 같은 70/20/10을 넣거나
    `choose_ratios`를 기본 config로만 불러서, ratio를 상수로 박은 엔진도 통과했다
    (변이로 확인). 여기서는 `select_next`를 통해 세 category를 각각 우세하게 주입하므로
    어떤 고정 ratio도 세 경우 중 둘에서 실패한다. 세션 첫 문장이므로 deficit은 곧
    ratio 순서다.
    """
    dominant_share, minor_share = 0.8, 0.1
    shares = {role: dominant_share if role is dominant else minor_share for role in ALL_ROLES}
    cfg = override_config(
        get_config(),
        learning={
            "review_ratio": shares[REVIEW],
            "new_ratio": shares[NEW],
            "exploration_ratio": shares[EXPLORATION],
        },
    ).learning
    clock = MutableClock()
    user = factories.make_user(db_session)
    reviewed = factories.make_learning_item(db_session)
    anchor = _ready_sentence(db_session, [reviewed])
    _learning_state(db_session, user, reviewed, anchor_sentence_id=anchor.id)
    _schedule(db_session, user, reviewed, next_review_at=clock.now() - timedelta(days=1))
    _expose(db_session, user, reviewed, clock.now())
    promoted = factories.make_learning_item(db_session)
    _ready_sentence(db_session, [promoted])
    _learning_state(db_session, user, promoted, active=True)
    untouched = factories.make_learning_item(db_session)
    _ready_sentence(db_session, [untouched])
    materialize_candidates(db_session, user=user, now=clock.now(), cfg=cfg)
    study_session = _study_session(db_session, user)

    # 전제: 세 pool이 모두 있고 backlog 세트로 바뀌지 않았다. 둘 중 하나라도 깨지면
    # 아래 단정은 ratio가 아니라 pool 유무나 backlog를 보게 된다.
    assert {c.presentation_role for c in _candidates_of(db_session, user)} == set(ALL_ROLES)
    assert count_backlog(db_session, user_id=user.id, now=clock.now()) < cfg.backlog_threshold

    selection = select_next(
        db_session, user=user, study_session_id=study_session.id, now=clock.now(), cfg=cfg
    )

    assert selection is not None
    assert selection.presentation_role is dominant


@pytest.mark.integration
def test_review_ordering_prefers_the_earliest_schedule(db_session: Session) -> None:
    clock = MutableClock()
    user = factories.make_user(db_session)
    later = factories.make_learning_item(db_session)
    earlier = factories.make_learning_item(db_session)
    for item, days in ((later, 1), (earlier, 9)):
        sentence = _ready_sentence(db_session, [item])
        _learning_state(db_session, user, item, anchor_sentence_id=sentence.id)
        _schedule(db_session, user, item, next_review_at=clock.now() - timedelta(days=days))
        _candidate(db_session, user, sentence, role=REVIEW, reason=FSRS_DUE, targets=[item])
    study_session = _study_session(db_session, user)

    selection = _select(db_session, user, study_session, clock.now())

    assert selection is not None
    assert selection.target_item_ids == (earlier.id,)


@pytest.mark.integration
def test_a_null_mastery_outranks_a_measured_one_at_the_same_schedule(
    db_session: Session,
) -> None:
    """NULL은 "능력 0"이 아니라 evidence 부족이므로 가장 낮은 값으로 취급해 먼저 본다."""
    clock = MutableClock()
    user = factories.make_user(db_session)
    measured = factories.make_learning_item(db_session)
    unmeasured = factories.make_learning_item(db_session)
    due_at = clock.now() - timedelta(days=1)
    for item in (measured, unmeasured):
        sentence = _ready_sentence(db_session, [item])
        _learning_state(db_session, user, item, anchor_sentence_id=sentence.id)
        _schedule(db_session, user, item, next_review_at=due_at)
        _candidate(db_session, user, sentence, role=REVIEW, reason=FSRS_DUE, targets=[item])
    factories.make_mastery(
        db_session,
        user,
        measured,
        comprehension_mastery=0.9,
        algorithm_version=MASTERY_ALGORITHM_FILLER,
    )

    selection = _select(
        db_session, user, study_session=_study_session(db_session, user), now=clock.now()
    )

    assert selection is not None
    assert selection.target_item_ids == (unmeasured.id,)


@pytest.mark.integration
def test_the_candidate_matching_the_current_stage_wins_over_an_older_one(
    db_session: Session,
) -> None:
    """candidate 단위 tie-break 5번. stage가 오른 뒤에도 낮은 stage candidate가 Ready
    Pool에 남으므로(ADR-019), 가장 오래된 것이 먼저 뽑히면 최소 노출이 실제 ladder
    위치보다 낮은 stage로 기운다. candidate id가 더 커도 일치하는 쪽을 고른다."""
    clock = MutableClock()
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    stale_sentence = _ready_sentence(db_session, [item])
    fresh_sentence = _ready_sentence(db_session, [item])
    _learning_state(
        db_session,
        user,
        item,
        stage=ContextStage.NEAR_ORIGINAL,
        anchor_sentence_id=stale_sentence.id,
    )
    _schedule(db_session, user, item, next_review_at=clock.now() - timedelta(days=1))
    stale = _candidate(
        db_session,
        user,
        stale_sentence,
        role=REVIEW,
        reason=FSRS_DUE,
        targets=[item],
        stage=ContextStage.ANCHOR,
    )
    fresh = _candidate(
        db_session,
        user,
        fresh_sentence,
        role=REVIEW,
        reason=FSRS_DUE,
        targets=[item],
        stage=ContextStage.NEAR_ORIGINAL,
    )
    assert stale.id < fresh.id, "옛 tie-break(candidate id ASC)와 갈리는 배치여야 한다"

    selection = _select(db_session, user, _study_session(db_session, user), clock.now())

    assert selection is not None
    assert selection.candidate_id == fresh.id


@pytest.mark.integration
def test_without_a_matching_candidate_the_lower_stage_one_is_still_chosen(
    db_session: Session,
) -> None:
    """**배제가 아니라 선호다.** 일치하는 candidate가 하나도 없으면 낮은 stage
    candidate를 그대로 고른다 --- `Pool Fallback` 2단계가 의도적으로 허용한
    anchor reinforcement 노출을 이 규칙이 막으면 안 된다."""
    clock = MutableClock()
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    anchor_sentence = _ready_sentence(db_session, [item])
    _learning_state(
        db_session,
        user,
        item,
        stage=ContextStage.VARIED,
        anchor_sentence_id=anchor_sentence.id,
    )
    _schedule(db_session, user, item, next_review_at=clock.now() + timedelta(days=365))
    anchor_candidate = _candidate(
        db_session,
        user,
        anchor_sentence,
        role=REVIEW,
        reason=REINFORCEMENT,
        targets=[item],
        stage=ContextStage.ANCHOR,
    )

    selection = _select(db_session, user, _study_session(db_session, user), clock.now())

    assert selection is not None, "일치하는 candidate가 없다고 낮은 stage를 배제하면 안 된다"
    assert selection.candidate_id == anchor_candidate.id
    assert selection.context_stage is ContextStage.ANCHOR


@pytest.mark.integration
def test_the_stage_match_is_judged_on_the_dominant_target(db_session: Session) -> None:
    """판정 대상은 **dominant target**(order key 최소값을 만든 target)이다.

    target이 둘인 candidate의 두 stage는 구조적으로 갈린다(같은 presentation에서 한
    target이 explicit `몰랐음`, 다른 target이 무신호면 전이 규칙이 target마다 따로
    적용된다). "아무 target이나 일치하면 통과"로 읽으면 낡은 `anchor` candidate가
    동승자 item 덕분에 항상 일치로 판정되어 규칙이 무력해진다.
    """
    clock = MutableClock()
    user = factories.make_user(db_session)
    passenger = factories.make_learning_item(db_session, lemma="同乗")
    dominant = factories.make_learning_item(db_session, lemma="牽引")
    shared = _ready_sentence(db_session, [passenger, dominant])
    fresh_sentence = _ready_sentence(db_session, [dominant])
    _learning_state(db_session, user, passenger, stage=ContextStage.ANCHOR)
    _learning_state(db_session, user, dominant, stage=ContextStage.NEAR_ORIGINAL)
    # dominant target = order key 최소값. 첫 항이 next_review_at ASC이므로 더 오래
    # 밀린 쪽이 두 candidate의 키를 **똑같이** 지배하고, 남는 것은 5~6번뿐이다.
    _schedule(db_session, user, passenger, next_review_at=clock.now() - timedelta(days=1))
    _schedule(db_session, user, dominant, next_review_at=clock.now() - timedelta(days=9))
    stale = _candidate(
        db_session,
        user,
        shared,
        role=REVIEW,
        reason=FSRS_DUE,
        targets=[passenger, dominant],
        stage=ContextStage.ANCHOR,
    )
    fresh = _candidate(
        db_session,
        user,
        fresh_sentence,
        role=REVIEW,
        reason=FSRS_DUE,
        targets=[dominant],
        stage=ContextStage.NEAR_ORIGINAL,
    )
    assert stale.id < fresh.id, "옛 tie-break(candidate id ASC)와 갈리는 배치여야 한다"

    selection = _select(db_session, user, _study_session(db_session, user), clock.now())

    assert selection is not None
    assert selection.candidate_id == fresh.id, (
        "동승 target(passenger)이 anchor와 일치하는 것은 판정에 쓰이지 않는다"
    )


@pytest.mark.integration
def test_a_split_passenger_target_does_not_disqualify_the_candidate(
    db_session: Session,
) -> None:
    """`06`의 두 번째 불릿: **"모든 target이 일치해야 통과"로 읽으면 multi-target
    candidate가 사실상 배제된다.**

    한 candidate의 두 target은 ladder가 갈리는 것이 구조적이므로(같은 presentation
    에서 한 target이 explicit `몰랐음`, 다른 target이 무신호면 전이 규칙이 target
    마다 따로 적용된다), 동승 target이 어긋났다는 이유로 5번에서 지면 그 candidate는
    **갈린 순간부터 영구히** 불리해진다. 배제는 이 규칙이 하지 않기로 한 것이다
    (ADR-019).

    바로 위 `..._judged_on_the_dominant_target`은 dominant 불일치 + 동승 일치만
    본다. 여기는 그 **반대 방향** --- dominant 일치 + 동승 불일치 --- 이고, 판정이
    dominant 하나로 끝나는지(`all`이 아닌지)를 고정한다.
    """
    clock = MutableClock()
    user = factories.make_user(db_session)
    split_passenger = factories.make_learning_item(db_session, lemma="別途")
    leader = factories.make_learning_item(db_session, lemma="主導")
    shared = _ready_sentence(db_session, [split_passenger, leader])
    solo_sentence = _ready_sentence(db_session, [leader])
    # 동승자의 ladder만 갈려 있다. candidate.context_stage는 dominant(leader)와 일치한다.
    _learning_state(db_session, user, split_passenger, stage=ContextStage.ANCHOR)
    _learning_state(db_session, user, leader, stage=ContextStage.NEAR_ORIGINAL)
    # 둘 다 due여야 fsrs_due의 usable에 남는다. 더 밀린 leader가 dominant다.
    _schedule(db_session, user, split_passenger, next_review_at=clock.now() - timedelta(days=1))
    _schedule(db_session, user, leader, next_review_at=clock.now() - timedelta(days=9))
    multi_target = _candidate(
        db_session,
        user,
        shared,
        role=REVIEW,
        reason=FSRS_DUE,
        targets=[split_passenger, leader],
        stage=ContextStage.NEAR_ORIGINAL,
    )
    single_target = _candidate(
        db_session,
        user,
        solo_sentence,
        role=REVIEW,
        reason=FSRS_DUE,
        targets=[leader],
        stage=ContextStage.NEAR_ORIGINAL,
    )
    # dominant target이 같으므로 1~4의 order key도 같다. 5번이 갈리지 않으면 6번(id
    # ASC)이 결정한다 --- multi-target이 일치로 판정될 때에만 먼저 만든 쪽이 이긴다.
    assert multi_target.id < single_target.id

    selection = _select(db_session, user, _study_session(db_session, user), clock.now())

    assert selection is not None
    assert selection.candidate_id == multi_target.id, (
        "동승 target의 stage가 갈렸다고 multi-target candidate를 불일치로 판정하면 안 된다"
    )


@pytest.mark.integration
def test_a_badly_overdue_candidate_beats_a_matching_but_less_urgent_one(
    db_session: Session,
) -> None:
    """5번은 1~4 **다음**이다(`5. ... 6. ...`가 `1~4`의 동률에 얹힌다).

    stage 일치는 1~4가 이미 동률일 때만 갈리는 항이지 우선순위 자체가 아니다. 두
    항의 순서가 뒤집히면 심하게 밀린 due item이 stage만 맞는 덜 급한 item에 밀리고,
    그것은 tie-break가 아니라 Review Ordering 정책의 변경이다.
    """
    clock = MutableClock()
    user = factories.make_user(db_session)
    overdue = factories.make_learning_item(db_session, lemma="延滞")
    barely_due = factories.make_learning_item(db_session, lemma="直近")
    overdue_sentence = _ready_sentence(db_session, [overdue])
    barely_due_sentence = _ready_sentence(db_session, [barely_due])
    # order key 1순위가 next_review_at ASC다. 두 due 시각을 크게 벌려 1~4에서 확실히
    # 갈리게 하고, 그 위에 5번을 **반대 방향으로** 얹는다.
    _learning_state(db_session, user, overdue, stage=ContextStage.NEAR_ORIGINAL)
    _learning_state(db_session, user, barely_due, stage=ContextStage.ANCHOR)
    _schedule(db_session, user, overdue, next_review_at=clock.now() - timedelta(days=90))
    _schedule(db_session, user, barely_due, next_review_at=clock.now() - timedelta(minutes=1))
    stage_mismatched = _candidate(
        db_session,
        user,
        overdue_sentence,
        role=REVIEW,
        reason=FSRS_DUE,
        targets=[overdue],
        # state는 near_original이므로 이 candidate는 5번에서 지는 쪽이다.
        stage=ContextStage.ANCHOR,
    )
    stage_matched = _candidate(
        db_session,
        user,
        barely_due_sentence,
        role=REVIEW,
        reason=FSRS_DUE,
        targets=[barely_due],
        stage=ContextStage.ANCHOR,
    )
    assert stage_mismatched.id < stage_matched.id

    selection = _select(db_session, user, _study_session(db_session, user), clock.now())

    assert selection is not None
    assert selection.candidate_id == stage_mismatched.id, (
        "stage 일치가 order key보다 앞서면 심하게 밀린 due item이 영구히 뒤로 밀린다"
    )
    assert selection.target_item_ids == (overdue.id,)


@pytest.mark.integration
def test_the_most_urgent_target_sets_the_candidate_priority(db_session: Session) -> None:
    """candidate의 order key = 그 candidate의 usable target들의 order key **최소값**.

    "가장 급한 target이 candidate의 우선순위를 정한다. ... 최대값이나 평균을 쓰면
    급한 target이 덜 급한 동승자 때문에 밀린다." 이 배치에서 최대값을 쓰면
    multi-target candidate가 덜 급한 동승자 때문에 단일 target candidate에 진다.

    세 item의 stage와 두 candidate의 stage를 전부 같게 두어 5번 항을 상수로 만든다
    --- dominant는 stage 판정에도 쓰이므로 그렇게 해야 order key 효과만 남는다.
    """
    clock = MutableClock()
    user = factories.make_user(db_session)
    urgent = factories.make_learning_item(db_session, lemma="緊急")
    lazy = factories.make_learning_item(db_session, lemma="悠長")
    middle = factories.make_learning_item(db_session, lemma="中間")
    shared = _ready_sentence(db_session, [urgent, lazy])
    middle_sentence = _ready_sentence(db_session, [middle])
    for item in (urgent, lazy, middle):
        _learning_state(db_session, user, item, stage=ContextStage.ANCHOR)
    _schedule(db_session, user, urgent, next_review_at=clock.now() - timedelta(days=90))
    _schedule(db_session, user, middle, next_review_at=clock.now() - timedelta(days=30))
    _schedule(db_session, user, lazy, next_review_at=clock.now() - timedelta(minutes=1))
    multi_target = _candidate(
        db_session,
        user,
        shared,
        role=REVIEW,
        reason=FSRS_DUE,
        targets=[urgent, lazy],
        stage=ContextStage.ANCHOR,
    )
    single_target = _candidate(
        db_session,
        user,
        middle_sentence,
        role=REVIEW,
        reason=FSRS_DUE,
        targets=[middle],
        stage=ContextStage.ANCHOR,
    )
    assert multi_target.context_stage is single_target.context_stage, "5번 항은 상수여야 한다"

    selection = _select(db_session, user, _study_session(db_session, user), clock.now())

    assert selection is not None
    assert selection.candidate_id == multi_target.id, (
        "덜 급한 동승자(lazy)가 candidate의 우선순위를 정하면 안 된다"
    )
    assert selection.target_item_ids == (urgent.id, lazy.id)


@pytest.mark.integration
def test_two_matching_candidates_fall_back_to_the_stable_tie_break(
    db_session: Session,
) -> None:
    """규칙 6. 5번이 동률이면 순서가 흔들리지 않는 기존 tie-break로 갈린다."""
    clock = MutableClock()
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    first_sentence = _ready_sentence(db_session, [item])
    second_sentence = _ready_sentence(db_session, [item])
    _learning_state(db_session, user, item, anchor_sentence_id=first_sentence.id)
    _schedule(db_session, user, item, next_review_at=clock.now() - timedelta(days=1))
    first = _candidate(
        db_session, user, first_sentence, role=REVIEW, reason=FSRS_DUE, targets=[item]
    )
    second = _candidate(
        db_session, user, second_sentence, role=REVIEW, reason=FSRS_DUE, targets=[item]
    )
    assert first.context_stage is second.context_stage

    study_session = _study_session(db_session, user)
    picks = {_select(db_session, user, study_session, clock.now()) for _ in range(3)}

    assert picks == {
        Selection(
            candidate_id=first.id,
            sentence_id=first_sentence.id,
            presentation_role=REVIEW,
            review_reason=FSRS_DUE,
            context_stage=first.context_stage,
            target_item_ids=(item.id,),
        )
    }


@pytest.mark.integration
def test_the_stage_tie_break_does_not_change_the_chosen_reason(db_session: Session) -> None:
    """reason 선택이 먼저 일어난다. stage가 어긋나도 `context_repair`가 밀리지 않는다."""
    clock = MutableClock()
    user = factories.make_user(db_session)
    repairing = factories.make_learning_item(db_session, lemma="修復")
    due = factories.make_learning_item(db_session, lemma="期限")
    repair_sentence = _ready_sentence(db_session, [repairing])
    due_sentence = _ready_sentence(db_session, [due])
    _learning_state(db_session, user, repairing, stage=ContextStage.ANCHOR)
    _learning_state(db_session, user, due, stage=ContextStage.ANCHOR)
    _schedule(db_session, user, repairing, next_review_at=clock.now() + timedelta(days=365))
    _schedule(db_session, user, due, next_review_at=clock.now() - timedelta(days=9))
    repair = _candidate(
        db_session,
        user,
        repair_sentence,
        role=REVIEW,
        reason=CONTEXT_REPAIR,
        targets=[repairing],
        # state는 anchor이므로 이 candidate는 5번에서 지는 쪽이다.
        stage=ContextStage.NEAR_ORIGINAL,
    )
    _candidate(db_session, user, due_sentence, role=REVIEW, reason=FSRS_DUE, targets=[due])

    selection = _select(db_session, user, _study_session(db_session, user), clock.now())

    assert selection is not None
    assert selection.review_reason is CONTEXT_REPAIR
    assert selection.candidate_id == repair.id


@pytest.mark.integration
def test_materialization_and_the_tie_break_start_the_ladder_at_the_same_stage(
    db_session: Session,
) -> None:
    """ladder 시작점은 **한 사실**이다. 두 자리가 그것을 따로 선언한다.

    materialization은 `user_item_learning_state` 행이 없는 item의 candidate를
    ladder 시작 stage로 만들고(`_review_plans`), tie-break 5번은 같은 item의 판정
    stage를 `INITIAL_CONTEXT_STAGE`로 읽는다(`_load_review_targets`). 두 값이
    갈리면 **state 행이 없는 item의 candidate가 5번에서 영구히 불일치**가 되어,
    자기 자신을 위해 만들어진 candidate가 낮은 우선순위로 밀린다. 값이 같은 지금은
    무해하므로 어떤 동작 테스트도 이 결합을 보지 못한다 --- 그래서 여기서 두 값이
    같다는 것 자체를 단언한다.
    """
    clock = MutableClock()
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    _ready_sentence(db_session, [item])
    # `user_item_learning_state` 행을 **만들지 않는다.** 그 경우에만 두 선언이 쓰인다.
    _schedule(db_session, user, item, next_review_at=clock.now() - timedelta(days=1))
    _expose(db_session, user, item, clock.now())

    materialize_candidates(db_session, user=user, now=clock.now(), cfg=get_config().learning)

    (candidate,) = _candidates_of(db_session, user, role=REVIEW)
    assert candidate.context_stage is INITIAL_CONTEXT_STAGE, (
        "materialization과 tie-break가 ladder 시작점을 다른 상수로 표현하면 안 된다"
    )


@pytest.mark.integration
def test_selection_never_writes_to_review_states(db_session: Session) -> None:
    """Scenario A의 전제다. 선택은 FSRS rating도 mastery evidence도 만들지 않는다."""
    clock = MutableClock()
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    sentence = _ready_sentence(db_session, [item])
    _learning_state(db_session, user, item, anchor_sentence_id=sentence.id)
    _schedule(db_session, user, item, next_review_at=clock.now() - timedelta(days=1))
    _candidate(db_session, user, sentence, role=REVIEW, reason=FSRS_DUE, targets=[item])
    study_session = _study_session(db_session, user)
    before = _review_state_rows(db_session)

    assert _select(db_session, user, study_session, clock.now()) is not None

    assert _review_state_rows(db_session) == before


def _review_state_rows(db_session: Session) -> list[tuple[object, ...]]:
    """모든 컬럼을 값으로 떠 둔다. 컬럼이 늘어도 이 스냅샷이 자동으로 함께 본다."""
    db_session.flush()
    columns = [column.key for column in ReviewState.__table__.columns]
    return [
        tuple(getattr(state, name) for name in columns)
        for state in db_session.execute(sa.select(ReviewState).order_by(ReviewState.id))
        .scalars()
        .all()
    ]
