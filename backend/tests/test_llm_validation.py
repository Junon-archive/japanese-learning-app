"""Deterministic validation 1~10 + 13 (08_LLM_SPEC.md).

각 검사 항목마다 **정확히 그 항목의 사유 코드**가 나오는 실패 케이스를 하나씩
둔다. 케이스는 최소한으로 만든다 --- 앞선 항목이 먼저 걸리면 뒤 항목의 테스트가
통과하는 것처럼 보이면서 실은 아무것도 검사하지 않는다.

DB를 쓰지 않는다. `make test-unit`에 들어간다.
"""

from __future__ import annotations

from types import EllipsisType

import pytest

from app.llm.schemas import ExplanationPayload, ItemPayload, SentencePayload, SpanPayload
from app.llm.tasks import SchemaParseError, parse_sentence_batch
from app.llm.validation import (
    Rejection,
    RejectionReason,
    SentencePolicy,
    ValidatedSentence,
    validate_explanation,
    validate_sentence,
)
from app.models.enums import StartingLevel

# 「猫が好きです。」 = 7 code point. 猫[0,1) が[1,2) 好き[2,4) です[4,6) 。[6,7)
JAPANESE = "猫が好きです。"

POLICY = SentencePolicy(
    max_sentence_length_chars=60,
    max_targets_per_sentence=2,
    max_new_items_per_sentence=2,
)


def explanation(**overrides: str | None) -> ExplanationPayload:
    fields: dict[str, str | None] = {
        "reading": "ねこ",
        "core_meaning": "고양이",
        "meaning_in_context": "화자가 기르는 고양이",
        "nuance": "구어에서 흔하다",
        "example_sentence": "猫が寝ている。",
        "example_translation": "고양이가 자고 있다.",
    }
    fields.update(overrides)
    return ExplanationPayload.model_validate(fields)


def spans(*ranges: tuple[int, int]) -> tuple[SpanPayload, ...]:
    return tuple(
        SpanPayload(start_codepoint=start, end_codepoint=end, span_order=order)
        for order, (start, end) in enumerate(ranges)
    )


def item(
    *,
    item_ref: str = "it0",
    surface_form: str = "猫",
    is_tappable: bool = True,
    span_ranges: tuple[tuple[int, int], ...] = ((0, 1),),
    explanation_payload: ExplanationPayload | EllipsisType | None = ...,
    raw_spans: tuple[SpanPayload, ...] | None = None,
) -> ItemPayload:
    # `None`은 "설명 없음"이라는 뜻의 값이므로 기본값 자리에 쓸 수 없다.
    payload = (
        explanation() if isinstance(explanation_payload, EllipsisType) else explanation_payload
    )
    return ItemPayload(
        item_ref=item_ref,
        surface_form=surface_form,
        is_tappable=is_tappable,
        spans=raw_spans if raw_spans is not None else spans(*span_ranges),
        explanation=payload,
    )


def sentence(
    *,
    japanese: str = JAPANESE,
    korean_translation: str = "고양이를 좋아합니다.",
    items: tuple[ItemPayload, ...] = (),
) -> SentencePayload:
    return SentencePayload(
        japanese=japanese,
        korean_translation=korean_translation,
        difficulty_label=StartingLevel.BEGINNER,
        items=items if items else (item(),),
    )


def check(
    payload: SentencePayload,
    *,
    requested: frozenset[str] = frozenset({"it0"}),
    new: frozenset[str] = frozenset(),
    policy: SentencePolicy = POLICY,
) -> ValidatedSentence | Rejection:
    return validate_sentence(payload, requested_refs=requested, new_refs=new, policy=policy)


def reason(result: ValidatedSentence | Rejection) -> RejectionReason:
    assert isinstance(result, Rejection), result
    return result.reason


def accepted(result: ValidatedSentence | Rejection) -> SentencePayload:
    assert isinstance(result, ValidatedSentence), result
    return result.sentence


def test_a_well_formed_sentence_is_accepted() -> None:
    assert accepted(check(sentence())).japanese == JAPANESE


# --------------------------------------------------------------------------
# 1  schema_parse_failed
# --------------------------------------------------------------------------


def test_1_schema_parse_failed() -> None:
    with pytest.raises(SchemaParseError) as error:
        parse_sentence_batch("not json at all")
    assert error.value.reason is RejectionReason.SCHEMA_PARSE_FAILED


# --------------------------------------------------------------------------
# 2  empty_japanese
# --------------------------------------------------------------------------


@pytest.mark.parametrize("japanese", ["", "   ", "　"])
def test_2_empty_japanese(japanese: str) -> None:
    assert reason(check(sentence(japanese=japanese))) is RejectionReason.EMPTY_JAPANESE


# --------------------------------------------------------------------------
# 3  sentence_too_long
# --------------------------------------------------------------------------


def test_3_sentence_too_long_uses_the_configured_limit() -> None:
    tight = SentencePolicy(
        max_sentence_length_chars=len(JAPANESE) - 1,
        max_targets_per_sentence=2,
        max_new_items_per_sentence=2,
    )
    assert reason(check(sentence(), policy=tight)) is RejectionReason.SENTENCE_TOO_LONG

    exact = SentencePolicy(
        max_sentence_length_chars=len(JAPANESE),
        max_targets_per_sentence=2,
        max_new_items_per_sentence=2,
    )
    assert accepted(check(sentence(), policy=exact)).japanese == JAPANESE


# --------------------------------------------------------------------------
# 4  missing_translation
# --------------------------------------------------------------------------


def test_4_missing_translation() -> None:
    assert reason(check(sentence(korean_translation="   "))) is RejectionReason.MISSING_TRANSLATION


# --------------------------------------------------------------------------
# 5  target_count_out_of_range
# --------------------------------------------------------------------------


def test_5_no_target_at_all() -> None:
    payload = SentencePayload(
        japanese=JAPANESE,
        korean_translation="고양이를 좋아합니다.",
        difficulty_label=StartingLevel.BEGINNER,
        items=(),
    )
    assert reason(check(payload)) is RejectionReason.TARGET_COUNT_OUT_OF_RANGE


def test_5_more_targets_than_a_sentence_may_carry() -> None:
    """상한을 넘는 target 수. 신규 item이 아니므로 10번은 발화하지 않는다."""
    payload = sentence(
        items=(
            item(item_ref="it0", surface_form="猫", span_ranges=((0, 1),)),
            item(item_ref="it1", surface_form="好き", span_ranges=((2, 4),)),
            item(item_ref="it2", surface_form="です", span_ranges=((4, 6),)),
        )
    )
    result = check(payload, requested=frozenset({"it0", "it1", "it2"}))
    assert reason(result) is RejectionReason.TARGET_COUNT_OUT_OF_RANGE


# --------------------------------------------------------------------------
# 6  surface_not_found
# --------------------------------------------------------------------------


def test_6_surface_form_is_not_the_text_the_spans_cover() -> None:
    """span은 범위 안이고 겹치지도 않는데 덮은 글자가 `surface_form`과 다르다.

    `surface_form`이 문장에 아예 없으므로 자동 보정도 적용되지 않는다.
    """
    payload = sentence(items=(item(surface_form="犬", span_ranges=((0, 1),)),))
    assert reason(check(payload)) is RejectionReason.SURFACE_NOT_FOUND


def test_6_two_occurrences_are_not_repaired() -> None:
    """후보가 둘이면 어느 것이 의도였는지 알 수 없으므로 보정하지 않는다."""
    payload = sentence(
        japanese="猫と猫",
        items=(item(surface_form="猫", span_ranges=((1, 2),)),),
    )
    assert reason(check(payload)) is RejectionReason.SURFACE_NOT_FOUND


# --------------------------------------------------------------------------
# 7  span_out_of_range
# --------------------------------------------------------------------------


def test_7_span_ends_past_the_sentence() -> None:
    """보정이 손댈 수 없는 형태로 둔다 --- 그래야 7번 자체가 검사된다."""
    payload = sentence(
        japanese="猫と猫",
        items=(item(surface_form="猫", span_ranges=((0, 99),)),),
    )
    assert reason(check(payload)) is RejectionReason.SPAN_OUT_OF_RANGE


def test_7_utf16_offsets_leave_a_lone_surrogate_behind() -> None:
    """offset을 UTF-16 code unit으로 적어 넣은 응답의 흔적을 거부한다."""
    payload = sentence(
        japanese="猫\ud83dです",
        items=(item(surface_form="猫", span_ranges=((0, 1),)),),
    )
    assert reason(check(payload)) is RejectionReason.SPAN_OUT_OF_RANGE


def test_7_span_order_must_be_a_permutation() -> None:
    payload = sentence(
        items=(
            item(
                surface_form="猫好き",
                raw_spans=(
                    SpanPayload(start_codepoint=0, end_codepoint=1, span_order=0),
                    SpanPayload(start_codepoint=2, end_codepoint=4, span_order=7),
                ),
            ),
        )
    )
    assert reason(check(payload)) is RejectionReason.SPAN_OUT_OF_RANGE


# --------------------------------------------------------------------------
# 8  span_overlap
# --------------------------------------------------------------------------


def test_8_cross_item_overlap_is_ambiguous() -> None:
    """**서로 다른 item**의 tappable span이 겹친다.

    item 하나 안만 보는 검사로는 잡히지 않는다. 두 item 모두 자기 span과
    `surface_form`이 정확히 맞으므로 6·7번은 통과한다. 그래도 그 문장은 tap한
    글자가 어느 item인지 정할 수 없어 렌더링 자체가 불가능하다.
    """
    payload = sentence(
        items=(
            item(item_ref="it0", surface_form="猫が", span_ranges=((0, 2),)),
            item(item_ref="it1", surface_form="が好き", span_ranges=((1, 4),)),
        )
    )
    result = check(payload, requested=frozenset({"it0", "it1"}))
    assert reason(result) is RejectionReason.SPAN_OVERLAP


def test_8_non_tappable_items_do_not_create_ambiguity() -> None:
    """tap할 수 없는 item의 span은 일반 텍스트로 흘러간다."""
    payload = sentence(
        items=(
            item(item_ref="it0", surface_form="猫が", span_ranges=((0, 2),)),
            item(
                item_ref="it1",
                surface_form="が好き",
                span_ranges=((1, 4),),
                is_tappable=False,
                explanation_payload=None,
            ),
        )
    )
    result = check(payload, requested=frozenset({"it0", "it1"}))
    assert accepted(result).japanese == JAPANESE


def test_8_spans_inside_one_item_may_not_overlap_either() -> None:
    payload = sentence(
        items=(
            item(
                surface_form="猫がが好",
                raw_spans=(
                    SpanPayload(start_codepoint=0, end_codepoint=2, span_order=0),
                    SpanPayload(start_codepoint=1, end_codepoint=3, span_order=1),
                ),
            ),
        )
    )
    assert reason(check(payload)) is RejectionReason.SPAN_OVERLAP


def test_8_discontinuous_spans_are_normal_data() -> None:
    """떨어져 있는 span은 겹침이 아니다 (불연속 표현)."""
    payload = sentence(items=(item(surface_form="猫好き", span_ranges=((0, 1), (2, 4))),))
    assert accepted(check(payload)).items[0].surface_form == "猫好き"


# --------------------------------------------------------------------------
# 9  missing_explanation
# --------------------------------------------------------------------------


def test_9_every_tappable_item_needs_an_explanation() -> None:
    """대상은 target만이 아니라 `is_tappable = true`인 **모든** item이다.

    약한 해석(target only)을 쓰면 생성 validation은 통과했는데 candidate는 될 수
    없는 문장이 조용히 쌓인다 (08_LLM_SPEC.md의 `Ready invariant와 같은 범위`).
    """
    payload = sentence(
        items=(
            item(item_ref="it0", surface_form="猫", span_ranges=((0, 1),)),
            item(
                item_ref="it1",
                surface_form="好き",
                span_ranges=((2, 4),),
                explanation_payload=None,
            ),
        )
    )
    result = check(payload, requested=frozenset({"it0", "it1"}))
    assert reason(result) is RejectionReason.MISSING_EXPLANATION


@pytest.mark.parametrize(
    "field", ["reading", "core_meaning", "meaning_in_context", "nuance", "example_sentence"]
)
def test_9_required_explanation_fields_may_not_be_empty(field: str) -> None:
    payload = sentence(items=(item(explanation_payload=explanation(**{field: "  "})),))
    assert reason(check(payload)) is RejectionReason.MISSING_EXPLANATION


def test_9_example_translation_may_be_null() -> None:
    payload = sentence(items=(item(explanation_payload=explanation(example_translation=None)),))
    assert accepted(check(payload)).items[0].explanation is not None


def test_9_untappable_items_need_nothing() -> None:
    payload = sentence(
        items=(
            item(item_ref="it0", surface_form="猫", span_ranges=((0, 1),)),
            item(
                item_ref="it1",
                surface_form="好き",
                span_ranges=((2, 4),),
                is_tappable=False,
                explanation_payload=None,
            ),
        )
    )
    result = check(payload, requested=frozenset({"it0", "it1"}))
    assert accepted(result).items[1].explanation is None


def test_9_explain_item_response_uses_the_same_field_rule() -> None:
    assert isinstance(validate_explanation(explanation()).explanation, ExplanationPayload)  # type: ignore[union-attr]

    rejected = validate_explanation(explanation(nuance=""))
    assert isinstance(rejected, Rejection)
    assert rejected.reason is RejectionReason.MISSING_EXPLANATION


# --------------------------------------------------------------------------
# 10  too_many_targets
# --------------------------------------------------------------------------


def test_10_counts_new_items_only() -> None:
    """5번과 세는 대상이 다르다. 여기서는 문장의 target 수가 상한 안이다."""
    policy = SentencePolicy(
        max_sentence_length_chars=60,
        max_targets_per_sentence=3,
        max_new_items_per_sentence=1,
    )
    payload = sentence(
        items=(
            item(item_ref="it0", surface_form="猫", span_ranges=((0, 1),)),
            item(item_ref="it1", surface_form="好き", span_ranges=((2, 4),)),
        )
    )
    requested = frozenset({"it0", "it1"})

    rejected = check(payload, requested=requested, new=requested, policy=policy)
    assert reason(rejected) is RejectionReason.TOO_MANY_TARGETS

    # 같은 문장이라도 신규가 하나뿐이면 통과한다.
    ok = check(payload, requested=requested, new=frozenset({"it0"}), policy=policy)
    assert accepted(ok).japanese == JAPANESE


# --------------------------------------------------------------------------
# 13  unknown_item_ref
# --------------------------------------------------------------------------


def test_13_a_ref_the_request_never_sent() -> None:
    payload = sentence(items=(item(item_ref="it9"),))
    assert reason(check(payload)) is RejectionReason.UNKNOWN_ITEM_REF


# --------------------------------------------------------------------------
# span 자동 보정 (그 뒤 6·7·8 재실행)
# --------------------------------------------------------------------------


def test_span_is_repaired_when_the_surface_occurs_exactly_once() -> None:
    payload = sentence(items=(item(surface_form="好き", span_ranges=((0, 1),)),))

    repaired = accepted(check(payload)).items[0]
    assert repaired.spans == (SpanPayload(start_codepoint=2, end_codepoint=4, span_order=0),)


def test_repair_is_not_attempted_for_discontinuous_expressions() -> None:
    """span이 여럿이면 위치를 재구성할 수 없다. 형태소 분석기는 MVP 밖이다."""
    payload = sentence(items=(item(surface_form="猫好き", span_ranges=((0, 1), (5, 6))),))
    assert reason(check(payload)) is RejectionReason.SURFACE_NOT_FOUND


def test_repaired_spans_are_validated_again() -> None:
    """보정 결과가 옳다고 가정하지 않는다.

    `が好き`는 문장에 정확히 한 번 나오므로 보정이 적용되고, 보정된 위치는 앞
    item의 span과 겹친다. 보정 뒤 8번을 다시 돌리지 않으면 이 문장이 Ready가 되고,
    request 경로의 렌더러가 그때서야 500으로 터진다.
    """
    payload = sentence(
        items=(
            item(item_ref="it0", surface_form="猫が", span_ranges=((0, 2),)),
            item(item_ref="it1", surface_form="が好き", span_ranges=((5, 6),)),
        )
    )
    result = check(payload, requested=frozenset({"it0", "it1"}))
    assert reason(result) is RejectionReason.SPAN_OVERLAP


def test_correct_spans_are_left_alone() -> None:
    payload = sentence(items=(item(surface_form="猫", span_ranges=((0, 1),)),))
    assert accepted(check(payload)).items[0].spans == spans((0, 1))
