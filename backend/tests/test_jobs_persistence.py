"""생성 결과 영속화 (`08_LLM_SPEC.md`, ADR-015의 `트랜잭션 경계`).

여기 있는 테스트는 전부 `committed_db`를 쓴다. `persistence`가 검사받는 것이 정확히
"커밋된 뒤에 무엇이 남는가"이므로, 커밋이 SAVEPOINT release로 바뀌는 `db_session`
으로는 `completed`와 콘텐츠가 **같은** 커밋이었는지 볼 수 없다.

시각은 `study_clock`이 준다. 이 모듈은 `datetime.now()`를 부르지 않는다.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence
from datetime import datetime
from typing import Any, Never

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_config
from app.furigana import RubyComputation, RubyItem
from app.jobs import observability, persistence, queue
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


# --------------------------------------------------------------------------
# 후리가나 (MVP-02, ADR-021 결정 4, 11_OBSERVABILITY.md)
#
# "明日は君に任せる。": 明0 日1 は2 君3 に4 任5 せ6 る7 。8, tappable `任せる` = [5, 8).
# --------------------------------------------------------------------------

RUBY_LOGGER = "app.jobs"


def _records(caplog: pytest.LogCaptureFixture, message: str) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.getMessage() == message]


def _save_one(db: Session, clock: MutableClock, **kwargs: object) -> Sentence:
    item = factories.make_learning_item(db)
    job = _job(db)
    completion = persistence.save_sentences(
        db,
        job=job,
        sentences=[_new_sentence(item.id, **kwargs)],
        rejected=[],
        provenance=_provenance(clock),
        now=clock.now(),
    )
    sentence = db.get(Sentence, completion.stored[0], populate_existing=True)
    assert sentence is not None
    return sentence


@pytest.mark.integration
def test_a_stored_sentence_carries_ruby_and_logs_counts_only(
    db: Session, study_clock: MutableClock, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger=RUBY_LOGGER):
        sentence = _save_one(db, study_clock, explanation=_explanation())

    assert sentence.status is SentenceStatus.VALIDATED
    assert sentence.ruby_json is not None
    assert sentence.ruby_json["spans"] == [[0, 2, "あした"], [3, 4, "きみ"], [5, 6, "まか"]]
    assert sentence.ruby_json["computed_at"] == study_clock.now().isoformat().replace("+00:00", "Z")
    (record,) = _records(caplog, observability.RUBY_COMPUTED)
    fields = {
        name: record.__dict__[name]
        for name in (
            "sentence_id",
            "algorithm_version",
            "spans",
            "omitted_tappable_boundary",
            "omitted_numeric",
            "omitted_no_reading",
            "corrected_explanation_tokens",
            "corrected_table_rules",
        )
    }
    assert fields == {
        "sentence_id": sentence.id,
        "algorithm_version": 2,
        "spans": 3,
        "omitted_tappable_boundary": 0,
        "omitted_numeric": 0,
        "omitted_no_reading": 0,
        "corrected_explanation_tokens": 1,
        "corrected_table_rules": 1,
    }
    # 문장 텍스트·읽기 문자열이 어떤 ruby 로그에도 없다.
    for ruby_record in caplog.records:
        if ruby_record.getMessage().startswith("ruby."):
            rendered = repr(ruby_record.__dict__)
            for text in ("明日", "任せる", "あした", "まか"):
                assert text not in rendered


@pytest.mark.integration
def test_the_text_and_spans_are_not_changed_by_ruby(db: Session, study_clock: MutableClock) -> None:
    sentence = _save_one(db, study_clock, explanation=_explanation())

    span = db.execute(sa.select(SentenceItemSpan)).scalar_one()
    assert sentence.japanese == JAPANESE
    assert (span.start_codepoint, span.end_codepoint, span.span_order) == (5, 8, 0)


@pytest.mark.integration
def test_a_reading_mismatch_is_logged_with_the_stored_sentence_item_id(
    db: Session, study_clock: MutableClock, caplog: pytest.LogCaptureFixture
) -> None:
    """계산은 payload 순번으로 하고, 로그는 flush 뒤 실제 `sentence_item_id`로 남긴다."""
    wrong = ExplanationPayload(**{**_explanation().model_dump(), "reading": "まかせ"})
    with caplog.at_level(logging.INFO, logger=RUBY_LOGGER):
        sentence = _save_one(db, study_clock, explanation=wrong)

    sentence_item = db.execute(sa.select(SentenceItem)).scalar_one()
    (record,) = _records(caplog, observability.RUBY_READING_MISMATCH)
    assert (record.__dict__["sentence_id"], record.__dict__["sentence_item_id"]) == (
        sentence.id,
        sentence_item.id,
    )
    assert _records(caplog, observability.RUBY_EXPLANATION_OVERRIDE) == []
    # 설명 데이터는 고치지 않는다.
    assert db.execute(sa.select(SentenceItemExplanation.reading)).scalar_one() == "まかせ"


@pytest.mark.integration
def test_an_explanation_override_is_logged_with_the_tappable_items_stored_id(
    db: Session, study_clock: MutableClock, caplog: pytest.LogCaptureFixture
) -> None:
    """AC 25: 계층 1 정렬이 성립했는데 분석기와 다르면 `ruby.explanation_override`다.

    앞에 non-tappable item을 두어 로그의 `sentence_item_id`가 payload 순번이 아니라 **그
    tappable item의 실제 id**임을 본다. 저장 ruby는 설명 읽기이고 설명 데이터는 그대로다.
    """
    plain = factories.make_learning_item(db)
    target = factories.make_learning_item(db)
    job = _job(db)
    explanation = ExplanationPayload(**{**_explanation().model_dump(), "reading": "にんせる"})
    payload = SentencePayload(
        japanese=JAPANESE,
        korean_translation="내일은 너에게 맡길게.",
        difficulty_label=StartingLevel.BEGINNER,
        items=(
            ItemPayload(
                item_ref="plain",
                surface_form="明日",
                is_tappable=False,
                spans=(SpanPayload(start_codepoint=0, end_codepoint=2, span_order=0),),
                explanation=None,
            ),
            ItemPayload(
                item_ref="target",
                surface_form=SURFACE,
                is_tappable=True,
                spans=(SpanPayload(start_codepoint=5, end_codepoint=8, span_order=0),),
                explanation=explanation,
            ),
        ),
    )

    with caplog.at_level(logging.INFO, logger=RUBY_LOGGER):
        completion = persistence.save_sentences(
            db,
            job=job,
            sentences=[
                NewSentence(
                    payload=payload,
                    item_ids={"plain": plain.id, "target": target.id},
                    parent_sentence_id=None,
                )
            ],
            rejected=[],
            provenance=_provenance(study_clock),
            now=study_clock.now(),
        )

    (sentence_id,) = completion.stored
    sentence = db.get(Sentence, sentence_id, populate_existing=True)
    assert sentence is not None
    assert sentence.status is SentenceStatus.VALIDATED
    assert sentence.ruby_json is not None
    assert [5, 6, "にん"] in sentence.ruby_json["spans"]
    tappable_item_id = db.execute(
        sa.select(SentenceItem.id).where(SentenceItem.is_tappable.is_(True))
    ).scalar_one()
    (record,) = _records(caplog, observability.RUBY_EXPLANATION_OVERRIDE)
    assert (record.__dict__["sentence_id"], record.__dict__["sentence_item_id"]) == (
        sentence_id,
        tappable_item_id,
    )
    assert _records(caplog, observability.RUBY_READING_MISMATCH) == []
    assert "にんせる" not in repr(record.__dict__) and "任せる" not in repr(record.__dict__)
    assert db.execute(sa.select(SentenceItemExplanation.reading)).scalar_one() == "にんせる"


@pytest.mark.integration
def test_a_failed_ruby_computation_still_stores_a_validated_sentence(
    db: Session,
    study_clock: MutableClock,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(japanese: str, items: Sequence[RubyItem], *, now: datetime) -> RubyComputation:
        raise RuntimeError("simulated ruby failure")

    monkeypatch.setattr(persistence, "compute_ruby", broken)

    with caplog.at_level(logging.INFO, logger=RUBY_LOGGER):
        sentence = _save_one(db, study_clock, explanation=_explanation())

    assert sentence.status is SentenceStatus.VALIDATED
    assert sentence.ruby_json is None
    # JSON `null`이 아니라 SQL NULL이어야 backfill 대상(`ruby_json IS NULL`)이다.
    assert db.scalar(sa.select(Sentence.id).where(Sentence.ruby_json.is_(None))) == sentence.id
    assert _count(db, SentenceItemExplanation) == 1
    (record,) = _records(caplog, observability.RUBY_FAILED)
    assert record.levelno == logging.WARNING
    assert record.__dict__["sentence_id"] == sentence.id
    assert record.__dict__["error"] == "RuntimeError: simulated ruby failure"
    assert _records(caplog, observability.RUBY_COMPUTED) == []


@pytest.mark.integration
def test_the_ready_invariant_still_rejects_without_any_ruby_log(
    db: Session, study_clock: MutableClock, caplog: pytest.LogCaptureFixture
) -> None:
    """되돌아간 문장에 대해 `ruby.computed`를 남기지 않는다(없는 sentence_id를 가리키게 된다)."""
    item = factories.make_learning_item(db)
    job = _job(db)
    with caplog.at_level(logging.INFO, logger=RUBY_LOGGER):
        completion = persistence.save_sentences(
            db,
            job=job,
            sentences=[_new_sentence(item.id, explanation=None)],
            rejected=[],
            provenance=_provenance(study_clock),
            now=study_clock.now(),
        )

    assert completion.stored == ()
    assert [record for record in caplog.records if record.getMessage().startswith("ruby.")] == []


@pytest.mark.integration
def test_saving_an_explanation_does_not_touch_ruby(
    db: Session, study_clock: MutableClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`EXPLAIN_ITEM`은 문장·span을 바꾸지 않으므로 ruby를 다시 계산하지 않는다."""
    item = factories.make_learning_item(db)
    sentence = factories.make_sentence(db)
    stored_ruby = {"spans": [[3, 4, "きみ"]], "marker": "unchanged"}
    sentence.ruby_json = stored_ruby
    sentence_item = factories.make_sentence_item(db, sentence, item, surface_form=SURFACE)
    job = _job(db)
    db.commit()

    def forbidden(*args: object, **kwargs: object) -> Never:
        raise AssertionError("save_explanation이 ruby를 계산했다")

    monkeypatch.setattr(persistence, "compute_ruby", forbidden)

    persistence.save_explanation(
        db,
        job=job,
        sentence_item_id=sentence_item.id,
        explanation=_explanation(),
        provenance=_provenance(study_clock),
        now=study_clock.now(),
    )

    reloaded = db.get(Sentence, sentence.id, populate_existing=True)
    assert reloaded is not None
    assert reloaded.ruby_json == stored_ruby


@pytest.mark.integration
def test_a_failing_ruby_log_does_not_block_storing_or_promotion(
    db: Session,
    study_clock: MutableClock,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """로그 단계의 예외가 저장 트랜잭션을 되돌리지 않는다. 문장은 validated, ruby_json은 저장된다."""

    def broken_log(**kwargs: object) -> Never:
        raise RuntimeError("simulated log failure")

    monkeypatch.setattr(observability, "log_ruby_computed", broken_log)

    with caplog.at_level(logging.WARNING, logger="app.jobs"):
        sentence = _save_one(db, study_clock, explanation=_explanation())

    assert sentence.status is SentenceStatus.VALIDATED
    assert sentence.ruby_json is not None
    job = db.execute(sa.select(GenerationJob)).scalar_one()
    assert job.status is GenerationJobStatus.COMPLETED
    (record,) = [r for r in caplog.records if r.getMessage() == observability.RUBY_LOG_FAILED]
    assert record.levelno == logging.WARNING
    assert (record.__dict__["sentence_id"], record.__dict__["error_type"]) == (
        sentence.id,
        "RuntimeError",
    )
