"""Deterministic content validation 1~10 + 13 (`08_LLM_SPEC.md`).

**structured output도 거짓말한다.** 실제로 관찰되는 것들: span offset이 UTF-16
기준이거나 글자 중간을 자름, `surface_form`이 문장에 없음, 요청하지 않은
`item_ref`, 번역 필드에 일본어, 길이 초과, 같은 문장 반복. 그래서 서버가 응답을
**다시** 파싱하고 다시 검증한다. 모델의 자기보고를 믿는 field는 하나도 없다.

검사를 통과하지 못한 문장은 **어떤 행으로도 저장하지 않는다.** `draft`로 남기지
않는다(`08_LLM_SPEC.md`의 `탈락한 콘텐츠의 처리`). 대신 사유 코드를 남긴다.

11·12(duplicate)는 corpus가 필요하므로 `app.llm.duplicates`에 있다.

## 재사용

span 판정(6·7·8)을 여기서 새로 구현하지 않는다. `app.render`의
`validate_item_spans`(item 하나 안)와 `build_render_segments`(문장 전체의 tappable
span)가 그대로 판정한다. 복제하면 worker가 Ready로 선언한 문장을 request 경로의
렌더러가 500으로 거절하는 형태로 갈라진다(ADR-015).

## 한계

deterministic validation만으로 "target expression이 정확히 의도한 sense로
자연스럽게 사용되었는가"를 **보장할 수 없다.** 여기서 하는 것은 구조 검사와 span
일치까지이고, `meaning_in_context`는 존재와 non-empty만 본다. 나머지는 사용자
content flag와 실제 사용 feedback이 메운다(`08_LLM_SPEC.md`의
`Sense correctness limitation`). Mandatory second-model judge는 MVP 범위 밖이다.

DB를 모른다(G11(a)). 정책값은 전부 인자다 --- `get_config()`를 부르지 않는다.
"""

from __future__ import annotations

import enum
import itertools
from dataclasses import dataclass

from app.llm.schemas import ExplanationPayload, ItemPayload, SentencePayload, SpanPayload
from app.render import (
    ItemSpan,
    RenderSpanError,
    SpanRef,
    build_render_segments,
    validate_item_spans,
)


class RejectionReason(enum.StrEnum):
    """`08_LLM_SPEC.md`의 사유 코드 집합. 이 목록이 canonical이며 늘리지 않는다.

    `generation_jobs.result_ref.rejected`와 `11_OBSERVABILITY.md`의 validation
    failure 집계가 같은 문자열을 쓴다. 오른쪽 주석은 명세의 검사 번호다.
    """

    SCHEMA_PARSE_FAILED = "schema_parse_failed"  # 1
    EMPTY_JAPANESE = "empty_japanese"  # 2
    SENTENCE_TOO_LONG = "sentence_too_long"  # 3
    MISSING_TRANSLATION = "missing_translation"  # 4
    TARGET_COUNT_OUT_OF_RANGE = "target_count_out_of_range"  # 5
    SURFACE_NOT_FOUND = "surface_not_found"  # 6
    SPAN_OUT_OF_RANGE = "span_out_of_range"  # 7
    SPAN_OVERLAP = "span_overlap"  # 8
    MISSING_EXPLANATION = "missing_explanation"  # 9
    TOO_MANY_TARGETS = "too_many_targets"  # 10
    DUPLICATE_HASH = "duplicate_hash"  # 11
    DUPLICATE_SIMILARITY = "duplicate_similarity"  # 12
    UNKNOWN_ITEM_REF = "unknown_item_ref"  # 13


@dataclass(frozen=True)
class Rejection:
    """탈락. 집계 단위는 `reason`이고 `detail`은 그 한 건의 진단이다.

    `detail`에는 응답 조각(문장 slice, 모델이 지어낸 `item_ref`)이 들어갈 수 있으므로
    로그가 아니라 `generation_jobs.result_ref.rejected`에만 남는다
    (`jobs/persistence.py`의 `_log_rejections`).
    """

    reason: RejectionReason
    detail: str


@dataclass(frozen=True)
class ValidatedSentence:
    """검사 1~10·13을 통과한 문장. `sentence.items`의 span은 **보정 후** 값이다.

    감싸는 타입을 따로 두는 이유는 ADR-015의 "validation의 반환 타입을 accept /
    reject로 좁게 둔다"이다. 검증하지 않은 `SentencePayload`를 저장 경로에 그대로
    넘길 수 없게 만든다. 11·12는 아직 남아 있다(`app.llm.duplicates`).
    """

    sentence: SentencePayload


@dataclass(frozen=True)
class ValidatedExplanation:
    """`EXPLAIN_ITEM` 응답 중 검사 9를 통과한 것."""

    explanation: ExplanationPayload


@dataclass(frozen=True)
class SentencePolicy:
    """검사 3·5·10이 쓰는 정책값. 전부 호출자가 config에서 읽어 넘긴다.

    `max_targets_per_sentence`와 `max_new_items_per_sentence`는 MVP에서 둘 다
    `learning.max_new_items_per_sentence`에서 온다. 그래도 **인자를 나눠 두는
    이유**는 두 검사가 세는 대상이 다르기 때문이다 --- 5번은 문장의 target 전부를,
    10번은 그중 신규 item만 센다. 하나로 합치면 신규 ⊆ 전체이므로 10번이 영영
    발화하지 않는 죽은 검사가 된다.
    """

    max_sentence_length_chars: int
    max_targets_per_sentence: int
    max_new_items_per_sentence: int


# explanation에서 비어 있으면 안 되는 field. `example_translation`만 null 허용이다
# (`08_LLM_SPEC.md`의 `Ready invariant와 같은 범위`).
REQUIRED_EXPLANATION_FIELDS = (
    "reading",
    "core_meaning",
    "meaning_in_context",
    "nuance",
    "example_sentence",
)


def validate_sentence(
    payload: SentencePayload,
    *,
    requested_refs: frozenset[str],
    new_refs: frozenset[str],
    policy: SentencePolicy,
) -> ValidatedSentence | Rejection:
    """문장 하나에 검사 2~10과 13을 건다. 첫 실패에서 멈춘다.

    `requested_refs`는 이 요청이 보낸 `item_ref` 집합, `new_refs`는 그중 이
    사용자에게 신규인 것(검사 10). 둘 다 worker가 요청을 만들 때 이미 알고 있는
    값이며 응답에서 읽지 않는다.
    """
    japanese = payload.japanese

    if not japanese.strip():  # 2
        return Rejection(RejectionReason.EMPTY_JAPANESE, "japanese is empty")

    if len(japanese) > policy.max_sentence_length_chars:  # 3
        return Rejection(
            RejectionReason.SENTENCE_TOO_LONG,
            f"{len(japanese)} code points exceeds {policy.max_sentence_length_chars}",
        )

    if not payload.korean_translation.strip():  # 4
        return Rejection(RejectionReason.MISSING_TRANSLATION, "korean_translation is empty")

    unknown = [item.item_ref for item in payload.items if item.item_ref not in requested_refs]
    if unknown:  # 13
        return Rejection(
            RejectionReason.UNKNOWN_ITEM_REF,
            f"item_ref not in the request: {sorted(unknown)}",
        )

    # 응답의 item은 전부 요청한 target이다. worker는 요청에 실어 보낸 item_ref
    # 집합 밖의 표현으로 `sentence_items`를 만들지 않는다(`08_LLM_SPEC.md`의
    # `worker가 만들지 않는 것`).
    target_count = len(payload.items)
    if not 1 <= target_count <= policy.max_targets_per_sentence:  # 5
        return Rejection(
            RejectionReason.TARGET_COUNT_OUT_OF_RANGE,
            f"{target_count} targets, expected 1..{policy.max_targets_per_sentence}",
        )

    new_count = sum(1 for item in payload.items if item.item_ref in new_refs)
    if new_count > policy.max_new_items_per_sentence:  # 10
        return Rejection(
            RejectionReason.TOO_MANY_TARGETS,
            f"{new_count} new targets exceeds {policy.max_new_items_per_sentence}",
        )

    # span 자동 보정은 검사 **이전**에 끝난다. 아래 6·7·8은 보정된 span으로 다시
    # 처음부터 돌고, 보정이 만들어낸 span도 예외 없이 같은 검사를 받는다.
    items = tuple(_corrected_item(japanese, item) for item in payload.items)

    for item in items:
        rejection = _validate_item_spans(japanese, item)  # 6, 7
        if rejection is not None:
            return rejection

    overlap = _reject_cross_item_overlap(japanese, items)  # 8
    if overlap is not None:
        return overlap

    for item in items:  # 9
        rejection = _validate_tappable_explanation(item)
        if rejection is not None:
            return rejection

    return ValidatedSentence(payload.model_copy(update={"items": items}))


def validate_explanation(payload: ExplanationPayload) -> ValidatedExplanation | Rejection:
    """`EXPLAIN_ITEM` 응답에 검사 9의 field 조건을 건다."""
    missing = _missing_explanation_fields(payload)
    if missing is not None:
        return Rejection(RejectionReason.MISSING_EXPLANATION, missing)
    return ValidatedExplanation(payload)


# --------------------------------------------------------------------------
# span (6 / 7 / 8)
# --------------------------------------------------------------------------


def _item_spans(item: ItemPayload) -> tuple[ItemSpan, ...]:
    return tuple(
        ItemSpan(
            start_codepoint=span.start_codepoint,
            end_codepoint=span.end_codepoint,
            span_order=span.span_order,
        )
        for span in item.spans
    )


def _corrected_item(japanese: str, item: ItemPayload) -> ItemPayload:
    """모델이 틀린 offset을 **단 한 경우에만** 고친다.

    조건: span이 정확히 1개이고 `surface_form`이 문장에 정확히 1회 나타난다. 그때
    그 위치로 span을 통째로 교체한다. 후보가 여럿이면 어느 것이 의도였는지 알 수
    없고, span이 여럿이면 불연속 표현이라 위치를 재구성할 수 없다. 형태소
    분석기나 다중 후보 매칭은 MVP 의무 밖이다
    (`06_LLM_ENGINEERING_PRINCIPLES.md`의 `MVP 구현 의무 범위`).

    이미 맞는 span은 건드리지 않는다. 보정 결과가 옳다고 가정하지도 않는다 ---
    돌려준 item은 호출부에서 6·7·8을 처음부터 다시 받는다. 특히 보정된 위치가
    **다른 item의 span과 겹치는** 경우가 실제로 생기고, 그것은 8번에서 걸린다.
    """
    if item.surface_form and _spans_match(japanese, item):
        return item
    if len(item.spans) != 1 or not item.surface_form:
        return item
    if japanese.count(item.surface_form) != 1:
        return item

    # `str.index` / `str.count`는 code point 단위다(CPython의 str은 code point 열).
    start = japanese.index(item.surface_form)
    corrected = SpanPayload(
        start_codepoint=start,
        end_codepoint=start + len(item.surface_form),
        span_order=0,
    )
    return item.model_copy(update={"spans": (corrected,)})


def _spans_match(japanese: str, item: ItemPayload) -> bool:
    try:
        validate_item_spans(japanese, item.surface_form, _item_spans(item))
    except RenderSpanError:
        return False
    return True


def _validate_item_spans(japanese: str, item: ItemPayload) -> Rejection | None:
    """item 하나의 span 집합 (검사 6·7 + item 안의 overlap).

    판정은 `app.render.validate_item_spans`가 한다. 그 함수는 세 가지를 한 예외로
    합쳐 내므로, **탈락시킬지**가 아니라 **어떤 사유 코드로 집계할지**만 아래에서
    다시 가려낸다. 분류가 틀려도 결과는 여전히 탈락이다.
    """
    spans = _item_spans(item)
    if not spans:
        return Rejection(RejectionReason.SPAN_OUT_OF_RANGE, f"item {item.item_ref!r} has no spans")
    try:
        validate_item_spans(japanese, item.surface_form, spans)
    except RenderSpanError as error:
        if _has_invalid_boundary(japanese, spans):
            return Rejection(RejectionReason.SPAN_OUT_OF_RANGE, f"{item.item_ref}: {error}")
        if _overlaps(spans):
            return Rejection(RejectionReason.SPAN_OVERLAP, f"{item.item_ref}: {error}")
        return Rejection(RejectionReason.SURFACE_NOT_FOUND, f"{item.item_ref}: {error}")
    return None


def _has_invalid_boundary(japanese: str, spans: tuple[ItemSpan, ...]) -> bool:
    """검사 7: code point index 범위와 `span_order`의 유효성.

    lone surrogate가 섞인 문자열도 여기로 본다 --- 그것은 offset을 UTF-16 code unit
    기준으로 적어 넣은 응답의 흔적이고, 그 순간 모든 span 경계가 의미를 잃는다.
    """
    if any(0xD800 <= ord(char) <= 0xDFFF for char in japanese):
        return True
    if sorted(span.span_order for span in spans) != list(range(len(spans))):
        return True
    return any(
        not 0 <= span.start_codepoint < span.end_codepoint <= len(japanese) for span in spans
    )


def _overlaps(spans: tuple[ItemSpan, ...]) -> bool:
    ordered = sorted(spans, key=lambda span: span.start_codepoint)
    return any(
        current.start_codepoint < previous.end_codepoint
        for previous, current in itertools.pairwise(ordered)
    )


def _reject_cross_item_overlap(japanese: str, items: tuple[ItemPayload, ...]) -> Rejection | None:
    """검사 8: 서로 **다른** item의 tappable span이 겹치면 그 문장은 ambiguous하다.

    `validate_item_spans`는 item 하나 안만 본다. 문장의 tappable span **전부를**
    `build_render_segments`에 한 번에 넣으면 그 함수가 span을 정렬한 뒤 이미 하는
    `start < cursor` 검사가 cross-item overlap까지 잡는다. seed loader가 같은
    방식이며, 그래서 "렌더링이 터지는 조건"과 "생성을 거부하는 조건"이 정의상
    같아진다.

    `sentence_item_id`에는 아직 DB id가 없으므로 문장 안 item의 순번을 넣는다.
    """
    spans = [
        SpanRef(
            sentence_item_id=index,
            learning_item_id=index,
            is_tappable=True,
            start_codepoint=span.start_codepoint,
            end_codepoint=span.end_codepoint,
        )
        for index, item in enumerate(items)
        if item.is_tappable
        for span in item.spans
    ]
    try:
        build_render_segments(japanese, spans)
    except RenderSpanError as error:
        return Rejection(RejectionReason.SPAN_OVERLAP, str(error))
    return None


# --------------------------------------------------------------------------
# explanation (9)
# --------------------------------------------------------------------------


def _validate_tappable_explanation(item: ItemPayload) -> Rejection | None:
    """검사 9의 범위는 target만이 아니라 `is_tappable = true`인 **모든** item이다.

    Ready invariant와 같은 범위다(`08_LLM_SPEC.md`의
    `Ready invariant와 같은 범위`). 약한 해석(target only)을 쓰면 생성 validation은
    통과했는데 candidate는 될 수 없는 문장이 조용히 쌓이고, 어느 지표에도 실패로
    잡히지 않아 pool이 비는 이유가 보이지 않는다.
    """
    if not item.is_tappable:
        return None
    if item.explanation is None:
        return Rejection(
            RejectionReason.MISSING_EXPLANATION,
            f"tappable item {item.item_ref!r} has no explanation",
        )
    missing = _missing_explanation_fields(item.explanation)
    if missing is not None:
        return Rejection(RejectionReason.MISSING_EXPLANATION, f"{item.item_ref}: {missing}")
    return None


def _missing_explanation_fields(explanation: ExplanationPayload) -> str | None:
    empty = [
        name for name in REQUIRED_EXPLANATION_FIELDS if not str(getattr(explanation, name)).strip()
    ]
    if empty:
        return f"empty explanation fields: {empty}"
    return None
