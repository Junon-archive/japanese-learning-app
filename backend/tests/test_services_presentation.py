"""`/next`와 `/complete` (05_API_SPEC.md, 07_SRS_SPEC.md, 10_ERROR_HANDLING.md).

고정하는 것:

-   `finalize_presentation()`이 exposure를 만드는 **유일한** 자리이고 멱등하다.
-   quarantined content는 exposure를 만들지 않는다.
-   **무신호 review는 exposure와 deferral을 동시에 만든다.** click과 probe skip은
    신호가 아니다(07_SRS_SPEC.md의 `No-signal review`).
-   Ready Pool이 비면 None + replenishment job이고 provider 호출은 없다.
-   `/finish`가 마지막 presentation의 exposure를 기록한다.

정책값은 전부 config에서 읽는다. 12나 3을 적어 두면 config를 무시하는 구현이 통과한다.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.config import get_config
from app.models import (
    GenerationJob,
    ItemExposure,
    LearningEvent,
    LearningItem,
    ReviewState,
    Sentence,
    StudyPresentation,
    StudySession,
    User,
    UserItemLearningState,
    UserSentenceCandidate,
)
from app.models.enums import (
    CandidateStatus,
    ContextStage,
    EventType,
    PresentationRole,
    ReviewReason,
    SentenceStatus,
)
from app.services.interactions import respond_to_probe
from app.services.presentation import (
    PresentationClosedError,
    begin_interaction,
    complete_presentation,
    finalize_presentation,
    next_presentation,
)
from app.services.study_session import StudySessionClosedError, finish, start_or_resume
from app.srs.fsrs_binding import FSRS_PARAMS_VERSION
from tests import factories
from tests.clock import MutableClock

pytestmark = pytest.mark.integration

# "それは君に任せる。" 에서 `任せる`의 code point 구간.
_TARGET_START = 5
_TARGET_END = 8


@dataclass(frozen=True)
class Scene:
    user: User
    study_session: StudySession
    sentence: Sentence
    item: LearningItem
    candidate: UserSentenceCandidate
    presentation: StudyPresentation


def _scene(
    db: Session,
    *,
    role: PresentationRole = PresentationRole.NEW,
    review_reason: ReviewReason | None = None,
) -> Scene:
    """문장 하나 + target item 하나 + 그 문장을 보여준 presentation."""
    cfg = get_config()
    user = factories.make_user(db)
    study_session = factories.make_study_session(
        db, user, target_minutes=cfg.learning.default_session_minutes
    )
    sentence = factories.make_sentence(db)
    item = factories.make_learning_item(db)
    sentence_item = factories.make_sentence_item(db, sentence, item, surface_form="任せる")
    factories.make_span(db, sentence_item, start=_TARGET_START, end=_TARGET_END)
    factories.make_explanation(db, sentence_item)
    candidate = factories.make_candidate(
        db, user, sentence, status=CandidateStatus.SHOWN, presentation_role=role
    )
    factories.make_candidate_target(db, candidate, item)
    presentation = factories.make_presentation(
        db,
        user,
        study_session,
        candidate,
        sentence,
        presentation_role=role,
        review_reason=review_reason,
    )
    return Scene(
        user=user,
        study_session=study_session,
        sentence=sentence,
        item=item,
        candidate=candidate,
        presentation=presentation,
    )


def _exposures(db: Session, scene: Scene) -> list[ItemExposure]:
    return list(
        db.execute(
            sa.select(ItemExposure)
            .where(ItemExposure.study_presentation_id == scene.presentation.id)
            .order_by(ItemExposure.id)
        )
        .scalars()
        .all()
    )


def _events(db: Session, *, user_id: int, event_type: EventType) -> list[LearningEvent]:
    return list(
        db.execute(
            sa.select(LearningEvent)
            .where(LearningEvent.user_id == user_id, LearningEvent.event_type == event_type)
            .order_by(LearningEvent.id)
        )
        .scalars()
        .all()
    )


def _review_state(db: Session, scene: Scene) -> ReviewState | None:
    return db.execute(
        sa.select(ReviewState).where(
            ReviewState.user_id == scene.user.id,
            ReviewState.learning_item_id == scene.item.id,
        )
    ).scalar_one_or_none()


def _learning_state(db: Session, scene: Scene) -> UserItemLearningState | None:
    return db.execute(
        sa.select(UserItemLearningState).where(
            UserItemLearningState.user_id == scene.user.id,
            UserItemLearningState.learning_item_id == scene.item.id,
        )
    ).scalar_one_or_none()


def _due_review_state(db: Session, scene: Scene, clock: MutableClock) -> ReviewState:
    state = factories.make_review_state(
        db, scene.user, scene.item, state=2, params_version=FSRS_PARAMS_VERSION
    )
    state.next_review_at = clock.now()
    state.reps = 4
    state.lapses = 1
    db.flush()
    return state


# --------------------------------------------------------------------------
# exposure 확정
# --------------------------------------------------------------------------


def test_completing_records_one_exposure_for_each_target_item(
    db_session: Session, study_clock: MutableClock
) -> None:
    scene = _scene(db_session)

    finalize_presentation(
        db_session, presentation=scene.presentation, now=study_clock.now(), cfg=get_config()
    )

    exposures = _exposures(db_session, scene)
    assert [exposure.learning_item_id for exposure in exposures] == [scene.item.id]
    assert exposures[0].created_at == study_clock.now()
    assert scene.presentation.completed_at == study_clock.now()


def test_finalizing_twice_changes_nothing(db_session: Session, study_clock: MutableClock) -> None:
    """멱등 가드. 두 번째 호출이 exposure를 하나 더 만들면 최소 5회 노출이 거짓으로 찬다."""
    cfg = get_config()
    scene = _scene(db_session)
    finalize_presentation(
        db_session, presentation=scene.presentation, now=study_clock.now(), cfg=cfg
    )
    first_completed_at = scene.presentation.completed_at

    study_clock.advance(timedelta(minutes=5))
    finalize_presentation(
        db_session, presentation=scene.presentation, now=study_clock.now(), cfg=cfg
    )

    assert len(_exposures(db_session, scene)) == 1
    assert scene.presentation.completed_at == first_completed_at
    assert (
        len(_events(db_session, user_id=scene.user.id, event_type=EventType.SENTENCE_COMPLETED))
        == 1
    )


def test_completing_consumes_the_candidate(db_session: Session, study_clock: MutableClock) -> None:
    scene = _scene(db_session)

    finalize_presentation(
        db_session, presentation=scene.presentation, now=study_clock.now(), cfg=get_config()
    )

    assert scene.candidate.status is CandidateStatus.CONSUMED


def test_the_exposure_cache_is_recomputed_not_incremented(
    db_session: Session, study_clock: MutableClock
) -> None:
    """`+= 1`이면 flag/quarantine 이후 캐시가 유효 건수와 갈린다(07_SRS_SPEC.md)."""
    scene = _scene(db_session, role=PresentationRole.REVIEW, review_reason=ReviewReason.FSRS_DUE)
    state = _due_review_state(db_session, scene, study_clock)
    state.meaningful_exposure_count = 7  # 캐시가 어긋난 상태
    db_session.flush()

    finalize_presentation(
        db_session, presentation=scene.presentation, now=study_clock.now(), cfg=get_config()
    )

    assert state.meaningful_exposure_count == 1


# --------------------------------------------------------------------------
# quarantine
# --------------------------------------------------------------------------


def test_a_quarantined_sentence_produces_no_exposure(
    db_session: Session, study_clock: MutableClock
) -> None:
    scene = _scene(db_session)
    scene.sentence.status = SentenceStatus.QUARANTINED
    db_session.flush()

    finalize_presentation(
        db_session, presentation=scene.presentation, now=study_clock.now(), cfg=get_config()
    )

    assert _exposures(db_session, scene) == []
    # presentation은 닫힌다. 열어 두면 그 세션이 영영 다음 문장으로 못 넘어간다.
    assert scene.presentation.completed_at == study_clock.now()


def test_a_quarantined_candidate_produces_no_exposure(
    db_session: Session, study_clock: MutableClock
) -> None:
    scene = _scene(db_session)
    scene.candidate.status = CandidateStatus.QUARANTINED
    db_session.flush()

    finalize_presentation(
        db_session, presentation=scene.presentation, now=study_clock.now(), cfg=get_config()
    )

    assert _exposures(db_session, scene) == []
    assert scene.candidate.status is CandidateStatus.QUARANTINED


def test_a_quarantined_presentation_does_not_defer_the_review(
    db_session: Session, study_clock: MutableClock
) -> None:
    """flag된 문장을 본 것은 학습 경험이 아니다. 무신호 처리도 하지 않는다."""
    scene = _scene(db_session, role=PresentationRole.REVIEW, review_reason=ReviewReason.FSRS_DUE)
    state = _due_review_state(db_session, scene, study_clock)
    scene.sentence.status = SentenceStatus.QUARANTINED
    db_session.flush()

    finalize_presentation(
        db_session, presentation=scene.presentation, now=study_clock.now(), cfg=get_config()
    )

    assert state.deferred_until is None


# --------------------------------------------------------------------------
# 무신호 (07_SRS_SPEC.md의 `No-signal review`)
# --------------------------------------------------------------------------


def test_a_no_signal_review_gets_both_an_exposure_and_a_deferral(
    db_session: Session, study_clock: MutableClock
) -> None:
    """둘은 모순이 아니다. 문맥 경험 횟수는 늘고 기억 증거는 늘지 않는다."""
    cfg = get_config()
    scene = _scene(db_session, role=PresentationRole.REVIEW, review_reason=ReviewReason.FSRS_DUE)
    state = _due_review_state(db_session, scene, study_clock)
    next_review_at = state.next_review_at

    finalize_presentation(
        db_session, presentation=scene.presentation, now=study_clock.now(), cfg=cfg
    )

    assert len(_exposures(db_session, scene)) == 1
    assert state.deferred_until == study_clock.now() + timedelta(
        hours=cfg.learning.passive_review_deferral_hours
    )
    # rating을 추론하지 않았다. due 상태도 그대로다.
    assert state.next_review_at == next_review_at
    assert state.reps == 4
    assert state.lapses == 1
    assert state.stability is None
    learning_state = _learning_state(db_session, scene)
    assert learning_state is not None
    assert learning_state.passive_no_signal_count == 1


def test_a_click_is_not_a_signal(db_session: Session, study_clock: MutableClock) -> None:
    """`item_clicked`를 신호로 세면 클릭 한 번이 무한 due loop를 만든다(Scenario B)."""
    cfg = get_config()
    scene = _scene(db_session, role=PresentationRole.REVIEW, review_reason=ReviewReason.FSRS_DUE)
    state = _due_review_state(db_session, scene, study_clock)
    factories.make_event(
        db_session,
        scene.user,
        scene.study_session,
        client_event_id=uuid.uuid4(),
        event_type=EventType.ITEM_CLICKED,
        presentation=scene.presentation,
        item=scene.item,
    )

    finalize_presentation(
        db_session, presentation=scene.presentation, now=study_clock.now(), cfg=cfg
    )

    assert state.deferred_until == study_clock.now() + timedelta(
        hours=cfg.learning.passive_review_deferral_hours
    )


@pytest.mark.parametrize(
    "event_type",
    [
        EventType.EXPLANATION_REVEALED,
        EventType.TRANSLATION_REVEALED,
        EventType.MASTERY_PROBE_SHOWN,
        EventType.MASTERY_PROBE_SKIPPED,
    ],
)
def test_other_non_rating_events_are_not_signals(
    db_session: Session, study_clock: MutableClock, event_type: EventType
) -> None:
    cfg = get_config()
    scene = _scene(db_session, role=PresentationRole.REVIEW, review_reason=ReviewReason.FSRS_DUE)
    state = _due_review_state(db_session, scene, study_clock)
    factories.make_event(
        db_session,
        scene.user,
        scene.study_session,
        client_event_id=uuid.uuid4(),
        event_type=event_type,
        presentation=scene.presentation,
        item=scene.item,
    )

    finalize_presentation(
        db_session, presentation=scene.presentation, now=study_clock.now(), cfg=cfg
    )

    assert state.deferred_until is not None


@pytest.mark.parametrize(
    "event_type",
    [
        EventType.SELF_REPORT_KNOWN,
        EventType.SELF_REPORT_UNCERTAIN,
        EventType.SELF_REPORT_UNKNOWN,
        EventType.MASTERY_PROBE_KNOWN,
        EventType.MASTERY_PROBE_UNCERTAIN,
        EventType.MASTERY_PROBE_UNKNOWN,
    ],
)
def test_an_fsrs_rating_event_suppresses_the_deferral(
    db_session: Session, study_clock: MutableClock, event_type: EventType
) -> None:
    cfg = get_config()
    scene = _scene(db_session, role=PresentationRole.REVIEW, review_reason=ReviewReason.FSRS_DUE)
    state = _due_review_state(db_session, scene, study_clock)
    factories.make_event(
        db_session,
        scene.user,
        scene.study_session,
        client_event_id=uuid.uuid4(),
        event_type=event_type,
        presentation=scene.presentation,
        item=scene.item,
    )

    finalize_presentation(
        db_session, presentation=scene.presentation, now=study_clock.now(), cfg=cfg
    )

    assert state.deferred_until is None
    learning_state = _learning_state(db_session, scene)
    assert learning_state is None or learning_state.passive_no_signal_count == 0


def test_a_signal_on_one_target_does_not_cover_the_other(
    db_session: Session, study_clock: MutableClock
) -> None:
    """판정 단위는 presentation이 아니라 (presentation, item) 쌍이다."""
    cfg = get_config()
    scene = _scene(db_session, role=PresentationRole.REVIEW, review_reason=ReviewReason.FSRS_DUE)
    answered = _due_review_state(db_session, scene, study_clock)
    other_item = factories.make_learning_item(db_session)
    factories.make_candidate_target(db_session, scene.candidate, other_item)
    silent = factories.make_review_state(
        db_session, scene.user, other_item, state=2, params_version=FSRS_PARAMS_VERSION
    )
    factories.make_event(
        db_session,
        scene.user,
        scene.study_session,
        client_event_id=uuid.uuid4(),
        event_type=EventType.SELF_REPORT_KNOWN,
        presentation=scene.presentation,
        item=scene.item,
    )

    finalize_presentation(
        db_session, presentation=scene.presentation, now=study_clock.now(), cfg=cfg
    )

    assert answered.deferred_until is None
    assert silent.deferred_until == study_clock.now() + timedelta(
        hours=cfg.learning.passive_review_deferral_hours
    )


def test_a_new_role_presentation_does_not_create_a_review_state(
    db_session: Session, study_clock: MutableClock
) -> None:
    """아직 스케줄이 없는 item을 defer할 대상은 없다. 행을 만들어 주지도 않는다."""
    scene = _scene(db_session, role=PresentationRole.NEW)

    finalize_presentation(
        db_session, presentation=scene.presentation, now=study_clock.now(), cfg=get_config()
    )

    assert _review_state(db_session, scene) is None
    learning_state = _learning_state(db_session, scene)
    assert learning_state is not None
    assert learning_state.passive_no_signal_count == 1


# --------------------------------------------------------------------------
# /finish 연결
# --------------------------------------------------------------------------


def test_finishing_a_session_records_the_last_presentations_exposure(
    db_session: Session, study_clock: MutableClock
) -> None:
    """`/finish`가 `finalize_presentation()`을 거치지 않으면 마지막 문장의 노출이 영영 사라진다.

    07_SRS_SPEC.md의 조건 2가 "`Next`로 이동했거나 **세션을 정상 완료**했다"이다.
    """
    cfg = get_config()
    scene = _scene(db_session)

    study_clock.advance(timedelta(seconds=30))
    finish(
        db_session,
        user_id=scene.user.id,
        session_id=scene.study_session.id,
        now=study_clock.now(),
        cfg=cfg,
    )

    exposures = _exposures(db_session, scene)
    assert [exposure.learning_item_id for exposure in exposures] == [scene.item.id]
    assert scene.presentation.completed_at == study_clock.now()
    assert scene.candidate.status is CandidateStatus.CONSUMED


def test_finishing_defers_a_no_signal_review_too(
    db_session: Session, study_clock: MutableClock
) -> None:
    cfg = get_config()
    scene = _scene(db_session, role=PresentationRole.REVIEW, review_reason=ReviewReason.FSRS_DUE)
    state = _due_review_state(db_session, scene, study_clock)

    finish(
        db_session,
        user_id=scene.user.id,
        session_id=scene.study_session.id,
        now=study_clock.now(),
        cfg=cfg,
    )

    assert state.deferred_until == study_clock.now() + timedelta(
        hours=cfg.learning.passive_review_deferral_hours
    )


# --------------------------------------------------------------------------
# /complete 진입점
# --------------------------------------------------------------------------


def test_completing_someone_elses_presentation_is_not_found(
    db_session: Session, study_clock: MutableClock
) -> None:
    from app.services.presentation import PresentationNotFoundError

    scene = _scene(db_session)
    intruder = factories.make_user(db_session)

    with pytest.raises(PresentationNotFoundError):
        complete_presentation(
            db_session,
            user_id=intruder.id,
            presentation_id=scene.presentation.id,
            now=study_clock.now(),
            cfg=get_config(),
        )

    assert _exposures(db_session, scene) == []


# --------------------------------------------------------------------------
# /next
# --------------------------------------------------------------------------


def test_an_open_presentation_is_returned_instead_of_a_new_one(
    db_session: Session, study_clock: MutableClock
) -> None:
    """`열린 presentation 불변식`. 재시도가 candidate를 헛되이 소비하지 않는다."""
    cfg = get_config()
    scene = _scene(db_session)

    view = next_presentation(
        db_session,
        user=scene.user,
        session_id=scene.study_session.id,
        now=study_clock.now(),
        cfg=cfg,
    )

    assert view is not None
    assert view.presentation_id == scene.presentation.id
    count = db_session.execute(
        sa.select(sa.func.count())
        .select_from(StudyPresentation)
        .where(StudyPresentation.study_session_id == scene.study_session.id)
    ).scalar_one()
    assert count == 1


def test_next_renders_segments_that_rebuild_the_sentence(
    db_session: Session, study_clock: MutableClock
) -> None:
    scene = _scene(db_session)

    view = next_presentation(
        db_session,
        user=scene.user,
        session_id=scene.study_session.id,
        now=study_clock.now(),
        cfg=get_config(),
    )

    assert view is not None
    assert "".join(segment.text for segment in view.render_segments) == scene.sentence.japanese
    assert [item.learning_item_id for item in view.tappable_items] == [scene.item.id]


def test_next_creates_a_presentation_and_marks_the_candidate_shown(
    db_session: Session, study_clock: MutableClock
) -> None:
    cfg = get_config()
    scene = _scene(db_session)
    # 열린 presentation을 닫아 두면 다음 `/next`가 새 candidate를 고른다.
    finalize_presentation(
        db_session, presentation=scene.presentation, now=study_clock.now(), cfg=cfg
    )
    sentence = factories.make_sentence(db_session)
    sentence_item = factories.make_sentence_item(
        db_session, sentence, scene.item, surface_form="任せる"
    )
    factories.make_span(db_session, sentence_item, start=_TARGET_START, end=_TARGET_END)
    factories.make_explanation(db_session, sentence_item)
    candidate = factories.make_candidate(
        db_session,
        scene.user,
        sentence,
        status=CandidateStatus.READY,
        presentation_role=PresentationRole.NEW,
        context_stage=ContextStage.NEAR_ORIGINAL,
    )
    factories.make_candidate_target(db_session, candidate, scene.item)

    study_clock.advance(timedelta(seconds=10))
    view = next_presentation(
        db_session,
        user=scene.user,
        session_id=scene.study_session.id,
        now=study_clock.now(),
        cfg=cfg,
    )

    assert view is not None
    assert view.sentence_id == sentence.id
    assert view.presentation_id != scene.presentation.id
    assert candidate.status is CandidateStatus.SHOWN
    viewed = _events(db_session, user_id=scene.user.id, event_type=EventType.SENTENCE_VIEWED)
    assert [event.study_presentation_id for event in viewed] == [view.presentation_id]


def test_an_empty_pool_returns_none_and_enqueues_replenishment(
    db_session: Session, study_clock: MutableClock
) -> None:
    """Scenario E. provider를 부르지 않고 job만 남긴다(10_ERROR_HANDLING.md)."""
    cfg = get_config()
    user = factories.make_user(db_session)
    started = start_or_resume(db_session, user=user, now=study_clock.now(), cfg=cfg)

    view = next_presentation(
        db_session, user=user, session_id=started.session.id, now=study_clock.now(), cfg=cfg
    )

    assert view is None
    jobs = list(
        db_session.execute(sa.select(GenerationJob).order_by(GenerationJob.id)).scalars().all()
    )
    roles = {job.payload_json["presentation_role"] for job in jobs}
    assert roles == {role.value for role in PresentationRole}
    assert all(job.max_attempts == cfg.jobs.max_job_attempts for job in jobs)


def test_an_empty_pool_does_not_enqueue_twice_in_the_same_day(
    db_session: Session, study_clock: MutableClock
) -> None:
    cfg = get_config()
    user = factories.make_user(db_session)
    started = start_or_resume(db_session, user=user, now=study_clock.now(), cfg=cfg)
    next_presentation(
        db_session, user=user, session_id=started.session.id, now=study_clock.now(), cfg=cfg
    )

    study_clock.advance(timedelta(minutes=1))
    next_presentation(
        db_session, user=user, session_id=started.session.id, now=study_clock.now(), cfg=cfg
    )

    count = db_session.execute(sa.select(sa.func.count()).select_from(GenerationJob)).scalar_one()
    assert count == len(PresentationRole)


def test_next_on_a_finished_session_is_rejected(
    db_session: Session, study_clock: MutableClock
) -> None:
    cfg = get_config()
    user = factories.make_user(db_session)
    started = start_or_resume(db_session, user=user, now=study_clock.now(), cfg=cfg)
    finish(
        db_session,
        user_id=user.id,
        session_id=started.session.id,
        now=study_clock.now(),
        cfg=cfg,
    )

    with pytest.raises(StudySessionClosedError):
        next_presentation(
            db_session,
            user=user,
            session_id=started.session.id,
            now=study_clock.now(),
            cfg=cfg,
        )


# --------------------------------------------------------------------------
# 상태 게이트가 시계보다 앞선다 (05_API_SPEC.md, ADR-014)
# --------------------------------------------------------------------------


@pytest.mark.parametrize("closing", ["session", "presentation"])
def test_a_rejected_interaction_never_moves_the_session_clock(
    db_session: Session, study_clock: MutableClock, closing: str
) -> None:
    """게이트는 `touch()`**보다 앞에** 있어야 한다.

    뒤에 두면 거부당한 요청이 끝난 세션의 `last_activity_at`과 `active_seconds`를
    먼저 밀어 놓는다. HTTP 경계에서는 rollback이 그것을 가려 주므로(예외가 나면
    commit이 없다) 이 구조는 여기서만 관측된다 --- 나중에 어느 호출부가 예외를
    잡고 commit하는 순간 그 차이가 DB에 남는다.
    """
    cfg = get_config()
    scene = _scene(db_session)
    expected: type[Exception]
    if closing == "session":
        scene.study_session.ended_at = study_clock.now()
        expected = StudySessionClosedError
    else:
        scene.presentation.completed_at = study_clock.now()
        expected = PresentationClosedError
    db_session.flush()
    before = (scene.study_session.last_activity_at, scene.study_session.active_seconds)
    later = study_clock.advance(timedelta(seconds=30))

    with pytest.raises(expected):
        begin_interaction(
            db_session,
            user_id=scene.user.id,
            presentation_id=scene.presentation.id,
            now=later,
            cfg=cfg,
        )

    assert (
        scene.study_session.last_activity_at,
        scene.study_session.active_seconds,
    ) == before


# --------------------------------------------------------------------------
# probe 재조회 (ADR-009)
# --------------------------------------------------------------------------


def test_the_same_open_presentation_keeps_one_probe_id(
    db_session: Session, study_clock: MutableClock
) -> None:
    """`choose_probe()`는 idempotent하지 않다. 재호출하면 pacing이 달라진다.

    그래서 열린 presentation을 다시 받는 경로는 uuid5 자연키로 기존
    `mastery_probe_shown` event를 조회한다(05_API_SPEC.md의 `Mastery Probe`).
    """
    cfg = get_config()
    scene = _scene(db_session)
    finalize_presentation(
        db_session, presentation=scene.presentation, now=study_clock.now(), cfg=cfg
    )
    # probe pacing 조건 2: 세션에 `probe_min_gap_presentations`개의 선행 presentation.
    for _ in range(cfg.learning.probe_min_gap_presentations):
        factories.make_presentation(
            db_session,
            scene.user,
            scene.study_session,
            scene.candidate,
            scene.sentence,
            completed_at=study_clock.now(),
        )
    sentence = factories.make_sentence(db_session)
    sentence_item = factories.make_sentence_item(
        db_session, sentence, scene.item, surface_form="任せる"
    )
    factories.make_span(db_session, sentence_item, start=_TARGET_START, end=_TARGET_END)
    factories.make_explanation(db_session, sentence_item)
    candidate = factories.make_candidate(
        db_session,
        scene.user,
        sentence,
        status=CandidateStatus.READY,
        presentation_role=PresentationRole.NEW,
        context_stage=ContextStage.NEAR_ORIGINAL,
    )
    factories.make_candidate_target(db_session, candidate, scene.item)

    first = next_presentation(
        db_session,
        user=scene.user,
        session_id=scene.study_session.id,
        now=study_clock.now(),
        cfg=cfg,
    )
    study_clock.advance(timedelta(seconds=5))
    second = next_presentation(
        db_session,
        user=scene.user,
        session_id=scene.study_session.id,
        now=study_clock.now(),
        cfg=cfg,
    )

    assert first is not None and second is not None
    assert first.probe is not None
    assert second.probe is not None
    assert second.probe.probe_id == first.probe.probe_id
    assert second.probe.expression == "任せる"
    shown = _events(db_session, user_id=scene.user.id, event_type=EventType.MASTERY_PROBE_SHOWN)
    assert len(shown) == 1


def test_an_answered_probe_is_not_shown_again(
    db_session: Session, study_clock: MutableClock
) -> None:
    """probe 하나에 응답은 최대 1건이다. 다시 실으면 답할 수 없는 질문을 렌더한다.

    skip도 응답이다 --- 건너뛴 probe가 reload마다 되살아나면 `Skip`이 의미를 잃는다.
    """
    cfg = get_config()
    scene = _scene(db_session)
    finalize_presentation(
        db_session, presentation=scene.presentation, now=study_clock.now(), cfg=cfg
    )
    for _ in range(cfg.learning.probe_min_gap_presentations):
        factories.make_presentation(
            db_session,
            scene.user,
            scene.study_session,
            scene.candidate,
            scene.sentence,
            completed_at=study_clock.now(),
        )
    sentence = factories.make_sentence(db_session)
    sentence_item = factories.make_sentence_item(
        db_session, sentence, scene.item, surface_form="任せる"
    )
    factories.make_span(db_session, sentence_item, start=_TARGET_START, end=_TARGET_END)
    factories.make_explanation(db_session, sentence_item)
    candidate = factories.make_candidate(
        db_session,
        scene.user,
        sentence,
        status=CandidateStatus.READY,
        presentation_role=PresentationRole.NEW,
        context_stage=ContextStage.NEAR_ORIGINAL,
    )
    factories.make_candidate_target(db_session, candidate, scene.item)
    shown = next_presentation(
        db_session,
        user=scene.user,
        session_id=scene.study_session.id,
        now=study_clock.now(),
        cfg=cfg,
    )
    assert shown is not None and shown.probe is not None

    respond_to_probe(
        db_session,
        user_id=scene.user.id,
        presentation_id=shown.presentation_id,
        probe_id=shown.probe.probe_id,
        signal=None,
        client_event_id=uuid.uuid4(),
        now=study_clock.now(),
        cfg=cfg,
    )
    again = next_presentation(
        db_session,
        user=scene.user,
        session_id=scene.study_session.id,
        now=study_clock.now(),
        cfg=cfg,
    )

    assert again is not None
    assert again.presentation_id == shown.presentation_id
    assert again.probe is None
