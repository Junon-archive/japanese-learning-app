"""생성 결과 영속화 (`08_LLM_SPEC.md`, ADR-015의 `트랜잭션 경계`).

여기 있는 테스트는 전부 `committed_db`를 쓴다. `persistence`가 검사받는 것이 정확히
"커밋된 뒤에 무엇이 남는가"이므로, 커밋이 SAVEPOINT release로 바뀌는 `db_session`
으로는 `completed`와 콘텐츠가 **같은** 커밋이었는지 볼 수 없다.

시각은 `study_clock`이 준다. 이 모듈은 `datetime.now()`를 부르지 않는다.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_config
from app.jobs import persistence, queue
from app.jobs.persistence import NewSentence, NothingToDo, Provenance
from app.llm.schemas import ExplanationPayload, ItemPayload, SentencePayload, SpanPayload
from app.llm.validation import Rejection, RejectionReason
from app.models.content import Sentence, SentenceItem, SentenceItemExplanation, SentenceItemSpan
from app.models.enums import (
    ExplanationStatus,
    GenerationJobStatus,
    LlmTaskType,
    SentenceSourceType,
    SentenceStatus,
    StartingLevel,
)
from app.models.jobs import GenerationJob
from app.normalization import normalized_sentence_hash
from tests import factories
from tests.clock import MutableClock

JAPANESE = "明日は君に任せる。"
SURFACE = "任せる"


@pytest.fixture
def db(committed_db: sessionmaker[Session]) -> Iterator[Session]:
    with committed_db() as session:
        yield session


def _provenance(clock: MutableClock) -> Provenance:
    """`prompt_versions` 행에서 온 값. 코드에 모델명을 박지 않는다."""
    return Provenance(
        provider="stub",
        model="test-model",
        prompt_version="sentence_gen_v1",
        generated_at=clock.now(),
    )


def _job(db: Session, *, key: str = "persistence-test") -> GenerationJob:
    job = factories.make_generation_job(
        db, idempotency_key=key, max_attempts=get_config().jobs.max_job_attempts
    )
    job.status = GenerationJobStatus.RUNNING
    db.commit()
    return job


def _payload(
    *,
    japanese: str = JAPANESE,
    label: str = "it0",
    explanation: ExplanationPayload | None = None,
    is_tappable: bool = True,
) -> SentencePayload:
    start = japanese.index(SURFACE)
    return SentencePayload(
        japanese=japanese,
        korean_translation="내일은 너에게 맡길게.",
        difficulty_label=StartingLevel.BEGINNER,
        items=(
            ItemPayload(
                item_ref=label,
                surface_form=SURFACE,
                is_tappable=is_tappable,
                spans=(
                    SpanPayload(
                        start_codepoint=start,
                        end_codepoint=start + len(SURFACE),
                        span_order=0,
                    ),
                ),
                explanation=explanation,
            ),
        ),
    )


def _explanation() -> ExplanationPayload:
    return ExplanationPayload(
        reading="まかせる",
        core_meaning="맡기다",
        meaning_in_context="그 일을 너에게 넘기다",
        nuance="일상 대화",
        example_sentence="あとは彼に任せるよ。",
        example_translation=None,
    )


def _new_sentence(item_id: int, **kwargs: object) -> NewSentence:
    payload = _payload(**kwargs)  # type: ignore[arg-type]
    return NewSentence(
        payload=payload,
        item_ids={payload.items[0].item_ref: item_id},
        parent_sentence_id=None,
    )


def _count(db: Session, model: type[object]) -> int:
    return int(db.execute(sa.select(sa.func.count()).select_from(model)).scalar_one())


def _result(job: GenerationJob) -> dict[str, Any]:
    """`result_ref`는 nullable이다. 없으면 그 자체가 실패다."""
    assert job.result_ref is not None
    return job.result_ref


# --------------------------------------------------------------------------
# Ready invariant (불변식 #6)
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_a_tappable_item_without_an_explanation_leaves_nothing_in_the_database(
    db: Session, study_clock: MutableClock
) -> None:
    """저장 직전 재확인이 `validated` 승격을 막는다. `draft`로도 남지 않는다.

    validation을 우회해 직접 저장을 시도한다 --- 이 재확인을 지우면 "explanation
    없는 validated 문장"이 DB에 생기는 경로가 살아난다.
    """
    item = factories.make_learning_item(db)
    job = _job(db)
    db.commit()

    completion = persistence.save_sentences(
        db,
        job=job,
        sentences=[_new_sentence(item.id, explanation=None)],
        rejected=[],
        provenance=_provenance(study_clock),
        now=study_clock.now(),
    )

    assert completion.stored == ()
    assert [item.reason for item in completion.rejected] == [RejectionReason.MISSING_EXPLANATION]
    assert _count(db, Sentence) == 0
    assert _count(db, SentenceItem) == 0
    assert _count(db, SentenceItemSpan) == 0
    assert _count(db, SentenceItemExplanation) == 0
    # 저장한 것이 없으면 completed가 아니다. 사유만 남는다.
    stored_job = db.get(GenerationJob, job.id, populate_existing=True)
    assert stored_job is not None
    assert stored_job.status is GenerationJobStatus.RUNNING
    assert stored_job.result_ref == {
        "rejected": [
            {
                "reason": "missing_explanation",
                "detail": _result(stored_job)["rejected"][0]["detail"],
            }
        ]
    }


@pytest.mark.integration
def test_an_untappable_item_needs_no_explanation(db: Session, study_clock: MutableClock) -> None:
    """Ready invariant의 대상은 `is_tappable = true`인 item이다."""
    item = factories.make_learning_item(db)
    job = _job(db)
    db.commit()

    completion = persistence.save_sentences(
        db,
        job=job,
        sentences=[_new_sentence(item.id, explanation=None, is_tappable=False)],
        rejected=[],
        provenance=_provenance(study_clock),
        now=study_clock.now(),
    )

    assert len(completion.stored) == 1
    sentence = db.get(Sentence, completion.stored[0])
    assert sentence is not None
    assert sentence.status is SentenceStatus.VALIDATED


# --------------------------------------------------------------------------
# provenance
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_the_stored_content_carries_provenance_from_the_prompt_version_row(
    db: Session, study_clock: MutableClock
) -> None:
    """provider / model / prompt_version은 실행 context에서 온다. 응답에는 그 field가 없다."""
    item = factories.make_learning_item(db)
    job = _job(db)
    db.commit()
    provenance = _provenance(study_clock)

    completion = persistence.save_sentences(
        db,
        job=job,
        sentences=[_new_sentence(item.id, explanation=_explanation())],
        rejected=[],
        provenance=provenance,
        now=study_clock.now(),
    )

    sentence = db.get(Sentence, completion.stored[0])
    assert sentence is not None
    assert sentence.source_type is SentenceSourceType.GENERATED
    assert sentence.generation_job_id == job.id
    assert sentence.normalized_hash == normalized_sentence_hash(JAPANESE)
    assert sentence.difficulty_json == {"label": "beginner"}
    assert sentence.provenance_json == {
        "provider": "stub",
        "model": "test-model",
        "prompt_version": "sentence_gen_v1",
        "generated_at": study_clock.now().isoformat(),
    }

    explanation = db.execute(sa.select(SentenceItemExplanation)).scalar_one()
    assert (explanation.provider, explanation.model, explanation.prompt_version) == (
        "stub",
        "test-model",
        "sentence_gen_v1",
    )
    assert explanation.generated_at == study_clock.now()
    assert explanation.status is ExplanationStatus.VALIDATED

    stored_job = db.get(GenerationJob, job.id, populate_existing=True)
    assert stored_job is not None
    assert stored_job.status is GenerationJobStatus.COMPLETED
    assert _result(stored_job)["sentence_ids"] == [sentence.id]
    assert _result(stored_job)["rejected"] == []


@pytest.mark.integration
def test_parent_sentence_id_is_recorded_in_both_the_column_and_provenance(
    db: Session, study_clock: MutableClock
) -> None:
    """`near_original` lineage. 그 밖의 경우 provenance에 키 자체가 없다."""
    item = factories.make_learning_item(db)
    anchor = factories.make_sentence(db)
    job = _job(db)
    db.commit()
    payload = _payload(explanation=_explanation())

    completion = persistence.save_sentences(
        db,
        job=job,
        sentences=[
            NewSentence(
                payload=payload,
                item_ids={"it0": item.id},
                parent_sentence_id=anchor.id,
            )
        ],
        rejected=[],
        provenance=_provenance(study_clock),
        now=study_clock.now(),
    )

    sentence = db.get(Sentence, completion.stored[0])
    assert sentence is not None
    assert sentence.parent_sentence_id == anchor.id
    assert sentence.provenance_json["parent_sentence_id"] == anchor.id


# --------------------------------------------------------------------------
# at-least-once
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_storing_the_same_sentence_twice_for_the_same_job_creates_one_row(
    db: Session, study_clock: MutableClock
) -> None:
    """재실행이 같은 hash를 만나면 **이미 저장한 것**으로 보고 성공 처리한다.

    `normalized_hash`에 UNIQUE를 걸어 IntegrityError로 막는 대안은 "콘텐츠는 있는데
    job은 failed"라는 더 나쁜 상태를 만든다.
    """
    item = factories.make_learning_item(db)
    job = _job(db)
    db.commit()

    first = persistence.save_sentences(
        db,
        job=job,
        sentences=[_new_sentence(item.id, explanation=_explanation())],
        rejected=[],
        provenance=_provenance(study_clock),
        now=study_clock.now(),
    )
    job.status = GenerationJobStatus.RUNNING
    db.commit()
    second = persistence.save_sentences(
        db,
        job=job,
        sentences=[_new_sentence(item.id, explanation=_explanation())],
        rejected=[],
        provenance=_provenance(study_clock),
        now=study_clock.now(),
    )

    assert first.stored == second.stored
    assert second.rejected == ()
    assert _count(db, Sentence) == 1
    assert _count(db, SentenceItem) == 1


@pytest.mark.integration
def test_the_same_hash_from_another_job_is_a_duplicate(
    db: Session, study_clock: MutableClock
) -> None:
    """다른 job이 만든 같은 문장은 corpus 비교(11번)가 놓친 duplicate다.

    `detail`은 이 backstop이 잡았음을 밝힌다. 사유 코드는 11번과 같으므로, 표지가 없으면
    두 단계를 구별할 수 없다(`persistence.DUPLICATE_BACKSTOP_MARKER`).
    """
    item = factories.make_learning_item(db)
    other = factories.make_sentence(db, japanese=JAPANESE)
    job = _job(db)
    db.commit()

    completion = persistence.save_sentences(
        db,
        job=job,
        sentences=[_new_sentence(item.id, explanation=_explanation())],
        rejected=[],
        provenance=_provenance(study_clock),
        now=study_clock.now(),
    )

    assert completion.stored == ()
    assert [item.reason for item in completion.rejected] == [RejectionReason.DUPLICATE_HASH]
    assert completion.rejected[0].detail == (
        f"normalized_hash matches sentence {other.id} ({persistence.DUPLICATE_BACKSTOP_MARKER})"
    )
    assert _count(db, Sentence) == 1


@pytest.mark.integration
def test_a_failure_while_marking_completed_leaves_no_content_behind(
    db: Session, study_clock: MutableClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`completed`를 콘텐츠와 **다른** 커밋으로 나누면 이 테스트가 빨개진다.

    나누면 "저장은 됐는데 completed가 아닌" job이 남고, 그 job이 재실행되어 콘텐츠를
    두 번 만든다(ADR-015). 그 상태를 만드는 유일한 방법이 두 커밋 사이의 실패이므로
    여기서 그 지점을 실패시킨다.
    """

    def boom(*args: object, **kwargs: object) -> None:
        raise sa.exc.OperationalError("commit", None, Exception("connection lost"))

    item = factories.make_learning_item(db)
    job = _job(db)
    db.commit()
    monkeypatch.setattr(queue, "apply_completion", boom)

    with pytest.raises(persistence.PersistenceError):
        persistence.save_sentences(
            db,
            job=job,
            sentences=[_new_sentence(item.id, explanation=_explanation())],
            rejected=[],
            provenance=_provenance(study_clock),
            now=study_clock.now(),
        )

    assert _count(db, Sentence) == 0
    assert _count(db, SentenceItemExplanation) == 0
    stored_job = db.get(GenerationJob, job.id, populate_existing=True)
    assert stored_job is not None
    assert stored_job.status is GenerationJobStatus.RUNNING


# --------------------------------------------------------------------------
# 부분 수용과 완료 조건
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_one_bad_sentence_does_not_discard_the_good_ones(
    db: Session, study_clock: MutableClock
) -> None:
    """부분 수용. 탈락 건수와 사유는 `result_ref.rejected`에 함께 남는다."""
    item = factories.make_learning_item(db)
    job = _job(db)
    db.commit()

    completion = persistence.save_sentences(
        db,
        job=job,
        sentences=[
            _new_sentence(item.id, japanese="今日は君に任せる。", explanation=_explanation()),
            _new_sentence(item.id, japanese="明日も君に任せる。", explanation=None),
            _new_sentence(item.id, japanese="来週は君に任せる。", explanation=_explanation()),
        ],
        rejected=[Rejection(RejectionReason.SENTENCE_TOO_LONG, "60자 초과")],
        provenance=_provenance(study_clock),
        now=study_clock.now(),
    )

    assert len(completion.stored) == 2
    assert [item.reason.value for item in completion.rejected] == [
        "sentence_too_long",
        "missing_explanation",
    ]
    stored_job = db.get(GenerationJob, job.id, populate_existing=True)
    assert stored_job is not None
    assert stored_job.status is GenerationJobStatus.COMPLETED
    assert len(_result(stored_job)["sentence_ids"]) == 2
    assert [row["reason"] for row in _result(stored_job)["rejected"]] == [
        "sentence_too_long",
        "missing_explanation",
    ]


@pytest.mark.integration
def test_completion_and_content_land_in_the_same_commit(
    db: Session, study_clock: MutableClock, committed_db: sessionmaker[Session]
) -> None:
    """다른 커넥션에서 봤을 때 "문장은 있는데 job은 completed가 아닌" 순간이 없다.

    나누면 저장은 됐는데 completed가 아닌 job이 재실행되어 콘텐츠를 두 번 만든다
    (ADR-015).
    """
    item = factories.make_learning_item(db)
    job = _job(db)
    db.commit()

    persistence.save_sentences(
        db,
        job=job,
        sentences=[_new_sentence(item.id, explanation=_explanation())],
        rejected=[],
        provenance=_provenance(study_clock),
        now=study_clock.now(),
    )

    with committed_db() as observer:
        sentences = observer.execute(sa.select(Sentence.generation_job_id)).scalars().all()
        statuses = observer.execute(sa.select(GenerationJob.status)).scalars().all()
    assert sentences == [job.id]
    assert statuses == [GenerationJobStatus.COMPLETED]


@pytest.mark.integration
def test_nothing_to_do_completes_the_job_without_content(
    db: Session, study_clock: MutableClock
) -> None:
    """빈 결과는 실패가 아니다."""
    job = _job(db)
    db.commit()

    completion = NothingToDo().complete(db, job=job, response=None, now=study_clock.now())

    assert completion.stored == ()
    stored_job = db.get(GenerationJob, job.id, populate_existing=True)
    assert stored_job is not None
    assert stored_job.status is GenerationJobStatus.COMPLETED
    assert stored_job.finished_at == study_clock.now()
    assert _count(db, Sentence) == 0


# --------------------------------------------------------------------------
# EXPLAIN_ITEM 결과
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_a_stored_explanation_is_validated_and_carries_provenance(
    db: Session, study_clock: MutableClock
) -> None:
    item = factories.make_learning_item(db)
    sentence = factories.make_sentence(db)
    sentence_item = factories.make_sentence_item(db, sentence, item, surface_form=SURFACE)
    job = _job(db)
    db.commit()

    completion = persistence.save_explanation(
        db,
        job=job,
        sentence_item_id=sentence_item.id,
        explanation=_explanation(),
        provenance=_provenance(study_clock),
        now=study_clock.now(),
    )

    explanation = db.get(SentenceItemExplanation, completion.stored[0])
    assert explanation is not None
    assert explanation.status is ExplanationStatus.VALIDATED
    assert explanation.prompt_version == "sentence_gen_v1"
    stored_job = db.get(GenerationJob, job.id, populate_existing=True)
    assert stored_job is not None
    assert stored_job.status is GenerationJobStatus.COMPLETED
    assert _result(stored_job)["sentence_item_explanation_ids"] == [explanation.id]


# --------------------------------------------------------------------------
# provenance의 출처
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_the_active_prompt_version_row_is_the_only_source_of_model_and_provider(
    db: Session, study_clock: MutableClock
) -> None:
    factories.make_prompt_version(
        db,
        task_type=LlmTaskType.GENERATE_SENTENCE_BATCH,
        version="sentence_gen_v1",
        provider="stub",
        model="some-model-name",
    )
    db.commit()

    provenance = persistence.active_provenance(
        db, task_type=LlmTaskType.GENERATE_SENTENCE_BATCH, now=study_clock.now()
    )

    assert provenance == Provenance(
        provider="stub",
        model="some-model-name",
        prompt_version="sentence_gen_v1",
        generated_at=study_clock.now(),
    )


@pytest.mark.integration
def test_an_inactive_row_is_not_a_source(db: Session, study_clock: MutableClock) -> None:
    """active 행이 없으면 재시도해도 결과가 같다. 호출자는 `dead_letter`로 보낸다."""
    factories.make_prompt_version(
        db,
        task_type=LlmTaskType.GENERATE_SENTENCE_BATCH,
        version="sentence_gen_v1",
        active=False,
    )
    db.commit()

    assert (
        persistence.active_provenance(
            db, task_type=LlmTaskType.GENERATE_SENTENCE_BATCH, now=study_clock.now()
        )
        is None
    )
