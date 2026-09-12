"""Regression Scenario A~H (`12_TEST_PLAN.md`의 `Regression Scenarios`).

Wave 2의 합격 조건이다. 각 시나리오는 **독립 테스트**로 남는다 --- 하나로 묶으면
어느 규칙이 깨졌는지 실패 메시지가 말해주지 않는다.

규칙 셋을 이 파일 전체에 건다.

1.  **정책값을 리터럴로 적지 않는다.** 기대값은 `get_config()`에서 읽거나
    `override_config()`로 주입한 값에서 계산한다. 기본값에 기대어 숫자를 단정하면
    config를 아예 읽지 않는 구현도 통과한다(13_ACCEPTANCE_CRITERIA.md의
    `수치 취급 원칙`).
2.  **candidate를 손으로 INSERT하지 않는다.** Ready Pool은 항상
    `materialize_candidates` / `select_next`가 만든다(ADR-010,
    06_LEARNING_ENGINE.md의 `테스트에서의 candidate 구성`). 이 파일에
    `UserSentenceCandidate(...)`가 없는 것이 그 보장이다.
3.  **FSRS 기대값을 날짜 리터럴로 박지 않는다.** 라이브러리로 같은 입력을 직접
    계산해 비교한다. 리터럴을 박으면 interval을 cap하는 구현이 "기대값도 같이
    고치면" 통과해버린다(불변식 #4).

`review_states` / `user_item_learning_state` 행을 factory로 세우는 자리가 몇 군데
있다. 그것은 candidate가 아니라 **학습 상태**이고, 시나리오의 전제(이미 복습 중인
item, 이미 진행된 context stage)를 만드는 유일한 방법이다. 해당 테스트 docstring에
이유를 적는다.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from fsrs import Card, Rating, Scheduler
from fsrs import State as FsrsState
from sqlalchemy.orm import Session, sessionmaker

from app.config import AppConfig, get_config
from app.jobs import runner, worker
from app.learning.exposure import count_valid_exposures
from app.learning.mastery import OBSERVATION, ema, record_explicit_evidence
from app.learning.probe import select_probe_target
from app.learning.selection import materialize_candidates, select_next
from app.llm.prompts import PROMPT_TEMPLATES
from app.models import (
    GenerationJob,
    ItemExposure,
    LearningEvent,
    LearningItem,
    ReviewState,
    Sentence,
    SentenceItem,
    StudyPresentation,
    StudySession,
    User,
    UserItemLearningState,
    UserMastery,
    UserSentenceCandidate,
)
from app.models.enums import (
    CandidateStatus,
    ContentFlagReason,
    ContextStage,
    EventType,
    ExplicitSignal,
    JobType,
    LlmTaskType,
    PresentationRole,
    ReviewReason,
    SentenceStatus,
)
from app.services import content_flag, interactions, presentation, study_session
from app.srs.review import record_explicit_review
from tests import factories
from tests.clock import MutableClock
from tests.conftest import (
    StudyApi,
    assert_no_provider_import,
    no_outbound_network,
    override_config,
)
from tests.llm_fixtures import batch_response, item_payload, sentence_payload
from tests.provider_double import RecordingProvider

pytestmark = pytest.mark.integration

# 시나리오 자신이 정한 횟수이지 정책값이 아니다(12_TEST_PLAN.md의 Scenario B / G).
PASSIVE_ROUNDS = 5
SKIP_ROUNDS = 3
# `알고 있었음`을 이어 받아 카드가 learning step을 졸업하고 며칠짜리 interval에
# 도달하기까지의 복습 횟수. FSRS 기본 파라미터에 대한 관측값이며 정책값이 아니다.
GRADUATION_ROUNDS = 3
# flag된 문장이 "한 번도" 나오지 않는 것을 볼 만큼의 반복(Scenario H).
SELECTION_ATTEMPTS = 6
# `_first_exposure`가 원하는 item을 만날 때까지 넘겨볼 문장 수. 정책값이 아니라
# 무한 루프 대신 실패로 끝나게 하는 안전장치다.
FIRST_EXPOSURE_ATTEMPTS = 4

# FSRS memory state + 애플리케이션 카운터 + 스케줄. 무신호 review는 이 중
# `deferred_until` 하나만 건드려야 한다(07_SRS_SPEC.md).
SCHEDULE_COLUMNS = (
    "stability",
    "difficulty",
    "state",
    "step",
    "reps",
    "lapses",
    "next_review_at",
    "last_review_at",
    "deferred_until",
)
# 무신호가 절대 건드리면 안 되는 여섯. `deferred_until`과 `next_review_at`은 뺀다.
MEMORY_COLUMNS = ("stability", "difficulty", "state", "step", "reps", "lapses")


def _cfg(**sections: dict[str, Any]) -> AppConfig:
    return override_config(get_config(), **sections)


# --------------------------------------------------------------------------
# 세션 구동 (service 경로)
# --------------------------------------------------------------------------


def _start(db: Session, user: User, *, now: datetime, cfg: AppConfig) -> StudySession:
    return study_session.start_or_resume(db, user=user, now=now, cfg=cfg).session


def _next(
    db: Session, user: User, session_id: int, *, now: datetime, cfg: AppConfig
) -> presentation.PresentationView | None:
    return presentation.next_presentation(db, user=user, session_id=session_id, now=now, cfg=cfg)


def _complete(
    db: Session, user: User, presentation_id: int, *, now: datetime, cfg: AppConfig
) -> None:
    presentation.complete_presentation(
        db, user_id=user.id, presentation_id=presentation_id, now=now, cfg=cfg
    )


def _finish(db: Session, user: User, session_id: int, *, now: datetime, cfg: AppConfig) -> None:
    study_session.finish(db, user_id=user.id, session_id=session_id, now=now, cfg=cfg)


def _click(
    db: Session,
    user: User,
    view: presentation.PresentationView,
    *,
    sentence_item_id: int,
    now: datetime,
    cfg: AppConfig,
) -> interactions.ExplanationView:
    return interactions.click_item(
        db,
        user_id=user.id,
        presentation_id=view.presentation_id,
        sentence_item_id=sentence_item_id,
        client_event_id=uuid.uuid4(),
        now=now,
        cfg=cfg,
    )


def _report(
    db: Session,
    user: User,
    view: presentation.PresentationView,
    *,
    sentence_item_id: int,
    signal: ExplicitSignal,
    now: datetime,
    cfg: AppConfig,
) -> None:
    interactions.self_report(
        db,
        user_id=user.id,
        presentation_id=view.presentation_id,
        sentence_item_id=sentence_item_id,
        signal=signal,
        client_event_id=uuid.uuid4(),
        now=now,
        cfg=cfg,
    )


# --------------------------------------------------------------------------
# 조회
# --------------------------------------------------------------------------


def _schedule_snapshot(db: Session, *, user_id: int) -> dict[int, tuple[object, ...]]:
    """item별 `review_states` 9컬럼.

    ORM 인스턴스가 아니라 **컬럼을 직접** 읽는다. identity map에 남은 객체를 읽으면
    `synchronize_session=False`인 UPDATE가 지나가도 파이썬 쪽 값이 그대로여서,
    "아무도 쓰지 않았다"는 단정이 거짓 통과한다.
    """
    rows = db.execute(
        sa.select(
            ReviewState.learning_item_id,
            *(getattr(ReviewState, column) for column in SCHEDULE_COLUMNS),
        ).where(ReviewState.user_id == user_id)
    ).all()
    return {row[0]: tuple(row[1:]) for row in rows}


def _utc(moment: datetime) -> datetime:
    """DB가 돌려주는 시각에는 세션 timezone(Asia/Seoul)이 붙어 있다.

    같은 순간이므로 비교에는 문제가 없지만, 시계에 그대로 넣으면 UTC를 요구하는
    FSRS 라이브러리가 거부한다. 시각을 DB에서 읽어 시계로 옮길 때만 쓴다.
    """
    return moment.astimezone(UTC)


def _card_of(state: ReviewState) -> Card:
    """`review_states` 컬럼에서 `Card`를 만든다. 기대값을 라이브러리로 직접 계산하기 위한 것이다."""
    return Card(
        card_id=None,
        state=FsrsState(state.state),
        step=state.step,
        stability=state.stability,
        difficulty=state.difficulty,
        due=state.next_review_at,
        last_review=state.last_review_at,
    )


def _state_of(db: Session, *, user: User, item: LearningItem) -> ReviewState | None:
    return db.execute(
        sa.select(ReviewState).where(
            ReviewState.user_id == user.id, ReviewState.learning_item_id == item.id
        )
    ).scalar_one_or_none()


def _mastery_of(db: Session, *, user: User, item: LearningItem) -> UserMastery | None:
    return db.execute(
        sa.select(UserMastery).where(
            UserMastery.user_id == user.id, UserMastery.learning_item_id == item.id
        )
    ).scalar_one_or_none()


def _learning_state_of(
    db: Session, *, user: User, item: LearningItem
) -> UserItemLearningState | None:
    return db.execute(
        sa.select(UserItemLearningState).where(
            UserItemLearningState.user_id == user.id,
            UserItemLearningState.learning_item_id == item.id,
        )
    ).scalar_one_or_none()


def _sentence_item_id(db: Session, *, sentence_id: int, item: LearningItem) -> int:
    return db.execute(
        sa.select(SentenceItem.id).where(
            SentenceItem.sentence_id == sentence_id,
            SentenceItem.learning_item_id == item.id,
        )
    ).scalar_one()


def _target_item_ids(db: Session, *, candidate_id: int) -> set[int]:
    from app.models import UserSentenceCandidateTarget

    rows = db.execute(
        sa.select(UserSentenceCandidateTarget.learning_item_id).where(
            UserSentenceCandidateTarget.candidate_id == candidate_id
        )
    ).scalars()
    return set(rows)


def _exposures(db: Session, *, user: User, item: LearningItem) -> list[ItemExposure]:
    return list(
        db.execute(
            sa.select(ItemExposure)
            .where(
                ItemExposure.user_id == user.id,
                ItemExposure.learning_item_id == item.id,
            )
            .order_by(ItemExposure.id)
        )
        .scalars()
        .all()
    )


def _events(db: Session, *, user: User, event_type: EventType) -> list[LearningEvent]:
    return list(
        db.execute(
            sa.select(LearningEvent)
            .where(
                LearningEvent.user_id == user.id,
                LearningEvent.event_type == event_type,
            )
            .order_by(LearningEvent.id)
        )
        .scalars()
        .all()
    )


# --------------------------------------------------------------------------
# 전제 만들기
# --------------------------------------------------------------------------


def _first_exposure(
    db: Session, user: User, item: LearningItem, *, clock: MutableClock, cfg: AppConfig
) -> None:
    """엔진 경로로 그 item을 한 번 제시하고 닫는다 --- 유효 exposure 1건을 만든다.

    `review` pool은 "이미 target으로 제시된 적이 있는 item"이다(ADR-013). exposure가
    0건인 item은 `new` 또는 exploration의 몫이므로, "이미 복습 중"이라는 전제를
    만들려면 그 첫 제시가 실제로 일어나야 한다. candidate는 여전히 손으로 만들지
    않는다.

    신호는 주지 않는다. 아직 `review_states` 행이 없어 deferral도 생기지 않으므로
    (07_SRS_SPEC.md의 `No-signal review`) 이 전제가 뒤의 라운드를 가리지 않는다.
    """
    session = _start(db, user, now=clock.now(), cfg=cfg)
    for _ in range(FIRST_EXPOSURE_ATTEMPTS):
        view = _next(db, user, session.id, now=clock.now(), cfg=cfg)
        assert view is not None, f"{item.lemma}: 제시할 문장이 없다"
        row = db.get(StudyPresentation, view.presentation_id)
        assert row is not None
        targets = _target_item_ids(db, candidate_id=row.candidate_id)
        _complete(db, user, view.presentation_id, now=clock.now(), cfg=cfg)
        if item.id in targets:
            _finish(db, user, session.id, now=clock.now(), cfg=cfg)
            return
    raise AssertionError(f"{item.lemma}이 target으로 제시되지 않았다")


def _schedule(
    db: Session,
    user: User,
    item: LearningItem,
    *,
    cfg: AppConfig,
    now: datetime,
    signal: ExplicitSignal = ExplicitSignal.KNOWN,
) -> ReviewState:
    """진행 중인 복습 스케줄. FSRS 컬럼을 손으로 적지 않고 `app/srs/`로 만든다."""
    return record_explicit_review(
        db,
        user_id=user.id,
        learning_item_id=item.id,
        signal=signal,
        now=now,
        config=cfg,
    )


# --------------------------------------------------------------------------
# Scenario A --- due 20개 / 12분 세션
#
# "일부만 표시된다 / 미표시 due는 failure·lapse로 처리되지 않는다 / due 상태와
# next_review_at이 그대로 유지된다."
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _SessionRun:
    presented_item_ids: set[int]
    presentation_ids: list[int]
    # 실제로 밟은 경로. 이것을 단정하지 않으면 backlog가 통째로 Pool Fallback으로
    # 새도 아래 두 테스트가 초록으로 남는다.
    path: list[tuple[PresentationRole, ReviewReason | None]]


def _due_backlog(
    db: Session, user: User, *, count: int, cfg: AppConfig, clock: MutableClock
) -> list[LearningItem]:
    """이미 한 번 제시된 적이 있고 지금 전부 due인 item `count`개. 각자 문장 하나를 갖는다.

    **첫 제시를 엔진으로 밟는 것이 이 fixture의 핵심이다.** 유효 exposure가 0건인
    item은 `review` pool에 들어가지 않는다(ADR-013: 첫 제시는 `new`의 몫이고 두
    pool은 배타적이다). 이 단계를 건너뛰면 backlog 20개가 통째로 review pool에서
    탈락해 세션이 Pool Fallback 2의 `reinforcement`로만 굴러가고, Scenario A가
    지키려는 `fsrs_due` backlog 경로를 **한 번도 지나지 않는다.**

    워밍업 단계에서는 신호를 주지 않는다. 신호를 주면 그 자리에서 스케줄이 생겨
    다음 item의 워밍업이 review presentation에 막힌다. 스케줄과 mastery는 워밍업이
    전부 끝난 뒤 두 번째 loop에서 만든다.

    mastery를 남기는 이유는 explicit evidence가 있는 item이 exploration 후보에서
    빠지기 때문이다(06_LEARNING_ENGINE.md의 조건 1). 그래야 이 시나리오가 review
    경로만 본다.
    """
    items: list[LearningItem] = []
    for index in range(count):
        item = factories.make_learning_item(db, lemma=f"backlog{index:02d}")
        factories.make_ready_sentence(db, [item])
        _first_exposure(db, user, item, clock=clock, cfg=cfg)
        items.append(item)

    now = clock.now()
    for index, item in enumerate(items):
        assert count_valid_exposures(db, user_id=user.id, learning_item_id=item.id) > 0, (
            "워밍업이 유효 노출을 남기지 않았다"
        )
        record_explicit_evidence(
            db,
            user_id=user.id,
            learning_item_id=item.id,
            signal=ExplicitSignal.KNOWN,
            now=now,
            alpha=cfg.learning.mastery_ema_alpha,
        )
        state = _schedule(db, user, item, cfg=cfg, now=now)
        # 서로 다른 과거 시각이라 Review Ordering(next_review_at ASC)이 결정적이다.
        state.next_review_at = now - timedelta(days=count - index)
        db.flush()
    return items


def _run_session(
    db: Session,
    user: User,
    *,
    clock: MutableClock,
    cfg: AppConfig,
    presentations: int,
    minutes: float,
) -> _SessionRun:
    """`minutes`를 고르게 나눠 쓰며 `presentations`개를 제시하고 세션을 끝낸다."""
    session = _start(db, user, now=clock.now(), cfg=cfg)
    step = timedelta(minutes=minutes / presentations)
    presented: set[int] = set()
    ids: list[int] = []
    path: list[tuple[PresentationRole, ReviewReason | None]] = []
    for _ in range(presentations):
        view = _next(db, user, session.id, now=clock.now(), cfg=cfg)
        assert view is not None, "backlog가 있는데 제시할 것이 없다"
        shown_row = db.get(StudyPresentation, view.presentation_id)
        assert shown_row is not None
        presented |= _target_item_ids(db, candidate_id=shown_row.candidate_id)
        ids.append(view.presentation_id)
        path.append((view.presentation_role, view.review_reason))
        clock.advance(step)
        _complete(db, user, view.presentation_id, now=clock.now(), cfg=cfg)
    _finish(db, user, session.id, now=clock.now(), cfg=cfg)
    return _SessionRun(presented_item_ids=presented, presentation_ids=ids, path=path)


def test_scenario_a_a_session_shows_only_part_of_the_due_backlog(db_session: Session) -> None:
    """세션 하나가 backlog 전체를 소화하지 않는다.

    "몇 문장"은 엔진이 강제하는 값이 아니다. 12분 안에 사용자가 실제로 넘기는
    문장 수이므로 config에서 파생한다 --- 숫자를 박으면 그 숫자가 정책인 것처럼
    굳는다.
    """
    cfg = _cfg()
    clock = MutableClock()
    user = factories.make_user(db_session)
    backlog = cfg.learning.candidate_materialization_batch_size
    shown = cfg.learning.minimum_meaningful_exposures
    items = _due_backlog(db_session, user, count=backlog, cfg=cfg, clock=clock)

    run = _run_session(
        db_session,
        user,
        clock=clock,
        cfg=cfg,
        presentations=shown,
        minutes=cfg.learning.default_session_minutes,
    )

    assert len(run.presentation_ids) == shown
    assert 0 < len(run.presented_item_ids) < len(items)
    # backlog 세션은 due를 소화하는 경로여야 한다. reinforcement fallback으로
    # 굴러가면 아래 "미표시 due 불변" 단정이 due 경로와 무관해진다.
    assert run.path == [(PresentationRole.REVIEW, ReviewReason.FSRS_DUE)] * shown


def test_scenario_a_unshown_due_items_keep_every_schedule_column(db_session: Session) -> None:
    """미표시 due는 failure도 lapse도 아니다. `review_states` 9컬럼이 통째로 불변이고
    여전히 due여야 한다. 선택이 상태를 쓰기 시작하면 여기서 잡힌다."""
    cfg = _cfg()
    clock = MutableClock()
    user = factories.make_user(db_session)
    backlog = cfg.learning.candidate_materialization_batch_size
    _due_backlog(db_session, user, count=backlog, cfg=cfg, clock=clock)
    before = _schedule_snapshot(db_session, user_id=user.id)

    run = _run_session(
        db_session,
        user,
        clock=clock,
        cfg=cfg,
        presentations=cfg.learning.minimum_meaningful_exposures,
        minutes=cfg.learning.default_session_minutes,
    )

    # 이 단정이 없으면 backlog가 review pool에서 통째로 탈락해도(그래서 due를
    # 아무도 건드릴 일이 없어져도) 아래 불변 단정이 초록으로 남는다.
    assert run.path == [(PresentationRole.REVIEW, ReviewReason.FSRS_DUE)] * len(
        run.presentation_ids
    )
    after = _schedule_snapshot(db_session, user_id=user.id)
    untouched = sorted(set(before) - run.presented_item_ids)
    assert untouched, "미표시 due가 하나도 없으면 이 시나리오가 성립하지 않는다"
    assert {item_id: after[item_id] for item_id in untouched} == {
        item_id: before[item_id] for item_id in untouched
    }
    states = db_session.execute(
        sa.select(ReviewState).where(ReviewState.learning_item_id.in_(untouched))
    ).scalars()
    for state in states:
        assert state.next_review_at <= clock.now()
        assert state.deferred_until is None


# --------------------------------------------------------------------------
# Scenario B --- passive exposure 5회, explicit signal 0
#
# "mastery가 Known으로 상승하지 않는다 / 같은 세션에서 무한 due 반복이 없다 /
# passive_exposures_before_probe 이후 probe 우선순위가 상승한다."
# --------------------------------------------------------------------------


def test_scenario_b_five_no_signal_reviews_leave_memory_state_untouched(
    db_session: Session,
) -> None:
    """무신호 review 5회. 확인하는 것은 정확히 다음이다.

    ``` text
    mastery                       NULL 유지, evidence_count 0
    FSRS memory state / 카운터     6컬럼 불변
    deferred_until                매회 now + 주입한 passive_review_deferral_hours
    item_exposures                무신호여도 5건 (경험은 했다)
    passive_no_signal_count       5
    deferral 유효 구간             같은 item이 다시 뽑히지 않는다
    ```

    한 세션에서 5회를 만들 수 없다는 점이 이 시나리오의 핵심이다 ---
    `deferred_until`이 재선택을 막으므로 세션을 나누고 시계를 그만큼 민다.
    기본값이 아닌 deferral을 주입해 "설정을 실제로 읽는가"까지 본다.

    `review_states` 행은 `app/srs/`의 실제 경로(`record_explicit_review`)로 만들고,
    그 앞의 첫 제시는 엔진으로 밟는다 --- exposure 0건인 item은 `review` pool에
    들어가지 않는다(ADR-013). 두 전제 모두 시나리오가 세는 5회 밖이며, mastery는
    별도 테이블이라 이 전제로 mastery가 생기지 않는다(불변식 #3).
    """
    deferral_hours = get_config().learning.passive_review_deferral_hours + 1
    cfg = _cfg(learning={"passive_review_deferral_hours": deferral_hours})
    clock = MutableClock()
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    # 무신호 노출도 ladder를 올리고(ADR-012) 올라간 stage는 아직 보지 않은 문장을
    # 요구하므로(06_LEARNING_ENGINE.md의 `stage -> sentence`) 라운드 수만큼 문맥을 둔다.
    for index in range(PASSIVE_ROUNDS + 1):
        factories.make_ready_sentence(db_session, [item], surfaces=[f"任せる{index}"])
    _first_exposure(db_session, user, item, clock=clock, cfg=cfg)
    warm_up_exposures = len(_exposures(db_session, user=user, item=item))
    assert warm_up_exposures == 1
    state = _schedule(db_session, user, item, cfg=cfg, now=clock.now())
    state.next_review_at = clock.now() - timedelta(days=1)
    db_session.flush()
    baseline = tuple(getattr(state, column) for column in MEMORY_COLUMNS)

    for round_index in range(PASSIVE_ROUNDS):
        session = _start(db_session, user, now=clock.now(), cfg=cfg)
        view = _next(db_session, user, session.id, now=clock.now(), cfg=cfg)
        assert view is not None, f"round {round_index}: due인데 제시할 것이 없다"
        assert view.presentation_role is PresentationRole.REVIEW
        # 신호를 하나도 주지 않는다. click도 probe 응답도 하지 않는다.
        completed_at = clock.advance(timedelta(minutes=1))
        _complete(db_session, user, view.presentation_id, now=completed_at, cfg=cfg)

        assert state.deferred_until == completed_at + timedelta(hours=deferral_hours)
        assert tuple(getattr(state, column) for column in MEMORY_COLUMNS) == baseline
        assert (
            len(_exposures(db_session, user=user, item=item)) == warm_up_exposures + round_index + 1
        )
        assert _mastery_of(db_session, user=user, item=item) is None

        # deferral이 유효한 동안 같은 item이 다시 뽑히지 않는다.
        assert _next(db_session, user, session.id, now=clock.now(), cfg=cfg) is None

        _finish(db_session, user, session.id, now=clock.now(), cfg=cfg)
        clock.advance(timedelta(hours=deferral_hours))

    learning_state = _learning_state_of(db_session, user=user, item=item)
    assert learning_state is not None
    # 전제로 밟은 첫 제시도 무신호였다. 그래서 둘 다 라운드 수보다 1 크다.
    assert learning_state.passive_no_signal_count == PASSIVE_ROUNDS + warm_up_exposures
    assert len(_exposures(db_session, user=user, item=item)) == PASSIVE_ROUNDS + warm_up_exposures
    assert _mastery_of(db_session, user=user, item=item) is None
    assert state.next_review_at <= clock.now(), "무신호는 스케줄을 미루지 않는다"


def test_scenario_b_passive_repetition_raises_probe_priority(db_session: Session) -> None:
    """`passive_exposures_before_probe`에 도달한 item이 먼저 질문받는다 (ADR-011).

    두 item 모두 explicit evidence가 없어 우선순위 자체는 같다. 그래서 순서를
    가르는 것은 passive 반복뿐이고, 스쳐 지나가기만 한 쪽이 `learning_item_id`
    tie-break를 **이겨야** 한다. 임계값은 주입한 값을 쓴다.
    """
    threshold = 2
    cfg = _cfg(learning={"passive_exposures_before_probe": threshold})
    clock = MutableClock()
    user = factories.make_user(db_session)
    quiet = factories.make_learning_item(db_session, lemma="quiet")
    passive = factories.make_learning_item(db_session, lemma="passive")
    assert quiet.id < passive.id, "tie-break가 id ASC이므로 순서가 이래야 의미가 있다"
    factories.make_learning_state(db_session, user, quiet, passive_no_signal_count=threshold - 1)
    factories.make_learning_state(db_session, user, passive, passive_no_signal_count=threshold)
    study = factories.make_study_session(
        db_session, user, target_minutes=cfg.learning.default_session_minutes
    )

    target = select_probe_target(
        db_session,
        user_id=user.id,
        study_session_id=study.id,
        target_item_ids=[quiet.id, passive.id],
        now=clock.now(),
        config=cfg,
    )

    assert target is not None
    assert target.learning_item_id == passive.id


# --------------------------------------------------------------------------
# Scenario C --- 첫 exposure에서 `알고 있었음`
#
# "FSRS rating은 Good / mastery에 explicit evidence(observation)가 반영된다 /
# exposure < minimum이므로 reinforcement 노출이 계속 가능하다 / FSRS interval을
# 억지로 cap하지 않는다."
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _FirstKnown:
    item: LearningItem
    view: presentation.PresentationView
    reported_at: datetime
    session_id: int


def _first_exposure_known(
    db: Session, user: User, *, clock: MutableClock, cfg: AppConfig
) -> _FirstKnown:
    """학습 target이지만 아직 스케줄이 없는 item을 처음 보여주고 `알고 있었음`을 받는다.

    `user_item_learning_state`를 factory로 세우는 이유: `new` role은 "승격됐지만 아직
    FSRS 스케줄이 없는 item"이고(06_LEARNING_ENGINE.md), 그 전제를 만드는 다른
    경로가 Wave 2에 없다. candidate는 손으로 만들지 않는다 --- 이 상태 위에서
    materialization이 `new` candidate를 만든다.

    **주의(굶주림).** `is_active_learning_target = True` + `review_states` 없음
    상태의 item에 유효 exposure가 1건이라도 붙으면 `new`(exposure 0건만),
    `review`(`review_states` 필요), exploration(활성 target 제외) 어디에도 들지
    못해 영구히 제시되지 않는다. 여기서는 그 첫 제시 직후 `알고 있었음`이 아니라
    승격 경로가 스케줄을 만들기 전 상태를 잠깐 쓰는 것이고, 프로덕션에서는 승격이
    항상 FSRS 기록을 동반하므로 도달할 수 없다. `interactions._apply_explicit_evidence`
    의 FSRS 기록 조건을 완화하면 이 조합이 실제 굶주림이 된다.
    """
    item = factories.make_learning_item(db, lemma="任せる")
    sentence = factories.make_ready_sentence(db, [item])
    factories.make_learning_state(db, user, item, is_active_learning_target=True)

    session = _start(db, user, now=clock.now(), cfg=cfg)
    view = _next(db, user, session.id, now=clock.now(), cfg=cfg)
    assert view is not None
    assert view.presentation_role is PresentationRole.NEW
    assert view.sentence_id == sentence.id

    sentence_item_id = _sentence_item_id(db, sentence_id=sentence.id, item=item)
    _click(db, user, view, sentence_item_id=sentence_item_id, now=clock.now(), cfg=cfg)
    reported_at = clock.advance(timedelta(seconds=30))
    _report(
        db,
        user,
        view,
        sentence_item_id=sentence_item_id,
        signal=ExplicitSignal.KNOWN,
        now=reported_at,
        cfg=cfg,
    )
    return _FirstKnown(item=item, view=view, reported_at=reported_at, session_id=session.id)


def test_scenario_c_known_is_recorded_as_good_with_the_library_interval(
    db_session: Session,
) -> None:
    """기대 스케줄을 라이브러리로 직접 계산해 비교한다.

    날짜 리터럴을 적으면 interval을 cap하는 구현이 "기대값도 같이 고치면" 통과한다.
    `Card(due=now)`에 `Rating.Good`을 먹인 결과와 **정확히** 같아야 한다 ---
    그것이 불변식 #4의 "cap하지 않는다"이다.
    """
    cfg = _cfg()
    clock = MutableClock()
    user = factories.make_user(db_session)

    first = _first_exposure_known(db_session, user, clock=clock, cfg=cfg)

    expected, _log = Scheduler(enable_fuzzing=cfg.srs.fsrs_enable_fuzzing).review_card(
        Card(card_id=None, due=first.reported_at), Rating.Good, first.reported_at
    )
    state = _state_of(db_session, user=user, item=first.item)
    assert state is not None
    assert (state.reps, state.lapses) == (1, 0)
    assert state.next_review_at == expected.due
    assert state.stability == expected.stability
    assert state.difficulty == expected.difficulty
    assert state.state == int(expected.state)
    assert state.step == expected.step
    assert state.next_review_at > first.reported_at


def test_scenario_c_repeated_known_reviews_never_cap_the_interval(db_session: Session) -> None:
    """`알고 있었음`을 이어서 받으면 interval은 라이브러리가 주는 대로 자란다.

    첫 review만 보면 cap을 알아채지 못한다 --- 첫 Good은 learning step이라 10분
    남짓이고, "하루 이내로 당긴다" 같은 cap은 거기에 걸리지 않는다. 그래서 같은
    rating 시퀀스를 라이브러리로 나란히 돌려 **며칠짜리 interval에 도달한 뒤에도**
    저장값이 같은지 본다. 최소 노출을 채우는 것은 interval이 아니라
    `reinforcement`의 일이다(불변식 #4).
    """
    cfg = _cfg()
    clock = MutableClock()
    user = factories.make_user(db_session)
    scheduler = Scheduler(enable_fuzzing=cfg.srs.fsrs_enable_fuzzing)

    first = _first_exposure_known(db_session, user, clock=clock, cfg=cfg)
    _complete(db_session, user, first.view.presentation_id, now=clock.now(), cfg=cfg)
    expected, _log = scheduler.review_card(
        Card(card_id=None, due=first.reported_at), Rating.Good, first.reported_at
    )
    _finish(db_session, user, first.session_id, now=clock.now(), cfg=cfg)

    reviewed_at = first.reported_at
    for round_index in range(GRADUATION_ROUNDS):
        state = _state_of(db_session, user=user, item=first.item)
        assert state is not None
        clock.set(_utc(state.next_review_at))
        session = _start(db_session, user, now=clock.now(), cfg=cfg)
        view = _next(db_session, user, session.id, now=clock.now(), cfg=cfg)
        assert view is not None, f"round {round_index}: 복습할 것이 없다"
        assert view.presentation_role is PresentationRole.REVIEW

        reviewed_at = clock.now()
        _report(
            db_session,
            user,
            view,
            sentence_item_id=_sentence_item_id(
                db_session, sentence_id=view.sentence_id, item=first.item
            ),
            signal=ExplicitSignal.KNOWN,
            now=reviewed_at,
            cfg=cfg,
        )
        _complete(db_session, user, view.presentation_id, now=clock.now(), cfg=cfg)
        _finish(db_session, user, session.id, now=clock.now(), cfg=cfg)

        expected, _log = scheduler.review_card(expected, Rating.Good, reviewed_at)
        state = _state_of(db_session, user=user, item=first.item)
        assert state is not None
        assert state.next_review_at == expected.due
        assert state.stability == expected.stability

    assert expected.due - reviewed_at > timedelta(days=1), (
        "며칠짜리 interval에 도달하지 못했다 --- 이 상태로는 cap을 감시하지 못한다"
    )


def test_scenario_c_known_writes_explicit_mastery_evidence(db_session: Session) -> None:
    """old가 NULL이므로 첫 evidence가 그대로 값이 된다(02_LEARNING_POLICY.md).

    관측값도 alpha도 리터럴로 적지 않는다. 주입한 alpha로 같은 EMA를 계산해 맞춘다.
    """
    alpha = round(get_config().learning.mastery_ema_alpha / 2, 3)
    cfg = _cfg(learning={"mastery_ema_alpha": alpha})
    clock = MutableClock()
    user = factories.make_user(db_session)

    first = _first_exposure_known(db_session, user, clock=clock, cfg=cfg)

    mastery = _mastery_of(db_session, user=user, item=first.item)
    assert mastery is not None
    assert mastery.comprehension_mastery == pytest.approx(
        ema(None, OBSERVATION[ExplicitSignal.KNOWN], alpha)
    )
    assert mastery.evidence_count == 1
    # MVP에 audio가 없다. NULL은 "능력 0"이 아니라 "측정하지 않음"이다.
    assert mastery.listening_mastery is None


def test_scenario_c_reinforcement_stays_available_below_the_minimum(
    db_session: Session,
) -> None:
    """`next_review_at`이 미래인데도 `reinforcement` candidate를 고를 수 있어야 한다.

    이것이 불변식 #4의 반대편이다 --- interval을 줄이지 않고 최소 노출을 채우는
    유일한 수단이 이 reason이다. 최소 노출 값은 주입한 것을 쓴다.
    """
    minimum = get_config().learning.minimum_meaningful_exposures
    cfg = _cfg(learning={"minimum_meaningful_exposures": minimum})
    clock = MutableClock()
    user = factories.make_user(db_session)

    first = _first_exposure_known(db_session, user, clock=clock, cfg=cfg)
    _complete(db_session, user, first.view.presentation_id, now=clock.now(), cfg=cfg)

    exposures = count_valid_exposures(db_session, user_id=user.id, learning_item_id=first.item.id)
    assert exposures == 1
    assert exposures < minimum

    state = _state_of(db_session, user=user, item=first.item)
    assert state is not None and state.next_review_at > clock.now()

    selection = select_next(
        db_session,
        user=user,
        study_session_id=first.session_id,
        now=clock.now(),
        cfg=cfg.learning,
    )
    assert selection is not None
    assert selection.presentation_role is PresentationRole.REVIEW
    assert selection.review_reason is ReviewReason.REINFORCEMENT
    assert first.item.id in selection.target_item_ids


# --------------------------------------------------------------------------
# Scenario D --- new context에서 실패
#
# "`몰랐음`이면 Again evidence를 기록한다 / 다음 context는 `context_repair`로 한
# 단계 쉬워질 수 있다 / 해당 문장이 flag되면 파생된 failure evidence를 무효화할 수
# 있다."
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _NewContextFailure:
    item: LearningItem
    anchor_sentence_id: int
    failed_sentence_id: int
    failed_presentation_id: int
    mastery_before: float
    card_before: Card
    failed_at: datetime


def _fail_in_new_context(
    db: Session, user: User, *, clock: MutableClock, cfg: AppConfig
) -> _NewContextFailure:
    """anchor에서 `애매함`으로 학습을 시작한 item을 새 문맥에서 `몰랐음`으로 실패시킨다.

    stage를 `new_context`로 올리는 한 줄만 손으로 쓴다. 전이 자체는 이제
    `advance_context_stage`가 수행하지만(07_SRS_SPEC.md의 `전이 규칙`) ladder
    꼭대기까지 가려면 성공 노출이 세 번 더 필요하고, 이 시나리오가 보려는 것은 그
    등반이 아니라 **꼭대기에서의 실패**다. candidate는 손으로 만들지 않는다 ---
    그 stage 위에서 materialization이 새 문맥 candidate를 만든다.
    """
    item = factories.make_learning_item(db, lemma="任せる")
    anchor = factories.make_ready_sentence(db, [item])
    new_context = factories.make_ready_sentence(db, [item], surfaces=["任せて"])

    # 1. anchor에서 `애매함`. 승격(promote_incidental) + Hard. 아직 lapse는 없다.
    first_session = _start(db, user, now=clock.now(), cfg=cfg)
    first_view = _next(db, user, first_session.id, now=clock.now(), cfg=cfg)
    assert first_view is not None
    assert first_view.sentence_id == anchor.id
    assert first_view.context_stage is ContextStage.ANCHOR
    _report(
        db,
        user,
        first_view,
        sentence_item_id=_sentence_item_id(db, sentence_id=anchor.id, item=item),
        signal=ExplicitSignal.UNCERTAIN,
        now=clock.now(),
        cfg=cfg,
    )
    _complete(db, user, first_view.presentation_id, now=clock.now(), cfg=cfg)
    _finish(db, user, first_session.id, now=clock.now(), cfg=cfg)

    state = _state_of(db, user=user, item=item)
    assert state is not None and state.lapses == 0
    mastery = _mastery_of(db, user=user, item=item)
    assert mastery is not None and mastery.comprehension_mastery is not None
    mastery_before = mastery.comprehension_mastery

    # 2. ladder 꼭대기로 건너뛴다(위 docstring). 다음 노출은 새 문맥이다.
    learning_state = _learning_state_of(db, user=user, item=item)
    assert learning_state is not None
    learning_state.context_stage = ContextStage.NEW_CONTEXT
    db.flush()

    clock.set(_utc(state.next_review_at))
    second_session = _start(db, user, now=clock.now(), cfg=cfg)
    second_view = _next(db, user, second_session.id, now=clock.now(), cfg=cfg)
    assert second_view is not None
    assert second_view.context_stage is ContextStage.NEW_CONTEXT
    assert second_view.sentence_id == new_context.id

    failed_at = clock.advance(timedelta(seconds=20))
    card_before = _card_of(state)
    _report(
        db,
        user,
        second_view,
        sentence_item_id=_sentence_item_id(db, sentence_id=new_context.id, item=item),
        signal=ExplicitSignal.UNKNOWN,
        now=failed_at,
        cfg=cfg,
    )
    _complete(db, user, second_view.presentation_id, now=clock.now(), cfg=cfg)
    _finish(db, user, second_session.id, now=clock.now(), cfg=cfg)

    return _NewContextFailure(
        item=item,
        anchor_sentence_id=anchor.id,
        failed_sentence_id=new_context.id,
        failed_presentation_id=second_view.presentation_id,
        mastery_before=mastery_before,
        card_before=card_before,
        failed_at=failed_at,
    )


def test_scenario_d_unknown_in_a_new_context_is_recorded_as_again(db_session: Session) -> None:
    """새 문맥 실패도 explicit `몰랐음`이면 Again이다(07_SRS_SPEC.md의 `New-context Failure`).

    "문장이 어려웠을 뿐"이라며 기록을 무르지 않는다. 기록(FSRS)과 다음 문맥 선택은
    별도 의사결정이다.
    """
    alpha = round(get_config().learning.mastery_ema_alpha / 2, 3)
    cfg = _cfg(learning={"mastery_ema_alpha": alpha})
    clock = MutableClock()
    user = factories.make_user(db_session)

    failure = _fail_in_new_context(db_session, user, clock=clock, cfg=cfg)

    state = _state_of(db_session, user=user, item=failure.item)
    assert state is not None
    assert state.lapses == 1
    assert state.reps == 2

    # 실패 직전 카드에 `Again`을 먹인 결과와 정확히 같아야 한다. rating이 Hard나
    # Good으로 기록되면 stability/difficulty/due가 전부 달라진다.
    expected, _log = Scheduler(enable_fuzzing=cfg.srs.fsrs_enable_fuzzing).review_card(
        failure.card_before, Rating.Again, failure.failed_at
    )
    assert state.stability == expected.stability
    assert state.difficulty == expected.difficulty
    assert state.state == int(expected.state)
    assert state.step == expected.step
    assert state.next_review_at == expected.due

    mastery = _mastery_of(db_session, user=user, item=failure.item)
    assert mastery is not None
    assert mastery.comprehension_mastery == pytest.approx(
        ema(failure.mastery_before, OBSERVATION[ExplicitSignal.UNKNOWN], alpha)
    )
    assert mastery.evidence_count == 2


def test_scenario_d_the_next_review_repairs_the_context(db_session: Session) -> None:
    """실패 후 한 단계 쉬운 문맥으로 되돌린 다음 review의 reason은 `context_repair`다.

    우선순위 1이므로 fsrs_due / reinforcement가 함께 가능해도 이것이 먼저다
    (06_LEARNING_ENGINE.md). **stage를 손으로 내리지 않는다** --- explicit `몰랐음`이
    exposure 확정과 같은 자리에서 ladder를 한 칸 내리고(07_SRS_SPEC.md의 `전이 규칙`),
    `context_repair`는 그 결과를 읽을 뿐이다. 이 경로가 프로덕션에서 실제로 도달
    가능하다는 것이 이 테스트의 요지다.
    """
    cfg = _cfg()
    clock = MutableClock()
    user = factories.make_user(db_session)
    failure = _fail_in_new_context(db_session, user, clock=clock, cfg=cfg)
    # `varied`는 아직 보지 않은 문장을 요구한다(06_LEARNING_ENGINE.md의
    # `stage -> sentence`). 되돌린 stage에 쓸 문맥을 하나 둔다.
    repair_sentence = factories.make_ready_sentence(db_session, [failure.item], surfaces=["任せた"])

    learning_state = _learning_state_of(db_session, user=user, item=failure.item)
    assert learning_state is not None
    assert learning_state.context_stage is ContextStage.VARIED, "실패가 ladder를 내리지 않았다"

    session = _start(db_session, user, now=clock.now(), cfg=cfg)
    view = _next(db_session, user, session.id, now=clock.now(), cfg=cfg)

    assert view is not None
    assert view.presentation_role is PresentationRole.REVIEW
    assert view.review_reason is ReviewReason.CONTEXT_REPAIR
    assert view.context_stage is ContextStage.VARIED
    assert view.sentence_id == repair_sentence.id


def test_scenario_d_flagging_the_sentence_invalidates_the_failure_exposure(
    db_session: Session,
) -> None:
    """flag된 문장에서 나온 노출은 `invalidated_at`으로 무효화된다(10_ERROR_HANDLING.md).

    행을 지우지 않는다. `item_exposures`는 immutable log이고, 최소 노출 판정이 세는
    것은 `invalidated_at IS NULL`인 행뿐이다.
    """
    cfg = _cfg()
    clock = MutableClock()
    user = factories.make_user(db_session)
    failure = _fail_in_new_context(db_session, user, clock=clock, cfg=cfg)
    before = count_valid_exposures(db_session, user_id=user.id, learning_item_id=failure.item.id)
    flagged_at = clock.advance(timedelta(minutes=1))

    content_flag.flag_content(
        db_session,
        user_id=user.id,
        presentation_id=failure.failed_presentation_id,
        reason=ContentFlagReason.UNNATURAL,
        note=None,
        client_event_id=uuid.uuid4(),
        now=flagged_at,
        cfg=cfg,
    )

    exposures = _exposures(db_session, user=user, item=failure.item)
    failed = [
        exposure
        for exposure in exposures
        if exposure.study_presentation_id == failure.failed_presentation_id
    ]
    assert len(failed) == 1
    assert failed[0].invalidated_at == flagged_at
    after = count_valid_exposures(db_session, user_id=user.id, learning_item_id=failure.item.id)
    assert after == before - 1
    state = _state_of(db_session, user=user, item=failure.item)
    assert state is not None
    assert state.meaningful_exposure_count == after


# --------------------------------------------------------------------------
# Scenario E --- New Ready Pool 비어 있음
#
# "다른 available category 또는 reinforcement로 진행한다 / synchronous LLM 호출이
# 없다 / replenishment job이 enqueue된다."
# --------------------------------------------------------------------------


def _jobs(db: Session) -> list[GenerationJob]:
    return list(db.execute(sa.select(GenerationJob).order_by(GenerationJob.id)).scalars().all())


def test_scenario_e_an_empty_pool_answers_two_hundred_with_no_presentation(
    study_api: StudyApi, db_session: Session
) -> None:
    """빈 pool은 오류가 아니라 상태다(10_ERROR_HANDLING.md의 `Empty Pool`).

    예외로 만들면 client가 무한 spinner나 오류 화면으로 간다. 그리고 그 순간에도
    provider를 부르지 않는다 --- 그 대신 replenishment job만 남는다.
    """
    study_api.use_config(_cfg())
    started = study_api.client.post("/api/study/session")
    assert started.status_code == 200
    session_id = started.json()["session"]["session_id"]

    with no_outbound_network():
        response = study_api.client.post(f"/api/study/session/{session_id}/next")

    assert response.status_code == 200
    assert response.json() == {"presentation": None}
    assert_no_provider_import()

    jobs = _jobs(db_session)
    assert jobs, "모든 pool이 비었는데 replenishment job이 없다"
    assert {job.job_type for job in jobs} == {JobType.GENERATE_SENTENCE_BATCH}


def test_scenario_e_another_available_category_carries_the_session(
    study_api: StudyApi, db_session: Session
) -> None:
    """`new` pool이 비어도 세션은 멈추지 않는다. 쓸 수 있는 category로 진행한다.

    그때는 생성 요청도 만들지 않는다 --- 보여줄 것이 있는데 job을 쌓으면
    생성 비용만 늘어난다.
    """
    cfg = _cfg()
    study_api.use_config(cfg)
    item = factories.make_learning_item(db_session)
    factories.make_ready_sentence(db_session, [item])

    started = study_api.client.post("/api/study/session")
    session_id = started.json()["session"]["session_id"]
    with no_outbound_network():
        response = study_api.client.post(f"/api/study/session/{session_id}/next")

    assert response.status_code == 200
    payload = response.json()["presentation"]
    assert payload is not None
    assert payload["presentation_role"] == PresentationRole.EXPLORATION.value
    assert _jobs(db_session) == []


def test_scenario_e_the_enqueued_job_refills_the_pool(
    committed_api: StudyApi, committed_db: sessionmaker[Session]
) -> None:
    """Scenario E의 마지막 줄을 끝까지 본다: enqueue된 job이 소비되어 **pool이 회복된다.**

    위 두 테스트는 "빈 pool이 오류가 아니고 job이 생긴다"까지다. 그것만으로는 job을
    아무도 처리하지 않는 구현도 통과한다 --- 사용자에게는 pool이 영영 비어 있는 것과
    같다. 그래서 여기서는 worker를 실제로 한 바퀴 돌려 `/next`가 그 문장을 제시하는
    것까지 확인한다.

    `study_api`가 아니라 `committed_api`를 쓴다. worker는 요청이 **커밋한** job을 다른
    커넥션에서 보아야 하고, `db_session`은 커넥션 하나 안에서 끝난다(conftest의
    fixture docstring).

    주의: 여기서 `no_outbound_network()`는 **warm pool에 의존한다.** 그 헬퍼는
    `socket.socket.connect`를 막으므로 unix socket인 테스트 DB 연결도 함께 막는다.
    블록 안의 요청이 통과하는 것은 바로 위의 `/session`이 이미 커넥션을 pool에
    올려 두었기 때문이고, 블록 안에서 **새 커넥션이 필요해지면** 이 테스트는
    provider와 무관한 이유로 빨개진다(pool 크기 설정 변경, 요청당 세션 수 변경 등).
    그때 고칠 곳은 구현이 아니라 이 블록이다 --- 불변식 #1의 non-fragile한 증명은
    `test_no_provider_in_request_path.py`가 단일 커넥션(`study_api`)과 별도 프로세스로
    따로 들고 있고, 여기서의 단정은 그 위에 얹는 보너스다.

    provider는 인자로 주입한다. `LLM_PROVIDER`를 세팅하지 않는다 --- `stub`은 env 값이
    아니라 provenance 값이다(ADR-016의 `개정`). job -> worker -> pool의 나머지 경우
    (EXPLAIN_ITEM / GENERATE_REVIEW_CONTEXT / ceiling / 재실행)는
    `test_worker_pool_integration.py`가 본다.
    """
    cfg = _cfg()
    committed_api.use_config(cfg)
    now = committed_api.clock.now()
    with committed_db() as setup:
        factories.make_learning_item(setup, lemma="仕方ない")
        for template in PROMPT_TEMPLATES.values():
            if template.task_type is LlmTaskType.GENERATE_SENTENCE_BATCH:
                factories.make_prompt_version(
                    setup, task_type=template.task_type, version=template.version
                )
        setup.commit()

    started = committed_api.client.post("/api/study/session")
    assert started.status_code == 200, started.text
    session_id = started.json()["session"]["session_id"]

    with no_outbound_network():
        empty = committed_api.client.post(f"/api/study/session/{session_id}/next")
    assert empty.status_code == 200, empty.text
    assert empty.json() == {"presentation": None}
    assert_no_provider_import()

    with committed_db() as observer:
        queued = _jobs(observer)
    assert queued, "replenishment job이 없으면 회복될 것도 없다"
    assert {job.job_type for job in queued} == {JobType.GENERATE_SENTENCE_BATCH}

    japanese = "それは仕方ないと思う。"
    provider = RecordingProvider(
        responses=[
            batch_response(sentence_payload(japanese, [item_payload("it0", "仕方ない", japanese)]))
        ]
    )
    turns = 0
    while worker.run_once(
        session_factory=committed_db,
        provider=provider,
        run_job=runner.run_job,
        cfg=cfg,
        now=now,
    ):
        turns += 1
        assert turns <= len(queued), "worker가 대기열을 비우지 않는다"

    # 대상 item이 있는 role은 하나뿐이므로 나머지 job은 provider를 부르지 않는다.
    assert provider.call_count == 1

    refilled = committed_api.client.post(f"/api/study/session/{session_id}/next")

    assert refilled.status_code == 200, refilled.text
    shown = refilled.json()["presentation"]
    assert shown is not None, "worker가 만든 문장이 Ready Pool로 돌아오지 않았다"
    assert shown["japanese"] == japanese


# --------------------------------------------------------------------------
# Scenario F --- target 외 unknown incidental expression 클릭
#
# "click만으로 SRS에 등록되지 않는다 / `몰랐음`·`애매함` explicit 입력 시 learning
# state가 활성화된다 / `알고 있었음`이면 신규 item으로 강제 등록되지 않는다."
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _Incidental:
    view: presentation.PresentationView
    target: LearningItem
    incidental: LearningItem
    sentence_item_id: int


def _show_sentence_with_incidental(
    db: Session, user: User, *, clock: MutableClock, cfg: AppConfig
) -> _Incidental:
    """target 하나 + target이 아닌 tappable 표현 하나가 든 문장을 제시한다.

    candidate를 손으로 만들지 않는다. 문장당 target 수 상한
    (`max_new_items_per_sentence`)을 1로 주입하면 materialization이 첫 item만
    target으로 싣고, 나머지 item은 **화면에는 있지만 학습 target이 아닌**
    incidental 표현이 된다. 상한을 실제로 따르는지까지 함께 보게 된다
    (13_ACCEPTANCE_CRITERIA.md의 `configured max new items per sentence`).
    """
    assert cfg.learning.max_new_items_per_sentence == 1, "이 helper는 상한 1을 전제한다"
    target = factories.make_learning_item(db, lemma="仕事")
    incidental = factories.make_learning_item(db, lemma="任せる")
    sentence = factories.make_ready_sentence(db, [target, incidental])

    session = _start(db, user, now=clock.now(), cfg=cfg)
    view = _next(db, user, session.id, now=clock.now(), cfg=cfg)
    assert view is not None
    assert view.sentence_id == sentence.id
    shown = db.get(StudyPresentation, view.presentation_id)
    assert shown is not None
    assert _target_item_ids(db, candidate_id=shown.candidate_id) == {target.id}
    return _Incidental(
        view=view,
        target=target,
        incidental=incidental,
        sentence_item_id=_sentence_item_id(db, sentence_id=sentence.id, item=incidental),
    )


def test_scenario_f_clicking_an_incidental_item_registers_nothing(db_session: Session) -> None:
    """click은 auxiliary signal이다(02_LEARNING_POLICY.md의 `Incidental Item Click`).

    `clicked = unknown`으로 추론하지 않는다. raw event만 남고 mastery도 FSRS도
    learning state도 생기지 않는다.
    """
    cfg = _cfg(learning={"max_new_items_per_sentence": 1})
    clock = MutableClock()
    user = factories.make_user(db_session)
    shown = _show_sentence_with_incidental(db_session, user, clock=clock, cfg=cfg)

    explanation = _click(
        db_session,
        user,
        shown.view,
        sentence_item_id=shown.sentence_item_id,
        now=clock.now(),
        cfg=cfg,
    )

    assert explanation.learning_item_id == shown.incidental.id
    assert _state_of(db_session, user=user, item=shown.incidental) is None
    assert _mastery_of(db_session, user=user, item=shown.incidental) is None
    learning_state = _learning_state_of(db_session, user=user, item=shown.incidental)
    assert learning_state is None or learning_state.is_active_learning_target is False
    assert len(_events(db_session, user=user, event_type=EventType.ITEM_CLICKED)) == 1


@pytest.mark.parametrize(
    "signal", [ExplicitSignal.UNKNOWN, ExplicitSignal.UNCERTAIN], ids=["unknown", "uncertain"]
)
def test_scenario_f_an_explicit_gap_activates_the_incidental_item(
    db_session: Session, signal: ExplicitSignal
) -> None:
    """`몰랐음` / `애매함`이 그때서야 학습 target으로 승격시킨다.

    승격됐으므로 이번에는 FSRS 스케줄도 함께 생긴다 --- 사용자가 모른다고 말한
    표현은 복습 대상이다.
    """
    cfg = _cfg(learning={"max_new_items_per_sentence": 1})
    clock = MutableClock()
    user = factories.make_user(db_session)
    shown = _show_sentence_with_incidental(db_session, user, clock=clock, cfg=cfg)
    _click(
        db_session,
        user,
        shown.view,
        sentence_item_id=shown.sentence_item_id,
        now=clock.now(),
        cfg=cfg,
    )

    _report(
        db_session,
        user,
        shown.view,
        sentence_item_id=shown.sentence_item_id,
        signal=signal,
        now=clock.now(),
        cfg=cfg,
    )

    learning_state = _learning_state_of(db_session, user=user, item=shown.incidental)
    assert learning_state is not None
    assert learning_state.is_active_learning_target is True
    mastery = _mastery_of(db_session, user=user, item=shown.incidental)
    assert mastery is not None
    assert mastery.comprehension_mastery == pytest.approx(
        ema(None, OBSERVATION[signal], cfg.learning.mastery_ema_alpha)
    )
    state = _state_of(db_session, user=user, item=shown.incidental)
    assert state is not None
    assert state.reps == 1
    # 그 문장이 이 item의 최초 학습 문맥으로 남는다(07_SRS_SPEC.md의
    # `anchor_sentence_id 지정` 1번). 이것이 없으면 anchor가 `sentences.id ASC`로
    # 뽑힌 낯선 문장이 되고 사용자가 실제로 물어본 문맥이 사라진다.
    assert learning_state.anchor_sentence_id == shown.view.sentence_id

    # 이 presentation은 이 item의 exposure를 만들지 않는다 --- target이 아니기
    # 때문이다(07_SRS_SPEC.md의 `target item의 canonical 정의`). 그래서 ladder도
    # 움직이지 않는다.
    _complete(db_session, user, shown.view.presentation_id, now=clock.now(), cfg=cfg)
    assert _exposures(db_session, user=user, item=shown.incidental) == []
    assert learning_state.context_stage is ContextStage.ANCHOR
    assert len(_exposures(db_session, user=user, item=shown.target)) == 1


def test_scenario_f_the_promoted_item_returns_as_new_in_the_same_sentence(
    db_session: Session,
) -> None:
    """승격된 item의 첫 제시는 `new`이고 문장은 **사용자가 물어본 그 문장**이다.

    이것이 좁은 target 정의의 대가를 상쇄한다(ADR-013의 (D)). 최초 문맥은 5회
    중 1회로 정상 계상되며 시점만 한 presentation 뒤로 밀린다. 게다가 이때의
    재제시는 그냥 반복이 아니라 "이제 target으로서 설명·probe 대상이 되는" 제시다.

    `review` pool이 아니라 `new` pool이 가져간다는 점도 함께 고정한다. 승격이
    만든 `review_states` 행을 기준으로 삼던 옛 정의로는 이 pool이 항상 비었다.
    """
    cfg = _cfg(learning={"max_new_items_per_sentence": 1})
    clock = MutableClock()
    user = factories.make_user(db_session)
    shown = _show_sentence_with_incidental(db_session, user, clock=clock, cfg=cfg)
    _report(
        db_session,
        user,
        shown.view,
        sentence_item_id=shown.sentence_item_id,
        signal=ExplicitSignal.UNKNOWN,
        now=clock.now(),
        cfg=cfg,
    )
    _complete(db_session, user, shown.view.presentation_id, now=clock.now(), cfg=cfg)
    first_row = db_session.get(StudyPresentation, shown.view.presentation_id)
    assert first_row is not None
    _finish(db_session, user, first_row.study_session_id, now=clock.now(), cfg=cfg)

    session = _start(db_session, user, now=clock.advance(timedelta(minutes=1)), cfg=cfg)
    view = _next(db_session, user, session.id, now=clock.now(), cfg=cfg)

    assert view is not None
    assert view.presentation_role is PresentationRole.NEW
    assert view.sentence_id == shown.view.sentence_id
    assert view.context_stage is ContextStage.ANCHOR
    row = db_session.get(StudyPresentation, view.presentation_id)
    assert row is not None
    assert _target_item_ids(db_session, candidate_id=row.candidate_id) == {shown.incidental.id}

    # 그 제시가 닫히면 최초 문맥이 1회로 계상되고 ladder가 비로소 움직인다.
    _complete(db_session, user, view.presentation_id, now=clock.now(), cfg=cfg)
    assert len(_exposures(db_session, user=user, item=shown.incidental)) == 1
    learning_state = _learning_state_of(db_session, user=user, item=shown.incidental)
    assert learning_state is not None
    assert learning_state.context_stage is ContextStage.NEAR_ORIGINAL


def test_scenario_f_known_never_forces_a_new_srs_item(db_session: Session) -> None:
    """`알고 있었음`은 신규 item을 SRS에 밀어 넣지 않는다(02_LEARNING_POLICY.md).

    이미 아는 표현까지 복습 큐에 넣으면 큐가 사용자가 아는 것으로 채워진다.
    mastery는 그래도 갱신한다 --- 사용자가 말한 것은 그 자체로 evidence다.
    두 결과가 함께 있어야 이 시나리오다.
    """
    cfg = _cfg(learning={"max_new_items_per_sentence": 1})
    clock = MutableClock()
    user = factories.make_user(db_session)
    shown = _show_sentence_with_incidental(db_session, user, clock=clock, cfg=cfg)
    _click(
        db_session,
        user,
        shown.view,
        sentence_item_id=shown.sentence_item_id,
        now=clock.now(),
        cfg=cfg,
    )

    _report(
        db_session,
        user,
        shown.view,
        sentence_item_id=shown.sentence_item_id,
        signal=ExplicitSignal.KNOWN,
        now=clock.now(),
        cfg=cfg,
    )

    assert _state_of(db_session, user=user, item=shown.incidental) is None
    learning_state = _learning_state_of(db_session, user=user, item=shown.incidental)
    assert learning_state is None or learning_state.is_active_learning_target is False
    mastery = _mastery_of(db_session, user=user, item=shown.incidental)
    assert mastery is not None
    assert mastery.comprehension_mastery == pytest.approx(
        ema(None, OBSERVATION[ExplicitSignal.KNOWN], cfg.learning.mastery_ema_alpha)
    )


# --------------------------------------------------------------------------
# Scenario G --- probe를 계속 skip
#
# "mastery 변화가 없다 / 같은 item을 즉시 다시 묻지 않는다 /
# `probe_skip_cooldown_days`가 적용된다."
# --------------------------------------------------------------------------


def _item_with_sentence(db: Session, *, lemma: str) -> LearningItem:
    return factories.make_learning_item(db, lemma=lemma)


def _make_due(
    db: Session, user: User, item: LearningItem, *, cfg: AppConfig, now: datetime, due_at: datetime
) -> ReviewState:
    """복습 중이지만 아직 explicit evidence가 없는 item. probe 1순위 대상이 된다."""
    state = _schedule(db, user, item, cfg=cfg, now=now)
    state.next_review_at = due_at
    db.flush()
    return state


def _probe_of(
    db: Session, user: User, view: presentation.PresentationView
) -> presentation.ProbeView:
    assert view.probe is not None, "이 presentation에 probe가 실려야 한다"
    return view.probe


def test_scenario_g_skipping_a_probe_changes_no_learning_state(db_session: Session) -> None:
    """skip은 mastery evidence도 FSRS grade도 아니다(02_LEARNING_POLICY.md의 `Skip`).

    남는 것은 "물어봤다"는 사실뿐이다. cooldown을 넘겨 다시 물어도 계속 skip할 수
    있어야 하고, 그동안 mastery와 FSRS는 그대로여야 한다.
    """
    cooldown_days = get_config().learning.probe_skip_cooldown_days
    cfg = _cfg(
        learning={"probe_min_gap_presentations": 1, "probe_skip_cooldown_days": cooldown_days}
    )
    clock = MutableClock()
    user = factories.make_user(db_session)
    opening_item = _item_with_sentence(db_session, lemma="opening")
    probed = _item_with_sentence(db_session, lemma="probed")
    # 스케줄보다 첫 제시가 먼저다. exposure 0건인 item은 `review` pool에 들어가지
    # 않고(ADR-013), 스케줄이 없는 동안의 무신호 제시는 deferral도 만들지 않는다.
    for item in (opening_item, probed):
        factories.make_ready_sentence(db_session, [item])
        _first_exposure(db_session, user, item, clock=clock, cfg=cfg)
    _make_due(
        db_session,
        user,
        opening_item,
        cfg=cfg,
        now=clock.now(),
        due_at=clock.now() - timedelta(days=2),
    )
    _make_due(
        db_session,
        user,
        probed,
        cfg=cfg,
        now=clock.now(),
        due_at=clock.now() - timedelta(days=1),
    )
    state = _state_of(db_session, user=user, item=probed)
    assert state is not None
    baseline = tuple(getattr(state, column) for column in (*MEMORY_COLUMNS, "next_review_at"))

    for round_index in range(SKIP_ROUNDS):
        session = _start(db_session, user, now=clock.now(), cfg=cfg)
        opening = _next(db_session, user, session.id, now=clock.now(), cfg=cfg)
        assert opening is not None
        assert opening.probe is None, "세션 첫 문장에는 probe를 싣지 않는다(간격 규칙)"
        opening_row = db_session.get(StudyPresentation, opening.presentation_id)
        assert opening_row is not None
        assert _target_item_ids(db_session, candidate_id=opening_row.candidate_id) == {
            opening_item.id
        }
        _complete(db_session, user, opening.presentation_id, now=clock.now(), cfg=cfg)

        view = _next(db_session, user, session.id, now=clock.now(), cfg=cfg)
        assert view is not None
        probe = _probe_of(db_session, user, view)
        assert probe.learning_item_id == probed.id

        skipped_at = clock.advance(timedelta(seconds=10))
        result = interactions.respond_to_probe(
            db_session,
            user_id=user.id,
            presentation_id=view.presentation_id,
            probe_id=probe.probe_id,
            signal=None,
            client_event_id=uuid.uuid4(),
            now=skipped_at,
            cfg=cfg,
        )
        assert result.signal is None

        learning_state = _learning_state_of(db_session, user=user, item=probed)
        assert learning_state is not None
        assert learning_state.probe_skip_count == round_index + 1
        assert learning_state.last_probe_at == skipped_at
        assert _mastery_of(db_session, user=user, item=probed) is None
        assert (
            tuple(getattr(state, column) for column in (*MEMORY_COLUMNS, "next_review_at"))
            == baseline
        )

        _complete(db_session, user, view.presentation_id, now=clock.now(), cfg=cfg)
        _finish(db_session, user, session.id, now=clock.now(), cfg=cfg)
        # cooldown을 넘겨야 같은 item을 다시 묻는다. 그 전이었다면 다음 round의
        # probe 대상이 이 item이 아니고 위의 단정이 깨진다.
        clock.advance(timedelta(days=cooldown_days))

    learning_state = _learning_state_of(db_session, user=user, item=probed)
    assert learning_state is not None
    assert learning_state.probe_skip_count == SKIP_ROUNDS


def test_scenario_g_the_skip_cooldown_keeps_the_item_out_until_it_expires(
    db_session: Session,
) -> None:
    """`probe_skip_cooldown_days` 안에서는 같은 item을 다시 묻지 않는다.

    주입한 cooldown으로 확인한다. 경계는 포함이다 --- 정확히 cooldown이 지난
    순간은 다시 물을 수 있다.
    """
    cooldown_days = get_config().learning.probe_skip_cooldown_days + 1
    cfg = _cfg(learning={"probe_skip_cooldown_days": cooldown_days})
    clock = MutableClock()
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    factories.make_learning_state(db_session, user, item, last_probe_at=clock.now())
    study = factories.make_study_session(
        db_session, user, target_minutes=cfg.learning.default_session_minutes
    )

    def _target_now() -> int | None:
        chosen = select_probe_target(
            db_session,
            user_id=user.id,
            study_session_id=study.id,
            target_item_ids=[item.id],
            now=clock.now(),
            config=cfg,
        )
        return None if chosen is None else chosen.learning_item_id

    clock.advance(timedelta(days=cooldown_days) - timedelta(seconds=1))
    assert _target_now() is None

    clock.advance(timedelta(seconds=1))
    assert _target_now() == item.id


def test_scenario_g_a_session_never_exceeds_the_probe_budget(db_session: Session) -> None:
    """`mastery_probe_target_per_session_max`를 넘겨 묻지 않는다.

    min은 강제하지 않는다 --- 후보가 없어 `..._min`에 못 미치는 것은 실패가 아니다
    (06_LEARNING_ENGINE.md의 `Probe Pacing`). 여기서 보는 것은 상한뿐이다.
    """
    budget = 1
    cfg = _cfg(
        learning={
            "mastery_probe_target_per_session_max": budget,
            "mastery_probe_target_per_session_min": budget,
            "probe_min_gap_presentations": 1,
        }
    )
    clock = MutableClock()
    user = factories.make_user(db_session)
    presentations = budget + 3
    for index in range(presentations):
        item = factories.make_learning_item(db_session, lemma=f"probe{index}")
        factories.make_ready_sentence(db_session, [item])

    session = _start(db_session, user, now=clock.now(), cfg=cfg)
    shown = 0
    for _ in range(presentations):
        view = _next(db_session, user, session.id, now=clock.now(), cfg=cfg)
        if view is None:
            break
        shown += 1
        clock.advance(timedelta(seconds=30))
        _complete(db_session, user, view.presentation_id, now=clock.now(), cfg=cfg)

    probes = _events(db_session, user=user, event_type=EventType.MASTERY_PROBE_SHOWN)
    assert shown > budget, "상한이 실제로 걸리려면 제시 수가 상한보다 많아야 한다"
    assert len(probes) <= cfg.learning.mastery_probe_target_per_session_max
    assert len(probes) == budget


# --------------------------------------------------------------------------
# Scenario H --- 사용자가 `unnatural` flag
#
# "candidate/sentence가 quarantined된다 / 향후 selection에서 제외된다 / 해당
# content에서 파생된 negative mastery evidence를 무효화할 수 있다."
# --------------------------------------------------------------------------


def test_scenario_h_flagged_content_is_quarantined_and_never_selected_again(
    db_session: Session,
) -> None:
    """flag는 즉시 quarantine이다(10_ERROR_HANDLING.md, 불변식 #7).

    확인하는 것은 넷이다.

    ``` text
    sentences.status                     -> quarantined
    그 문장의 모든 candidate             -> quarantined (다른 사용자 것도)
    그 presentation의 item_exposures     -> invalidated_at
    review_states.meaningful_exposure_count  -> 유효 건수로 재계산
    ```

    그리고 이후 `/next`를 여러 번 호출해도 그 문장은 한 번도 나오지 않아야 한다.
    """
    cfg = _cfg()
    clock = MutableClock()
    user = factories.make_user(db_session)
    other = factories.make_user(db_session)
    flagged_item = factories.make_learning_item(db_session, lemma="flagged")
    flagged_sentence = factories.make_ready_sentence(db_session, [flagged_item])
    # `몰랐음`으로 학습 target이 된 item이다. 아직 target으로 제시된 적이 없으므로
    # 첫 제시는 `new`이고 문장은 anchor다(ADR-013). 이 전제가 없으면 그 item은
    # 어느 pool에도 속하지 않아 flag할 문장 자체가 나오지 않는다.
    #
    # 굶주림 주의: `is_active_learning_target = True`이면서 exposure가 이미 1건 이상
    # 붙은 item에 `review_states`가 없으면 세 pool 어디에도 못 들어간다. 여기서는
    # 바로 아래에서 스케줄을 만들어 그 조합을 피한다. 프로덕션에서는 승격이 항상 FSRS
    # 기록을 동반해 도달할 수 없지만, `interactions._apply_explicit_evidence`의 기록
    # 조건이 완화되면 실제 굶주림이 된다.
    factories.make_learning_state(db_session, user, flagged_item, is_active_learning_target=True)
    factories.make_mastery(
        db_session,
        user,
        flagged_item,
        comprehension_mastery=OBSERVATION[ExplicitSignal.UNKNOWN],
        algorithm_version="scenario-h",
    )
    state = _schedule(db_session, user, flagged_item, cfg=cfg, now=clock.now())
    state.next_review_at = clock.now() - timedelta(days=1)
    db_session.flush()
    for index in range(SELECTION_ATTEMPTS):
        spare = factories.make_learning_item(db_session, lemma=f"spare{index}")
        factories.make_ready_sentence(db_session, [spare])

    session = _start(db_session, user, now=clock.now(), cfg=cfg)
    view = _next(db_session, user, session.id, now=clock.now(), cfg=cfg)
    assert view is not None
    assert view.sentence_id == flagged_sentence.id
    _complete(db_session, user, view.presentation_id, now=clock.now(), cfg=cfg)
    assert state.meaningful_exposure_count == 1

    # 다른 사용자의 Ready Pool에도 같은 문장의 candidate가 있다. sentences는 global
    # content이므로 신고한 사람만 격리하면 남의 pool에 quarantine된 문장이 남는다.
    materialize_candidates(db_session, user=other, now=clock.now(), cfg=cfg.learning)
    other_candidates = db_session.execute(
        sa.select(UserSentenceCandidate).where(
            UserSentenceCandidate.user_id == other.id,
            UserSentenceCandidate.sentence_id == flagged_sentence.id,
        )
    ).scalars()
    assert [candidate.status for candidate in other_candidates] == [CandidateStatus.READY]

    flagged_at = clock.advance(timedelta(minutes=1))
    content_flag.flag_content(
        db_session,
        user_id=user.id,
        presentation_id=view.presentation_id,
        reason=ContentFlagReason.UNNATURAL,
        note=None,
        client_event_id=uuid.uuid4(),
        now=flagged_at,
        cfg=cfg,
    )

    sentence = db_session.get(Sentence, flagged_sentence.id)
    assert sentence is not None and sentence.status is SentenceStatus.QUARANTINED
    live = db_session.execute(
        sa.select(UserSentenceCandidate).where(
            UserSentenceCandidate.sentence_id == flagged_sentence.id,
            UserSentenceCandidate.status.in_(
                (CandidateStatus.QUEUED, CandidateStatus.READY, CandidateStatus.SHOWN)
            ),
        )
    ).scalars()
    assert list(live) == []
    (exposure,) = _exposures(db_session, user=user, item=flagged_item)
    assert exposure.invalidated_at == flagged_at
    assert count_valid_exposures(db_session, user_id=user.id, learning_item_id=flagged_item.id) == 0
    assert state.meaningful_exposure_count == 0

    seen: list[int] = []
    for _ in range(SELECTION_ATTEMPTS):
        clock.advance(timedelta(minutes=1))
        following = _next(db_session, user, session.id, now=clock.now(), cfg=cfg)
        if following is None:
            break
        seen.append(following.sentence_id)
        _complete(db_session, user, following.presentation_id, now=clock.now(), cfg=cfg)

    assert seen, "격리 이후에도 보여줄 문장이 있어야 이 단정에 의미가 있다"
    assert flagged_sentence.id not in seen
