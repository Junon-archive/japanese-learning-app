"""`EXPLAIN_ITEM` handler --- missing explanation repair job (`08_LLM_SPEC.md`).

이 job의 목적은 하나다. explanation이 없어 Ready invariant를 만족하지 못하던 문장이
그 설명을 얻어 **다음 materialization에서 candidate가 되는 것**. 그래서 마지막
단정은 저장된 행이 아니라 `has_ready_sentence`다.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_config
from app.jobs import runner
from app.learning.selection import has_ready_sentence
from app.llm.prompts import explain_item as explain_item_prompt
from app.models.content import SentenceItem, SentenceItemExplanation
from app.models.enums import (
    ExplanationStatus,
    GenerationJobStatus,
    JobType,
    LlmTaskType,
)
from app.models.jobs import GenerationJob
from tests import factories
from tests.clock import MutableClock
from tests.llm_fixtures import explanation_payload
from tests.provider_double import RecordingProvider

COMPLETED = GenerationJobStatus.COMPLETED
RETRY = GenerationJobStatus.RETRY
DEAD_LETTER = GenerationJobStatus.DEAD_LETTER

JAPANESE = "それは君に任せる。"
SURFACE = "任せる"


@pytest.fixture
def db(committed_db: sessionmaker[Session]) -> Iterator[Session]:
    with committed_db() as session:
        yield session


def _prompt_version(db: Session) -> None:
    factories.make_prompt_version(
        db,
        task_type=LlmTaskType.EXPLAIN_ITEM,
        version=explain_item_prompt.VERSION,
    )


def _unexplained_item(db: Session) -> SentenceItem:
    """explanation만 없는 문장 하나. 그래서 아직 candidate가 될 수 없다."""
    item = factories.make_learning_item(db, lemma=SURFACE)
    sentence = factories.make_sentence(db, japanese=JAPANESE)
    sentence_item = factories.make_sentence_item(db, sentence, item, surface_form=SURFACE)
    start = JAPANESE.index(SURFACE)
    factories.make_span(db, sentence_item, start=start, end=start + len(SURFACE))
    db.commit()
    return sentence_item


def _job(db: Session, *, sentence_item_id: object) -> GenerationJob:
    job = factories.make_generation_job(
        db,
        idempotency_key=f"explain:{sentence_item_id}:2026-01-01",
        max_attempts=get_config().jobs.max_job_attempts,
    )
    job.job_type = JobType.EXPLAIN_ITEM
    job.payload_json = {"sentence_item_id": sentence_item_id}
    job.status = GenerationJobStatus.RUNNING
    job.retry_count = 1
    db.commit()
    return job


def _run(
    db: Session, job: GenerationJob, provider: RecordingProvider, clock: MutableClock
) -> GenerationJobStatus:
    return runner.run_job(db, job=job, provider=provider, cfg=get_config(), now=clock.now())


def _reload(db: Session, job: GenerationJob) -> GenerationJob:
    fresh = db.get(GenerationJob, job.id, populate_existing=True)
    assert fresh is not None
    return fresh


def _count_explanations(db: Session) -> int:
    return int(
        db.execute(sa.select(sa.func.count()).select_from(SentenceItemExplanation)).scalar_one()
    )


def _result(job: GenerationJob) -> dict[str, Any]:
    """`result_ref`는 nullable이다. 없으면 그 자체가 실패다."""
    assert job.result_ref is not None
    return job.result_ref


# --------------------------------------------------------------------------


@pytest.mark.integration
def test_the_repaired_sentence_satisfies_the_ready_invariant(
    db: Session, study_clock: MutableClock
) -> None:
    """설명이 붙는 순간 그 문장은 다시 candidate 후보가 된다."""
    sentence_item = _unexplained_item(db)
    assert not has_ready_sentence(db, learning_item_id=sentence_item.learning_item_id)
    _prompt_version(db)
    job = _job(db, sentence_item_id=sentence_item.id)
    provider = RecordingProvider(responses=[json.dumps(explanation_payload(), ensure_ascii=False)])

    status = _run(db, job, provider, study_clock)

    assert status is COMPLETED
    assert has_ready_sentence(db, learning_item_id=sentence_item.learning_item_id)
    explanation = db.execute(sa.select(SentenceItemExplanation)).scalar_one()
    assert explanation.sentence_item_id == sentence_item.id
    assert explanation.status is ExplanationStatus.VALIDATED
    assert (explanation.provider, explanation.model, explanation.prompt_version) == (
        "stub",
        "test-model",
        explain_item_prompt.VERSION,
    )
    assert explanation.generated_at == study_clock.now()
    assert _result(_reload(db, job))["sentence_item_explanation_ids"] == [explanation.id]


@pytest.mark.integration
def test_the_request_carries_the_sentence_the_surface_and_the_spans(
    db: Session, study_clock: MutableClock
) -> None:
    """문장을 새로 만들지 않는다. 모델은 이미 저장된 것을 설명하기만 한다."""
    sentence_item = _unexplained_item(db)
    _prompt_version(db)
    job = _job(db, sentence_item_id=sentence_item.id)
    provider = RecordingProvider(responses=[json.dumps(explanation_payload(), ensure_ascii=False)])

    _run(db, job, provider, study_clock)

    context = json.loads(provider.calls[0].context)
    start = JAPANESE.index(SURFACE)
    assert context["japanese"] == JAPANESE
    assert context["surface_form"] == SURFACE
    assert context["spans"] == [
        {"start_codepoint": start, "end_codepoint": start + len(SURFACE), "span_order": 0}
    ]


@pytest.mark.integration
def test_an_existing_validated_explanation_costs_no_provider_call(
    db: Session, study_clock: MutableClock
) -> None:
    """at-least-once 대비. 이미 채워졌으면 같은 설명을 다시 사지 않는다."""
    sentence_item = _unexplained_item(db)
    factories.make_explanation(db, sentence_item)
    db.commit()
    _prompt_version(db)
    job = _job(db, sentence_item_id=sentence_item.id)
    provider = RecordingProvider(responses=[])

    status = _run(db, job, provider, study_clock)

    assert status is COMPLETED
    assert provider.call_count == 0
    assert _count_explanations(db) == 1
    assert _reload(db, job).status is COMPLETED


@pytest.mark.integration
def test_a_draft_explanation_does_not_satisfy_the_check(
    db: Session, study_clock: MutableClock
) -> None:
    """Ready invariant가 요구하는 것은 `status = validated`인 설명이다."""
    sentence_item = _unexplained_item(db)
    factories.make_explanation(db, sentence_item, status=ExplanationStatus.DRAFT)
    db.commit()
    _prompt_version(db)
    job = _job(db, sentence_item_id=sentence_item.id)
    provider = RecordingProvider(responses=[json.dumps(explanation_payload(), ensure_ascii=False)])

    status = _run(db, job, provider, study_clock)

    assert status is COMPLETED
    assert provider.call_count == 1
    assert has_ready_sentence(db, learning_item_id=sentence_item.learning_item_id)


@pytest.mark.integration
def test_an_incomplete_explanation_is_rejected_and_retried(
    db: Session, study_clock: MutableClock
) -> None:
    """검사 9: `example_translation`을 뺀 나머지 field는 비어 있을 수 없다."""
    sentence_item = _unexplained_item(db)
    _prompt_version(db)
    job = _job(db, sentence_item_id=sentence_item.id)
    provider = RecordingProvider(
        responses=[json.dumps(explanation_payload(nuance="  "), ensure_ascii=False)]
    )

    status = _run(db, job, provider, study_clock)

    assert status is RETRY
    assert _count_explanations(db) == 0
    stored = _reload(db, job)
    assert [row["reason"] for row in _result(stored)["rejected"]] == ["missing_explanation"]
    # 호출은 이미 일어났으므로 usage는 남는다.
    assert _result(stored)["usage"]["provider_calls"] == 1


@pytest.mark.integration
def test_a_payload_that_points_at_no_sentence_item_is_a_dead_letter(
    db: Session, study_clock: MutableClock
) -> None:
    sentence_item = _unexplained_item(db)
    _prompt_version(db)
    job = _job(db, sentence_item_id=sentence_item.id + 10_000)
    provider = RecordingProvider(responses=[])

    status = _run(db, job, provider, study_clock)

    assert status is DEAD_LETTER
    assert provider.call_count == 0
    assert _reload(db, job).last_error == "missing_reference"


@pytest.mark.integration
def test_a_payload_without_a_sentence_item_id_is_a_dead_letter(
    db: Session, study_clock: MutableClock
) -> None:
    _prompt_version(db)
    job = _job(db, sentence_item_id="not-an-id")
    provider = RecordingProvider(responses=[])

    status = _run(db, job, provider, study_clock)

    assert status is DEAD_LETTER
    assert _reload(db, job).last_error == "invalid_payload"
