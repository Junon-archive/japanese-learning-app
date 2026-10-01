"""요청 조립과 prompt version (08_LLM_SPEC.md의 `요청 context`).

DB도 네트워크도 쓰지 않는다. `make test-unit`에 들어간다.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.llm.prompts import PROMPT_TEMPLATES, UnknownPromptVersionError, template_for
from app.llm.schemas import SpanPayload
from app.llm.tasks import (
    ExplainItemInput,
    ReviewContextInput,
    SentenceBatchInput,
    TargetItem,
    build_explain_item_request,
    build_review_context_request,
    build_sentence_batch_request,
    item_ref,
    requested_refs,
)
from app.models.enums import ContextStage, Language, LlmTaskType

TARGET = TargetItem(
    item_ref="it0",
    item_type="word",
    lemma="猫",
    reading="ねこ",
    default_meaning="고양이",
)

BATCH = SentenceBatchInput(
    learner_level="beginner",
    targets=(TARGET,),
    preferred_targets_per_sentence=1,
    max_targets_per_sentence=2,
    max_sentence_length_chars=60,
    avoid_examples=("猫が好きです。",),
)


def context(raw: str) -> dict[str, Any]:
    parsed: dict[str, Any] = json.loads(raw)
    return parsed


def test_item_ref_format_lives_in_one_place() -> None:
    assert [item_ref(index) for index in range(3)] == ["it0", "it1", "it2"]
    assert requested_refs([TARGET]) == frozenset({"it0"})


def test_prompt_versions_are_the_three_the_spec_names() -> None:
    assert {
        (task.value, language.value, version) for task, language, version in PROMPT_TEMPLATES
    } == {
        ("GENERATE_SENTENCE_BATCH", "ja", "sentence_gen_v2"),
        ("GENERATE_REVIEW_CONTEXT", "ja", "review_context_v2"),
        ("EXPLAIN_ITEM", "ja", "explain_item_v2"),
        ("GENERATE_SENTENCE_BATCH", "en", "sentence_gen_en_v1"),
        ("GENERATE_REVIEW_CONTEXT", "en", "review_context_en_v1"),
        ("EXPLAIN_ITEM", "en", "explain_item_en_v1"),
    }


def test_an_active_version_with_no_template_is_not_retryable() -> None:
    """`prompt_versions.active`가 코드에 없는 `(language, version)`을 가리키면 결과가 늘 같다."""
    with pytest.raises(UnknownPromptVersionError):
        template_for(LlmTaskType.GENERATE_SENTENCE_BATCH, Language.JA, "sentence_gen_v3")

    with pytest.raises(UnknownPromptVersionError):
        template_for(LlmTaskType.EXPLAIN_ITEM, Language.JA, "sentence_gen_v2")

    with pytest.raises(UnknownPromptVersionError):
        # 본문은 코드에 있지만 그 언어에는 없다 (ja의 sentence_gen_v2가 en에는 없다).
        template_for(LlmTaskType.GENERATE_SENTENCE_BATCH, Language.EN, "sentence_gen_v2")


def test_sentence_batch_request_carries_the_model_it_was_given() -> None:
    request = build_sentence_batch_request(
        BATCH, language=Language.JA, model="whatever-the-row-says", prompt_version="sentence_gen_v2"
    )

    assert request.model == "whatever-the-row-says"
    assert (
        request.instructions
        == template_for(
            LlmTaskType.GENERATE_SENTENCE_BATCH, Language.JA, "sentence_gen_v2"
        ).instructions
    )
    assert request.json_schema["$defs"]


def test_sentence_batch_request_picks_the_template_for_the_jobs_language() -> None:
    """worker는 job의 `(job_type, language)`로 prompt를 고른다(`08_LLM_SPEC.md`)."""
    request = build_sentence_batch_request(
        BATCH, language=Language.EN, model="m", prompt_version="sentence_gen_en_v1"
    )

    assert (
        request.instructions
        == template_for(
            LlmTaskType.GENERATE_SENTENCE_BATCH, Language.EN, "sentence_gen_en_v1"
        ).instructions
    )
    assert (
        request.instructions
        != template_for(
            LlmTaskType.GENERATE_SENTENCE_BATCH, Language.JA, "sentence_gen_v2"
        ).instructions
    )


def test_sentence_batch_context_holds_only_what_the_spec_allows() -> None:
    """전체 mastery 목록도, 사용자 식별자도, event 원문도 싣지 않는다 (원칙 2)."""
    request = build_sentence_batch_request(
        BATCH, language=Language.JA, model="m", prompt_version="sentence_gen_v2"
    )
    payload = context(request.context)

    assert set(payload) == {
        "learner_level",
        "preferred_targets_per_sentence",
        "max_targets_per_sentence",
        "max_sentence_length_chars",
        "sentences_requested",
        "target_items",
        "avoid_examples",
    }
    assert payload["target_items"] == [
        {
            "item_ref": "it0",
            "type": "word",
            "lemma": "猫",
            "reading": "ねこ",
            "default_meaning": "고양이",
        }
    ]
    assert "learning_item_id" not in request.context
    assert "user_id" not in request.context


def test_review_context_request_asks_for_one_sentence_and_names_the_stage() -> None:
    payload = ReviewContextInput(
        learner_level="beginner",
        target=TARGET,
        context_stage=ContextStage.NEAR_ORIGINAL,
        anchor_text="猫が好きです。",
        max_sentence_length_chars=60,
        avoid_examples=(),
    )

    request = build_review_context_request(
        payload, language=Language.JA, model="m", prompt_version="review_context_v2"
    )
    body = context(request.context)

    assert body["sentences_requested"] == 1
    assert body["context_stage"] == "near_original"
    assert body["anchor_text"] == "猫が好きです。"
    assert request.schema_name == "sentence_batch"


def test_both_generation_tasks_share_one_response_schema() -> None:
    """두 task의 차이는 요청 context와 저장 시 lineage이지 응답 모양이 아니다."""
    batch = build_sentence_batch_request(
        BATCH, language=Language.JA, model="m", prompt_version="sentence_gen_v2"
    )
    review = build_review_context_request(
        ReviewContextInput(
            learner_level="beginner",
            target=TARGET,
            context_stage=ContextStage.VARIED,
            anchor_text="猫が好きです。",
            max_sentence_length_chars=60,
            avoid_examples=(),
        ),
        language=Language.JA,
        model="m",
        prompt_version="review_context_v2",
    )

    assert batch.json_schema == review.json_schema
    assert batch.instructions != review.instructions


def test_explain_item_request_uses_the_explanation_schema() -> None:
    request = build_explain_item_request(
        ExplainItemInput(
            learner_level="beginner",
            text="猫が好きです。",
            surface_form="猫",
            spans=(SpanPayload(start_codepoint=0, end_codepoint=1, span_order=0),),
        ),
        language=Language.JA,
        model="m",
        prompt_version="explain_item_v2",
    )

    assert request.schema_name == "explanation"
    assert set(request.json_schema["properties"]) == {
        "reading",
        "core_meaning",
        "meaning_in_context",
        "nuance",
        "example_sentence",
        "example_translation",
    }
    assert context(request.context)["surface_form"] == "猫"


# --------------------------------------------------------------------------
# 영어 prompt 본문 (MVP-03, ADR-024 결정 5)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("task_type", "version"),
    [
        (LlmTaskType.GENERATE_SENTENCE_BATCH, "sentence_gen_en_v1"),
        (LlmTaskType.GENERATE_REVIEW_CONTEXT, "review_context_en_v1"),
        (LlmTaskType.EXPLAIN_ITEM, "explain_item_en_v1"),
    ],
)
def test_english_prompt_templates_load_with_non_empty_instructions(
    task_type: LlmTaskType, version: str
) -> None:
    template = template_for(task_type, Language.EN, version)

    assert template.language is Language.EN
    assert template.version == version
    assert template.instructions.strip()


def test_english_sentence_batch_request_assembles_like_the_japanese_one() -> None:
    """요청 조립 경로가 언어와 무관하게 같은 모양을 낸다 --- 언어를 context에 싣지 않는다."""
    english_target = TargetItem(
        item_ref="it0",
        item_type="expression",
        lemma="you good?",
        reading=None,
        default_meaning="괜찮아?",
    )
    batch = SentenceBatchInput(
        learner_level="intermediate",
        targets=(english_target,),
        preferred_targets_per_sentence=1,
        max_targets_per_sentence=2,
        max_sentence_length_chars=120,
        avoid_examples=(),
    )

    request = build_sentence_batch_request(
        batch, language=Language.EN, model="m", prompt_version="sentence_gen_en_v1"
    )
    payload = context(request.context)

    assert (
        request.instructions
        == template_for(
            LlmTaskType.GENERATE_SENTENCE_BATCH, Language.EN, "sentence_gen_en_v1"
        ).instructions
    )
    assert "language" not in payload
    assert payload["target_items"] == [
        {
            "item_ref": "it0",
            "type": "expression",
            "lemma": "you good?",
            "reading": None,
            "default_meaning": "괜찮아?",
        }
    ]
