"""`EXPLAIN_ITEM` / `GENERATE_REVIEW_CONTEXT` enqueue 트리거 (09_BACKGROUND_JOBS.md).

handler가 있어도 job을 만드는 쪽이 없으면 그 handler는 영원히 실행되지 않는다. 그래서
이 파일의 단정은 "job row가 생겼는가"이고, 마지막 하나는 그 job이 실제로 처리되면 그
문장이 **ready가 되는가**까지 본다(end-to-end).

트리거 지점은 materialization(L1)이고 enqueue는 `app/jobs/`(L2)다. L1은 L2를 import할
수 없으므로(ADR-015) materialization은 사실만 `MaterializationGaps`로 올리고
`services/`가 enqueue한다. 그래서 여기서는 `materialize_candidates`를 직접 부르지 않고
**service 진입점**을 부른다 --- gap 수집만 되고 enqueue가 빠진 구현이 통과하면 안 된다.

`provider를 부르지 않는다`(불변식 #1)는 request 경로의 단정이고, 마지막 e2e만 worker를
돌린다.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from datetime import timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from app.config import AppConfig, get_config
from app.jobs import runner, worker
from app.learning.exposure import count_valid_exposures
from app.learning.selection import has_ready_sentence
from app.llm.prompts import explain_item as explain_item_prompt
from app.models.content import LearningItem, Sentence, SentenceItem
from app.models.enums import (
    CandidateStatus,
    ContextStage,
    GenerationJobStatus,
    JobType,
    LlmTaskType,
    PresentationRole,
    ReviewReason,
    SentenceStatus,
)
from app.models.jobs import GenerationJob
from app.models.learning import UserItemLearningState
from app.models.user import User
from app.services import study_session as study_session_service
from tests import factories
from tests.clock import MutableClock
from tests.conftest import StudyApi, assert_no_provider_import, no_outbound_network, override_config
from tests.llm_fixtures import explanation_payload
from tests.provider_double import RecordingProvider

EXPLAIN_ITEM = JobType.EXPLAIN_ITEM
REVIEW_CONTEXT = JobType.GENERATE_REVIEW_CONTEXT

FSRS_PARAMS_VERSION_FILLER = "test"
FSRS_STATE_FILLER = 1


# --------------------------------------------------------------------------
# fixture / helper
# --------------------------------------------------------------------------


@pytest.fixture
def cfg() -> AppConfig:
    return get_config()


@pytest.fixture
def committed_session(committed_db: sessionmaker[Session]) -> Iterator[Session]:
    with committed_db() as session:
        yield session


def _sentence_with(
    db: Session,
    *,
    explained: Sequence[LearningItem] = (),
    unexplained: Sequence[LearningItem] = (),
) -> tuple[Sentence, list[SentenceItem]]:
    """surface를 이어 붙여 문장을 만들고 span을 그 위치로 둔다.

    `unexplained` item에는 validated explanation을 두지 않는다. 그 하나 때문에 문장 전체가
    Ready invariant를 만족하지 못하고 materialization이 건너뛴다 --- 범위는 target item이
    아니라 그 문장의 **모든** tappable item이다(06_LEARNING_ENGINE.md).
    """
    items = [*explained, *unexplained]
    sentence = factories.make_sentence(db, japanese="".join(item.lemma for item in items))
    sentence_items = []
    cursor = 0
    for item in items:
        sentence_item = factories.make_sentence_item(db, sentence, item, surface_form=item.lemma)
        factories.make_span(db, sentence_item, start=cursor, end=cursor + len(item.lemma))
        if item in explained:
            factories.make_explanation(db, sentence_item)
        sentence_items.append(sentence_item)
        cursor += len(item.lemma)
    return sentence, sentence_items


def _review_item_stuck_at(
    db: Session,
    user: User,
    item: LearningItem,
    *,
    stage: ContextStage,
    now: MutableClock,
) -> Sentence:
    """그 stage에 맞는 미노출 문장이 없는 review item 하나를 만든다.

    `varied`는 "anchor가 아니고 아직 노출되지 않은 문장"을 요구한다. anchor 하나뿐이고
    그것이 이미 제시됐으면 조건을 만족하는 문장이 없다 --- `GENERATE_REVIEW_CONTEXT`의
    트리거 지점이다. 노출을 실제로 밟지 않고 세우는 이유는 stage가 이미 ladder 뒤쪽에
    도달한 item이 전제이기 때문이다(`factories.make_learning_state`의 주의).
    """
    anchor = factories.make_ready_sentence(db, [item])
    db.add(
        UserItemLearningState(
            user_id=user.id,
            learning_item_id=item.id,
            context_stage=stage,
            anchor_sentence_id=anchor.id,
            is_active_learning_target=True,
            updated_at=factories.NOW,
        )
    )
    review_state = factories.make_review_state(
        db, user, item, state=FSRS_STATE_FILLER, params_version=FSRS_PARAMS_VERSION_FILLER
    )
    review_state.next_review_at = now.now() - timedelta(days=1)

    # exposure 1건이 있어야 그 item이 `new`가 아니라 `review` pool의 몫이다(ADR-013).
    study = factories.make_study_session(
        db, user, target_minutes=get_config().learning.default_session_minutes
    )
    candidate = factories.make_candidate(
        db,
        user,
        anchor,
        status=CandidateStatus.CONSUMED,
        presentation_role=PresentationRole.REVIEW,
    )
    presentation = factories.make_presentation(
        db,
        user,
        study,
        candidate,
        anchor,
        presentation_role=PresentationRole.REVIEW,
        review_reason=ReviewReason.FSRS_DUE,
        completed_at=now.now(),
    )
    factories.make_exposure(db, user, item, presentation, anchor)
    db.flush()
    return anchor


def _jobs(db: Session, *, job_type: JobType | None = None) -> list[GenerationJob]:
    statement = sa.select(GenerationJob).order_by(GenerationJob.id)
    if job_type is not None:
        statement = statement.where(GenerationJob.job_type == job_type)
    return list(db.execute(statement).scalars().all())


def _start_session(db: Session, user: User, *, now: MutableClock, cfg: AppConfig) -> int:
    """`POST /api/study/session`의 service 진입점. materialization을 1회 돌린다."""
    started = study_session_service.start_or_resume(db, user=user, now=now.now(), cfg=cfg)
    return started.session.id


# --------------------------------------------------------------------------
# EXPLAIN_ITEM
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_a_sentence_skipped_for_a_missing_explanation_orders_one(
    db_session: Session, study_clock: MutableClock, cfg: AppConfig
) -> None:
    """건너뛴 문장의 누락 `sentence_item`마다 1건. key는 `explain:{id}:{UTC 날짜}`다."""
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    _, (sentence_item,) = _sentence_with(db_session, unexplained=[item])

    _start_session(db_session, user, now=study_clock, cfg=cfg)

    (job,) = _jobs(db_session, job_type=EXPLAIN_ITEM)
    assert job.payload_json == {"sentence_item_id": sentence_item.id}
    assert job.idempotency_key == f"explain:{sentence_item.id}:{study_clock.now():%Y-%m-%d}"
    assert job.status is GenerationJobStatus.QUEUED
    assert job.next_attempt_at == study_clock.now()
    assert job.created_at == study_clock.now()
    assert job.max_attempts == cfg.jobs.max_job_attempts


@pytest.mark.integration
def test_only_the_items_without_an_explanation_are_ordered(
    db_session: Session, study_clock: MutableClock, cfg: AppConfig
) -> None:
    """이미 설명이 있는 item에 job을 만들지 않는다. 그것은 순수한 provider 비용이다."""
    user = factories.make_user(db_session)
    explained = factories.make_learning_item(db_session, lemma="任せる")
    missing = factories.make_learning_item(db_session, lemma="預ける")
    _, (_, missing_item) = _sentence_with(db_session, explained=[explained], unexplained=[missing])

    _start_session(db_session, user, now=study_clock, cfg=cfg)

    assert [job.payload_json for job in _jobs(db_session, job_type=EXPLAIN_ITEM)] == [
        {"sentence_item_id": missing_item.id}
    ]


@pytest.mark.integration
def test_the_same_sentence_item_is_ordered_once_a_day(
    db_session: Session, study_clock: MutableClock, cfg: AppConfig
) -> None:
    """억제 창 안에서는 몇 번을 검사해도 job 1건이다. `ON CONFLICT DO NOTHING`."""
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    _sentence_with(db_session, unexplained=[item])

    _start_session(db_session, user, now=study_clock, cfg=cfg)
    study_clock.advance(timedelta(minutes=5))
    _start_session(db_session, user, now=study_clock, cfg=cfg)

    assert len(_jobs(db_session, job_type=EXPLAIN_ITEM)) == 1


@pytest.mark.integration
def test_a_ready_sentence_orders_nothing(
    db_session: Session, study_clock: MutableClock, cfg: AppConfig
) -> None:
    """검사한 문장이 invariant를 만족하면 아무것도 주문하지 않는다."""
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    factories.make_ready_sentence(db_session, [item])

    _start_session(db_session, user, now=study_clock, cfg=cfg)

    assert _jobs(db_session) == []


@pytest.mark.integration
def test_an_unexamined_sentence_is_not_ordered(
    db_session: Session, study_clock: MutableClock, cfg: AppConfig
) -> None:
    """이번 실행에서 **검사한 문장만** 대상이다. 누락 explanation을 찾겠다고 corpus
    전체를 훑지 않는다(09_BACKGROUND_JOBS.md)."""
    user = factories.make_user(db_session)
    examined = factories.make_learning_item(db_session, lemma="任せる")
    factories.make_ready_sentence(db_session, [examined])

    # 이 문장의 item은 이번 실행의 어떤 role 대상도 아니다: 최근에 노출됐으므로
    # exploration 후보 조건 3을 만족하지 않고, `review_states`도 학습 상태도 없어
    # review/new pool에도 들지 않는다.
    untouched = factories.make_learning_item(db_session, lemma="預ける")
    _sentence_with(db_session, unexplained=[untouched])
    seen = factories.make_ready_sentence(db_session, [untouched])
    study = factories.make_study_session(
        db_session, user, target_minutes=cfg.learning.default_session_minutes
    )
    candidate = factories.make_candidate(db_session, user, seen, status=CandidateStatus.CONSUMED)
    presentation = factories.make_presentation(db_session, user, study, candidate, seen)
    factories.make_exposure(db_session, user, untouched, presentation, seen)
    db_session.flush()

    _start_session(db_session, user, now=study_clock, cfg=cfg)

    assert _jobs(db_session, job_type=EXPLAIN_ITEM) == []


# --------------------------------------------------------------------------
# GENERATE_REVIEW_CONTEXT
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_a_stage_without_a_sentence_orders_one_review_context(
    db_session: Session, study_clock: MutableClock, cfg: AppConfig
) -> None:
    """`(item, stage)` 하나당 1건이고 stage와 anchor가 payload에 실린다."""
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    anchor = _review_item_stuck_at(
        db_session, user, item, stage=ContextStage.VARIED, now=study_clock
    )

    _start_session(db_session, user, now=study_clock, cfg=cfg)

    (job,) = _jobs(db_session, job_type=REVIEW_CONTEXT)
    assert job.payload_json == {
        "user_id": user.id,
        "learning_item_id": item.id,
        "context_stage": ContextStage.VARIED.value,
        "anchor_sentence_id": anchor.id,
    }
    assert job.idempotency_key == (
        f"review_ctx:{user.id}:{item.id}:varied:{study_clock.now():%Y-%m-%d}"
    )
    assert job.status is GenerationJobStatus.QUEUED
    assert job.next_attempt_at == study_clock.now()
    assert job.max_attempts == cfg.jobs.max_job_attempts


@pytest.mark.integration
def test_the_same_item_and_stage_are_ordered_once_a_day(
    db_session: Session, study_clock: MutableClock, cfg: AppConfig
) -> None:
    """세션을 두 번 열어도 job 1건이다. `ON CONFLICT DO NOTHING`."""
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    _review_item_stuck_at(db_session, user, item, stage=ContextStage.VARIED, now=study_clock)

    _start_session(db_session, user, now=study_clock, cfg=cfg)
    study_clock.advance(timedelta(minutes=5))
    _start_session(db_session, user, now=study_clock, cfg=cfg)

    assert len(_jobs(db_session, job_type=REVIEW_CONTEXT)) == 1


@pytest.mark.integration
def test_a_quarantined_anchor_orders_no_review_context(
    db_session: Session, study_clock: MutableClock, cfg: AppConfig
) -> None:
    """불변식 #7. 격리된 anchor를 기준으로 만든 문맥은 그 자체가 오염된 문맥이다.

    handler도 그 경우를 끝내지만 job 하나가 attempt와 지표를 그대로 소모한다. anchor
    재지정은 request 경로의 소관이다.
    """
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    anchor = _review_item_stuck_at(
        db_session, user, item, stage=ContextStage.VARIED, now=study_clock
    )
    anchor.status = SentenceStatus.QUARANTINED
    db_session.flush()

    _start_session(db_session, user, now=study_clock, cfg=cfg)

    assert _jobs(db_session, job_type=REVIEW_CONTEXT) == []


@pytest.mark.integration
def test_an_item_without_any_anchor_orders_no_review_context(
    db_session: Session, study_clock: MutableClock, cfg: AppConfig
) -> None:
    """쓸 문장이 **아예 없는** 경우는 이 job이 아니라 Pool Fallback 3단계의 몫이다.

    payload의 `anchor_sentence_id`를 채울 수 없고, 채운다 해도 anchor 없이 만든 "그
    anchor와 다른 상황"은 요청 자체가 성립하지 않는다(06_LEARNING_ENGINE.md의 두 job
    경계).
    """
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    db_session.add(
        UserItemLearningState(
            user_id=user.id,
            learning_item_id=item.id,
            context_stage=ContextStage.ANCHOR,
            anchor_sentence_id=None,
            is_active_learning_target=True,
            updated_at=factories.NOW,
        )
    )
    review_state = factories.make_review_state(
        db_session, user, item, state=FSRS_STATE_FILLER, params_version=FSRS_PARAMS_VERSION_FILLER
    )
    review_state.next_review_at = study_clock.now() - timedelta(days=1)
    db_session.flush()

    _start_session(db_session, user, now=study_clock, cfg=cfg)

    assert _jobs(db_session, job_type=REVIEW_CONTEXT) == []


# --------------------------------------------------------------------------
# request 경로 (불변식 #1)
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_the_request_path_enqueues_without_touching_a_provider(
    study_api: StudyApi, db_session: Session
) -> None:
    """두 job을 만드는 요청도 소켓을 열지 않고 provider SDK를 끌어오지 않는다."""
    user = study_api.user
    missing = factories.make_learning_item(db_session, lemma="任せる")
    _sentence_with(db_session, unexplained=[missing])
    stuck = factories.make_learning_item(db_session, lemma="預ける")
    _review_item_stuck_at(
        db_session, user, stuck, stage=ContextStage.NEW_CONTEXT, now=study_api.clock
    )

    with no_outbound_network():
        started = study_api.client.post("/api/study/session")
        assert started.status_code == 200, started.text
        session_id = started.json()["session"]["session_id"]
        following = study_api.client.post(f"/api/study/session/{session_id}/next")
        assert following.status_code == 200, following.text

    assert_no_provider_import()
    assert {job.job_type for job in _jobs(db_session)} >= {EXPLAIN_ITEM, REVIEW_CONTEXT}


# --------------------------------------------------------------------------
# `/next` 경로의 트리거 (`services/presentation.py`)
#
# enqueue 지점은 **둘**이다: 세션 시작(`services/study_session._materialize`)과
# `/next`(`services/presentation.next_presentation`). 위의 테스트들은 전부 앞쪽만
# 밟으므로, 뒤쪽 호출을 지워도 전부 통과한다 --- 그 회귀를 잡는 것이 아래 하나다.
# --------------------------------------------------------------------------


def _review_item_with_a_sentence_for(
    db: Session,
    user: User,
    item: LearningItem,
    *,
    stage: ContextStage,
    now: MutableClock,
    cfg: AppConfig,
) -> tuple[Sentence, Sentence]:
    """그 stage에 맞는 문장이 **있는** review item. `_review_item_stuck_at`의 반대다.

    전제가 "이미 ladder 뒤쪽에 도달했고 그 stage의 문맥이 아직 남아 있는 item"이므로
    stage와 첫 노출을 factory로 세운다(`factories.make_learning_state`의 주의). 그
    상태에서 materialization은 gap을 올리지 않는다 --- 이 테스트의 전제가 그것이고
    아래에서 단정한다.
    """
    anchor = factories.make_ready_sentence(db, [item], surfaces=["それは君に任せる。"])
    spare = factories.make_ready_sentence(db, [item], surfaces=["今日は全部君に任せる。"])
    factories.make_learning_state(
        db,
        user,
        item,
        context_stage=stage,
        is_active_learning_target=True,
        anchor_sentence_id=anchor.id,
    )
    review_state = factories.make_review_state(
        db, user, item, state=FSRS_STATE_FILLER, params_version=FSRS_PARAMS_VERSION_FILLER
    )
    review_state.next_review_at = now.now() - timedelta(days=1)

    # 유효 exposure 1건이 있어야 그 item이 `new`가 아니라 `review` pool의 몫이다(ADR-013).
    study = factories.make_study_session(
        db, user, target_minutes=cfg.learning.default_session_minutes
    )
    candidate = factories.make_candidate(
        db,
        user,
        anchor,
        status=CandidateStatus.CONSUMED,
        presentation_role=PresentationRole.REVIEW,
    )
    presentation = factories.make_presentation(
        db,
        user,
        study,
        candidate,
        anchor,
        presentation_role=PresentationRole.REVIEW,
        review_reason=ReviewReason.FSRS_DUE,
        completed_at=now.now(),
    )
    factories.make_exposure(db, user, item, presentation, anchor)
    db.flush()
    return anchor, spare


@pytest.mark.integration
def test_a_gap_that_only_appears_mid_session_is_still_ordered_from_next(
    study_api: StudyApi, db_session: Session
) -> None:
    """세션 시작에는 없었고 `/next`에서 생긴 gap도 job이 된다.

    `services/presentation.py`의 enqueue는 세션 시작의 것과 **별개 호출**이다. 그
    한 줄이 지워져도 위의 모든 트리거 테스트가 통과한다 --- 그것들은 세션 시작
    경로만 밟고, 유일하게 `/next`를 포함하는
    `test_the_request_path_enqueues_without_touching_a_provider`는 집합 비교(`>=`)라
    세션 시작이 이미 만든 job으로 충족된다. 그래서 여기서는 **정확한 증가분**을 본다.

    gap이 세션 중간에 생기는 경로는 stage 전이다. `varied`의 문맥이 남아 있으면
    materialization은 gap을 올리지 않는다. 그 문장을 제시하고 닫으면 (a) 무신호
    노출이 ladder를 한 칸 올리고 (b) 그 문장은 제시된 것이 되어, 새 stage에 맞는
    미노출 문장이 0건이 된다 --- 그 사실을 보고할 기회는 다음 `/next` 뿐이다.

    `minimum_meaningful_exposures`를 주입하는 이유는 노출 수를 그 아래로 두어 review
    reason이 계속 살아 있게 만드는 것이 전제이기 때문이다. 전제 자체를 아래에서
    단정한다 --- 그러지 않으면 정책값이 바뀌는 순간 이 테스트가 아무것도 검사하지
    않게 된다.
    """
    cfg = override_config(get_config(), learning={"minimum_meaningful_exposures": 8})
    study_api.use_config(cfg)
    user = study_api.user
    item = factories.make_learning_item(db_session, lemma="任せる")
    anchor, _spare = _review_item_with_a_sentence_for(
        db_session, user, item, stage=ContextStage.VARIED, now=study_api.clock, cfg=cfg
    )

    started = study_api.client.post("/api/study/session")
    assert started.status_code == 200, started.text
    session_id = started.json()["session"]["session_id"]

    # 전제 1: 세션 시작은 이 item에 대해 아무것도 주문하지 않는다. 그 stage의 문맥이
    # 아직 있기 때문이다. 이 줄이 깨지면 아래의 "증가분"이 의미를 잃는다.
    assert _jobs(db_session, job_type=REVIEW_CONTEXT) == []

    with no_outbound_network():
        shown = study_api.client.post(f"/api/study/session/{session_id}/next")
        assert shown.status_code == 200, shown.text
        first = shown.json()["presentation"]
        assert first is not None
        assert first["context_stage"] == ContextStage.VARIED.value

        # 전제 2: 첫 `/next`도 주문하지 않는다. 여기까지가 세션 시작과 같은 상태다.
        assert _jobs(db_session, job_type=REVIEW_CONTEXT) == []

        completed = study_api.client.post(
            f"/api/study/presentations/{first['presentation_id']}/complete"
        )
        assert completed.status_code == 200, completed.text

        # 전제 3: `/complete`는 enqueue 지점이 아니다. 노출과 stage 전이만 한다.
        assert _jobs(db_session, job_type=REVIEW_CONTEXT) == []

        following = study_api.client.post(f"/api/study/session/{session_id}/next")
        assert following.status_code == 200, following.text

    assert_no_provider_import()

    state = db_session.execute(
        sa.select(UserItemLearningState).where(
            UserItemLearningState.user_id == user.id,
            UserItemLearningState.learning_item_id == item.id,
        )
    ).scalar_one()
    # 무신호 노출이 ladder를 올렸다는 것을 먼저 본다. 올라가지 않았다면 새 stage도
    # 없고, 이 테스트는 "gap이 생기지 않는 상태"를 검사하는 것이 되어 버린다.
    assert state.context_stage is not ContextStage.VARIED

    exposures = count_valid_exposures(db_session, user_id=user.id, learning_item_id=item.id)
    assert exposures < cfg.learning.minimum_meaningful_exposures, (
        "노출이 최소치에 닿으면 review reason이 사라져 gap 자체가 생기지 않는다"
    )

    ordered = _jobs(db_session, job_type=REVIEW_CONTEXT)
    assert len(ordered) == 1, "`/next`가 발견한 gap을 아무도 주문하지 않았다"
    assert ordered[0].payload_json == {
        "user_id": user.id,
        "learning_item_id": item.id,
        # stage는 DB가 정한다. 리터럴로 적으면 ladder가 바뀔 때 조용히 어긋난다.
        "context_stage": state.context_stage.value,
        "anchor_sentence_id": anchor.id,
    }
    assert ordered[0].status is GenerationJobStatus.QUEUED


# --------------------------------------------------------------------------
# end-to-end: 만든 job이 실제로 문장을 ready로 만든다
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_the_ordered_explanation_makes_the_skipped_sentence_ready(
    committed_api: StudyApi,
    committed_db: sessionmaker[Session],
    committed_session: Session,
    cfg: AppConfig,
) -> None:
    """enqueue -> worker -> 그 문장이 ready.

    request 경로는 job만 만들고, provider를 부르는 것은 worker 한 번뿐이다. 설명이
    붙은 뒤 **다음 materialization**이 그 문장을 candidate로 만들어 `/next`가 문장을
    돌려준다 --- 이 한 줄이 끊어져 있으면 handler는 있어도 아무 일도 일어나지 않는다.
    """
    now = committed_api.clock.now()
    with committed_db() as setup:
        item = factories.make_learning_item(setup)
        _sentence_with(setup, unexplained=[item])
        factories.make_prompt_version(
            setup, task_type=LlmTaskType.EXPLAIN_ITEM, version=explain_item_prompt.VERSION
        )
        setup.commit()
        item_id = item.id

    started = committed_api.client.post("/api/study/session")
    assert started.status_code == 200, started.text
    session_id = started.json()["session"]["session_id"]

    (job,) = _jobs(committed_session, job_type=EXPLAIN_ITEM)
    assert job.status is GenerationJobStatus.QUEUED
    assert not has_ready_sentence(committed_session, learning_item_id=item_id)

    provider = RecordingProvider(responses=[json.dumps(explanation_payload(), ensure_ascii=False)])
    handled = worker.run_once(
        session_factory=committed_db,
        provider=provider,
        run_job=runner.run_job,
        cfg=cfg,
        now=now,
    )

    assert handled is True
    assert provider.call_count == 1
    committed_session.expire_all()
    assert has_ready_sentence(committed_session, learning_item_id=item_id)

    presented = committed_api.client.post(f"/api/study/session/{session_id}/next")

    assert presented.status_code == 200, presented.text
    assert presented.json()["presentation"] is not None
    assert provider.call_count == 1
