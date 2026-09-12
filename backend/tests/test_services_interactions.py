"""click / reveal / self-report / probe 응답 (05_API_SPEC.md의 `Interaction`).

고정하는 것:

-   같은 `client_event_id` 재전송은 부수효과를 **한 번만** 낸다(불변식 #10).
-   click 하나로는 아무것도 승격되지 않고 exposure도 생기지 않는다(불변식 #5).
-   `알고 있었음`은 아직 target이 아닌 item을 SRS에 강제 등록하지 않는다
    (02_LEARNING_POLICY.md의 `Incidental Item Click`).
-   probe skip은 mastery evidence도 FSRS grade도 아니다.
-   explanation이 없으면 **live LLM fallback 대신 예외**다.
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
    EventType,
    ExplanationStatus,
    ExplicitSignal,
    PresentationRole,
)
from app.services.content_flag import flag_content
from app.services.events import server_client_event_id
from app.services.interactions import (
    EvidenceAlreadyRecordedError,
    ExplanationMissingError,
    ProbeNotFoundError,
    SentenceItemNotFoundError,
    click_item,
    respond_to_probe,
    reveal_explanation,
    reveal_translation,
    self_report,
)
from app.services.presentation import PresentationNotFoundError
from app.services.study_session import start_or_resume
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
    sentence_item: SentenceItem
    presentation: StudyPresentation


def _scene(
    db: Session,
    *,
    role: PresentationRole = PresentationRole.NEW,
    with_explanation: bool = True,
) -> Scene:
    cfg = get_config()
    user = factories.make_user(db)
    study_session = factories.make_study_session(
        db, user, target_minutes=cfg.learning.default_session_minutes
    )
    sentence = factories.make_sentence(db)
    item = factories.make_learning_item(db)
    sentence_item = factories.make_sentence_item(db, sentence, item, surface_form="任せる")
    factories.make_span(db, sentence_item, start=_TARGET_START, end=_TARGET_END)
    if with_explanation:
        factories.make_explanation(db, sentence_item)
    candidate = factories.make_candidate(
        db, user, sentence, status=CandidateStatus.SHOWN, presentation_role=role
    )
    factories.make_candidate_target(db, candidate, item)
    presentation = factories.make_presentation(
        db, user, study_session, candidate, sentence, presentation_role=role
    )
    return Scene(
        user=user,
        study_session=study_session,
        sentence=sentence,
        item=item,
        sentence_item=sentence_item,
        presentation=presentation,
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


def _mastery(db: Session, scene: Scene) -> UserMastery | None:
    return db.execute(
        sa.select(UserMastery).where(
            UserMastery.user_id == scene.user.id,
            UserMastery.learning_item_id == scene.item.id,
        )
    ).scalar_one_or_none()


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


def _activate_target(db: Session, scene: Scene) -> None:
    db.add(
        UserItemLearningState(
            user_id=scene.user.id,
            learning_item_id=scene.item.id,
            context_stage=scene.presentation.context_stage,
            is_active_learning_target=True,
            updated_at=factories.NOW,
        )
    )
    db.flush()


def _another_exposure(db: Session, scene: Scene) -> StudyPresentation:
    """같은 item을 보여주는 **다른** presentation.

    노출당 evidence는 1건이므로(07_SRS_SPEC.md) 한 item에 evidence를 두 번 남기려면
    노출이 둘이어야 한다. 한 session에 열린 presentation은 하나이므로 session도 새로
    만든다.
    """
    cfg = get_config()
    study_session = factories.make_study_session(
        db, scene.user, target_minutes=cfg.learning.default_session_minutes
    )
    candidate = db.get(UserSentenceCandidate, scene.presentation.candidate_id)
    assert candidate is not None
    return factories.make_presentation(
        db,
        scene.user,
        study_session,
        candidate,
        scene.sentence,
        presentation_role=scene.presentation.presentation_role,
    )


def _show_probe(db: Session, scene: Scene, clock: MutableClock) -> LearningEvent:
    """`/next`가 남기는 것과 같은 `mastery_probe_shown` event."""
    event = LearningEvent(
        user_id=scene.user.id,
        study_session_id=scene.study_session.id,
        study_presentation_id=scene.presentation.id,
        sentence_id=scene.sentence.id,
        learning_item_id=scene.item.id,
        event_type=EventType.MASTERY_PROBE_SHOWN,
        client_event_id=server_client_event_id(
            EventType.MASTERY_PROBE_SHOWN,
            study_presentation_id=scene.presentation.id,
            learning_item_id=scene.item.id,
        ),
        created_at=clock.now(),
    )
    db.add(event)
    db.flush()
    return event


# --------------------------------------------------------------------------
# click / reveal
# --------------------------------------------------------------------------


def test_clicking_returns_the_precomputed_explanation(
    db_session: Session, study_clock: MutableClock
) -> None:
    scene = _scene(db_session)

    view = click_item(
        db_session,
        user_id=scene.user.id,
        presentation_id=scene.presentation.id,
        sentence_item_id=scene.sentence_item.id,
        client_event_id=uuid.uuid4(),
        now=study_clock.now(),
        cfg=get_config(),
    )

    assert view.learning_item_id == scene.item.id
    assert view.canonical_form == scene.item.lemma
    assert view.item_type == scene.item.type
    assert view.meaning_in_context


def test_clicking_alone_registers_nothing(db_session: Session, study_clock: MutableClock) -> None:
    """click은 raw event로만 남는다. mastery도 FSRS도 exposure도 만들지 않는다."""
    scene = _scene(db_session)

    click_item(
        db_session,
        user_id=scene.user.id,
        presentation_id=scene.presentation.id,
        sentence_item_id=scene.sentence_item.id,
        client_event_id=uuid.uuid4(),
        now=study_clock.now(),
        cfg=get_config(),
    )

    assert _mastery(db_session, scene) is None
    assert _review_state(db_session, scene) is None
    assert _learning_state(db_session, scene) is None
    exposures = db_session.execute(
        sa.select(sa.func.count()).select_from(ItemExposure)
    ).scalar_one()
    assert exposures == 0


def test_resending_a_click_records_one_event(
    db_session: Session, study_clock: MutableClock
) -> None:
    scene = _scene(db_session)
    key = uuid.uuid4()

    first = click_item(
        db_session,
        user_id=scene.user.id,
        presentation_id=scene.presentation.id,
        sentence_item_id=scene.sentence_item.id,
        client_event_id=key,
        now=study_clock.now(),
        cfg=get_config(),
    )
    second = click_item(
        db_session,
        user_id=scene.user.id,
        presentation_id=scene.presentation.id,
        sentence_item_id=scene.sentence_item.id,
        client_event_id=key,
        now=study_clock.now(),
        cfg=get_config(),
    )

    assert first == second
    assert len(_events(db_session, user_id=scene.user.id, event_type=EventType.ITEM_CLICKED)) == 1


def test_clicking_without_an_explanation_raises_instead_of_calling_a_provider(
    db_session: Session, study_clock: MutableClock
) -> None:
    """Ready invariant 위반 신호다. 여기서 조용히 생성하면 위반이 영영 안 드러난다."""
    scene = _scene(db_session, with_explanation=False)

    with pytest.raises(ExplanationMissingError):
        click_item(
            db_session,
            user_id=scene.user.id,
            presentation_id=scene.presentation.id,
            sentence_item_id=scene.sentence_item.id,
            client_event_id=uuid.uuid4(),
            now=study_clock.now(),
            cfg=get_config(),
        )


def test_a_draft_explanation_is_not_served(db_session: Session, study_clock: MutableClock) -> None:
    scene = _scene(db_session, with_explanation=False)
    factories.make_explanation(db_session, scene.sentence_item, status=ExplanationStatus.DRAFT)

    with pytest.raises(ExplanationMissingError):
        click_item(
            db_session,
            user_id=scene.user.id,
            presentation_id=scene.presentation.id,
            sentence_item_id=scene.sentence_item.id,
            client_event_id=uuid.uuid4(),
            now=study_clock.now(),
            cfg=get_config(),
        )


def test_an_item_from_another_sentence_is_not_found(
    db_session: Session, study_clock: MutableClock
) -> None:
    """문장 소속을 확인하지 않으면 화면에 없던 표현에 evidence를 붙일 수 있다."""
    scene = _scene(db_session)
    other_sentence = factories.make_sentence(db_session)
    other_item = factories.make_learning_item(db_session)
    foreign = factories.make_sentence_item(
        db_session, other_sentence, other_item, surface_form="任せる"
    )

    with pytest.raises(SentenceItemNotFoundError):
        click_item(
            db_session,
            user_id=scene.user.id,
            presentation_id=scene.presentation.id,
            sentence_item_id=foreign.id,
            client_event_id=uuid.uuid4(),
            now=study_clock.now(),
            cfg=get_config(),
        )


def test_clicking_someone_elses_presentation_is_not_found(
    db_session: Session, study_clock: MutableClock
) -> None:
    scene = _scene(db_session)
    intruder = factories.make_user(db_session)

    with pytest.raises(PresentationNotFoundError):
        click_item(
            db_session,
            user_id=intruder.id,
            presentation_id=scene.presentation.id,
            sentence_item_id=scene.sentence_item.id,
            client_event_id=uuid.uuid4(),
            now=study_clock.now(),
            cfg=get_config(),
        )


def test_revealing_the_explanation_records_an_event(
    db_session: Session, study_clock: MutableClock
) -> None:
    scene = _scene(db_session)

    reveal_explanation(
        db_session,
        user_id=scene.user.id,
        presentation_id=scene.presentation.id,
        sentence_item_id=scene.sentence_item.id,
        client_event_id=uuid.uuid4(),
        now=study_clock.now(),
        cfg=get_config(),
    )

    events = _events(db_session, user_id=scene.user.id, event_type=EventType.EXPLANATION_REVEALED)
    assert [event.learning_item_id for event in events] == [scene.item.id]
    assert _mastery(db_session, scene) is None


def test_revealing_the_translation_returns_it_and_records_the_event(
    db_session: Session, study_clock: MutableClock
) -> None:
    scene = _scene(db_session)

    translation = reveal_translation(
        db_session,
        user_id=scene.user.id,
        presentation_id=scene.presentation.id,
        client_event_id=uuid.uuid4(),
        now=study_clock.now(),
        cfg=get_config(),
    )

    assert translation == scene.sentence.korean_translation
    assert (
        len(_events(db_session, user_id=scene.user.id, event_type=EventType.TRANSLATION_REVEALED))
        == 1
    )


# --------------------------------------------------------------------------
# self-report
# --------------------------------------------------------------------------


def test_unknown_records_mastery_and_an_again_review(
    db_session: Session, study_clock: MutableClock
) -> None:
    """Core E2E 5~7단계. `몰랐음`은 mastery observation 0.0 + FSRS Again이다."""
    cfg = get_config()
    scene = _scene(db_session)
    _activate_target(db_session, scene)

    self_report(
        db_session,
        user_id=scene.user.id,
        presentation_id=scene.presentation.id,
        sentence_item_id=scene.sentence_item.id,
        signal=ExplicitSignal.UNKNOWN,
        client_event_id=uuid.uuid4(),
        now=study_clock.now(),
        cfg=cfg,
    )

    mastery = _mastery(db_session, scene)
    assert mastery is not None
    assert mastery.comprehension_mastery == 0.0
    assert mastery.evidence_count == 1
    state = _review_state(db_session, scene)
    assert state is not None
    assert state.reps == 1
    assert state.lapses == 1


def test_resending_a_self_report_does_not_move_mastery_twice(
    db_session: Session, study_clock: MutableClock
) -> None:
    """불변식 #10. row가 중복되지 않는 것만으로는 idempotency가 아니다."""
    cfg = get_config()
    scene = _scene(db_session)
    _activate_target(db_session, scene)
    key = uuid.uuid4()

    for _ in range(2):
        self_report(
            db_session,
            user_id=scene.user.id,
            presentation_id=scene.presentation.id,
            sentence_item_id=scene.sentence_item.id,
            signal=ExplicitSignal.UNCERTAIN,
            client_event_id=key,
            now=study_clock.now(),
            cfg=cfg,
        )

    mastery = _mastery(db_session, scene)
    assert mastery is not None
    assert mastery.evidence_count == 1
    state = _review_state(db_session, scene)
    assert state is not None
    assert state.reps == 1
    assert (
        len(_events(db_session, user_id=scene.user.id, event_type=EventType.SELF_REPORT_UNCERTAIN))
        == 1
    )


def test_unknown_on_an_incidental_item_promotes_it(
    db_session: Session, study_clock: MutableClock
) -> None:
    """Scenario F. click 뒤의 `몰랐음`이 학습 target으로 활성화한다."""
    cfg = get_config()
    scene = _scene(db_session)

    self_report(
        db_session,
        user_id=scene.user.id,
        presentation_id=scene.presentation.id,
        sentence_item_id=scene.sentence_item.id,
        signal=ExplicitSignal.UNKNOWN,
        client_event_id=uuid.uuid4(),
        now=study_clock.now(),
        cfg=cfg,
    )

    learning_state = _learning_state(db_session, scene)
    assert learning_state is not None
    assert learning_state.is_active_learning_target is True
    assert _review_state(db_session, scene) is not None


def test_known_on_an_incidental_item_does_not_register_it_in_srs(
    db_session: Session, study_clock: MutableClock
) -> None:
    """`알고 있었음`이면 SRS 신규 item으로 강제 등록하지 않는다(02_LEARNING_POLICY.md).

    mastery는 남는다 --- 사용자가 말한 것은 그 자체로 evidence다.
    """
    cfg = get_config()
    scene = _scene(db_session)

    self_report(
        db_session,
        user_id=scene.user.id,
        presentation_id=scene.presentation.id,
        sentence_item_id=scene.sentence_item.id,
        signal=ExplicitSignal.KNOWN,
        client_event_id=uuid.uuid4(),
        now=study_clock.now(),
        cfg=cfg,
    )

    assert _review_state(db_session, scene) is None
    learning_state = _learning_state(db_session, scene)
    assert learning_state is None or learning_state.is_active_learning_target is False
    mastery = _mastery(db_session, scene)
    assert mastery is not None


def test_known_on_an_item_already_in_srs_is_recorded(
    db_session: Session, study_clock: MutableClock
) -> None:
    """Scenario C. 진행 중인 복습에서의 `알고 있었음`은 Good으로 기록된다."""
    cfg = get_config()
    scene = _scene(db_session, role=PresentationRole.REVIEW)
    # fsrs 6의 `Learning`. `Review`(2)는 stability가 채워져 있어야 하는데 그 값을
    # 손으로 지어내면 테스트가 FSRS 내부 수치에 의존하게 된다.
    state = factories.make_review_state(
        db_session, scene.user, scene.item, state=1, params_version=FSRS_PARAMS_VERSION
    )
    state.step = 0
    db_session.flush()

    self_report(
        db_session,
        user_id=scene.user.id,
        presentation_id=scene.presentation.id,
        sentence_item_id=scene.sentence_item.id,
        signal=ExplicitSignal.KNOWN,
        client_event_id=uuid.uuid4(),
        now=study_clock.now(),
        cfg=cfg,
    )

    assert state.reps == 1
    assert state.lapses == 0
    # 최소 5회 노출을 위해 interval을 cap하지 않는다(불변식 #4).
    assert state.next_review_at > study_clock.now()


def test_the_mastery_alpha_comes_from_config(
    db_session: Session, study_clock: MutableClock
) -> None:
    """두 신호는 **다른 노출**에 있어야 한다. 한 노출의 evidence는 1건이다(ADR-018)."""
    cfg = get_config()
    scene = _scene(db_session)
    _activate_target(db_session, scene)
    later = _another_exposure(db_session, scene)

    self_report(
        db_session,
        user_id=scene.user.id,
        presentation_id=scene.presentation.id,
        sentence_item_id=scene.sentence_item.id,
        signal=ExplicitSignal.KNOWN,
        client_event_id=uuid.uuid4(),
        now=study_clock.now(),
        cfg=cfg,
    )
    self_report(
        db_session,
        user_id=scene.user.id,
        presentation_id=later.id,
        sentence_item_id=scene.sentence_item.id,
        signal=ExplicitSignal.UNKNOWN,
        client_event_id=uuid.uuid4(),
        now=study_clock.now(),
        cfg=cfg,
    )

    mastery = _mastery(db_session, scene)
    assert mastery is not None
    assert mastery.comprehension_mastery == pytest.approx(
        0.8 * (1.0 - cfg.learning.mastery_ema_alpha)
    )


# --------------------------------------------------------------------------
# probe 응답
# --------------------------------------------------------------------------


def test_a_probe_answer_uses_the_item_from_the_probe_event(
    db_session: Session, study_clock: MutableClock
) -> None:
    cfg = get_config()
    scene = _scene(db_session)
    _activate_target(db_session, scene)
    probe = _show_probe(db_session, scene, study_clock)

    result = respond_to_probe(
        db_session,
        user_id=scene.user.id,
        presentation_id=scene.presentation.id,
        probe_id=probe.id,
        signal=ExplicitSignal.UNCERTAIN,
        client_event_id=uuid.uuid4(),
        now=study_clock.now(),
        cfg=cfg,
    )

    assert result.learning_item_id == scene.item.id
    mastery = _mastery(db_session, scene)
    assert mastery is not None
    assert mastery.comprehension_mastery == 0.4
    state = _review_state(db_session, scene)
    assert state is not None
    assert state.reps == 1


def test_skipping_a_probe_is_not_evidence(db_session: Session, study_clock: MutableClock) -> None:
    """Scenario G. skip은 mastery evidence도 FSRS grade도 아니다."""
    cfg = get_config()
    scene = _scene(db_session)
    _activate_target(db_session, scene)
    probe = _show_probe(db_session, scene, study_clock)

    respond_to_probe(
        db_session,
        user_id=scene.user.id,
        presentation_id=scene.presentation.id,
        probe_id=probe.id,
        signal=None,
        client_event_id=uuid.uuid4(),
        now=study_clock.now(),
        cfg=cfg,
    )

    assert _mastery(db_session, scene) is None
    assert _review_state(db_session, scene) is None
    learning_state = _learning_state(db_session, scene)
    assert learning_state is not None
    assert learning_state.probe_skip_count == 1
    assert learning_state.last_probe_at == study_clock.now()
    assert (
        len(_events(db_session, user_id=scene.user.id, event_type=EventType.MASTERY_PROBE_SKIPPED))
        == 1
    )


def test_a_second_answer_to_the_same_probe_returns_the_first(
    db_session: Session, study_clock: MutableClock
) -> None:
    """probe 하나에 응답은 최대 1건이다(05_API_SPEC.md)."""
    cfg = get_config()
    scene = _scene(db_session)
    _activate_target(db_session, scene)
    probe = _show_probe(db_session, scene, study_clock)
    respond_to_probe(
        db_session,
        user_id=scene.user.id,
        presentation_id=scene.presentation.id,
        probe_id=probe.id,
        signal=ExplicitSignal.KNOWN,
        client_event_id=uuid.uuid4(),
        now=study_clock.now(),
        cfg=cfg,
    )

    result = respond_to_probe(
        db_session,
        user_id=scene.user.id,
        presentation_id=scene.presentation.id,
        probe_id=probe.id,
        signal=ExplicitSignal.UNKNOWN,
        client_event_id=uuid.uuid4(),
        now=study_clock.now(),
        cfg=cfg,
    )

    assert result.signal is ExplicitSignal.KNOWN
    mastery = _mastery(db_session, scene)
    assert mastery is not None
    assert mastery.evidence_count == 1
    assert (
        _events(db_session, user_id=scene.user.id, event_type=EventType.MASTERY_PROBE_UNKNOWN) == []
    )


def test_a_probe_id_from_another_presentation_is_rejected(
    db_session: Session, study_clock: MutableClock
) -> None:
    cfg = get_config()
    scene = _scene(db_session)
    other = _scene(db_session)
    probe = _show_probe(db_session, other, study_clock)

    with pytest.raises(ProbeNotFoundError):
        respond_to_probe(
            db_session,
            user_id=scene.user.id,
            presentation_id=scene.presentation.id,
            probe_id=probe.id,
            signal=ExplicitSignal.KNOWN,
            client_event_id=uuid.uuid4(),
            now=study_clock.now(),
            cfg=cfg,
        )


def test_a_probe_id_that_is_not_a_probe_event_is_rejected(
    db_session: Session, study_clock: MutableClock
) -> None:
    cfg = get_config()
    scene = _scene(db_session)
    clicked = factories.make_event(
        db_session,
        scene.user,
        scene.study_session,
        client_event_id=uuid.uuid4(),
        event_type=EventType.ITEM_CLICKED,
        presentation=scene.presentation,
        item=scene.item,
    )

    with pytest.raises(ProbeNotFoundError):
        respond_to_probe(
            db_session,
            user_id=scene.user.id,
            presentation_id=scene.presentation.id,
            probe_id=clicked.id,
            signal=ExplicitSignal.KNOWN,
            client_event_id=uuid.uuid4(),
            now=study_clock.now(),
            cfg=cfg,
        )


# --------------------------------------------------------------------------
# 노출당 evidence 1건 (07_SRS_SPEC.md, ADR-018)
# --------------------------------------------------------------------------


def test_a_second_self_report_on_the_same_exposure_is_rejected(
    db_session: Session, study_clock: MutableClock
) -> None:
    """다른 UUIDv4로 보낸 2회차는 409이고 EMA도 `reps`도 다시 움직이지 않는다.

    프론트에서 버튼을 잠그는 것으로는 재시도/두 탭/직접 호출에 뚫린다. 뚫린 결과가
    mastery와 `review_states`에 조용히 남으므로 서버가 막는다.
    """
    cfg = get_config()
    scene = _scene(db_session)
    _activate_target(db_session, scene)
    self_report(
        db_session,
        user_id=scene.user.id,
        presentation_id=scene.presentation.id,
        sentence_item_id=scene.sentence_item.id,
        signal=ExplicitSignal.UNKNOWN,
        client_event_id=uuid.uuid4(),
        now=study_clock.now(),
        cfg=cfg,
    )

    with pytest.raises(EvidenceAlreadyRecordedError):
        self_report(
            db_session,
            user_id=scene.user.id,
            presentation_id=scene.presentation.id,
            sentence_item_id=scene.sentence_item.id,
            signal=ExplicitSignal.KNOWN,
            client_event_id=uuid.uuid4(),
            now=study_clock.now(),
            cfg=cfg,
        )

    mastery = _mastery(db_session, scene)
    assert mastery is not None
    assert mastery.evidence_count == 1
    # 2회차로 덮어쓰지 않는다. `몰랐음`의 observation 0.0이 그 노출에 고정된다.
    assert mastery.comprehension_mastery == 0.0
    state = _review_state(db_session, scene)
    assert state is not None
    assert state.reps == 1
    # event row 자체가 만들어지지 않는다. 기록해 놓고 효과만 건너뛰면 raw history가
    # "두 번 답했다"로 남는다.
    assert _events(db_session, user_id=scene.user.id, event_type=EventType.SELF_REPORT_KNOWN) == []


def test_the_cap_counts_learning_items_not_sentence_items(
    db_session: Session, study_clock: MutableClock
) -> None:
    """판정 단위는 `learning_item`이다.

    한 문장에 같은 learning item을 가리키는 sentence item이 둘 있을 때
    `sentence_item` 단위로 세는 규칙은 evidence 2건을 통과시킨다.
    """
    cfg = get_config()
    scene = _scene(db_session)
    _activate_target(db_session, scene)
    twin = factories.make_sentence_item(db_session, scene.sentence, scene.item, surface_form="任せ")
    self_report(
        db_session,
        user_id=scene.user.id,
        presentation_id=scene.presentation.id,
        sentence_item_id=scene.sentence_item.id,
        signal=ExplicitSignal.UNKNOWN,
        client_event_id=uuid.uuid4(),
        now=study_clock.now(),
        cfg=cfg,
    )

    with pytest.raises(EvidenceAlreadyRecordedError):
        self_report(
            db_session,
            user_id=scene.user.id,
            presentation_id=scene.presentation.id,
            sentence_item_id=twin.id,
            signal=ExplicitSignal.KNOWN,
            client_event_id=uuid.uuid4(),
            now=study_clock.now(),
            cfg=cfg,
        )

    mastery = _mastery(db_session, scene)
    assert mastery is not None
    assert mastery.evidence_count == 1


def test_a_probe_answer_after_a_self_report_on_the_same_item_is_rejected(
    db_session: Session, study_clock: MutableClock
) -> None:
    """두 evidence 경로를 합쳐 센다. 한쪽만 막으면 상한이 성립하지 않는다.

    probe 후보는 그 presentation의 target item이므로 이 순서는 실제로 도달 가능하다.
    """
    cfg = get_config()
    scene = _scene(db_session)
    _activate_target(db_session, scene)
    probe = _show_probe(db_session, scene, study_clock)
    self_report(
        db_session,
        user_id=scene.user.id,
        presentation_id=scene.presentation.id,
        sentence_item_id=scene.sentence_item.id,
        signal=ExplicitSignal.KNOWN,
        client_event_id=uuid.uuid4(),
        now=study_clock.now(),
        cfg=cfg,
    )

    with pytest.raises(EvidenceAlreadyRecordedError):
        respond_to_probe(
            db_session,
            user_id=scene.user.id,
            presentation_id=scene.presentation.id,
            probe_id=probe.id,
            signal=ExplicitSignal.UNKNOWN,
            client_event_id=uuid.uuid4(),
            now=study_clock.now(),
            cfg=cfg,
        )

    mastery = _mastery(db_session, scene)
    assert mastery is not None
    assert mastery.evidence_count == 1
    assert (
        _events(db_session, user_id=scene.user.id, event_type=EventType.MASTERY_PROBE_UNKNOWN) == []
    )
    # 응답을 기록하지 않았으므로 `last_probe_at`도 움직이지 않는다.
    learning_state = _learning_state(db_session, scene)
    assert learning_state is not None
    assert learning_state.last_probe_at is None


def test_a_self_report_after_a_probe_skip_is_allowed(
    db_session: Session, study_clock: MutableClock
) -> None:
    """skip은 evidence가 아니므로 상한에 걸리지 않는다(02_LEARNING_POLICY.md의 `Skip`).

    세는 집합에 `mastery_probe_skipped`가 들어가면 이 테스트가 빨개진다.
    """
    cfg = get_config()
    scene = _scene(db_session)
    _activate_target(db_session, scene)
    probe = _show_probe(db_session, scene, study_clock)
    respond_to_probe(
        db_session,
        user_id=scene.user.id,
        presentation_id=scene.presentation.id,
        probe_id=probe.id,
        signal=None,
        client_event_id=uuid.uuid4(),
        now=study_clock.now(),
        cfg=cfg,
    )

    self_report(
        db_session,
        user_id=scene.user.id,
        presentation_id=scene.presentation.id,
        sentence_item_id=scene.sentence_item.id,
        signal=ExplicitSignal.UNKNOWN,
        client_event_id=uuid.uuid4(),
        now=study_clock.now(),
        cfg=cfg,
    )

    mastery = _mastery(db_session, scene)
    assert mastery is not None
    assert mastery.evidence_count == 1
    state = _review_state(db_session, scene)
    assert state is not None
    assert state.reps == 1


def test_a_probe_skip_after_a_self_report_is_allowed(
    db_session: Session, study_clock: MutableClock
) -> None:
    """skip은 상한 때문에 거부되지도 않는다. 물어본 사실은 남아야 한다."""
    cfg = get_config()
    scene = _scene(db_session)
    _activate_target(db_session, scene)
    probe = _show_probe(db_session, scene, study_clock)
    self_report(
        db_session,
        user_id=scene.user.id,
        presentation_id=scene.presentation.id,
        sentence_item_id=scene.sentence_item.id,
        signal=ExplicitSignal.KNOWN,
        client_event_id=uuid.uuid4(),
        now=study_clock.now(),
        cfg=cfg,
    )

    result = respond_to_probe(
        db_session,
        user_id=scene.user.id,
        presentation_id=scene.presentation.id,
        probe_id=probe.id,
        signal=None,
        client_event_id=uuid.uuid4(),
        now=study_clock.now(),
        cfg=cfg,
    )

    assert result.signal is None
    learning_state = _learning_state(db_session, scene)
    assert learning_state is not None
    assert learning_state.probe_skip_count == 1
    mastery = _mastery(db_session, scene)
    assert mastery is not None
    assert mastery.evidence_count == 1


# --------------------------------------------------------------------------
# 세션 활동 시각 (`touch()`)
# --------------------------------------------------------------------------


def test_interactions_alone_keep_the_session_from_timing_out(
    db_session: Session, study_clock: MutableClock
) -> None:
    """idle timeout은 "사용자가 떠났다"는 뜻이지 "Next를 안 눌렀다"가 아니다.

    한 문장을 오래 탐구하는 동안 `last_activity_at`이 멈춰 있으면 실제로 학습 중인
    세션이 `study_session_idle_timeout_minutes`를 넘겨 만료된다.
    """
    cfg = get_config()
    scene = _scene(db_session)
    timeout = timedelta(minutes=cfg.session.study_session_idle_timeout_minutes)

    # `/next`도 `/complete`도 누르지 않고 상호작용만 한다. 두 번에 걸쳐 timeout을
    # 넘기므로, 상호작용이 시각을 옮기지 않으면 두 번째 시점에서 만료된다.
    for _ in range(2):
        study_clock.advance(timeout - timedelta(minutes=1))
        click_item(
            db_session,
            user_id=scene.user.id,
            presentation_id=scene.presentation.id,
            sentence_item_id=scene.sentence_item.id,
            client_event_id=uuid.uuid4(),
            now=study_clock.now(),
            cfg=cfg,
        )

    resumed = start_or_resume(db_session, user=scene.user, now=study_clock.now(), cfg=cfg)
    assert resumed.resumed is True
    assert resumed.session.id == scene.study_session.id
    assert resumed.timed_out_session_id is None


def test_short_gaps_between_interactions_accumulate_active_seconds(
    db_session: Session, study_clock: MutableClock
) -> None:
    """상호작용 시간이 `/next` 시점의 긴 gap 하나로 뭉치면 0으로 버려진다."""
    cfg = get_config()
    scene = _scene(db_session)
    gap = timedelta(seconds=cfg.session.active_time_idle_gap_seconds - 1)

    study_clock.advance(gap)
    click_item(
        db_session,
        user_id=scene.user.id,
        presentation_id=scene.presentation.id,
        sentence_item_id=scene.sentence_item.id,
        client_event_id=uuid.uuid4(),
        now=study_clock.now(),
        cfg=cfg,
    )
    study_clock.advance(gap)
    reveal_translation(
        db_session,
        user_id=scene.user.id,
        presentation_id=scene.presentation.id,
        client_event_id=uuid.uuid4(),
        now=study_clock.now(),
        cfg=cfg,
    )

    assert scene.study_session.active_seconds == int(gap.total_seconds()) * 2
    assert scene.study_session.last_activity_at == study_clock.now()


@pytest.mark.parametrize(
    "interaction",
    ["explanation_revealed", "self_report", "probe_response", "flag"],
)
def test_every_state_changing_interaction_moves_the_activity_clock(
    db_session: Session, study_clock: MutableClock, interaction: str
) -> None:
    """하나라도 빠지면 그 endpoint만 쓰는 사용자가 idle로 밀려난다."""
    cfg = get_config()
    scene = _scene(db_session)
    _activate_target(db_session, scene)
    probe = _show_probe(db_session, scene, study_clock)
    study_clock.advance(timedelta(seconds=30))

    if interaction == "explanation_revealed":
        reveal_explanation(
            db_session,
            user_id=scene.user.id,
            presentation_id=scene.presentation.id,
            sentence_item_id=scene.sentence_item.id,
            client_event_id=uuid.uuid4(),
            now=study_clock.now(),
            cfg=cfg,
        )
    elif interaction == "self_report":
        self_report(
            db_session,
            user_id=scene.user.id,
            presentation_id=scene.presentation.id,
            sentence_item_id=scene.sentence_item.id,
            signal=ExplicitSignal.UNCERTAIN,
            client_event_id=uuid.uuid4(),
            now=study_clock.now(),
            cfg=cfg,
        )
    elif interaction == "probe_response":
        respond_to_probe(
            db_session,
            user_id=scene.user.id,
            presentation_id=scene.presentation.id,
            probe_id=probe.id,
            signal=None,
            client_event_id=uuid.uuid4(),
            now=study_clock.now(),
            cfg=cfg,
        )
    else:
        flag_content(
            db_session,
            user_id=scene.user.id,
            presentation_id=scene.presentation.id,
            reason=ContentFlagReason.UNNATURAL,
            note=None,
            client_event_id=uuid.uuid4(),
            now=study_clock.now(),
            cfg=cfg,
        )

    assert scene.study_session.last_activity_at == study_clock.now()
    assert scene.study_session.active_seconds == 30
