"""후리가나 정렬과 교정 계층 (ADR-021 결정 3·3a, 12_TEST_PLAN.md `정렬과 교정`).

DB가 필요 없다. 분석기는 실제 사전을 쓴다(호스트 기본 dependency group). 사전이 잘 내지 않는
토큰(모호·불일치·연탁 재분할)은 `Token` dataclass를 직접 만들어 `compute_ruby_from_tokens`에 넣는다.

seed 전체 생략 비율은 `-k omission -s`로 출력을 볼 수 있다.
"""

from __future__ import annotations

import importlib.metadata
import sys
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.furigana import (
    ALGORITHM_VERSION,
    ANALYZER_NAME,
    ANALYZER_VERSION,
    CORRECTION_RULES,
    DICTIONARY_NAME,
    DICTIONARY_VERSION,
    CorrectionRule,
    MismatchKind,
    ReadingMismatch,
    RubyComputation,
    RubyItem,
    RubySummary,
    Token,
    compute_ruby,
    compute_ruby_from_tokens,
    escape_control,
    first_matching_rule,
    format_mismatch,
    format_summary_lines,
    load_analyzer,
    normalize_explanation_reading,
    to_hiragana,
)
from app.render import ItemSpan, is_valid_reading

from .conftest import REPO_ROOT

NOW = datetime(2026, 9, 13, 9, 0, tzinfo=UTC)
SEED_SENTENCES = REPO_ROOT / "seed" / "sentences.yaml"

# ADR-021 `실측`: 중단 판정 기준(경계 때문에 생략한 토큰 / 한자 포함 토큰)이다. 학습 정책값이 아니라
# MVP-02 진행 판정 기준이다(11_OBSERVABILITY.md).
OMISSION_STOP_RATIO = 0.05


def item(item_id: int | str, spans: list[tuple[int, int]], reading: str) -> RubyItem:
    return RubyItem(
        sentence_item_id=item_id,
        spans=tuple(ItemSpan(start, end, order) for order, (start, end) in enumerate(spans)),
        explanation_reading=reading,
    )


def token(
    surface: str,
    begin: int,
    reading_form: str,
    *,
    pos: tuple[str, ...] = ("名詞", "普通名詞"),
    split_a: tuple[Token, ...] = (),
) -> Token:
    return Token(
        surface=surface,
        begin=begin,
        end=begin + len(surface),
        reading_form=reading_form,
        part_of_speech=pos,
        split_a=split_a,
    )


def ruby(japanese: str, items: list[RubyItem] | None = None) -> RubyComputation:
    return compute_ruby(japanese, items or [], now=NOW)


def spans_of(result: RubyComputation) -> list[tuple[int, int, str]]:
    return [(span.start_codepoint, span.end_codepoint, span.reading) for span in result.spans]


def hits(result: RubyComputation) -> dict[str, int]:
    return {
        f"{rule.surface}{rule.prev}{sorted(rule.next_in)}": count
        for rule, count in zip(CORRECTION_RULES, result.rule_hits, strict=True)
        if count
    }


# --------------------------------------------------------------------------
# 문자 분류와 가나 변환
# --------------------------------------------------------------------------


def test_katakana_conversion_is_a_fixed_codepoint_shift() -> None:
    assert to_hiragana("ァヶ" + "ヴ") == "ぁゖゔ"
    assert to_hiragana("コーヒー") == "こーひー", "ー는 그대로"
    assert to_hiragana("ヷ任a") == "ヷ任a", "U+30F7 이후와 그 밖의 문자는 그대로"


def test_explanation_reading_normalization() -> None:
    assert normalize_explanation_reading("ﾏｶｾ") == "まかせ"  # NFKC
    assert normalize_explanation_reading(" まか\u3000せ\n") == "まかせ"  # 모든 공백
    assert normalize_explanation_reading("マカセ") == "まかせ"


# --------------------------------------------------------------------------
# 정렬 단위 (결정 3)
# --------------------------------------------------------------------------


def test_okurigana_is_split_off() -> None:
    """`任せ マカセ` -> `任[まか]`."""
    result = ruby("この仕事、田中さんに任せてもいい。")

    assert spans_of(result) == [(2, 4, "しごと"), (5, 7, "たなか"), (10, 11, "まか")]


def test_okurigana_inside_a_longer_word() -> None:
    assert spans_of(ruby("大人しい犬だ。")) == [(0, 2, "おとな"), (4, 5, "いぬ")]


def test_iteration_mark_joins_the_kanji_run() -> None:
    """`時々`는 run 하나 `ときどき`다."""
    assert spans_of(ruby("時々雨が降る。"))[0] == (0, 2, "ときどき")


def test_small_ke_is_a_kanji_run_of_its_own_token() -> None:
    """`東京ヶ丘`의 ヶ는 Sudachi가 별도 토큰(ガ)으로 낸다 -> `ヶ[が]`."""
    assert spans_of(ruby("東京ヶ丘に住む。"))[:3] == [
        (0, 2, "とうきょう"),
        (2, 3, "が"),
        (3, 4, "おか"),
    ]


def test_ambiguous_alignment_gives_one_trimmed_span() -> None:
    """`お赤か青だ おあかかあおだ`: 赤·青 사이 か 때문에 정렬이 둘 -> 앞뒤 비한자 run만 뗀 span 하나."""
    japanese = "お赤か青だ"
    result = compute_ruby_from_tokens(japanese, [token(japanese, 0, "オアカカアオダ")], [], now=NOW)

    assert spans_of(result) == [(1, 4, "あかかあお")]
    assert result.ambiguous_tokens == 1


def test_unaligned_token_gets_one_whole_token_span() -> None:
    japanese = "見る"
    result = compute_ruby_from_tokens(japanese, [token(japanese, 0, "ミタ")], [], now=NOW)

    assert spans_of(result) == [(0, 2, "みた")]
    assert result.unaligned_tokens == 1


@pytest.mark.parametrize(
    ("japanese", "numeric", "expected"),
    [
        # a. 수사 품사(三) + c. 수사 바로 뒤 한자 토큰(十分). 토큰화 자체가 틀린 묶음이다
        ("三十分待った。", 2, [(3, 4, "ま")]),
        # b. 표면형에 숫자 문자
        ("1人で行く。", 1, [(3, 4, "い")]),
        ("１人で行く。", 1, [(3, 4, "い")]),
        # 이미 한 토큰으로 사전에 있는 수 표현은 2a에 걸리지 않아 달린다
        ("一人で行く。", 0, [(0, 2, "ひとり"), (3, 4, "い")]),
    ],
)
def test_numeric_rule(japanese: str, numeric: int, expected: list[tuple[int, int, str]]) -> None:
    result = ruby(japanese)

    assert result.omitted_numeric == numeric
    assert spans_of(result) == expected


def test_numeric_rule_c_needs_an_adjacent_numeral() -> None:
    """c는 바로 앞 토큰이 수사이고 끊김이 없을 때만이다."""
    numeral = ("名詞", "数詞")
    adjacent = [token("三", 0, "サン", pos=numeral), token("分", 1, "フン")]
    gap = [token("三", 0, "サン", pos=numeral), token("分", 2, "フン")]

    assert compute_ruby_from_tokens("三分", adjacent, [], now=NOW).omitted_numeric == 2
    result = compute_ruby_from_tokens("三 分", gap, [], now=NOW)
    assert result.omitted_numeric == 1
    assert spans_of(result) == [(2, 3, "ふん")]


def test_token_without_a_dictionary_reading_is_omitted() -> None:
    """사전에 없는 한자(𠮟)는 reading_form이 표면형 그대로다 -> no_reading."""
    result = ruby("𠮟る")

    assert result.omitted_no_reading == 1
    assert spans_of(result) == []


def test_boundary_conflict_is_rescued_by_short_unit_split() -> None:
    """`連絡先`에서 tappable `連絡`: A 분할(連絡 + 先) 읽기 이음이 같으므로 다시 단다.

    explanation `連絡`는 히라가나가 아니라 계층 1이 성립하지 않는다 -> 분석기 경로를 본다.
    """
    result = ruby("連絡先を交換しませんか。", [item(1, [(0, 2)], "連絡")])

    assert spans_of(result) == [(0, 2, "れんらく"), (2, 3, "さき"), (4, 6, "こうかん")]
    assert result.rescued_by_split == 1
    assert result.omitted_tappable_boundary == 0


def test_rendaku_split_is_not_rescued() -> None:
    """`本棚 ホンダナ`의 A 분할이 `ホン + タナ`면 이음이 달라 구제하지 않고 토큰 전체를 생략한다."""
    japanese = "本棚"
    split = (token("本", 0, "ホン"), token("棚", 1, "タナ"))
    tokens = [token(japanese, 0, "ホンダナ", split_a=split)]

    result = compute_ruby_from_tokens(japanese, tokens, [item(1, [(0, 1)], "本")], now=NOW)

    assert spans_of(result) == []
    assert result.omitted_tappable_boundary == 1
    assert result.rescued_by_split == 0


def test_boundary_crossing_token_is_omitted_entirely() -> None:
    """경계 검사(4): 토큰 span이 tappable span을 가로지르면 그 토큰의 한자 전부를 비운다.

    실제 사전의 `本棚`은 A 분할이 없다. explanation 읽기가 `本`만 덮고 `棚`은 비어 있어야 한다.
    """
    result = ruby("本棚を買った。", [item(1, [(0, 1)], "ほん")])

    assert spans_of(result) == [(0, 1, "ほん"), (3, 4, "か")]
    assert result.omitted_tappable_boundary == 1


def test_every_span_respects_every_tappable_boundary() -> None:
    japanese = "連絡先を交換しませんか。"
    tappable = [(0, 2), (4, 7)]
    result = ruby(japanese, [item(1, [tappable[0]], "連絡"), item(2, [tappable[1]], "交換し")])

    for span in result.spans:
        for start, end in tappable:
            inside = start <= span.start_codepoint and span.end_codepoint <= end
            disjoint = span.end_codepoint <= start or end <= span.start_codepoint
            assert inside or disjoint, (span, (start, end))


# --------------------------------------------------------------------------
# 교정 계층 1: explanation.reading 우선 (결정 3a)
# --------------------------------------------------------------------------


def test_explanation_reading_wins_and_discards_covering_analyzer_spans() -> None:
    """`お腹が空い` item(설명 おなかがすい)이 お腹·空い 두 토큰을 덮는다. 空い 교정 규칙은 적중하지 않는다."""
    result = ruby("お腹が空いた。何か食べよう。", [item(1, [(0, 5)], "おなかがすい")])

    assert spans_of(result) == [(1, 2, "なか"), (3, 4, "す"), (7, 8, "なに"), (9, 10, "た")]
    assert result.corrected_explanation_tokens == 2
    assert hits(result) == {"何()['か', 'が', 'も', 'を']": 1}
    assert result.mismatches == ()


def test_explanation_alignment_uses_the_normalized_reading() -> None:
    result = ruby("仕事を任せる。", [item(1, [(3, 5)], "ﾏｶｾ")])

    assert spans_of(result) == [(0, 2, "しごと"), (3, 4, "まか")]
    assert result.corrected_explanation_tokens == 1
    assert result.mismatches == ()


def test_explanation_that_does_not_align_falls_back_to_the_analyzer() -> None:
    """기본형 읽기(`まかせる`)는 표면형 `任せ`와 정렬되지 않는다 -> 분석기 읽기 + reading_mismatch."""
    result = ruby("仕事を任せる。", [item(7, [(3, 5)], "まかせる")])

    assert spans_of(result) == [(0, 2, "しごと"), (3, 4, "まか")]
    assert result.corrected_explanation_tokens == 0
    assert result.mismatches == (
        ReadingMismatch(MismatchKind.READING_MISMATCH, 7, "任せ", "まかせる", "まかせ"),
    )


def test_explanation_with_two_alignments_is_not_used() -> None:
    """정렬이 2개 이상이어도 계층 1을 쓰지 않는다. 설명 읽기를 글자에 나눠 붙일 근거가 없다."""
    japanese = "赤か青"
    # 분석기는 토큰 셋으로 낸다. 설명 읽기 あかかあお는 item 전체에 두 가지로 정렬된다.
    tokens = [token("赤", 0, "アカ"), token("か", 1, "カ", pos=("助詞",)), token("青", 2, "アオ")]

    result = compute_ruby_from_tokens(japanese, tokens, [item(1, [(0, 3)], "あかかあお")], now=NOW)

    assert spans_of(result) == [(0, 1, "あか"), (2, 3, "あお")]
    assert result.corrected_explanation_tokens == 0


def test_explanation_hiragana_condition_blocks_layer_one() -> None:
    """부분 읽기가 히라가나 조건을 어기면(`!`) 계층 1을 쓰지 않는다."""
    result = ruby("明日は早い。", [item(1, [(0, 2)], "あした!")])

    assert spans_of(result)[0] == (0, 2, "あした")
    assert result.corrected_explanation_tokens == 0
    assert [mismatch.kind for mismatch in result.mismatches] == [MismatchKind.READING_MISMATCH]


def test_discontinuous_item_splits_runs_at_span_boundaries() -> None:
    """item `気` + `乗`(불연속): 위치가 끊기는 곳에서 run을 자른다. 자르지 않으면 한 run이 사이
    `が全然`까지 덮는 span이 된다."""
    result = ruby("気が全然乗らない。", [item(1, [(0, 1), (4, 5)], "きの")])

    assert spans_of(result) == [(0, 1, "き"), (2, 4, "ぜんぜん"), (4, 5, "の")]
    assert result.corrected_explanation_tokens == 2


def test_discontinuous_item_with_okurigana() -> None:
    result = ruby("気が全然乗らない。", [item(1, [(0, 2), (4, 8)], "きがのらない")])

    assert spans_of(result) == [(0, 1, "き"), (2, 4, "ぜんぜん"), (4, 5, "の")]


def test_rescue_skips_sub_units_covered_by_the_explanation() -> None:
    """`連絡`은 explanation이, `先`은 재분할 구제가 단다."""
    result = ruby("連絡先を交換しませんか。", [item(1, [(0, 2)], "れんらく")])

    assert spans_of(result)[:2] == [(0, 2, "れんらく"), (2, 3, "さき")]
    assert result.rescued_by_split == 1
    assert result.corrected_explanation_tokens == 0, "連絡先의 한자가 전부 덮이지는 않았다"


# --------------------------------------------------------------------------
# 교정 계층 2: CORRECTION_RULES
# --------------------------------------------------------------------------


def test_correction_rules_are_the_adr_table() -> None:
    expected = (
        CorrectionRule("私", "わたし"),
        CorrectionRule("明日", "あした"),
        CorrectionRule("今日", "きょう"),
        CorrectionRule("何", "なに", next_in=frozenset({"を", "が", "も", "か"})),
        CorrectionRule("中", "じゅう", prev=("今日",)),
        CorrectionRule("中", "じゅう", prev=("日",)),
        CorrectionRule("空い", "すい", prev=("お腹", "が")),
        CorrectionRule("空く", "すく", prev=("お腹", "が")),
    )
    assert expected == CORRECTION_RULES
    assert all(is_valid_reading(rule.reading) for rule in CORRECTION_RULES)
    assert ALGORITHM_VERSION == 2


@pytest.mark.parametrize(
    ("japanese", "expected_first"),
    [
        ("私は行く。", (0, 1, "わたし")),
        ("明日は早い。", (0, 2, "あした")),
        ("何を食べる。", (0, 1, "なに")),
        ("何か食べよう。", (0, 1, "なに")),
        ("何ですか。", (0, 1, "なん")),  # 조건 밖: なん 유지
        ("お腹が空いている。", (1, 2, "なか")),
        ("席は空いていますか。", (0, 1, "せき")),
    ],
)
def test_rule_conditions(japanese: str, expected_first: tuple[int, int, str]) -> None:
    assert spans_of(ruby(japanese))[0] == expected_first


def test_rule_with_previous_tokens_hits_only_after_them() -> None:
    assert spans_of(ruby("お腹が空いている。"))[1] == (3, 4, "す")
    assert spans_of(ruby("席は空いていますか。"))[1] == (2, 3, "あ"), "席は空いて는 あい 유지"


def test_day_suffix_rules() -> None:
    """今日中 -> きょう + じゅう, 一日中 -> 中 じゅう(一·日은 숫자 규칙), 会議中 -> ちゅう 유지."""
    today = ruby("今日中に終わる。")
    assert spans_of(today)[:2] == [(0, 2, "きょう"), (2, 3, "じゅう")]
    assert today.corrected_table_rules == 2

    all_day = ruby("一日中寝た。")
    assert spans_of(all_day)[0] == (2, 3, "じゅう")
    assert all_day.omitted_numeric == 2

    assert spans_of(ruby("会議中です。"))[1] == (2, 3, "ちゅう")


def test_previous_token_chain_must_be_contiguous() -> None:
    tokens = [
        token("お腹", 0, "オナカ"),
        token("が", 2, "ガ", pos=("助詞",)),
        token("空い", 4, "アイ", pos=("動詞",)),
    ]
    japanese = "お腹が 空い"

    result = compute_ruby_from_tokens(japanese, tokens, [], now=NOW)

    assert spans_of(result)[1] == (4, 5, "あ")
    assert result.corrected_table_rules == 0


def test_next_token_must_be_adjacent() -> None:
    tokens = [token("何", 0, "ナン", pos=("代名詞",)), token("を", 2, "ヲ", pos=("助詞",))]

    result = compute_ruby_from_tokens("何 を", tokens, [], now=NOW)

    assert spans_of(result) == [(0, 1, "なん")]


def test_only_the_first_matching_rule_is_used() -> None:
    tokens = [token("日", 0, "ニチ"), token("中", 1, "チュウ")]
    rules = (
        CorrectionRule("中", "なか", prev=("日",)),
        CorrectionRule("中", "じゅう"),
    )

    assert first_matching_rule(tokens, 1, rules) == 0
    assert first_matching_rule(tokens, 0, rules) is None


def test_each_token_counts_one_hit() -> None:
    result = ruby("今日は何か食べよう。")

    assert result.corrected_table_rules == 2
    assert sum(result.rule_hits) == 2


def test_rescue_compares_the_corrected_reading() -> None:
    """재분할은 교정된 읽기와 A 분할 읽기 이음을 비교한다."""
    tappable = [item(1, [(0, 1)], "あ")]
    # 明日 -> あした. A 분할 이음 あす는 교정 읽기와 다르다 -> 구제하지 않는다.
    not_rescued = compute_ruby_from_tokens(
        "明日",
        [token("明日", 0, "アス", split_a=(token("明", 0, "ア"), token("日", 1, "ス")))],
        tappable,
        now=NOW,
    )
    # 今日 -> きょう. A 분할 이음 きょう가 교정 읽기와 같다 -> 구제한다.
    rescued = compute_ruby_from_tokens(
        "今日",
        [token("今日", 0, "コンニチ", split_a=(token("今", 0, "キョ"), token("日", 1, "ウ")))],
        [item(1, [(0, 1)], "!")],
        now=NOW,
    )

    assert not_rescued.omitted_tappable_boundary == 1
    assert spans_of(not_rescued) == [(0, 1, "あ")]
    assert rescued.rescued_by_split == 1
    assert spans_of(rescued) == [(0, 1, "きょ"), (1, 2, "う")]


# --------------------------------------------------------------------------
# explanation.reading 불일치 보고 두 종류
# --------------------------------------------------------------------------


def test_explanation_override_is_reported() -> None:
    """계층 1이 성립했고 교정 후 분석기 읽기(あした)와 다르다 -> 저장은 설명 읽기, 보고는 override."""
    result = ruby("明日は早い。", [item(3, [(0, 2)], "あす")])

    assert spans_of(result)[0] == (0, 2, "あす")
    assert result.mismatches == (
        ReadingMismatch(MismatchKind.EXPLANATION_OVERRIDE, 3, "明日", "あす", "あした"),
    )


def test_equal_readings_after_normalization_are_not_reported() -> None:
    result = ruby("明日は早い。", [item(3, [(0, 2)], "ア シ タ")])

    assert result.mismatches == ()


def test_items_without_kanji_are_not_compared() -> None:
    result = ruby("この仕事、田中さんに任せてもいい。", [item(2, [(12, 16)], "ちがう")])

    assert result.mismatches == ()


def test_reading_mismatch_reports_the_raw_explanation() -> None:
    result = ruby("連絡先を交換しませんか。", [item("x", [(0, 2)], "連絡")])

    assert result.mismatches == (
        ReadingMismatch(MismatchKind.READING_MISMATCH, "x", "連絡", "連絡", "れんらく"),
    )


# --------------------------------------------------------------------------
# 결정성과 ruby_json 모양
# --------------------------------------------------------------------------


def test_same_input_gives_the_same_result() -> None:
    japanese = "お腹が空いた。何か食べよう。"
    items = [item(1, [(0, 5)], "おなかがすい")]

    assert compute_ruby(japanese, items, now=NOW) == compute_ruby(japanese, items, now=NOW)


def test_computed_at_is_the_injected_now_in_utc() -> None:
    kst = timezone(timedelta(hours=9))
    result = compute_ruby("仕事", [], now=datetime(2026, 9, 13, 18, 0, tzinfo=kst))

    assert result.ruby_json["computed_at"] == "2026-09-13T09:00:00Z"


def test_naive_now_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        compute_ruby("仕事", [], now=datetime(2026, 9, 13, 9, 0))  # noqa: DTZ001


def test_ruby_json_shape() -> None:
    result = ruby("この仕事、田中さんに任せてもいい。", [item(1, [(10, 12)], "まかせ")])

    assert result.ruby_json == {
        "algorithm_version": 2,
        "analyzer": {"name": "sudachipy", "version": "0.6.11"},
        "dictionary": {"name": "sudachidict_core", "version": "20260723"},
        "split_mode": "C",
        "computed_at": "2026-09-13T09:00:00Z",
        "spans": [[2, 4, "しごと"], [5, 7, "たなか"], [10, 11, "まか"]],
        "omitted": {"tappable_boundary": 0, "numeric": 0, "no_reading": 0},
        "corrected": {"explanation_tokens": 1, "table_rules": 0},
    }


def test_sentence_without_kanji_stores_empty_spans_with_every_key() -> None:
    result = ruby("ちょっと")

    assert result.ruby_json["spans"] == []
    assert set(result.ruby_json["omitted"]) == {"tappable_boundary", "numeric", "no_reading"}
    assert set(result.ruby_json["corrected"]) == {"explanation_tokens", "table_rules"}


def test_recorded_versions_match_the_installed_packages() -> None:
    """provenance 상수가 실제로 설치된(= uv.lock) 패키지 메타데이터와 같다.

    `app/`은 `importlib`을 import하지 않는다(G13). 그래서 버전을 상수로 기록하고 여기서 대조한다.
    사전을 올리면서 상수를 빠뜨리면 이 테스트가 빨개진다.
    """
    assert (ANALYZER_NAME, DICTIONARY_NAME) == ("sudachipy", "sudachidict_core")
    assert importlib.metadata.version(ANALYZER_NAME) == ANALYZER_VERSION
    assert importlib.metadata.version(DICTIONARY_NAME) == DICTIONARY_VERSION


def test_analyzer_is_loaded_once_per_process() -> None:
    assert load_analyzer() is load_analyzer()


def test_real_analyzer_offsets_are_code_points() -> None:
    tokens = load_analyzer().tokenize("🍣𠮟る。仕事")

    assert [(item.surface, item.begin, item.end) for item in tokens][-1] == ("仕事", 4, 6)
    assert spans_of(ruby("🍣𠮟る。仕事")) == [(4, 6, "しごと")]


# --------------------------------------------------------------------------
# CLI 출력 (11_OBSERVABILITY.md)
# --------------------------------------------------------------------------


def test_summary_rule_and_mismatch_lines() -> None:
    summary = RubySummary()
    summary.add("sn_1", ruby("明日は早い。", [item(3, [(0, 2)], "あす")]))
    summary.add("sn_2", ruby("仕事を任せる。", [item(7, [(3, 5)], "まかせる")]))
    summary.add_failure()

    lines = format_summary_lines(summary)

    assert lines[0] == (
        "ruby: algorithm_version=2 sentences=3 computed=2 failed=1 omitted_tappable_boundary=0 "
        "omitted_numeric=0 omitted_no_reading=0 corrected_explanation_tokens=1 "
        "corrected_table_rules=0 reading_mismatches=1 explanation_overrides=1 kanji_tokens=4"
    )
    assert lines[1 : 1 + len(CORRECTION_RULES)] == [
        "rule 私->わたし hits=0",
        "rule 明日->あした hits=0",
        "rule 今日->きょう hits=0",
        "rule 何->なに next=か|が|も|を hits=0",
        "rule 中->じゅう prev=今日 hits=0",
        "rule 中->じゅう prev=日 hits=0",
        "rule 空い->すい prev=お腹,が hits=0",
        "rule 空く->すく prev=お腹,が hits=0",
    ]
    assert lines[1 + len(CORRECTION_RULES) :] == [
        "mismatch kind=explanation_override sentence=sn_1 item=3 surface=明日 "
        "explanation=あす analyzer=あした",
        "mismatch kind=reading_mismatch sentence=sn_2 item=7 surface=任せ "
        "explanation=まかせる analyzer=まかせ",
    ]


@pytest.mark.parametrize(
    ("raw", "escaped"),
    [
        ("\x1b[31mあ", "\\u001B[31mあ"),
        ("あ\nmismatch kind=x", "あ\\u000Amismatch kind=x"),
        ("\r\t\x00", "\\u000D\\u0009\\u0000"),
        ("\x7f\x80\x9f", "\\u007F\\u0080\\u009F"),
        ("\xa0まかせ ~", "\xa0まかせ ~"),  # C1 밖과 일반 문자는 그대로
    ],
)
def test_control_characters_are_escaped(raw: str, escaped: str) -> None:
    assert escape_control(raw) == escaped


def test_mismatch_line_escapes_llm_strings() -> None:
    mismatch = ReadingMismatch(MismatchKind.READING_MISMATCH, 9, "任\x1bせ", "まか\nせ", "まかせ")

    line = format_mismatch("12", mismatch)

    assert "\n" not in line and "\x1b" not in line
    assert "surface=任\\u001Bせ explanation=まか\\u000Aせ" in line


# --------------------------------------------------------------------------
# seed 전체 생략 비율 (ADR-021 `실측`, 11_OBSERVABILITY.md)
# --------------------------------------------------------------------------


def _seed_items(entry: dict[str, Any]) -> list[RubyItem]:
    return [
        RubyItem(
            sentence_item_id=raw["item_seed_id"],
            spans=tuple(
                ItemSpan(span["start_codepoint"], span["end_codepoint"], span["span_order"])
                for span in raw["spans"]
            ),
            explanation_reading=raw["explanation"]["reading"],
        )
        for raw in entry["items"]
        if raw["is_tappable"]
    ]


def test_seed_boundary_omission_ratio() -> None:
    """경계 때문에 생략한 토큰 / 한자를 포함한 토큰을 seed 전체로 계산해 출력한다(5% 이하).

    출력은 `-s`에서 보인다: `uv run pytest backend/tests/test_ruby_alignment.py -k omission -s`.
    """
    entries: list[dict[str, Any]] = yaml.safe_load(Path(SEED_SENTENCES).read_text("utf-8"))
    summary = RubySummary()
    spans = rescued = ambiguous = unaligned = uncomparable = 0
    for entry in entries:
        result = compute_ruby(entry["japanese"], _seed_items(entry), now=NOW)
        summary.add(entry["seed_id"], result)
        spans += len(result.spans)
        rescued += result.rescued_by_split
        ambiguous += result.ambiguous_tokens
        unaligned += result.unaligned_tokens
        uncomparable += result.uncomparable_items

    ratio = summary.omitted_tappable_boundary / summary.kanji_tokens
    report = [
        "",
        *format_summary_lines(summary),
        f"seed omission: boundary={summary.omitted_tappable_boundary} / "
        f"kanji_tokens={summary.kanji_tokens} = {ratio:.2%} (stop above "
        f"{OMISSION_STOP_RATIO:.0%}) numeric={summary.omitted_numeric} "
        f"({summary.omitted_numeric / summary.kanji_tokens:.2%}) spans={spans} "
        f"rescued_by_split={rescued} ambiguous={ambiguous} unaligned={unaligned} "
        f"uncomparable_items={uncomparable}",
    ]
    sys.stdout.write("\n".join(report) + "\n")

    assert summary.failed == 0
    assert summary.kanji_tokens > 0
    assert ratio <= OMISSION_STOP_RATIO
