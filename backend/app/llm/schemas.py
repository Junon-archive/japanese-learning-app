"""Structured output 스키마 (`08_LLM_SPEC.md`의 `Structured Output 스키마`).

`GENERATE_SENTENCE_BATCH`와 `GENERATE_REVIEW_CONTEXT`는 **같은 응답 스키마**를
쓴다. 두 task의 차이는 요청 context와 저장 시 lineage(`parent_sentence_id`)이지
응답 모양이 아니다. `EXPLAIN_ITEM`은 그 안의 `explanation` 객체 하나다.

규칙 세 가지가 이 파일의 모양을 정한다.

1.  모든 field가 required다. "없음"은 field 생략이 아니라 `null`이며, `null`을
    허용하는 것은 `explanation`(item 단위)과 `explanation.example_translation`
    뿐이다. strict structured output이 optional field를 잘 다루지 못한다.
2.  **모델이 우리 쪽 식별자를 만들지 않는다.** `sentence_id` / `learning_item_id`
    / `sentence_item_id`가 스키마에 없고, item 지시는 요청 로컬 라벨 `item_ref`
    로만 한다. DB id를 프롬프트에 싣지 않으므로 모델이 유효해 보이는 id를 지어낼
    수 없다.
3.  `register` / `topic` / `tags` / `provenance` / `model` / `context_stage`를
    두지 않는다. register metadata는 MVP에서 요청하지도 저장하지도 않고
    (`00_SCOPE.md`), provenance는 응답이 아니라 worker의 실행 context에서 채운다.
    `extra="forbid"`가 이 목록을 강제한다 --- 특히 모델이 "이건 near_original
    이다"라고 **자기 신고할 자리가 없어야** duplicate 검사를 스스로 면제받지
    못한다(`duplicates.skips_similarity_check`).

DB를 모른다(G11(a)). `app.models.enums`는 G11(a)가 명시한 유일한 예외다.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.enums import StartingLevel

# `frozen=True`는 검증을 통과한 payload가 뒤에서 조용히 바뀌지 않게 한다. span
# 자동 보정은 새 객체를 만든다(`validation._corrected_item`).
_STRICT = ConfigDict(extra="forbid", frozen=True)


class SpanPayload(BaseModel):
    """`japanese`에 대한 Unicode code point index. `[start, end)` 반열림 구간이다."""

    model_config = _STRICT

    start_codepoint: int
    end_codepoint: int
    span_order: int


class ExplanationPayload(BaseModel):
    """contextual explanation. `example_translation`만 `null`을 허용한다."""

    model_config = _STRICT

    reading: str
    core_meaning: str
    meaning_in_context: str
    nuance: str
    example_sentence: str
    example_translation: str | None


class ItemPayload(BaseModel):
    model_config = _STRICT

    item_ref: str
    surface_form: str
    is_tappable: bool
    spans: tuple[SpanPayload, ...]
    explanation: ExplanationPayload | None


class SentencePayload(BaseModel):
    model_config = _STRICT

    japanese: str
    korean_translation: str
    # 허용값은 difficulty ladder 3단계와 같다(06_LEARNING_ENGINE.md). 다른 값은
    # 여기 parsing 단계에서 걸린다. label이 실제 난이도와 맞는지는 검증하지 않는다.
    difficulty_label: StartingLevel
    items: tuple[ItemPayload, ...]


class SentenceBatchPayload(BaseModel):
    model_config = _STRICT

    sentences: tuple[SentencePayload, ...]


def json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """provider에 보낼 JSON Schema.

    `extra="forbid"`가 `additionalProperties: false`를, 기본값 없는 field가
    `required` 전량을 만든다. strict structured output이 요구하는 두 조건이 모델
    선언에서 그대로 따라 나오므로 스키마를 손으로 고쳐 쓰지 않는다.
    """
    return model.model_json_schema()
