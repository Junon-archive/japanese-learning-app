"""Structured output 스키마와 파싱 (08_LLM_SPEC.md의 `Structured Output 스키마`).

DB를 쓰지 않는다. `make test-unit`에 들어간다.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import BaseModel

from app.llm.schemas import (
    ExplanationPayload,
    ItemPayload,
    SentenceBatchPayload,
    SentencePayload,
    SpanPayload,
    json_schema,
)
from app.llm.tasks import SchemaParseError, parse_explanation, parse_sentence_batch
from app.llm.validation import RejectionReason

EXPLANATION: dict[str, Any] = {
    "reading": "ねこ",
    "core_meaning": "고양이",
    "meaning_in_context": "화자가 기르는 고양이",
    "nuance": "구어에서 흔하다",
    "example_sentence": "猫が寝ている。",
    "example_translation": "고양이가 자고 있다.",
}

ITEM: dict[str, Any] = {
    "item_ref": "it0",
    "surface_form": "猫",
    "is_tappable": True,
    "spans": [{"start_codepoint": 0, "end_codepoint": 1, "span_order": 0}],
    "explanation": EXPLANATION,
}

SENTENCE: dict[str, Any] = {
    "japanese": "猫が好きです。",
    "korean_translation": "고양이를 좋아합니다.",
    "difficulty_label": "beginner",
    "items": [ITEM],
}


def dumps(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False)


def batch(**overrides: object) -> str:
    return dumps({"sentences": [{**SENTENCE, **overrides}]})


def test_full_response_parses() -> None:
    parsed = parse_sentence_batch(batch())

    assert isinstance(parsed, SentenceBatchPayload)
    sentence = parsed.sentences[0]
    assert sentence.japanese == "猫が好きです。"
    assert sentence.difficulty_label == "beginner"
    assert sentence.items[0].spans == (
        SpanPayload(start_codepoint=0, end_codepoint=1, span_order=0),
    )


def test_broken_json_is_a_schema_parse_failure() -> None:
    with pytest.raises(SchemaParseError):
        parse_sentence_batch('{"sentences": [')


def test_missing_required_field_is_a_schema_parse_failure() -> None:
    """`null`을 허용하는 것은 `explanation`과 `example_translation`뿐이다.

    "없음"은 field 생략이 아니라 `null`이다. 생략을 통과시키면 strict structured
    output의 required 계약이 서버 쪽에서 조용히 느슨해진다.
    """
    without_translation = {
        key: value for key, value in SENTENCE.items() if key != "korean_translation"
    }
    with pytest.raises(SchemaParseError):
        parse_sentence_batch(dumps({"sentences": [without_translation]}))


def test_null_is_allowed_only_where_the_spec_allows_it() -> None:
    parsed = parse_sentence_batch(
        batch(items=[{**ITEM, "explanation": {**EXPLANATION, "example_translation": None}}])
    )
    assert parsed.sentences[0].items[0].explanation is not None

    parsed = parse_sentence_batch(
        batch(items=[{**ITEM, "is_tappable": False, "explanation": None}])
    )
    assert parsed.sentences[0].items[0].explanation is None

    with pytest.raises(SchemaParseError):
        parse_sentence_batch(
            batch(items=[{**ITEM, "explanation": {**EXPLANATION, "nuance": None}}])
        )


def test_unknown_difficulty_label_is_rejected_at_parsing() -> None:
    with pytest.raises(SchemaParseError):
        parse_sentence_batch(batch(difficulty_label="native"))


@pytest.mark.parametrize("field", ["register", "topic", "tags", "provenance", "model"])
def test_register_metadata_has_no_place_in_the_response(field: str) -> None:
    """MVP는 register metadata를 요청하지도 저장하지도 않는다 (00_SCOPE.md)."""
    with pytest.raises(SchemaParseError):
        parse_sentence_batch(batch(**{field: "casual"}))


@pytest.mark.parametrize("field", ["context_stage", "near_original", "is_near_original"])
def test_the_model_cannot_declare_its_own_duplicate_exemption(field: str) -> None:
    """모델이 "이건 near_original이야"라고 신고할 자리가 스키마에 없다.

    있으면 모델이 자기 응답에 그 field를 붙여 similarity 검사를 스스로 면제받는다.
    `duplicates.skips_similarity_check`가 task와 요청 stage에서만 계산하는 것과
    같은 규칙의 스키마 쪽 절반이다.
    """
    with pytest.raises(SchemaParseError):
        parse_sentence_batch(batch(**{field: True}))


EXPECTED_FIELDS = {
    SentenceBatchPayload: {"sentences"},
    SentencePayload: {"japanese", "korean_translation", "difficulty_label", "items"},
    ItemPayload: {"item_ref", "surface_form", "is_tappable", "spans", "explanation"},
    SpanPayload: {"start_codepoint", "end_codepoint", "span_order"},
    ExplanationPayload: {
        "reading",
        "core_meaning",
        "meaning_in_context",
        "nuance",
        "example_sentence",
        "example_translation",
    },
}


@pytest.mark.parametrize(("model", "expected"), list(EXPECTED_FIELDS.items()))
def test_response_models_carry_exactly_the_fields_the_spec_lists(
    model: type[BaseModel], expected: set[str]
) -> None:
    """응답 스키마의 field 목록을 통째로 고정한다.

    `extra="forbid"` 테스트만으로는 **field를 새로 추가하는** 변경을 잡지 못한다.
    특히 `is_near_original: bool = False` 하나를 더하면 그 순간 모델이 자기
    duplicate 면제를 신고할 수 있게 되는데, 그것은 스키마에 없는 field를 거부하는
    규칙을 하나도 어기지 않는다.
    """
    assert set(model.model_fields) == expected


@pytest.mark.parametrize("field", ["sentence_id", "learning_item_id", "sentence_item_id"])
def test_the_model_cannot_return_our_identifiers(field: str) -> None:
    """모델이 id를 만들지 않는다. 지시는 요청 로컬 라벨 `item_ref`로만 한다."""
    with pytest.raises(SchemaParseError):
        parse_sentence_batch(batch(items=[{**ITEM, field: 1}]))


def test_explain_item_response_is_the_explanation_object() -> None:
    parsed = parse_explanation(dumps(EXPLANATION))

    assert isinstance(parsed, ExplanationPayload)
    assert parsed.meaning_in_context == "화자가 기르는 고양이"

    with pytest.raises(SchemaParseError):
        parse_explanation(dumps({"explanation": EXPLANATION}))


def test_schema_parse_error_carries_the_canonical_reason_code() -> None:
    """검사 1의 사유 코드 (08_LLM_SPEC.md의 `탈락한 콘텐츠의 처리`)."""
    assert SchemaParseError.reason is RejectionReason.SCHEMA_PARSE_FAILED


# --------------------------------------------------------------------------
# provider에 보내는 JSON Schema
# --------------------------------------------------------------------------


def objects(schema: dict[str, Any]) -> list[dict[str, Any]]:
    """`$defs`를 포함한 모든 object 스키마."""
    found = [schema] if schema.get("type") == "object" else []
    for definition in schema.get("$defs", {}).values():
        if definition.get("type") == "object":
            found.append(definition)
    return found


@pytest.mark.parametrize("model", [SentenceBatchPayload, ExplanationPayload])
def test_json_schema_is_strict(model: type[BaseModel]) -> None:
    """strict structured output이 요구하는 두 조건이 모델 선언에서 따라 나온다."""
    schema = json_schema(model)
    found = objects(schema)
    assert found

    for definition in found:
        assert definition["additionalProperties"] is False, definition.get("title")
        assert sorted(definition["required"]) == sorted(definition["properties"]), definition.get(
            "title"
        )


def test_json_schema_pins_the_difficulty_ladder() -> None:
    schema = json_schema(SentenceBatchPayload)
    ladder = next(
        definition
        for definition in schema["$defs"].values()
        if "enum" in definition and "beginner" in definition["enum"]
    )
    assert sorted(ladder["enum"]) == ["advanced", "beginner", "intermediate"]


def test_payload_models_are_frozen() -> None:
    """검증을 통과한 payload가 저장 직전에 조용히 바뀌지 않는다."""
    sentence = parse_sentence_batch(batch()).sentences[0]
    with pytest.raises(ValueError, match="frozen"):
        sentence.japanese = "犬が好きです。"


def test_item_payload_keeps_spans_as_a_tuple() -> None:
    item = ItemPayload.model_validate(ITEM)
    assert isinstance(item.spans, tuple)
    assert isinstance(SentencePayload.model_validate(SENTENCE).items, tuple)
