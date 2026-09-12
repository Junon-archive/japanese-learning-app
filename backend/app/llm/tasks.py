"""MVP task 3종의 요청 조립과 응답 파싱 (`08_LLM_SPEC.md`).

``` text
GENERATE_SENTENCE_BATCH   worker only
GENERATE_REVIEW_CONTEXT   worker only
EXPLAIN_ITEM              worker only (missing explanation repair job)
```

`ANALYZE_SENTENCE`는 MVP에 호출자가 없으므로 구현하지 않는다(Future).

`GENERATE_SENTENCE_BATCH`는 **한 번의 structured output으로** sentence /
translation / SentenceItems / spans / contextual explanation까지 만든다. 그래야
사용자가 item을 tap한 순간 live LLM fallback이 필요 없다.

요청 context는 `08_LLM_SPEC.md`의 `요청 context`가 canonical이다. 전체 mastery
목록을 보내지 않고, 사용자 식별자 / `login_id` / event 원문 / mastery 수치를
프롬프트에 싣지 않는다. `register` / `topic` / `tags`도 요청하지 않는다.

DB를 모른다(G11(a)). `model`과 `prompt_version`은 호출자가 `prompt_versions`
행에서 읽어 넘긴다.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from app.llm.prompts import PromptTemplate, template_for
from app.llm.provider import LlmError, ProviderRequest
from app.llm.schemas import ExplanationPayload, SentenceBatchPayload, SpanPayload, json_schema
from app.llm.validation import RejectionReason
from app.models.enums import ContextStage, LlmTaskType

SENTENCE_BATCH_SCHEMA_NAME = "sentence_batch"
EXPLANATION_SCHEMA_NAME = "explanation"


class SchemaParseError(LlmError):
    """검사 1: structured schema parsing 실패.

    깨진 JSON / 누락된 필수 field / 스키마에 없는 field / 허용값 밖의
    `difficulty_label`이 전부 여기로 온다. 사유 코드를 클래스에 붙여 두는 이유는
    `generation_jobs.result_ref.rejected` 집계가 검사 1~13을 **한 집합**으로 세기
    때문이다 --- 파싱 실패만 문자열을 손으로 적으면 그 자리에서 갈린다.
    """

    reason = RejectionReason.SCHEMA_PARSE_FAILED


@dataclass(frozen=True)
class TargetItem:
    """요청에 싣는 target 하나. DB id를 싣지 않는다.

    `item_ref`는 **요청 로컬 라벨**이고 worker가 `item_ref -> learning_item_id`
    맵을 들고 있다가 응답을 되돌린다. DB id가 프롬프트에 없으므로 모델이 유효해
    보이는 id를 지어낼 수 없다.
    """

    item_ref: str
    item_type: str
    lemma: str
    reading: str | None
    default_meaning: str | None


@dataclass(frozen=True)
class SentenceBatchInput:
    """`GENERATE_SENTENCE_BATCH`의 동적 context. item 하나당 문장 하나를 요청한다."""

    learner_level: str
    targets: tuple[TargetItem, ...]
    preferred_targets_per_sentence: int
    max_targets_per_sentence: int
    max_sentence_length_chars: int
    # target item이 이미 등장한 기존 문장. 중복 생성을 줄이기 위한 **힌트**이고
    # 실제 판정은 `app.llm.duplicates`가 한다.
    avoid_japanese: tuple[str, ...]


@dataclass(frozen=True)
class ReviewContextInput:
    """`GENERATE_REVIEW_CONTEXT`의 동적 context. 응답 `sentences`는 1개다."""

    learner_level: str
    target: TargetItem
    context_stage: ContextStage
    # anchor 문장은 `near_original`이 "표현은 유지, 주변 문맥만 최소 변경"을
    # 지시하기 위해 필요하고, 나머지 stage에서는 "이것과 다른 상황"의 기준이다.
    anchor_japanese: str
    max_sentence_length_chars: int
    avoid_japanese: tuple[str, ...]


@dataclass(frozen=True)
class ExplainItemInput:
    """`EXPLAIN_ITEM`의 동적 context. 문장을 새로 만들지 않는다."""

    learner_level: str
    japanese: str
    surface_form: str
    spans: tuple[SpanPayload, ...]


def item_ref(index: int) -> str:
    """`it{n}`. n은 요청 안에서 0부터 증가하는 순번이다(`08_LLM_SPEC.md`).

    요청을 만드는 쪽과 응답을 되돌리는 쪽이 같은 규칙을 써야 하므로 형식이 이
    함수 하나에만 있다.
    """
    return f"it{index}"


def build_sentence_batch_request(
    payload: SentenceBatchInput, *, model: str, prompt_version: str
) -> ProviderRequest:
    template = template_for(LlmTaskType.GENERATE_SENTENCE_BATCH, prompt_version)
    context = {
        "learner_level": payload.learner_level,
        "preferred_targets_per_sentence": payload.preferred_targets_per_sentence,
        "max_targets_per_sentence": payload.max_targets_per_sentence,
        "max_sentence_length_chars": payload.max_sentence_length_chars,
        "sentences_requested": len(payload.targets),
        "target_items": [_target(target) for target in payload.targets],
        "avoid_japanese": list(payload.avoid_japanese),
    }
    return _request(template, model=model, context=context)


def build_review_context_request(
    payload: ReviewContextInput, *, model: str, prompt_version: str
) -> ProviderRequest:
    template = template_for(LlmTaskType.GENERATE_REVIEW_CONTEXT, prompt_version)
    context = {
        "learner_level": payload.learner_level,
        "context_stage": payload.context_stage.value,
        "anchor_japanese": payload.anchor_japanese,
        "max_sentence_length_chars": payload.max_sentence_length_chars,
        "max_targets_per_sentence": 1,
        "sentences_requested": 1,
        "target_items": [_target(payload.target)],
        "avoid_japanese": list(payload.avoid_japanese),
    }
    return _request(template, model=model, context=context)


def build_explain_item_request(
    payload: ExplainItemInput, *, model: str, prompt_version: str
) -> ProviderRequest:
    template = template_for(LlmTaskType.EXPLAIN_ITEM, prompt_version)
    context = {
        "learner_level": payload.learner_level,
        "japanese": payload.japanese,
        "surface_form": payload.surface_form,
        "spans": [span.model_dump() for span in payload.spans],
    }
    return _request(
        template,
        model=model,
        context=context,
        schema_name=EXPLANATION_SCHEMA_NAME,
        response_model=ExplanationPayload,
    )


def parse_sentence_batch(raw: str) -> SentenceBatchPayload:
    """`GENERATE_SENTENCE_BATCH` / `GENERATE_REVIEW_CONTEXT`의 응답 (같은 스키마)."""
    return _parse(SentenceBatchPayload, raw)


def parse_explanation(raw: str) -> ExplanationPayload:
    """`EXPLAIN_ITEM`의 응답."""
    return _parse(ExplanationPayload, raw)


def requested_refs(targets: Sequence[TargetItem]) -> frozenset[str]:
    """검사 13이 쓰는 집합. 요청이 실제로 보낸 라벨만 들어간다."""
    return frozenset(target.item_ref for target in targets)


# --------------------------------------------------------------------------


def _target(target: TargetItem) -> dict[str, Any]:
    return {
        "item_ref": target.item_ref,
        "type": target.item_type,
        "lemma": target.lemma,
        "reading": target.reading,
        "default_meaning": target.default_meaning,
    }


def _request(
    template: PromptTemplate,
    *,
    model: str,
    context: dict[str, Any],
    schema_name: str = SENTENCE_BATCH_SCHEMA_NAME,
    response_model: type[BaseModel] = SentenceBatchPayload,
) -> ProviderRequest:
    return ProviderRequest(
        model=model,
        instructions=template.instructions,
        context=json.dumps(context, ensure_ascii=False, indent=2, sort_keys=True),
        schema_name=schema_name,
        json_schema=json_schema(response_model),
    )


def _parse[T: BaseModel](model: type[T], raw: str) -> T:
    try:
        return model.model_validate_json(raw)
    except ValidationError as error:
        raise SchemaParseError(f"response does not match {model.__name__}: {error}") from error
