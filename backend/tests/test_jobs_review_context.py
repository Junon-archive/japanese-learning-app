"""`GENERATE_REVIEW_CONTEXT` handler (`08_LLM_SPEC.md`, `06_LEARNING_ENGINE.md`).

응답 스키마는 `GENERATE_SENTENCE_BATCH`와 같고 다른 것은 요청 context와 lineage다.
그래서 여기서 검사하는 것은 세 가지다: stage별 지시와 `parent_sentence_id`,
`near_original`의 similarity 면제, quarantined anchor에서의 정지(불변식 #7).
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
from app.llm.prompts import review_context as review_context_prompt
from app.models.content import Sentence
from app.models.enums import (
    ContextStage,
    GenerationJobStatus,
    JobType,
    LlmTaskType,
    SentenceSourceType,
    SentenceStatus,
)
from app.models.jobs import GenerationJob
from app.models.user import User
from tests import factories
from tests.clock import MutableClock
from tests.llm_fixtures import batch_response, item_payload, sentence_payload
from tests.provider_double import RecordingProvider

COMPLETED = GenerationJobStatus.COMPLETED
RETRY = GenerationJobStatus.RETRY
DEAD_LETTER = GenerationJobStatus.DEAD_LETTER

ANCHOR_JAPANESE = "それは君に任せる。"
SURFACE = "任せる"


@pytest.fixture
def db(committed_db: sessionmaker[Session]) -> Iterator[Session]:
    with committed_db() as session:
        yield session


def _prompt_version(db: Session) -> None:
    factories.make_prompt_version(
        db,
        task_type=LlmTaskType.GENERATE_REVIEW_CONTEXT,
        version=review_context_prompt.VERSION,
    )


def _job(
    db: Session,
    *,
    user: User,
    item_id: int,
    anchor_id: int,
    stage: ContextStage,
    payload: dict[str, object] | None = None,
) -> GenerationJob:
    job = factories.make_generation_job(
        db,
        idempotency_key=f"review_ctx:{user.id}:{item_id}:{stage.value}:2026-01-01",
        max_attempts=get_config().jobs.max_job_attempts,
    )
    job.job_type = JobType.GENERATE_REVIEW_CONTEXT
    job.payload_json = (
        {
            "user_id": user.id,
            "learning_item_id": item_id,
            "context_stage": stage.value,
            "anchor_sentence_id": anchor_id,
        }
        if payload is None
        else payload
    )
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


def _generated(db: Session) -> list[Sentence]:
    return list(
        db.execute(
            sa.select(Sentence)
            .where(Sentence.source_type == SentenceSourceType.GENERATED)
            .order_by(Sentence.id)
        )
        .scalars()
        .all()
    )


def _result(job: GenerationJob) -> dict[str, Any]:
    """`result_ref`는 nullable이다. 없으면 그 자체가 실패다."""
    assert job.result_ref is not None
    return job.result_ref


# --------------------------------------------------------------------------
# near_original
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_near_original_records_the_anchor_as_parent_and_skips_the_similarity_check(
    db: Session, study_clock: MutableClock
) -> None:
    """의도된 near-duplicate다. 12번(similarity)을 적용하지 않고 lineage를 남긴다.

    면제 판단은 요청 stage에서 나온다. 응답에는 그것을 실을 field가 없다.
    """
    user = factories.make_user(db)
    item = factories.make_learning_item(db, lemma=SURFACE)
    anchor = factories.make_ready_sentence(db, [item], surfaces=[ANCHOR_JAPANESE])
    _prompt_version(db)
    job = _job(
        db, user=user, item_id=item.id, anchor_id=anchor.id, stage=ContextStage.NEAR_ORIGINAL
    )
    # anchor와 한 글자만 다르다. similarity threshold(0.9)를 확실히 넘는다.
    japanese = "それは君に任せるよ。"
    provider = RecordingProvider(
        responses=[
            batch_response(sentence_payload(japanese, [item_payload("it0", SURFACE, japanese)]))
        ]
    )

    status = _run(db, job, provider, study_clock)

    assert status is COMPLETED
    stored = _generated(db)
    assert [row.japanese for row in stored] == [japanese]
    assert stored[0].parent_sentence_id == anchor.id
    assert stored[0].provenance_json["parent_sentence_id"] == anchor.id
    context = json.loads(provider.calls[0].context)
    assert context["context_stage"] == "near_original"
    assert context["anchor_japanese"] == ANCHOR_JAPANESE


@pytest.mark.integration
def test_varied_does_not_skip_the_similarity_check_and_records_no_parent(
    db: Session, study_clock: MutableClock
) -> None:
    """면제는 `near_original`만이다. `varied`에서 anchor를 베끼면 탈락한다."""
    user = factories.make_user(db)
    item = factories.make_learning_item(db, lemma=SURFACE)
    anchor = factories.make_ready_sentence(db, [item], surfaces=[ANCHOR_JAPANESE])
    _prompt_version(db)
    job = _job(db, user=user, item_id=item.id, anchor_id=anchor.id, stage=ContextStage.VARIED)
    japanese = "それは君に任せるよ。"
    provider = RecordingProvider(
        responses=[
            batch_response(sentence_payload(japanese, [item_payload("it0", SURFACE, japanese)]))
        ]
    )

    status = _run(db, job, provider, study_clock)

    assert status is RETRY
    assert _generated(db) == []
    assert [row["reason"] for row in _result(_reload(db, job))["rejected"]] == [
        "duplicate_similarity"
    ]


@pytest.mark.integration
def test_a_new_context_sentence_has_no_lineage(db: Session, study_clock: MutableClock) -> None:
    user = factories.make_user(db)
    item = factories.make_learning_item(db, lemma=SURFACE)
    anchor = factories.make_ready_sentence(db, [item], surfaces=[ANCHOR_JAPANESE])
    _prompt_version(db)
    job = _job(db, user=user, item_id=item.id, anchor_id=anchor.id, stage=ContextStage.NEW_CONTEXT)
    japanese = "今回の準備は後輩に任せる予定だ。"
    provider = RecordingProvider(
        responses=[
            batch_response(sentence_payload(japanese, [item_payload("it0", SURFACE, japanese)]))
        ]
    )

    status = _run(db, job, provider, study_clock)

    assert status is COMPLETED
    stored = _generated(db)
    assert stored[0].parent_sentence_id is None
    assert "parent_sentence_id" not in stored[0].provenance_json


# --------------------------------------------------------------------------
# 불변식 #7
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_a_quarantined_anchor_stops_the_job_without_creating_content(
    db: Session, study_clock: MutableClock
) -> None:
    """anchor 재지정은 request 경로(materialization)의 소관이다. worker는 흉내내지 않는다."""
    user = factories.make_user(db)
    item = factories.make_learning_item(db, lemma=SURFACE)
    anchor = factories.make_ready_sentence(db, [item], surfaces=[ANCHOR_JAPANESE])
    anchor.status = SentenceStatus.QUARANTINED
    db.commit()
    _prompt_version(db)
    job = _job(
        db, user=user, item_id=item.id, anchor_id=anchor.id, stage=ContextStage.NEAR_ORIGINAL
    )
    provider = RecordingProvider(responses=[])

    status = _run(db, job, provider, study_clock)

    assert status is COMPLETED
    assert provider.call_count == 0
    assert _generated(db) == []
    stored = _reload(db, job)
    assert stored.status is COMPLETED
    # anchor는 그대로다. worker가 다른 문장을 고르지 않는다.
    reloaded_anchor = db.get(Sentence, anchor.id, populate_existing=True)
    assert reloaded_anchor is not None
    assert reloaded_anchor.status is SentenceStatus.QUARANTINED


# --------------------------------------------------------------------------
# payload
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_a_payload_missing_the_stage_is_a_dead_letter(
    db: Session, study_clock: MutableClock
) -> None:
    user = factories.make_user(db)
    item = factories.make_learning_item(db)
    anchor = factories.make_sentence(db)
    _prompt_version(db)
    job = _job(
        db,
        user=user,
        item_id=item.id,
        anchor_id=anchor.id,
        stage=ContextStage.ANCHOR,
        payload={
            "user_id": user.id,
            "learning_item_id": item.id,
            "anchor_sentence_id": anchor.id,
        },
    )
    provider = RecordingProvider(responses=[])

    status = _run(db, job, provider, study_clock)

    assert status is DEAD_LETTER
    assert _reload(db, job).last_error == "invalid_payload"


@pytest.mark.integration
def test_a_payload_that_points_at_no_anchor_is_a_dead_letter(
    db: Session, study_clock: MutableClock
) -> None:
    user = factories.make_user(db)
    item = factories.make_learning_item(db)
    anchor = factories.make_sentence(db)
    _prompt_version(db)
    job = _job(
        db,
        user=user,
        item_id=item.id,
        anchor_id=anchor.id + 10_000,
        stage=ContextStage.VARIED,
    )
    provider = RecordingProvider(responses=[])

    status = _run(db, job, provider, study_clock)

    assert status is DEAD_LETTER
    assert provider.call_count == 0
    assert _reload(db, job).last_error == "missing_reference"
