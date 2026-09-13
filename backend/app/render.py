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

**ruby(후리가나, MVP-02, ADR-021).** 저장값 모양 파싱(`parse_stored_ruby`), 검증
(`validate_ruby_spans`), segment 안 분할(`build_render_segments`의 `ruby`)도 여기에 둔다.
같은 검증 함수를 계산 시점(`app/furigana.py`)과 표시 시점(API)이 **둘 다** 부른다.
분석기를 모른다. 좌표는 `sentence_item_spans`와 같은 code point `[start, end)`다.
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


class RubySpanError(RenderSpanError):
    """ruby 값이 문장·tappable span과 맞지 않거나 저장값 모양이 틀렸다.

    `RenderSpanError`와 달리 표시 시점에는 500이 아니다(05_API_SPEC.md R6). 호출자는 tappable
    segment를 먼저 만들고(그 실패는 500) ruby 검증은 그 뒤에 따로 부른다.
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
class RubySpan:
    """`sentences.ruby_json.spans`의 원소 하나. `[start_codepoint, end_codepoint, reading]`."""

    start_codepoint: int
    end_codepoint: int
    reading: str


@dataclass(frozen=True)
class RubyPart:
    """segment 안의 표시 조각. `reading`이 None이면 후리가나 없이 text만 그린다."""

    text: str
    reading: str | None


@dataclass(frozen=True)
class RenderSegment:
    """`sentence_item_id`가 NULL이면 tap할 수 없는 일반 텍스트다.

    `ruby`가 비어 있으면 이 segment에 달 읽기가 없다(R2). 그 밖에는 parts의 text를 이으면
    `text`와 같다(R1).
    """

    text: str
    sentence_item_id: int | None
    ruby: tuple[RubyPart, ...] = ()


@dataclass(frozen=True)
class TappableItem:
    sentence_item_id: int
    learning_item_id: int


def build_render_segments(
    japanese: str,
    spans: Sequence[SpanRef],
    ruby: Sequence[RubySpan] | None = None,
) -> list[RenderSegment]:
    """문장을 순서대로 이어 붙일 수 있는 segment 목록으로 자른다.

    `is_tappable = false`인 sentence_item의 span은 **일반 텍스트로 흘려보낸다.**
    tap 대상이 아닌 것을 segment로 갈라 놓으면 frontend가 tappable 여부를 다시
    판단해야 한다.

    같은 `sentence_item_id`의 span이 여러 개인 불연속 표현(`気が全然乗らない`)은
    **각 span이 각각 segment**가 되고 전부 같은 `sentence_item_id`를 갖는다. 사이
    텍스트는 `sentence_item_id = None` segment다. 두 span을 하나로 합치면 그 사이의
    `全然`이 표현의 일부가 되어 원문이 깨진다.

    길이 0인 segment는 만들지 않는다.

    `ruby`가 있으면 tappable span을 **먼저** 검증한 뒤(`RenderSpanError`) ruby를 검증하고
    (`RubySpanError`) segment마다 `RubyPart`로 자른다. `None`이나 빈 목록이면 모든 segment의
    ruby는 `()`다.
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

    if not ruby:
        return segments
    validate_ruby_spans(
        japanese, ruby, [(span.start_codepoint, span.end_codepoint) for span in tappable]
    )
    return _attach_ruby(japanese, segments, ruby)


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


# --------------------------------------------------------------------------
# ruby (MVP-02, ADR-021 결정 2·5, 05_API_SPEC.md R1~R6)
# --------------------------------------------------------------------------

# R4: 히라가나 U+3041..U+3096, ゝ(U+309D), ゞ(U+309E), ー(U+30FC). unicodedata는 쓰지 않는다
# (Python minor마다 Unicode 버전이 달라 판정이 갈릴 수 있다).
_READING_EXTRA_CODEPOINTS = frozenset({0x309D, 0x309E, 0x30FC})


def is_reading_char(char: str) -> bool:
    """ruby 읽기에 허용되는 문자 하나인지(R4)."""
    codepoint = ord(char)
    return 0x3041 <= codepoint <= 0x3096 or codepoint in _READING_EXTRA_CODEPOINTS


def is_valid_reading(reading: str) -> bool:
    """비어 있지 않고 모든 문자가 R4 집합 안이다."""
    return bool(reading) and all(is_reading_char(char) for char in reading)


def parse_stored_ruby(value: object) -> list[RubySpan]:
    """`sentences.ruby_json` 저장값에서 span 목록을 꺼낸다. 모양만 본다.

    `None`(미계산, R5)은 호출자가 먼저 가른다 --- 여기로 넘기면 모양 오류다. 범위·겹침·경계·
    읽기 문자 집합은 `validate_ruby_spans`의 몫이다. 모양이 틀리면 `RubySpanError`다(R6).
    """
    if not isinstance(value, dict):
        raise RubySpanError(f"ruby_json must be an object, got {type(value).__name__}")
    if "spans" not in value:
        raise RubySpanError("ruby_json has no 'spans'")
    raw_spans = value["spans"]
    if not isinstance(raw_spans, list):
        raise RubySpanError(f"ruby_json.spans must be an array, got {type(raw_spans).__name__}")

    parsed: list[RubySpan] = []
    for index, raw in enumerate(raw_spans):
        if not isinstance(raw, list) or len(raw) != 3:
            raise RubySpanError(f"ruby_json.spans[{index}] must be a 3-element array")
        start, end, reading = raw
        # bool은 int의 하위 타입이다. JSON true를 좌표 1로 읽지 않는다.
        if not _is_plain_int(start) or not _is_plain_int(end):
            raise RubySpanError(f"ruby_json.spans[{index}] start/end must be integers")
        if not isinstance(reading, str):
            raise RubySpanError(f"ruby_json.spans[{index}] reading must be a string")
        parsed.append(RubySpan(start_codepoint=start, end_codepoint=end, reading=reading))
    return parsed


def validate_ruby_spans(
    japanese: str,
    ruby: Sequence[RubySpan],
    tappable_spans: Sequence[tuple[int, int]],
) -> None:
    """ruby span 목록이 문장과 tappable span에 맞는지 확인한다(04_DB_SPEC.md `ruby_json`, R6).

    `tappable_spans`는 `is_tappable = true`인 sentence_item의 span `(start, end)` 전부다.
    non-tappable span은 렌더링에서 일반 텍스트로 흐르므로 경계가 아니다.

    - 모든 span이 원문 code point 범위 안이고 start < end
    - start 오름차순이고 서로 겹치지 않는다
    - 어떤 span도 tappable span의 경계를 넘지 않는다(안에 있거나 완전히 밖)
    - reading이 비어 있지 않고 R4 문자만으로 되어 있다
    """
    length = len(japanese)
    previous_end = 0
    for index, span in enumerate(ruby):
        start, end = span.start_codepoint, span.end_codepoint
        if not 0 <= start < end <= length:
            raise RubySpanError(
                f"ruby span {index} [{start}, {end}) is out of range "
                f"for a sentence of {length} code points"
            )
        if start < previous_end:
            raise RubySpanError(
                f"ruby span {index} [{start}, {end}) is not in ascending order "
                "or overlaps the previous span"
            )
        previous_end = end
        for tappable_start, tappable_end in tappable_spans:
            inside = tappable_start <= start and end <= tappable_end
            disjoint = end <= tappable_start or tappable_end <= start
            if not (inside or disjoint):
                raise RubySpanError(
                    f"ruby span {index} [{start}, {end}) crosses the tappable span "
                    f"[{tappable_start}, {tappable_end})"
                )
        if not is_valid_reading(span.reading):
            raise RubySpanError(f"ruby span {index} reading is empty or not hiragana")


def _is_plain_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _attach_ruby(
    japanese: str, segments: list[RenderSegment], ruby: Sequence[RubySpan]
) -> list[RenderSegment]:
    """검증된 ruby span을 segment마다 `RubyPart`로 자른다(R1~R3).

    검증을 통과한 span은 정의상 segment 하나 안에 들어간다(tappable span 안이거나, 일반 텍스트
    segment = 인접 tappable span 사이의 최대 구간 안). 그래도 걸치면 조용히 자르지 않고 던진다.
    """
    result: list[RenderSegment] = []
    remaining = list(ruby)
    segment_start = 0
    for segment in segments:
        segment_end = segment_start + len(segment.text)
        inside: list[RubySpan] = []
        while remaining and remaining[0].start_codepoint < segment_end:
            span = remaining.pop(0)
            if span.end_codepoint > segment_end:
                raise RubySpanError(
                    f"ruby span [{span.start_codepoint}, {span.end_codepoint}) crosses "
                    f"the segment [{segment_start}, {segment_end})"
                )
            inside.append(span)
        result.append(
            RenderSegment(
                segment.text,
                segment.sentence_item_id,
                _ruby_parts(japanese, segment_start, segment_end, inside),
            )
        )
        segment_start = segment_end
    return result


def _ruby_parts(
    japanese: str, segment_start: int, segment_end: int, inside: Sequence[RubySpan]
) -> tuple[RubyPart, ...]:
    """R2: 달 읽기가 없으면 `[{"text": ..., "reading": null}]`가 아니라 `()`.

    R3: span 사이의 일반 텍스트는 **최대 구간 하나**를 part 하나로 만든다. 그래서 reading이
    null인 part가 서로 인접하는 일이 없고, 길이 0인 part도 없다.
    """
    if not inside:
        return ()
    parts: list[RubyPart] = []
    cursor = segment_start
    for span in inside:
        if span.start_codepoint > cursor:
            parts.append(RubyPart(japanese[cursor : span.start_codepoint], None))
        parts.append(RubyPart(japanese[span.start_codepoint : span.end_codepoint], span.reading))
        cursor = span.end_codepoint
    if cursor < segment_end:
        parts.append(RubyPart(japanese[cursor:segment_end], None))
    return tuple(parts)
