"""render segment 생성 (05_API_SPEC.md, 04_DB_SPEC.md의 `sentence_item_spans`).

DB가 필요 없다. 순수 함수이므로 integration 마크도 fixture도 쓰지 않는다.

핵심 단정 둘:
  - segment text를 이어 붙이면 원문과 정확히 같다.
  - offset은 **code point** 기준이다. UTF-16 code unit이 아니다.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from app.render import (
    ItemSpan,
    RenderSegment,
    RenderSpanError,
    SpanRef,
    build_render_segments,
    build_tappable_items,
    validate_item_spans,
)

# 표준 예시(06/05 명세). `気が` + `乗らない`가 한 item이고 사이에 `全然`이 낀다.
DISCONTINUOUS = "気が全然乗らない"

# BMP 밖 문자 둘. UTF-16에서는 각각 2 code unit, Python `str`에서는 1 code point다.
# 🍣 = U+1F363, 𠮷 = U+20BB7.
ASTRAL_PREFIX = "🍣𠮷"


def span(
    sentence_item_id: int,
    start: int,
    end: int,
    *,
    learning_item_id: int = 1,
    is_tappable: bool = True,
) -> SpanRef:
    return SpanRef(
        sentence_item_id=sentence_item_id,
        learning_item_id=learning_item_id,
        is_tappable=is_tappable,
        start_codepoint=start,
        end_codepoint=end,
    )


def rendered(segments: list[RenderSegment]) -> list[tuple[str, int | None]]:
    return [(segment.text, segment.sentence_item_id) for segment in segments]


# --------------------------------------------------------------------------
# 연결 불변식 (property)
# --------------------------------------------------------------------------


def _span_sets(length: int, start: int = 0) -> Iterator[list[tuple[int, int]]]:
    """길이 `length` 문자열 위의 서로 겹치지 않는 span 조합 **전부**.

    무작위 생성 대신 전수 열거를 쓴다. 짧은 문자열에서는 경우의 수가 작고, 실패가
    항상 같은 입력으로 재현된다.
    """
    yield []
    for begin in range(start, length):
        for end in range(begin + 1, length + 1):
            for rest in _span_sets(length, end):
                yield [(begin, end), *rest]


@pytest.mark.parametrize("text", ["今日は家にいた", ASTRAL_PREFIX + "気が乗ら"])
def test_joining_every_segment_reproduces_the_sentence(text: str) -> None:
    """frontend는 text를 순서대로 이어 붙이기만 한다. 이 등식이 깨지면 문장이 깨진다."""
    cases = 0
    for offsets in _span_sets(len(text)):
        spans = [span(index + 1, begin, end) for index, (begin, end) in enumerate(offsets)]
        segments = build_render_segments(text, spans)

        assert "".join(segment.text for segment in segments) == text
        assert all(segment.text for segment in segments), "빈 segment를 만들지 않는다"
        assert [segment.sentence_item_id for segment in segments if segment.sentence_item_id] == [
            index + 1 for index in range(len(offsets))
        ]
        cases += 1
    assert cases > 20, "전수 열거가 실제로 여러 경우를 훑었는지"


def test_a_span_covering_the_whole_sentence_yields_exactly_one_segment() -> None:
    """앞뒤로 길이 0인 segment를 붙이지 않는다."""
    segments = build_render_segments(DISCONTINUOUS, [span(7, 0, len(DISCONTINUOUS))])

    assert rendered(segments) == [(DISCONTINUOUS, 7)]


# --------------------------------------------------------------------------
# 불연속 span
# --------------------------------------------------------------------------


def test_discontinuous_spans_of_one_item_become_two_segments_with_the_same_id() -> None:
    """`気が全然乗らない`의 item은 `気が` + `乗らない`다. 사이 `全然`은 표현이 아니다."""
    spans = [span(7, 0, 2), span(7, 4, 8)]

    segments = build_render_segments(DISCONTINUOUS, spans)

    assert rendered(segments) == [("気が", 7), ("全然", None), ("乗らない", 7)]


def test_discontinuous_spans_are_one_tappable_item() -> None:
    spans = [span(7, 4, 8, learning_item_id=42), span(7, 0, 2, learning_item_id=42)]

    items = build_tappable_items(spans)

    assert [(item.sentence_item_id, item.learning_item_id) for item in items] == [(7, 42)]


def test_spans_are_ordered_by_start_not_by_input_order() -> None:
    segments = build_render_segments(DISCONTINUOUS, [span(7, 4, 8), span(9, 0, 2)])

    assert rendered(segments) == [("気が", 9), ("全然", None), ("乗らない", 7)]


# --------------------------------------------------------------------------
# tappable 여부
# --------------------------------------------------------------------------


def test_non_tappable_spans_flow_through_as_plain_text() -> None:
    """tap할 수 없는 span을 segment로 갈라 놓으면 frontend가 다시 판단해야 한다."""
    spans = [span(7, 0, 2, is_tappable=False), span(9, 4, 8)]

    segments = build_render_segments(DISCONTINUOUS, spans)

    assert rendered(segments) == [("気が全然", None), ("乗らない", 9)]


def test_non_tappable_items_are_not_listed() -> None:
    spans = [span(7, 0, 2, learning_item_id=42, is_tappable=False), span(9, 4, 8)]

    assert [item.sentence_item_id for item in build_tappable_items(spans)] == [9]


def test_tappable_items_are_deduped_and_sorted_by_sentence_item_id() -> None:
    spans = [span(9, 4, 8, learning_item_id=2), span(7, 0, 2), span(7, 2, 4)]

    assert [item.sentence_item_id for item in build_tappable_items(spans)] == [7, 9]


def test_a_non_tappable_span_may_overlap_a_tappable_one() -> None:
    """overlap 금지는 tappable span끼리의 규칙이다. 무시되는 span은 자리를 차지하지 않는다."""
    spans = [span(7, 0, 8, is_tappable=False), span(9, 0, 2)]

    assert rendered(build_render_segments(DISCONTINUOUS, spans)) == [
        ("気が", 9),
        ("全然乗らない", None),
    ]


# --------------------------------------------------------------------------
# code point vs UTF-16
# --------------------------------------------------------------------------


def test_offsets_are_code_points_not_utf16_code_units() -> None:
    """🍣와 𠮷는 UTF-16에서 각각 2 code unit이다. 그 차이가 드러나는 자리다."""
    text = ASTRAL_PREFIX + DISCONTINUOUS
    assert len(text.encode("utf-16-le")) // 2 == len(text) + 2, "두 기준이 실제로 갈리는 입력"

    # code point 기준으로 `気が`는 2..4다. UTF-16 기준이면 4..6이 되어 `全然`을 자른다.
    segments = build_render_segments(text, [span(7, 2, 4)])

    assert rendered(segments) == [(ASTRAL_PREFIX, None), ("気が", 7), ("全然乗らない", None)]


def test_a_span_may_start_at_an_astral_character() -> None:
    """surrogate pair 한 짝을 반으로 자르지 않는다 --- code point 하나이므로 자를 수가 없다."""
    text = ASTRAL_PREFIX + "が好き"

    segments = build_render_segments(text, [span(7, 0, 2)])

    assert rendered(segments) == [(ASTRAL_PREFIX, 7), ("が好き", None)]


def test_the_last_code_point_is_reachable() -> None:
    text = "気が" + ASTRAL_PREFIX

    segments = build_render_segments(text, [span(7, 2, 4)])

    assert rendered(segments) == [("気が", None), (ASTRAL_PREFIX, 7)]


# --------------------------------------------------------------------------
# 잘못된 span
# --------------------------------------------------------------------------


def test_overlapping_tappable_spans_are_rejected() -> None:
    spans = [span(7, 0, 4), span(9, 2, 6)]

    with pytest.raises(RenderSpanError, match="overlap"):
        build_render_segments(DISCONTINUOUS, spans)


def test_two_spans_that_share_a_start_are_rejected() -> None:
    spans = [span(7, 0, 2), span(9, 0, 4)]

    with pytest.raises(RenderSpanError, match="overlap"):
        build_render_segments(DISCONTINUOUS, spans)


@pytest.mark.parametrize(("start", "end"), [(2, 2), (4, 2)])
def test_an_empty_or_reversed_span_is_rejected(start: int, end: int) -> None:
    with pytest.raises(RenderSpanError, match="empty or reversed"):
        build_render_segments(DISCONTINUOUS, [span(7, start, end)])


def test_a_span_past_the_end_of_the_sentence_is_rejected() -> None:
    with pytest.raises(RenderSpanError, match="past the sentence"):
        build_render_segments(DISCONTINUOUS, [span(7, 4, len(DISCONTINUOUS) + 1)])


def test_a_negative_start_is_rejected() -> None:
    """음수를 통과시키면 Python 슬라이스가 뒤에서부터 세어 조용히 다른 곳을 자른다."""
    with pytest.raises(RenderSpanError, match="before the sentence"):
        build_render_segments(DISCONTINUOUS, [span(7, -2, 2)])


def test_a_sentence_without_spans_is_one_plain_segment() -> None:
    assert rendered(build_render_segments(DISCONTINUOUS, [])) == [(DISCONTINUOUS, None)]


# --------------------------------------------------------------------------
# item 단위 span 검증 (`validate_item_spans`)
#
# seed 적재와 생성 validation이 같이 쓰는 검사다. 각 테스트는 **특정 검사 한 줄을
# 지우면 빨개지도록** 짰다.
# --------------------------------------------------------------------------

SENTENCE = "仕事を任せる。"  # 7 code points: 仕 事 を 任 せ る 。


def item_spans(*triples: tuple[int, int, int]) -> tuple[ItemSpan, ...]:
    return tuple(
        ItemSpan(start_codepoint=start, end_codepoint=end, span_order=order)
        for start, end, order in triples
    )


def test_span_order_must_be_zero_based_and_contiguous() -> None:
    """span_order 검사를 지우면 빨개진다.

    offset과 surface_form은 서로 맞으므로 span_order 검사만이 유일한 거부 사유다.
    """
    with pytest.raises(RenderSpanError, match="span_order"):
        validate_item_spans(SENTENCE, "仕事", item_spans((0, 2, 1)))


@pytest.mark.parametrize(
    ("start", "end", "surface_form"),
    [
        # 각 케이스의 surface_form은 "범위 검사를 지웠을 때 Python 슬라이싱이
        # 실제로 만들어내는 문자열"이다. 검사를 지우면 surface_form 대조도
        # 통과해버리므로 예외가 사라지고 테스트가 빨개진다.
        (0, 99, SENTENCE),  # end가 문장 밖
        (-1, 2, ""),  # 음수 start (슬라이싱은 뒤에서 세므로 조용히 빈 문자열)
        (2, 2, ""),  # 빈 span
    ],
)
def test_item_span_offsets_outside_the_sentence_are_rejected(
    start: int, end: int, surface_form: str
) -> None:
    with pytest.raises(RenderSpanError, match="out of range"):
        validate_item_spans(SENTENCE, surface_form, item_spans((start, end, 0)))


def test_sentence_with_a_lone_surrogate_is_rejected() -> None:
    """lone surrogate 검사를 지우면 빨개진다.

    span은 문장과 정합하므로 그 검사가 사라지면 아무 예외도 나지 않는다.
    lone surrogate는 offset이 code point가 아니라 UTF-16 code unit이라는 신호다.
    """
    japanese = "仕事\ud800を任せる。"
    with pytest.raises(RenderSpanError, match="lone surrogate"):
        validate_item_spans(japanese, "仕事", item_spans((0, 2, 0)))


def test_overlapping_spans_within_one_item_are_rejected() -> None:
    """overlap 검사를 지우면 빨개진다.

    두 span이 `事`를 공유해도 이어붙인 결과가 surface_form과 같아서 다른 검사는
    전부 통과한다. 12_TEST_PLAN.md의 Unit 항목이 요구하는 거부다.
    """
    with pytest.raises(RenderSpanError, match="overlap"):
        validate_item_spans(SENTENCE, "仕事事を", item_spans((0, 2, 0), (1, 3, 1)))


def test_discontinuous_spans_are_allowed() -> None:
    """떨어져 있는(disjoint) span은 정상이다. 불연속 표현이 이 형태다.

    overlap 거부가 "붙어 있지 않으면 거부"로 과잉 구현되면 빨개진다.
    """
    validate_item_spans("気が全然乗らない。", "気が乗らない", item_spans((0, 2, 0), (4, 8, 1)))


def test_surface_form_is_compared_in_span_order_not_position() -> None:
    """조각을 잇는 순서는 `span_order`다. 위치 순으로 이으면 빨개진다."""
    validate_item_spans(SENTENCE, "任せる仕事", item_spans((3, 6, 0), (0, 2, 1)))
