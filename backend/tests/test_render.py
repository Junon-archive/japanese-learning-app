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
    RubyPart,
    RubySpan,
    RubySpanError,
    SpanRef,
    build_render_segments,
    build_tappable_items,
    parse_stored_ruby,
    validate_item_spans,
    validate_ruby_spans,
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


# --------------------------------------------------------------------------
# ruby (MVP-02, 05_API_SPEC.md의 `render_segments[].ruby` R1~R6, ADR-021 결정 5)
# --------------------------------------------------------------------------

# 05_API_SPEC.md 예시(끝 문장부호만 。). `任せ`(5511)와 `てもいい`(5512)가 tappable이다.
#   こ0 の1 仕2 事3 、4 田5 中6 さ7 ん8 に9 任10 せ11 て12 も13 い14 い15 。16
MAKASE = "この仕事、田中さんに任せてもいい。"
MAKASE_SPANS = [span(5511, 10, 12), span(5512, 12, 16)]
MAKASE_RUBY = [RubySpan(2, 4, "しごと"), RubySpan(5, 7, "たなか"), RubySpan(10, 11, "まか")]


def ruby(*triples: tuple[int, int, str]) -> list[RubySpan]:
    return [RubySpan(start, end, reading) for start, end, reading in triples]


def as_payload(segments: list[RenderSegment]) -> list[dict[str, object]]:
    return [
        {
            "text": segment.text,
            "sentence_item_id": segment.sentence_item_id,
            "ruby": [{"text": part.text, "reading": part.reading} for part in segment.ruby],
        }
        for segment in segments
    ]


def test_the_api_spec_example_is_reproduced_exactly() -> None:
    segments = build_render_segments(MAKASE, MAKASE_SPANS, ruby=MAKASE_RUBY)

    assert as_payload(segments) == [
        {
            "text": "この仕事、田中さんに",
            "sentence_item_id": None,
            "ruby": [
                {"text": "この", "reading": None},
                {"text": "仕事", "reading": "しごと"},
                {"text": "、", "reading": None},
                {"text": "田中", "reading": "たなか"},
                {"text": "さんに", "reading": None},
            ],
        },
        {
            "text": "任せ",
            "sentence_item_id": 5511,
            "ruby": [{"text": "任", "reading": "まか"}, {"text": "せ", "reading": None}],
        },
        {"text": "てもいい", "sentence_item_id": 5512, "ruby": []},
        {"text": "。", "sentence_item_id": None, "ruby": []},
    ]


def test_existing_callers_without_ruby_get_empty_ruby_on_every_segment() -> None:
    """`llm/validation.py`와 seed_loader는 두 인자로 부른다. 결과 segment는 예전과 같다."""
    segments = build_render_segments(MAKASE, MAKASE_SPANS)

    assert rendered(segments) == [
        ("この仕事、田中さんに", None),
        ("任せ", 5511),
        ("てもいい", 5512),
        ("。", None),
    ]
    assert all(segment.ruby == () for segment in segments)
    assert RenderSegment("x", None) == RenderSegment("x", None, ())


def test_r5_empty_stored_spans_give_empty_ruby_everywhere() -> None:
    """`spans: []`(계산했고 달 읽기 없음)도 모든 segment가 []다."""
    segments = build_render_segments(MAKASE, MAKASE_SPANS, ruby=[])

    assert all(segment.ruby == () for segment in segments)


def test_r1_parts_join_to_segment_text_for_every_placement() -> None:
    """R1·R2·R3을 전수로 본다: 겹치지 않는 ruby span 배치 전부(tappable `[2, 4)` 고정)."""
    text = "今日は家に"  # 5 code points
    tappable = [span(7, 2, 4)]
    cases = 0
    for offsets in _span_sets(len(text)):
        spans = ruby(*((begin, end, "よ") for begin, end in offsets))
        try:
            validate_ruby_spans(text, spans, [(2, 4)])
        except RubySpanError:
            continue  # tappable 경계를 넘는 배치는 거부 대상이다(아래 R6 테스트)
        segments = build_render_segments(text, tappable, ruby=spans)

        assert "".join(segment.text for segment in segments) == text
        emitted: list[str] = []
        for segment in segments:
            if not segment.ruby:
                continue
            assert "".join(part.text for part in segment.ruby) == segment.text  # R1
            assert any(part.reading is not None for part in segment.ruby)  # R2
            assert all(part.text for part in segment.ruby)  # R3: 빈 part 없음
            for previous, current in zip(segment.ruby, segment.ruby[1:], strict=False):
                assert not (previous.reading is None and current.reading is None)  # R3
            emitted.extend(part.text for part in segment.ruby if part.reading is not None)
        assert emitted == [text[begin:end] for begin, end in offsets], (
            "span이 사라지거나 늘지 않는다"
        )
        cases += 1
    assert cases > 10


def test_r2_a_segment_without_ruby_spans_is_empty_not_one_null_part() -> None:
    segments = build_render_segments(MAKASE, MAKASE_SPANS, ruby=ruby((2, 4, "しごと")))

    assert segments[0].ruby == (
        RubyPart("この", None),
        RubyPart("仕事", "しごと"),
        RubyPart("、田中さんに", None),
    )
    assert [segment.ruby for segment in segments[1:]] == [(), (), ()]


def test_r3_plain_text_between_spans_is_one_merged_part() -> None:
    """`、田中さんに`를 글자마다 쪼개지 않는다(정규형이 하나여야 fixture 일치가 결정적이다)."""
    segments = build_render_segments(MAKASE, [], ruby=ruby((2, 4, "しごと"), (13, 14, "も")))

    assert segments[0].ruby == (
        RubyPart("この", None),
        RubyPart("仕事", "しごと"),
        RubyPart("、田中さんに任せて", None),
        RubyPart("も", "も"),
        RubyPart("いい。", None),
    )


def test_adjacent_reading_spans_stay_separate_parts() -> None:
    segments = build_render_segments(MAKASE, [], ruby=ruby((2, 3, "し"), (3, 4, "ごと")))

    assert segments[0].ruby[1:3] == (RubyPart("仕", "し"), RubyPart("事", "ごと"))


def test_ruby_inside_each_discontinuous_segment_of_one_item() -> None:
    """`気が全然乗らない`: 불연속 item의 두 segment와 사이 일반 텍스트에 각각 붙는다."""
    spans = [span(7, 0, 2), span(7, 4, 8)]
    segments = build_render_segments(
        DISCONTINUOUS, spans, ruby=ruby((0, 1, "き"), (2, 4, "ぜんぜん"), (4, 5, "の"))
    )

    assert [(segment.text, segment.ruby) for segment in segments] == [
        ("気が", (RubyPart("気", "き"), RubyPart("が", None))),
        ("全然", (RubyPart("全然", "ぜんぜん"),)),
        ("乗らない", (RubyPart("乗", "の"), RubyPart("らない", None))),
    ]


def test_ruby_offsets_are_code_points() -> None:
    text = ASTRAL_PREFIX + "𠮟る"  # 𠮟 = U+20B9F
    segments = build_render_segments(text, [], ruby=ruby((2, 3, "しか")))

    assert segments[0].ruby == (
        RubyPart(ASTRAL_PREFIX, None),
        RubyPart("𠮟", "しか"),
        RubyPart("る", None),
    )


def test_r4_accepts_the_whole_reading_character_set() -> None:
    reading = chr(0x3041) + chr(0x3096) + "ゝゞー"
    validate_ruby_spans("仕事", ruby((0, 2, reading)), [])


def test_tappable_span_errors_are_raised_before_ruby_errors() -> None:
    """tappable span 오류는 500(`RenderSpanError`), ruby 오류는 200(`RubySpanError`)이다.

    둘이 함께 틀리면 tappable 쪽이 이겨야 호출자가 500을 ruby 무효로 삼키지 않는다.
    """
    with pytest.raises(RenderSpanError) as caught:
        build_render_segments(MAKASE, [span(7, 0, 4), span(9, 2, 6)], ruby=ruby((0, 99, "あ")))

    assert not isinstance(caught.value, RubySpanError)


# R6: 저장값이 검증을 통과하지 못하는 경우 전부. 각 입력은 다른 모든 조건을 만족한다.
INVALID_RUBY_CASES: dict[str, list[RubySpan]] = {
    "end past sentence": ruby((16, 18, "あ")),
    "negative start": ruby((-1, 2, "この")),
    "empty span": ruby((2, 2, "し")),
    "reversed span": ruby((4, 2, "し")),
    "overlap": ruby((2, 4, "しごと"), (3, 4, "ごと")),
    "descending start": ruby((5, 7, "たなか"), (2, 4, "しごと")),
    "crosses tappable start": ruby((9, 11, "にまか")),
    "crosses tappable end": ruby((11, 13, "せて")),
    "covers two tappables": ruby((10, 16, "まかせてもいい")),
    "empty reading": ruby((2, 4, "")),
    "katakana reading": ruby((5, 7, "タナカ")),
    "kanji reading": ruby((5, 7, "田中")),
    "ascii reading": ruby((5, 7, "tanaka")),
    "after U+3096": ruby((5, 7, "た" + chr(0x3097))),
    "control char": ruby((5, 7, "た\x1bな")),
    "space": ruby((5, 7, "た なか")),
}


@pytest.mark.parametrize("case", sorted(INVALID_RUBY_CASES))
def test_r6_invalid_ruby_spans_are_rejected(case: str) -> None:
    tappable = [(10, 12), (12, 16)]
    with pytest.raises(RubySpanError):
        validate_ruby_spans(MAKASE, INVALID_RUBY_CASES[case], tappable)
    with pytest.raises(RubySpanError):
        build_render_segments(MAKASE, MAKASE_SPANS, ruby=INVALID_RUBY_CASES[case])


def test_r6_a_non_tappable_boundary_is_not_a_ruby_boundary() -> None:
    spans = [span(7, 4, 8, is_tappable=False)]
    segments = build_render_segments(MAKASE, spans, ruby=ruby((2, 7, "しごとたなか")))

    assert segments[0].ruby[1] == RubyPart("仕事、田中", "しごとたなか")


def test_ruby_span_error_is_a_render_span_error() -> None:
    """ADR-021 결정 4: `RubySpanError(RenderSpanError)`."""
    assert issubclass(RubySpanError, RenderSpanError)


def test_parse_stored_ruby_reads_spans_in_order() -> None:
    stored = {
        "algorithm_version": 2,
        "spans": [[2, 4, "しごと"], [10, 11, "まか"]],
        "omitted": {"tappable_boundary": 0, "numeric": 0, "no_reading": 0},
    }

    assert parse_stored_ruby(stored) == ruby((2, 4, "しごと"), (10, 11, "まか"))
    assert parse_stored_ruby({"spans": []}) == []


# R6: 모양이 틀린 저장값. 파싱 예외가 아니라 `RubySpanError` 하나로 모인다.
MALFORMED_STORED: dict[str, object] = {
    "null": None,
    "array": [[2, 4, "しごと"]],
    "string": '{"spans": []}',
    "no spans": {"algorithm_version": 2},
    "spans object": {"spans": {"0": [2, 4, "しごと"]}},
    "spans string": {"spans": "[[2, 4]]"},
    "spans null": {"spans": None},
    "element too short": {"spans": [[2, 4]]},
    "element too long": {"spans": [[2, 4, "しごと", 1]]},
    "element object": {"spans": [{"start": 2, "end": 4, "reading": "しごと"}]},
    "element string": {"spans": ["2,4,しごと"]},
    "start string": {"spans": [["2", 4, "しごと"]]},
    "end float": {"spans": [[2, 4.0, "しごと"]]},
    "start bool": {"spans": [[True, 4, "しごと"]]},
    "start null": {"spans": [[None, 4, "しごと"]]},
    "reading null": {"spans": [[2, 4, None]]},
    "reading number": {"spans": [[2, 4, 3]]},
    "reading array": {"spans": [[2, 4, ["し", "ごと"]]]},
}


@pytest.mark.parametrize("case", sorted(MALFORMED_STORED))
def test_r6_malformed_stored_values_raise_ruby_span_error(case: str) -> None:
    with pytest.raises(RubySpanError):
        parse_stored_ruby(MALFORMED_STORED[case])
