"""테스트용 최소 row 생성기.

NOT NULL을 채우는 것이 목적이다. 학습 정책값(mastery, interval, ratio 등)의
기본값을 여기에 두지 않는다 --- 정책은 config에서 주입해야 하고, factory에 숫자가
쌓이면 테스트가 조용히 그 숫자에 의존하게 된다.

id는 반환된 객체에서 읽어라. 롤백 격리는 시퀀스를 되돌리지 않으므로 `id == 1`을
가정하면 실행 순서에 따라 깨진다.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models import (
    GenerationJob,
    ItemExposure,
    LearningEvent,
    LearningItem,
    ReviewState,
    Sentence,
    SentenceItem,
    SentenceItemExplanation,
    SentenceItemSpan,
    StudyPresentation,
    StudySession,
    User,
    UserItemLearningState,
    UserMastery,
    UserSentenceCandidate,
    UserSentenceCandidateTarget,
)
from app.models.enums import (
    CandidateStatus,
    ContextStage,
    EventType,
    ExplanationStatus,
    ExposureModality,
    GenerationJobStatus,
    JobType,
    LearningItemOrigin,
    LearningItemType,
    PresentationRole,
    ReviewReason,
    SentenceSourceType,
    SentenceStatus,
    StartingLevel,
)
from tests.clock import DEFAULT_START

# `created_at`에는 server_default가 없다(ADR-007). factory가 명시적으로 채운다.
# 값은 테스트 시계(`tests.clock`)와 같은 순간이어야 한다 --- 두 값이 갈리면
# "DB에 남은 시각"과 "요청이 본 시각"이 어긋나 시간 기반 단정이 거짓 통과한다.
NOW = DEFAULT_START

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
        created_at=NOW,
    )
    session.add(user)
    session.flush()
    return user


def make_learning_item(
    session: Session,
    *,
    lemma: str | None = None,
    difficulty_label: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> LearningItem:
    """`difficulty_label` / `metadata`는 exploration 정렬(06_LEARNING_ENGINE.md)의
    입력이므로 기본을 NULL/빈 값으로 둔다 --- factory가 정렬 기준을 몰래 정해 두면
    "정렬이 그 값을 본다"는 단정이 거짓 통과한다."""
    item = LearningItem(
        type=LearningItemType.EXPRESSION,
        lemma="任せる" if lemma is None else lemma,
        reading="まかせる",
        default_meaning="맡기다",
        difficulty_label=difficulty_label,
        origin=LearningItemOrigin.SEED,
        metadata_json={} if metadata is None else dict(metadata),
        created_at=NOW,
    )
    session.add(item)
    session.flush()
    return item


def make_sentence(
    session: Session,
    *,
    japanese: str | None = None,
    korean_translation: str | None = None,
    parent_sentence_id: int | None = None,
) -> Sentence:
    sentence = Sentence(
        japanese="それは君に任せる。" if japanese is None else japanese,
        korean_translation=(
            "그건 너에게 맡길게." if korean_translation is None else korean_translation
        ),
        source_type=SentenceSourceType.SEED,
        parent_sentence_id=parent_sentence_id,
        normalized_hash=_unique("hash-"),
        status=SentenceStatus.VALIDATED,
        created_at=NOW,
    )
    session.add(sentence)
    session.flush()
    return sentence


def make_ready_sentence(
    session: Session,
    items: Sequence[LearningItem],
    *,
    surfaces: Sequence[str] | None = None,
    parent_sentence_id: int | None = None,
) -> Sentence:
    """Ready invariant를 만족하는 문장 하나 (불변식 #6).

    surface를 순서대로 이어 붙여 본문을 만들고 그 위치를 그대로 span으로 쓴다.
    offset을 손으로 세면 문장을 한 글자 고칠 때마다 span이 조용히 어긋나고
    `build_render_segments`가 그때서야 터진다.

    tappable item마다 `validated` explanation을 둔다. 하나라도 빠지면 이 문장은
    애초에 candidate가 되지 못한다.
    """
    chosen = [item.lemma for item in items] if surfaces is None else list(surfaces)
    japanese = "".join(chosen)
    sentence = make_sentence(session, japanese=japanese, parent_sentence_id=parent_sentence_id)
    cursor = 0
    for item, surface in zip(items, chosen, strict=True):
        sentence_item = make_sentence_item(session, sentence, item, surface_form=surface)
        make_span(session, sentence_item, start=cursor, end=cursor + len(surface))
        make_explanation(session, sentence_item)
        cursor += len(surface)
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
    session: Session,
    user: User,
    sentence: Sentence,
    *,
    status: CandidateStatus,
    presentation_role: PresentationRole = PresentationRole.NEW,
    context_stage: ContextStage = ContextStage.ANCHOR,
) -> UserSentenceCandidate:
    """role/stage는 partial unique key의 일부라 호출자가 지정할 수 있어야 한다
    (`uq_user_sentence_candidates_active`)."""
    candidate = UserSentenceCandidate(
        user_id=user.id,
        sentence_id=sentence.id,
        presentation_role=presentation_role,
        context_stage=context_stage,
        status=status,
        updated_at=NOW,
        created_at=NOW,
    )
    session.add(candidate)
    session.flush()
    return candidate


def make_candidate_target(
    session: Session,
    candidate: UserSentenceCandidate,
    item: LearningItem,
    *,
    is_new_item: bool = False,
) -> UserSentenceCandidateTarget:
    target = UserSentenceCandidateTarget(
        candidate_id=candidate.id,
        learning_item_id=item.id,
        is_new_item=is_new_item,
    )
    session.add(target)
    session.flush()
    return target


def make_presentation(
    session: Session,
    user: User,
    study_session: StudySession,
    candidate: UserSentenceCandidate,
    sentence: Sentence,
    *,
    presentation_role: PresentationRole = PresentationRole.NEW,
    review_reason: ReviewReason | None = None,
    context_stage: ContextStage = ContextStage.ANCHOR,
    completed_at: datetime | None = None,
) -> StudyPresentation:
    """role은 무신호 처리 분기를 가르므로 호출자가 지정할 수 있어야 한다(07_SRS_SPEC.md)."""
    presentation = StudyPresentation(
        study_session_id=study_session.id,
        user_id=user.id,
        candidate_id=candidate.id,
        sentence_id=sentence.id,
        presentation_role=presentation_role,
        review_reason=review_reason,
        context_stage=context_stage,
        shown_at=NOW,
        completed_at=completed_at,
    )
    session.add(presentation)
    session.flush()
    return presentation


def make_sentence_item(
    session: Session,
    sentence: Sentence,
    item: LearningItem,
    *,
    surface_form: str,
    is_tappable: bool = True,
) -> SentenceItem:
    sentence_item = SentenceItem(
        sentence_id=sentence.id,
        learning_item_id=item.id,
        surface_form=surface_form,
        is_tappable=is_tappable,
        created_at=NOW,
    )
    session.add(sentence_item)
    session.flush()
    return sentence_item


def make_span(
    session: Session,
    sentence_item: SentenceItem,
    *,
    start: int,
    end: int,
    span_order: int = 0,
) -> SentenceItemSpan:
    """offset은 code point index다(04_DB_SPEC.md의 `sentence_item_spans`)."""
    span = SentenceItemSpan(
        sentence_item_id=sentence_item.id,
        start_codepoint=start,
        end_codepoint=end,
        span_order=span_order,
    )
    session.add(span)
    session.flush()
    return span


def make_explanation(
    session: Session,
    sentence_item: SentenceItem,
    *,
    status: ExplanationStatus = ExplanationStatus.VALIDATED,
) -> SentenceItemExplanation:
    explanation = SentenceItemExplanation(
        sentence_item_id=sentence_item.id,
        reading="まかせる",
        core_meaning="맡기다",
        meaning_in_context="그 일을 너에게 맡기다",
        nuance="일상 대화에서 쓰는 표현",
        example_sentence="あとは彼に任せるよ。",
        example_translation="나머지는 그에게 맡길게.",
        generated_at=NOW,
        status=status,
    )
    session.add(explanation)
    session.flush()
    return explanation


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
        created_at=NOW,
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
    presentation: StudyPresentation | None = None,
    item: LearningItem | None = None,
) -> LearningEvent:
    """무신호 판정은 `(presentation, learning_item)` 쌍을 보므로 둘을 붙일 수 있어야 한다."""
    event = LearningEvent(
        user_id=user.id,
        study_session_id=study_session.id,
        study_presentation_id=None if presentation is None else presentation.id,
        sentence_id=None if presentation is None else presentation.sentence_id,
        learning_item_id=None if item is None else item.id,
        event_type=event_type,
        client_event_id=client_event_id,
        created_at=NOW,
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
        created_at=NOW,
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


def make_learning_state(
    session: Session,
    user: User,
    item: LearningItem,
    *,
    context_stage: ContextStage = ContextStage.ANCHOR,
    is_active_learning_target: bool = False,
    anchor_sentence_id: int | None = None,
    passive_no_signal_count: int = 0,
    last_probe_at: datetime | None = None,
) -> UserItemLearningState:
    """`user_item_learning_state` 한 행.

    `context_stage` 전이의 canonical 정의는 `07_SRS_SPEC.md`의
    `전이 규칙 (MVP 확정)`이다(ADR-012): presentation을 닫는 단일 경로가 exposure를
    기록하는 그 트랜잭션에서 ladder를 움직인다. 따라서 stage는 **엔진 경로로
    쌓는 것이 원칙**이고, 이 factory로 stage를 직접 세우는 것은 그 노출을 실제로
    밟기 어려운 전제(예: 이미 뒤쪽 stage에 도달한 item)에 한정한다. 그렇게 쓰는
    테스트는 이유를 docstring에 적는다.

    `is_active_learning_target = True`인데 `review_states`가 없는 행을 만들 때는
    주의한다. 그 조합에 유효 exposure가 1건 이상 붙으면 `new`(exposure 0건만),
    `review`(`review_states` 필요), exploration(활성 target 제외) 어디에도 들지
    못해 **영구히 제시되지 않는다.** 지금 프로덕션에서는 승격이 항상 FSRS 기록을
    동반해 도달할 수 없는 상태지만, `interactions._apply_explicit_evidence`의 FSRS
    기록 조건이 완화되면 실제 굶주림이 된다.
    """
    state = UserItemLearningState(
        user_id=user.id,
        learning_item_id=item.id,
        anchor_sentence_id=anchor_sentence_id,
        context_stage=context_stage,
        passive_no_signal_count=passive_no_signal_count,
        last_probe_at=last_probe_at,
        is_active_learning_target=is_active_learning_target,
        updated_at=NOW,
    )
    session.add(state)
    session.flush()
    return state
