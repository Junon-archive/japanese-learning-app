"""Scenario H --- 사용자가 `unnatural` flag (10_ERROR_HANDLING.md, 12_TEST_PLAN.md).

고정하는 것:

-   sentence와 candidate가 **즉시** quarantined가 된다.
-   그 presentation의 `item_exposures`가 `invalidated_at`을 얻고, 캐시가 유효 건수로
    다시 계산된다.
-   그 뒤의 `/complete`는 exposure를 만들지 않는다.
-   재전송은 부수효과를 두 번 내지 않는다(불변식 #10).

**mastery / FSRS 되돌리기는 검증하지 않는다.** 구현하지 않았기 때문이다 --- 명세가
되돌리는 방법을 정하지 않았고 EMA는 역산이 불가능하다(`app/services/content_flag.py`의
모듈 docstring).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.config import get_config
from app.models import (
    ContentFlag,
    ItemExposure,
    LearningEvent,
    LearningItem,
    Sentence,
    StudyPresentation,
    StudySession,
    User,
    UserSentenceCandidate,
)
from app.models.enums import (
    CandidateStatus,
    ContentFlagReason,
    EventType,
    PresentationRole,
    SentenceStatus,
)
from app.services.content_flag import flag_content
from app.services.presentation import PresentationNotFoundError, finalize_presentation
from app.srs.fsrs_binding import FSRS_PARAMS_VERSION
from tests import factories
from tests.clock import MutableClock

pytestmark = pytest.mark.integration

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


def _scene(db: Session) -> Scene:
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
        db, user, sentence, status=CandidateStatus.SHOWN, presentation_role=PresentationRole.REVIEW
    )
    factories.make_candidate_target(db, candidate, item)
    presentation = factories.make_presentation(
        db,
        user,
        study_session,
        candidate,
        sentence,
        presentation_role=PresentationRole.REVIEW,
    )
    return Scene(
        user=user,
        study_session=study_session,
        sentence=sentence,
        item=item,
        candidate=candidate,
        presentation=presentation,
    )


def _flag(db: Session, scene: Scene, clock: MutableClock, key: uuid.UUID | None = None) -> None:
    flag_content(
        db,
        user_id=scene.user.id,
        presentation_id=scene.presentation.id,
        reason=ContentFlagReason.UNNATURAL,
        note="부자연스러움",
        client_event_id=key or uuid.uuid4(),
        now=clock.now(),
        cfg=get_config(),
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


def test_flagging_quarantines_the_sentence_and_its_candidates(
    db_session: Session, study_clock: MutableClock
) -> None:
    scene = _scene(db_session)

    _flag(db_session, scene, study_clock)

    db_session.refresh(scene.sentence)
    db_session.refresh(scene.candidate)
    assert scene.sentence.status is SentenceStatus.QUARANTINED
    assert scene.candidate.status is CandidateStatus.QUARANTINED


def test_flagging_quarantines_another_users_candidate_for_the_same_sentence(
    db_session: Session, study_clock: MutableClock
) -> None:
    """`sentences`는 global content다. 한 사람의 pool만 치우면 남는 ready가 생긴다."""
    scene = _scene(db_session)
    other_user = factories.make_user(db_session)
    other_candidate = factories.make_candidate(
        db_session,
        other_user,
        scene.sentence,
        status=CandidateStatus.READY,
        presentation_role=PresentationRole.NEW,
    )

    _flag(db_session, scene, study_clock)

    db_session.refresh(other_candidate)
    assert other_candidate.status is CandidateStatus.QUARANTINED


def test_flagging_records_the_flag_row_and_the_event(
    db_session: Session, study_clock: MutableClock
) -> None:
    scene = _scene(db_session)

    _flag(db_session, scene, study_clock)

    flags = list(db_session.execute(sa.select(ContentFlag)).scalars().all())
    assert len(flags) == 1
    assert flags[0].sentence_id == scene.sentence.id
    assert flags[0].study_presentation_id == scene.presentation.id
    assert flags[0].reason is ContentFlagReason.UNNATURAL
    assert flags[0].created_at == study_clock.now()
    events = list(
        db_session.execute(
            sa.select(LearningEvent).where(LearningEvent.event_type == EventType.CONTENT_FLAGGED)
        )
        .scalars()
        .all()
    )
    assert len(events) == 1


def test_flagging_invalidates_the_exposure_and_recomputes_the_cache(
    db_session: Session, study_clock: MutableClock
) -> None:
    cfg = get_config()
    scene = _scene(db_session)
    state = factories.make_review_state(
        db_session, scene.user, scene.item, state=2, params_version=FSRS_PARAMS_VERSION
    )
    finalize_presentation(
        db_session, presentation=scene.presentation, now=study_clock.now(), cfg=cfg
    )
    assert state.meaningful_exposure_count == 1

    _flag(db_session, scene, study_clock)

    exposures = _exposures(db_session, scene)
    assert len(exposures) == 1
    assert exposures[0].invalidated_at == study_clock.now()
    assert state.meaningful_exposure_count == 0


def test_completing_after_a_flag_creates_no_exposure(
    db_session: Session, study_clock: MutableClock
) -> None:
    scene = _scene(db_session)

    _flag(db_session, scene, study_clock)
    finalize_presentation(
        db_session, presentation=scene.presentation, now=study_clock.now(), cfg=get_config()
    )

    assert _exposures(db_session, scene) == []
    assert scene.presentation.completed_at == study_clock.now()


def test_resending_the_same_flag_does_not_duplicate_anything(
    db_session: Session, study_clock: MutableClock
) -> None:
    scene = _scene(db_session)
    key = uuid.uuid4()

    _flag(db_session, scene, study_clock, key)
    _flag(db_session, scene, study_clock, key)

    count = db_session.execute(sa.select(sa.func.count()).select_from(ContentFlag)).scalar_one()
    assert count == 1


def test_flagging_someone_elses_presentation_is_not_found(
    db_session: Session, study_clock: MutableClock
) -> None:
    scene = _scene(db_session)
    intruder = factories.make_user(db_session)

    with pytest.raises(PresentationNotFoundError):
        flag_content(
            db_session,
            user_id=intruder.id,
            presentation_id=scene.presentation.id,
            reason=ContentFlagReason.WRONG,
            note=None,
            client_event_id=uuid.uuid4(),
            now=study_clock.now(),
            cfg=get_config(),
        )

    db_session.refresh(scene.sentence)
    assert scene.sentence.status is SentenceStatus.VALIDATED
