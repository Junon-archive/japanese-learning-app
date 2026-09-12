"""`EXPLAIN_ITEM` handler --- missing explanation repair job 전용 (`08_LLM_SPEC.md`).

payload는 `{sentence_item_id}`다. 응답은 `explanation` 객체 하나이며 **문장을 새로
만들지 않는다.** 받은 설명을 `status = validated`로 저장하면 그 문장이 Ready
invariant를 다시 만족하게 되고, 다음 materialization이 candidate로 만든다.

이미 `validated` explanation이 있으면 provider를 부르지 않고 `completed`로 끝낸다
(at-least-once 대비).

commit하지 않는다(G7).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.config import AppConfig
from app.jobs import persistence, queue
from app.jobs.persistence import Completion, NothingToDo, Provenance
from app.llm.prompts import UnknownPromptVersionError
from app.llm.provider import ProviderRequest, ProviderResult
from app.llm.schemas import SpanPayload
from app.llm.tasks import ExplainItemInput, build_explain_item_request, parse_explanation
from app.llm.validation import Rejection, validate_explanation
from app.models.content import Sentence, SentenceItem, SentenceItemExplanation, SentenceItemSpan
from app.models.enums import ExplanationStatus, LlmTaskType, StartingLevel
from app.models.jobs import GenerationJob

TASK_TYPE = LlmTaskType.EXPLAIN_ITEM

# `sentences.difficulty_json.label`을 읽을 수 없을 때 요청에 싣는 값. ladder의 가장
# 낮은 단계이며(가장 쉬운 설명), 학습 정책값이 아니라 프롬프트 context의 기본값이다.
# EXPLAIN_ITEM payload에는 user가 없어 `users.starting_level`을 읽을 수 없다.
_FALLBACK_LEVEL = StartingLevel.BEGINNER


@dataclass(frozen=True)
class ExplanationPlan:
    """`EXPLAIN_ITEM`의 실행 계획. 문장 하나의 item 하나에 설명을 붙인다."""

    request: ProviderRequest | None
    provenance: Provenance
    sentence_item_id: int

    def complete(
        self,
        db: Session,
        *,
        job: GenerationJob,
        response: ProviderResult | None,
        now: datetime,
    ) -> Completion:
        if response is None:  # pragma: no cover - runner가 request=None일 때만 부른다
            return persistence.complete_without_content(db, job=job, now=now)

        checked = validate_explanation(parse_explanation(response.text))
        if isinstance(checked, Rejection):
            return persistence.record_rejections(db, job=job, rejected=[checked])

        queue.mark_validated(db, job=job)
        return persistence.save_explanation(
            db,
            job=job,
            sentence_item_id=self.sentence_item_id,
            explanation=checked.explanation,
            provenance=self.provenance,
            now=now,
        )


def prepare(
    db: Session, *, job: GenerationJob, cfg: AppConfig, now: datetime
) -> ExplanationPlan | NothingToDo | queue.PermanentReason:
    """그 `sentence_item`의 문장·surface_form·span을 요청 context에 싣는다."""
    del cfg  # 이 task에는 정책값이 없다. 길이 상한도 문장을 만들지 않으므로 쓰지 않는다.
    payload = job.payload_json or {}
    sentence_item_id = payload.get("sentence_item_id")
    if not isinstance(sentence_item_id, int):
        return queue.PermanentReason.INVALID_PAYLOAD

    sentence_item = db.get(SentenceItem, sentence_item_id)
    if sentence_item is None:
        return queue.PermanentReason.MISSING_REFERENCE
    sentence = db.get(Sentence, sentence_item.sentence_id)
    if sentence is None:  # pragma: no cover - FK가 보장한다
        return queue.PermanentReason.MISSING_REFERENCE

    if _has_validated_explanation(db, sentence_item_id=sentence_item_id):
        # 다른 attempt가 이미 채웠다. 같은 설명을 다시 사는 것은 순수한 비용이다.
        return NothingToDo()

    provenance = persistence.active_provenance(db, task_type=TASK_TYPE, now=now)
    if provenance is None:
        return queue.PermanentReason.NO_ACTIVE_PROMPT_VERSION

    try:
        request = build_explain_item_request(
            ExplainItemInput(
                learner_level=_learner_level(sentence),
                japanese=sentence.japanese,
                surface_form=sentence_item.surface_form,
                spans=_spans(db, sentence_item_id=sentence_item_id),
            ),
            model=provenance.model,
            prompt_version=provenance.prompt_version,
        )
    except UnknownPromptVersionError:
        return queue.PermanentReason.NO_ACTIVE_PROMPT_VERSION

    return ExplanationPlan(
        request=request,
        provenance=provenance,
        sentence_item_id=sentence_item_id,
    )


def _has_validated_explanation(db: Session, *, sentence_item_id: int) -> bool:
    return (
        db.execute(
            sa.select(SentenceItemExplanation.id).where(
                SentenceItemExplanation.sentence_item_id == sentence_item_id,
                SentenceItemExplanation.status == ExplanationStatus.VALIDATED,
            )
        ).first()
        is not None
    )


def _spans(db: Session, *, sentence_item_id: int) -> tuple[SpanPayload, ...]:
    rows = db.execute(
        sa.select(SentenceItemSpan)
        .where(SentenceItemSpan.sentence_item_id == sentence_item_id)
        .order_by(SentenceItemSpan.span_order)
    ).scalars()
    return tuple(
        SpanPayload(
            start_codepoint=row.start_codepoint,
            end_codepoint=row.end_codepoint,
            span_order=row.span_order,
        )
        for row in rows
    )


def _learner_level(sentence: Sentence) -> str:
    """요청에 실을 learner level.

    `EXPLAIN_ITEM`의 payload에는 사용자가 없다(`09_BACKGROUND_JOBS.md`의 payload 표).
    `sentences`는 global content이고 이 job은 그 콘텐츠를 고치는 일이므로, 사용자
    대신 **그 문장 자신의 난이도 label**을 싣는다. 읽을 수 없으면 가장 낮은 단계다.
    """
    label = (sentence.difficulty_json or {}).get("label")
    known = next((level for level in StartingLevel if level.value == label), _FALLBACK_LEVEL)
    return known.value
