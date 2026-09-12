"""Sentence를 렌더링용 segment list로 바꾸는 순수 함수 (05_API_SPEC.md).

offset 기준은 Unicode **code point** index다(04_DB_SPEC.md의 `sentence_item_spans`).
Python `str`가 곧 code point 시퀀스이므로 `start_codepoint` / `end_codepoint`를
**그대로 슬라이스 인덱스로 쓴다.** UTF-16 code unit으로 변환하지 않는다 --- 이모지나
BMP 밖 한자가 한 글자라도 들어오면 두 기준이 갈리고, 그 순간 span이 글자 중간을
자른다.

frontend는 받은 `text` 조각을 순서대로 이어 붙이기만 하고 인덱스를 전혀 보지
않는다. 그래서 이 모듈의 불변식은 하나로 압축된다.

    "".join(segment.text for segment in segments) == japanese

`validate_item_spans`는 적재/생성 시점의 검증이고 `build_render_segments`는 표시
시점의 렌더링이다. 둘을 한 모듈에 두는 이유는 판정 기준이 갈리면 검증을 통과한
문장이 렌더링에서 터지기 때문이다. 검증하는 쪽은 sentence_item 하나 안만 보고,
**문장 전체의 tappable span이 서로 겹치는지는 `build_render_segments`를 그대로
불러서** 확인한다(호출자 몫). 렌더링이 터지는 조건과 거부 조건이 정의상 같아진다.

DB를 모른다. span row를 `SpanRef`로 바꿔 넘기는 것은 호출하는 service의 몫이다.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from dataclasses import dataclass


class RenderSpanError(ValueError):
    """span이 문장과 맞지 않는다.

    콘텐츠 생성 validation이 막았어야 할 상태이므로 조용히 넘기지 않는다. 잘못된
    span을 무시하고 렌더링하면 사용자에게는 tappable이 하나 사라진 정상 문장처럼
    보이고, 아무도 그 문장을 고치지 않는다.
    """


@dataclass(frozen=True)
class SpanRef:
    """`sentence_item_spans` 한 행 + 소속 `sentence_items`의 식별자와 tappable 여부."""

    sentence_item_id: int
    learning_item_id: int
    is_tappable: bool
    start_codepoint: int
    end_codepoint: int


@dataclass(frozen=True)
class ItemSpan:
    """검증 전의 span 하나. 아직 어느 `sentence_item`에도 붙지 않았다."""

    start_codepoint: int
    end_codepoint: int
    span_order: int


@dataclass(frozen=True)
class RenderSegment:
    """`sentence_item_id`가 NULL이면 tap할 수 없는 일반 텍스트다."""

    text: str
    sentence_item_id: int | None


@dataclass(frozen=True)
class TappableItem:
    sentence_item_id: int
    learning_item_id: int


def build_render_segments(japanese: str, spans: Sequence[SpanRef]) -> list[RenderSegment]:
    """문장을 순서대로 이어 붙일 수 있는 segment 목록으로 자른다.

    `is_tappable = false`인 sentence_item의 span은 **일반 텍스트로 흘려보낸다.**
    tap 대상이 아닌 것을 segment로 갈라 놓으면 frontend가 tappable 여부를 다시
    판단해야 한다.

    같은 `sentence_item_id`의 span이 여러 개인 불연속 표현(`気が全然乗らない`)은
    **각 span이 각각 segment**가 되고 전부 같은 `sentence_item_id`를 갖는다. 사이
    텍스트는 `sentence_item_id = None` segment다. 두 span을 하나로 합치면 그 사이의
    `全然`이 표현의 일부가 되어 원문이 깨진다.

    길이 0인 segment는 만들지 않는다.
    """
    tappable = sorted(
        (span for span in spans if span.is_tappable),
        key=lambda span: (span.start_codepoint, span.end_codepoint),
    )

    segments: list[RenderSegment] = []
    cursor = 0
    for span in tappable:
        _validate(span, length=len(japanese))
        if span.start_codepoint < cursor:
            raise RenderSpanError(
                f"tappable spans overlap at codepoint {span.start_codepoint} "
                f"(sentence_item_id={span.sentence_item_id})"
            )
        if span.start_codepoint > cursor:
            segments.append(RenderSegment(japanese[cursor : span.start_codepoint], None))
        segments.append(
            RenderSegment(
                japanese[span.start_codepoint : span.end_codepoint],
                span.sentence_item_id,
            )
        )
        cursor = span.end_codepoint

    if cursor < len(japanese):
        segments.append(RenderSegment(japanese[cursor:], None))
    return segments


def build_tappable_items(spans: Sequence[SpanRef]) -> list[TappableItem]:
    """tap 가능한 sentence_item 목록. 불연속 표현의 span 여러 개는 한 항목으로 합친다."""
    items: dict[int, TappableItem] = {}
    for span in spans:
        if not span.is_tappable:
            continue
        items.setdefault(
            span.sentence_item_id,
            TappableItem(
                sentence_item_id=span.sentence_item_id,
                learning_item_id=span.learning_item_id,
            ),
        )
    return [items[key] for key in sorted(items)]


def validate_item_spans(japanese: str, surface_form: str, spans: Sequence[ItemSpan]) -> None:
    """sentence_item 하나의 span 집합이 문장과 맞는지 확인한다.

    offset이 `japanese`의 실제 code point index와 맞는지 본다. CPython의 `str`은
    code point 열이므로(PEP 393) `list(japanese)`의 원소 하나가 code point 하나다.
    이모지 같은 BMP 밖 문자도 여기서는 1칸이며 UTF-16 code unit 기준으로는 2칸이다.
    그 둘이 섞이는 유일한 통로는 lone surrogate(UTF-16 index를 그대로 옮겨 적은
    문자열)이므로 그런 문자열은 아예 거부한다.

    **범위는 item 하나 안이다.** 서로 다른 item의 span이 겹치는지는 문장의 tappable
    span 전부를 `build_render_segments`에 한 번에 넣어 확인한다. 여기의 overlap
    검사는 그 검사가 보지 않는 non-tappable item까지 덮는다.
    """
    codepoints = list(japanese)
    for offset, char in enumerate(codepoints):
        if 0xD800 <= ord(char) <= 0xDFFF:
            raise RenderSpanError(
                f"'japanese' contains a lone surrogate at code point {offset}; "
                "offsets must be Unicode code point indexes, not UTF-16 code units"
            )

    orders = sorted(span.span_order for span in spans)
    if orders != list(range(len(spans))):
        raise RenderSpanError(f"span_order must be 0..{len(spans) - 1} exactly once, got {orders}")

    pieces: list[str] = []
    for span in sorted(spans, key=lambda span: span.span_order):
        if not 0 <= span.start_codepoint < span.end_codepoint <= len(codepoints):
            raise RenderSpanError(
                f"span [{span.start_codepoint}, {span.end_codepoint}) is out of range "
                f"for a sentence of {len(codepoints)} code points"
            )
        pieces.append("".join(codepoints[span.start_codepoint : span.end_codepoint]))

    _reject_overlapping_spans(spans)

    covered = "".join(pieces)
    if covered != surface_form:
        raise RenderSpanError(f"spans cover {covered!r} but surface_form is {surface_form!r}")


def _reject_overlapping_spans(spans: Sequence[ItemSpan]) -> None:
    """서로 **겹치는** span을 거부한다.

    금지하는 것은 overlap뿐이다. **떨어져 있는(disjoint) span은 정상이다** ---
    `気が全然乗らない`처럼 하나의 표현이 문장 안에서 끊겨 나타나는 불연속 표현은
    span 여러 개로 표현하는 것이 정상 데이터다. 사이의 빈칸은 검사하지 않는다.

    겹치면 같은 code point가 같은 item의 두 span에 속하게 되어 같은 글자가
    surface_form에 두 번 들어간다.
    """
    ordered = sorted(spans, key=lambda span: span.start_codepoint)
    for previous, current in itertools.pairwise(ordered):
        if current.start_codepoint < previous.end_codepoint:
            raise RenderSpanError(
                f"spans [{previous.start_codepoint}, {previous.end_codepoint}) and "
                f"[{current.start_codepoint}, {current.end_codepoint}) overlap; "
                "spans may be discontinuous but must not cover the same code point twice"
            )


def _validate(span: SpanRef, *, length: int) -> None:
    if span.start_codepoint < 0:
        # 음수를 통과시키면 Python 슬라이스가 뒤에서부터 세어 조용히 다른 곳을 자른다.
        raise RenderSpanError(
            f"span starts before the sentence: start={span.start_codepoint} "
            f"(sentence_item_id={span.sentence_item_id})"
        )
    if span.end_codepoint <= span.start_codepoint:
        raise RenderSpanError(
            f"span is empty or reversed: start={span.start_codepoint} "
            f"end={span.end_codepoint} (sentence_item_id={span.sentence_item_id})"
        )
    if span.end_codepoint > length:
        raise RenderSpanError(
            f"span ends past the sentence: end={span.end_codepoint} "
            f"length={length} (sentence_item_id={span.sentence_item_id})"
        )
