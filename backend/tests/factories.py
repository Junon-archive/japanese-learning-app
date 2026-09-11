"""테스트용 최소 row 생성기.

NOT NULL을 채우는 것이 목적이다. 학습 정책값(mastery, interval, ratio 등)의
기본값을 여기에 두지 않는다 --- 정책은 config에서 주입해야 하고, factory에 숫자가
쌓이면 테스트가 조용히 그 숫자에 의존하게 된다.

id는 반환된 객체에서 읽어라. 롤백 격리는 시퀀스를 되돌리지 않으므로 `id == 1`을
가정하면 실행 순서에 따라 깨진다.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

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
    UserMastery,
    UserSentenceCandidate,
)
from app.models.enums import (
    CandidateStatus,
    ContextStage,
    EventType,
    ExposureModality,
    GenerationJobStatus,
    JobType,
    LearningItemOrigin,
    LearningItemType,
    PresentationRole,
    SentenceSourceType,
    SentenceStatus,
    StartingLevel,
)

NOW = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)

# 실제 hash가 아니다. 검증 경로를 타지 않는 자리 채우기 값이다.
_FAKE_HASH = "not-a-real-hash"


def _unique(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


def make_user(session: Session, *, login_id: str | None = None) -> User:
    user = User(
        login_id=login_id or _unique("user."),
        password_hash=_FAKE_HASH,
        timezone="Asia/Seoul",
        starting_level=StartingLevel.BEGINNER,
    )
    session.add(user)
    session.flush()
    return user


def make_learning_item(session: Session) -> LearningItem:
    item = LearningItem(
        type=LearningItemType.EXPRESSION,
        lemma="任せる",
        reading="まかせる",
        default_meaning="맡기다",
        origin=LearningItemOrigin.SEED,
    )
    session.add(item)
    session.flush()
    return item


def make_sentence(session: Session) -> Sentence:
    sentence = Sentence(
        japanese="それは君に任せる。",
        korean_translation="그건 너에게 맡길게.",
        source_type=SentenceSourceType.SEED,
        normalized_hash=_unique("hash-"),
        status=SentenceStatus.VALIDATED,
    )
    session.add(sentence)
    session.flush()
    return sentence


def make_study_session(session: Session, user: User, *, target_minutes: int) -> StudySession:
    """`target_minutes`는 config(default_session_minutes)에서 와야 하므로 필수 인자다."""
    study_session = StudySession(
        user_id=user.id,
        started_at=NOW,
        last_activity_at=NOW,
        target_minutes=target_minutes,
    )
    session.add(study_session)
    session.flush()
    return study_session


def make_candidate(
    session: Session, user: User, sentence: Sentence, *, status: CandidateStatus
) -> UserSentenceCandidate:
    candidate = UserSentenceCandidate(
        user_id=user.id,
        sentence_id=sentence.id,
        presentation_role=PresentationRole.NEW,
        context_stage=ContextStage.ANCHOR,
        status=status,
        updated_at=NOW,
    )
    session.add(candidate)
    session.flush()
    return candidate


def make_presentation(
    session: Session,
    user: User,
    study_session: StudySession,
    candidate: UserSentenceCandidate,
    sentence: Sentence,
) -> StudyPresentation:
    presentation = StudyPresentation(
        study_session_id=study_session.id,
        user_id=user.id,
        candidate_id=candidate.id,
        sentence_id=sentence.id,
        presentation_role=PresentationRole.NEW,
        context_stage=ContextStage.ANCHOR,
        shown_at=NOW,
    )
    session.add(presentation)
    session.flush()
    return presentation


def make_exposure(
    session: Session,
    user: User,
    item: LearningItem,
    presentation: StudyPresentation,
    sentence: Sentence,
) -> ItemExposure:
    exposure = ItemExposure(
        user_id=user.id,
        learning_item_id=item.id,
        study_presentation_id=presentation.id,
        sentence_id=sentence.id,
        modality=ExposureModality.READING,
        context_stage=ContextStage.ANCHOR,
    )
    session.add(exposure)
    session.flush()
    return exposure


def make_event(
    session: Session,
    user: User,
    study_session: StudySession,
    *,
    client_event_id: uuid.UUID,
    event_type: EventType = EventType.ITEM_CLICKED,
) -> LearningEvent:
    event = LearningEvent(
        user_id=user.id,
        study_session_id=study_session.id,
        event_type=event_type,
        client_event_id=client_event_id,
    )
    session.add(event)
    session.flush()
    return event


def make_generation_job(
    session: Session, *, idempotency_key: str, max_attempts: int
) -> GenerationJob:
    """`max_attempts`는 config(max_job_attempts)에서 오므로 필수 인자다."""
    job = GenerationJob(
        job_type=JobType.GENERATE_SENTENCE_BATCH,
        status=GenerationJobStatus.QUEUED,
        idempotency_key=idempotency_key,
        max_attempts=max_attempts,
        next_attempt_at=NOW,
    )
    session.add(job)
    session.flush()
    return job


def make_mastery(
    session: Session,
    user: User,
    item: LearningItem,
    *,
    comprehension_mastery: float | None,
    algorithm_version: str,
) -> UserMastery:
    mastery = UserMastery(
        user_id=user.id,
        learning_item_id=item.id,
        comprehension_mastery=comprehension_mastery,
        mastery_algorithm_version=algorithm_version,
        last_updated_at=NOW,
    )
    session.add(mastery)
    session.flush()
    return mastery


def make_review_state(
    session: Session,
    user: User,
    item: LearningItem,
    *,
    state: int,
    params_version: str,
) -> ReviewState:
    review_state = ReviewState(
        user_id=user.id,
        learning_item_id=item.id,
        state=state,
        next_review_at=NOW,
        fsrs_params_version=params_version,
    )
    session.add(review_state)
    session.flush()
    return review_state
