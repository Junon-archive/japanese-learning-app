"""후리가나(ruby) 계산: 사전 어댑터 + 한자 run 정렬 + 교정 계층 (ADR-021, L1).

규칙의 canonical은 ADR-021의 `결정 3`(정렬), `결정 3a`(교정 계층)이고 저장 모양은
`04_DB_SPEC.md`의 `ruby_json`이다. 이 모듈은 그 규칙을 **그대로** 옮긴다.

계층(ADR-021 결정 4, G14):
-   import하는 것은 L0 `app.render`와 `sudachipy`뿐이다. DB·설정·시계를 모른다.
    `computed_at`은 호출자가 주입한 `now`다(ADR-007).
-   이 모듈을 import할 수 있는 app 모듈은 `services/seed_loader.py`와 `jobs/persistence.py`뿐이다.
    API 프로세스에는 들어오지 않는다(API 이미지에는 분석기가 없다).

정렬 함수(`compute_ruby_from_tokens`)는 토큰 dataclass를 입력으로 받는 결정적 함수다. 단위
테스트는 사전이 잘 내지 않는 토큰(모호·불일치)을 직접 만들어 넣는다. `compute_ruby`는 그 앞에
사전 토큰화를 붙인 것뿐이다.
"""

from __future__ import annotations

import itertools
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from functools import cache
from typing import Any

from sudachipy import Dictionary, SplitMode  # type: ignore[import-untyped]

from app.render import ItemSpan, RubySpan, is_valid_reading, validate_ruby_spans

# 정렬 규칙(결정 3)과 교정 표(결정 3a)를 합친 규칙 버전. 둘 중 하나라도 바뀌면 1씩 올린다.
ALGORITHM_VERSION = 2

# provenance. 값은 설치된 패키지 메타데이터와 같아야 한다 --- `pyproject.toml`의 `==` 고정과
# 함께 바꾸고, test_ruby_alignment.py가 설치된 패키지 버전과 대조한다.
ANALYZER_NAME = "sudachipy"
ANALYZER_VERSION = "0.6.11"
DICTIONARY_NAME = "sudachidict_core"
DICTIONARY_VERSION = "20260723"
SPLIT_MODE = "C"

# --------------------------------------------------------------------------
# 문자 분류 (결정 3). 코드포인트 목록으로 고정한다 --- unicodedata의 범주 판정은 Python minor마다
# Unicode 버전이 달라 같은 입력의 판정이 갈릴 수 있다.
# --------------------------------------------------------------------------

_KANJI_RANGES: tuple[tuple[int, int], ...] = (
    (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF),
    (0xF900, 0xFAFF),
    (0x20000, 0x3FFFF),
)
# U+3005 々, U+3006 〆, U+3007(漢数字 영), U+30F5 ヵ, U+30F6 ヶ 는 한자 run에 붙는다.
_KANJI_EXTRA_CODEPOINTS = frozenset({0x3005, 0x3006, 0x3007, 0x30F5, 0x30F6})
# 숫자: ASCII 0-9, 전각 U+FF10..U+FF19.
_DIGITS = frozenset([*"0123456789", *(chr(codepoint) for codepoint in range(0xFF10, 0xFF1A))])
_NUMERAL_POS = "数詞"


def is_kanji(char: str) -> bool:
    codepoint = ord(char)
    if codepoint in _KANJI_EXTRA_CODEPOINTS:
        return True
    return any(low <= codepoint <= high for low, high in _KANJI_RANGES)


def has_kanji(text: str) -> bool:
    return any(is_kanji(char) for char in text)


def to_hiragana(text: str) -> str:
    """ァ..ヶ(U+30A1..U+30F6)를 -0x60해 ぁ..ゖ로 바꾼다. ー와 그 밖의 문자는 그대로다."""
    return "".join(
        chr(ord(char) - 0x60) if 0x30A1 <= ord(char) <= 0x30F6 else char for char in text
    )


def normalize_explanation_reading(reading: str) -> str:
    """설명 읽기 정규화: NFKC -> 모든 공백 제거 -> 가나 변환 (결정 3a)."""
    return to_hiragana("".join(unicodedata.normalize("NFKC", reading).split()))


# --------------------------------------------------------------------------
# 입력 타입
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Token:
    """SplitMode.C 형태소 하나. `begin`/`end`는 문장 전체의 code point index다.

    `split_a`는 SplitMode.A 재분할 결과다. 더 쪼개지지 않으면 비어 있다.
    """

    surface: str
    begin: int
    end: int
    reading_form: str
    part_of_speech: tuple[str, ...]
    split_a: tuple[Token, ...] = ()


@dataclass(frozen=True)
class RubyItem:
    """`is_tappable = true`인 sentence_item 하나. **tappable item만** 넘긴다.

    `sentence_item_id`는 호출자의 식별자다(seed는 문장 안 식별자, worker는 로컬 식별자,
    backfill은 DB id). 계산은 이 값을 보지 않고 불일치 보고에 그대로 싣는다.
    """

    sentence_item_id: int | str
    spans: tuple[ItemSpan, ...]
    explanation_reading: str


@dataclass(frozen=True)
class CorrectionRule:
    """`surface`: SplitMode.C 토큰 표면형과 글자 그대로 같다.
    `reading`: 그 토큰 전체의 읽기(히라가나). 결정 3의 정렬에 들어간다.
    `prev`: 바로 앞 토큰들의 표면형(끝이 바로 앞). 끊김 없이 이어져야 한다.
    `next_in`: 비어 있지 않으면 바로 다음 토큰 표면형이 이 안에 있어야 한다.
    """

    surface: str
    reading: str
    prev: tuple[str, ...] = ()
    next_in: frozenset[str] = frozenset()


# 결정 3a 계층 2. ADR-021의 표 그대로다. 바꾸는 절차(algorithm_version 올림, seed 규칙별 적중·변경
# 목록, demo fixture 재생성, 저장된 행 재계산 수단 설계)는 ADR-021 `규칙을 바꾸는 절차`를 따른다.
CORRECTION_RULES: tuple[CorrectionRule, ...] = (
    CorrectionRule("私", "わたし"),
    CorrectionRule("明日", "あした"),
    CorrectionRule("今日", "きょう"),
    CorrectionRule("何", "なに", next_in=frozenset({"を", "が", "も", "か"})),
    CorrectionRule("中", "じゅう", prev=("今日",)),
    CorrectionRule("中", "じゅう", prev=("日",)),
    CorrectionRule("空い", "すい", prev=("お腹", "が")),
    CorrectionRule("空く", "すく", prev=("お腹", "が")),
)


# --------------------------------------------------------------------------
# 출력 타입
# --------------------------------------------------------------------------


class MismatchKind(StrEnum):
    READING_MISMATCH = "reading_mismatch"  # 계층 1 정렬 불성립 + 두 읽기가 다르다
    EXPLANATION_OVERRIDE = "explanation_override"  # 계층 1 정렬 성립 + 두 읽기가 다르다


@dataclass(frozen=True)
class ReadingMismatch:
    kind: MismatchKind
    sentence_item_id: int | str
    surface: str  # item span을 span_order 순으로 이은 표면형
    explanation: str  # 설명 읽기 원문(정규화 전)
    analyzer: str  # 계층 1을 뺀 계산(교정 표 포함)의 읽기


@dataclass(frozen=True)
class RubyComputation:
    """문장 하나의 계산 결과. `ruby_json`이 저장값이고 나머지는 관측용이다."""

    ruby_json: dict[str, Any]
    spans: tuple[RubySpan, ...]
    kanji_tokens: int  # 생략 비율의 분모: 한자를 포함한 SplitMode.C 토큰 수
    omitted_tappable_boundary: int
    omitted_numeric: int
    omitted_no_reading: int
    corrected_explanation_tokens: int
    corrected_table_rules: int
    rule_hits: tuple[int, ...]  # CORRECTION_RULES 순서
    rescued_by_split: int  # 경계 충돌을 SplitMode.A 재분할로 구제한 토큰 수
    ambiguous_tokens: int  # 정렬이 2개 이상 -> 축약 span
    unaligned_tokens: int  # 정렬이 0개 -> 토큰 전체 span
    uncomparable_items: int  # 불일치 판정에서 ruby 없는 한자가 있어 비교하지 않은 item 수
    mismatches: tuple[ReadingMismatch, ...]


# --------------------------------------------------------------------------
# 정렬 (결정 3의 3)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _Run:
    kanji: bool
    start: int  # 문장 전체 code point index
    end: int
    text: str


def _surface_runs(text: str, begin: int) -> list[_Run]:
    """표면형을 한자 run / 비한자 run으로 자른다."""
    runs: list[_Run] = []
    for kanji, group in itertools.groupby(enumerate(text), key=lambda pair: is_kanji(pair[1])):
        chars = list(group)
        start = begin + chars[0][0]
        runs.append(_Run(kanji, start, start + len(chars), "".join(char for _, char in chars)))
    return runs


def _alignment(runs: Sequence[_Run], reading: str) -> tuple[int, tuple[str, ...]]:
    """reading에 대한 run 정렬 수(2에서 멈춘다)와, 정확히 1개일 때 run마다의 부분 읽기.

    비한자 run은 가나 변환한 글자가 reading의 그 자리와 글자 그대로 같아야 하고, 한자 run은
    reading의 비어 있지 않은 연속 부분 문자열 하나를 가진다. (run 번호, reading 위치)마다 남은
    정렬 수를 memo로 세므로 run이 많아도 지수 탐색이 되지 않는다.
    """
    memo: dict[tuple[int, int], int] = {}

    def count(index: int, offset: int) -> int:
        if index == len(runs):
            return 1 if offset == len(reading) else 0
        key = (index, offset)
        if key in memo:
            return memo[key]
        run = runs[index]
        total = 0
        if not run.kanji:
            kana = to_hiragana(run.text)
            if reading.startswith(kana, offset):
                total = count(index + 1, offset + len(kana))
        else:
            for stop in range(offset + 1, len(reading) + 1):
                total += count(index + 1, stop)
                if total >= 2:
                    break
        memo[key] = min(total, 2)
        return memo[key]

    found = count(0, 0)
    if found != 1:
        return found, ()

    parts: list[str] = []
    offset = 0
    for index, run in enumerate(runs):
        if not run.kanji:
            kana = to_hiragana(run.text)
            parts.append(kana)
            offset += len(kana)
            continue
        stop = next(
            stop for stop in range(offset + 1, len(reading) + 1) if count(index + 1, stop) == 1
        )
        parts.append(reading[offset:stop])
        offset = stop
    return 1, tuple(parts)


class _Shape(StrEnum):
    UNIQUE = "unique"
    AMBIGUOUS = "ambiguous"
    UNALIGNED = "unaligned"


def _align_token(token: Token, reading: str) -> tuple[list[RubySpan], _Shape]:
    runs = _surface_runs(token.surface, token.begin)
    found, parts = _alignment(runs, reading)
    if found == 1:
        spans = [
            RubySpan(run.start, run.end, part)
            for run, part in zip(runs, parts, strict=True)
            if run.kanji
        ]
        return spans, _Shape.UNIQUE
    if found >= 2:
        # 정렬이 둘 이상이면 앞뒤 비한자 run은 정의상 reading과 맞았으므로 떼는 것이 항상 가능하다.
        kanji_runs = [run for run in runs if run.kanji]
        lead = len(runs[0].text) if not runs[0].kanji else 0
        trail = len(runs[-1].text) if not runs[-1].kanji else 0
        trimmed = reading[lead : len(reading) - trail]
        return [RubySpan(kanji_runs[0].start, kanji_runs[-1].end, trimmed)], _Shape.AMBIGUOUS
    return [RubySpan(token.begin, token.end, reading)], _Shape.UNALIGNED


# --------------------------------------------------------------------------
# 교정 계층 1: tappable item span은 explanation.reading 우선 (결정 3a)
# --------------------------------------------------------------------------


def _item_surface(japanese: str, item: RubyItem) -> str:
    return "".join(
        japanese[span.start_codepoint : span.end_codepoint]
        for span in sorted(item.spans, key=lambda span: span.span_order)
    )


def _item_runs(japanese: str, item: RubyItem) -> list[_Run]:
    """item span을 span_order 순으로 이어 한자/비한자 run으로 자른다. span 경계에서도 자른다.

    ADR-021의 "위치가 이어지지 않는 곳(불연속 span 경계)에서도 자른다". span 단위로 자르면
    run이 항상 span 하나 안에 있어 explanation span이 tappable 경계 검사를 항상 통과한다.
    """
    runs: list[_Run] = []
    for span in sorted(item.spans, key=lambda span: span.span_order):
        text = japanese[span.start_codepoint : span.end_codepoint]
        runs.extend(_surface_runs(text, span.start_codepoint))
    return runs


def _explanation_spans(japanese: str, item: RubyItem) -> list[RubySpan] | None:
    """정렬이 정확히 1개이고 부분 읽기가 전부 히라가나 조건을 만족하면 한자 run마다 span.

    그 밖(0개, 2개 이상, 조건 위반)은 None --- 이 item은 계층 1을 쓰지 않는다.
    """
    runs = _item_runs(japanese, item)
    reading = normalize_explanation_reading(item.explanation_reading)
    found, parts = _alignment(runs, reading)
    if found != 1:
        return None
    spans = [
        RubySpan(run.start, run.end, part)
        for run, part in zip(runs, parts, strict=True)
        if run.kanji
    ]
    if not all(is_valid_reading(span.reading) for span in spans):
        return None
    return spans


# --------------------------------------------------------------------------
# 토큰 처리 (결정 3의 0~6, 결정 3a 계층 2)
# --------------------------------------------------------------------------


@dataclass
class _Pass:
    spans: list[RubySpan] = field(default_factory=list)
    kanji_tokens: int = 0
    omitted_tappable_boundary: int = 0
    omitted_numeric: int = 0
    omitted_no_reading: int = 0
    corrected_explanation_tokens: int = 0
    rule_hits: list[int] = field(default_factory=lambda: [0] * len(CORRECTION_RULES))
    rescued_by_split: int = 0
    ambiguous_tokens: int = 0
    unaligned_tokens: int = 0


def _rule_matches(rule: CorrectionRule, tokens: Sequence[Token], index: int) -> bool:
    token = tokens[index]
    if token.surface != rule.surface:
        return False
    if rule.prev:
        first = index - len(rule.prev)
        if first < 0:
            return False
        chain = tokens[first : index + 1]
        if tuple(previous.surface for previous in chain[:-1]) != rule.prev:
            return False
        if any(left.end != right.begin for left, right in itertools.pairwise(chain)):
            return False
    if rule.next_in:
        if index + 1 >= len(tokens):
            return False
        following = tokens[index + 1]
        if following.begin != token.end or following.surface not in rule.next_in:
            return False
    return True


def first_matching_rule(
    tokens: Sequence[Token],
    index: int,
    rules: Sequence[CorrectionRule] = CORRECTION_RULES,
) -> int | None:
    """표 순서대로 보고 처음 적중한 규칙의 번호. 없으면 None."""
    for rule_index, rule in enumerate(rules):
        if _rule_matches(rule, tokens, index):
            return rule_index
    return None


def _is_numeral(token: Token) -> bool:
    return len(token.part_of_speech) > 1 and token.part_of_speech[1] == _NUMERAL_POS


def _is_numeric(tokens: Sequence[Token], index: int) -> bool:
    """결정 3의 2. 호출 시점에 이 토큰에는 한자가 있다."""
    token = tokens[index]
    if _is_numeral(token):
        return True
    if any(char in _DIGITS for char in token.surface):
        return True
    if index > 0:
        previous = tokens[index - 1]
        return previous.end == token.begin and _is_numeral(previous)
    return False


def _within_boundaries(spans: Sequence[RubySpan], tappable: Sequence[tuple[int, int]]) -> bool:
    """결정 3의 4: 모든 span이 모든 tappable span T에 대해 (span ⊆ T) 또는 (span ∩ T = ∅)."""
    for span in spans:
        for start, end in tappable:
            inside = start <= span.start_codepoint and span.end_codepoint <= end
            disjoint = span.end_codepoint <= start or end <= span.start_codepoint
            if not (inside or disjoint):
                return False
    return True


def _fully_covered(token: Token, covered: frozenset[int]) -> bool:
    """(v2) 토큰의 한자 문자가 전부 explanation span에 덮였다."""
    return bool(covered) and all(
        token.begin + offset in covered
        for offset, char in enumerate(token.surface)
        if is_kanji(char)
    )


def _rescue(
    token: Token,
    reading: str,
    tappable: Sequence[tuple[int, int]],
    covered: frozenset[int],
) -> list[RubySpan] | None:
    """결정 3의 5. 읽기 이음이 (교정된) reading과 글자 그대로 같을 때만 A 분할로 다시 단다."""
    subs = token.split_a
    if len(subs) <= 1:
        return None
    if "".join(to_hiragana(sub.reading_form) for sub in subs) != reading:
        return None
    spans: list[RubySpan] = []
    for sub in subs:
        if not has_kanji(sub.surface) or _fully_covered(sub, covered):
            continue
        sub_spans, _ = _align_token(sub, to_hiragana(sub.reading_form))
        spans.extend(sub_spans)
    return spans if _within_boundaries(spans, tappable) else None


def _overlaps_any(span: RubySpan, others: Sequence[RubySpan]) -> bool:
    return any(
        span.start_codepoint < other.end_codepoint and other.start_codepoint < span.end_codepoint
        for other in others
    )


def _annotate_tokens(
    tokens: Sequence[Token],
    tappable: Sequence[tuple[int, int]],
    explanation_spans: Sequence[RubySpan],
) -> _Pass:
    covered = frozenset(
        position
        for span in explanation_spans
        for position in range(span.start_codepoint, span.end_codepoint)
    )
    result = _Pass()
    for index, token in enumerate(tokens):
        # 0
        if not has_kanji(token.surface):
            continue
        result.kanji_tokens += 1
        if _fully_covered(token, covered):
            result.corrected_explanation_tokens += 1
            continue
        # 1 (+ 계층 2)
        reading = to_hiragana(token.reading_form)
        rule_index = first_matching_rule(tokens, index)
        if rule_index is not None:
            result.rule_hits[rule_index] += 1
            reading = CORRECTION_RULES[rule_index].reading
        if not is_valid_reading(reading):
            result.omitted_no_reading += 1
            continue
        # 2
        if _is_numeric(tokens, index):
            result.omitted_numeric += 1
            continue
        # 3
        spans, shape = _align_token(token, reading)
        if shape is _Shape.AMBIGUOUS:
            result.ambiguous_tokens += 1
        elif shape is _Shape.UNALIGNED:
            result.unaligned_tokens += 1
        # 4, 5
        if not _within_boundaries(spans, tappable):
            rescued = _rescue(token, reading, tappable, covered)
            if rescued is None:
                result.omitted_tappable_boundary += 1
                continue
            result.rescued_by_split += 1
            spans = rescued
        # 6
        result.spans.extend(span for span in spans if not _overlaps_any(span, explanation_spans))
    return result


# --------------------------------------------------------------------------
# explanation.reading 불일치 판정 (결정 3a)
# --------------------------------------------------------------------------


def _analyzer_reading(
    japanese: str, item: RubyItem, analyzer_spans: Sequence[RubySpan]
) -> str | None:
    """계층 1을 뺀 계산의 ruby로 item span을 훑은 읽기. ruby 없는 한자가 있으면 None(비교 불가)."""
    by_start = {span.start_codepoint: span for span in analyzer_spans}
    parts: list[str] = []
    for item_span in sorted(item.spans, key=lambda span: span.span_order):
        position = item_span.start_codepoint
        while position < item_span.end_codepoint:
            ruby = by_start.get(position)
            if ruby is not None and ruby.end_codepoint <= item_span.end_codepoint:
                parts.append(ruby.reading)
                position = ruby.end_codepoint
                continue
            char = japanese[position]
            if is_kanji(char):
                return None
            parts.append(to_hiragana(char))
            position += 1
    return "".join(parts)


# --------------------------------------------------------------------------
# 계산 진입점
# --------------------------------------------------------------------------


def compute_ruby_from_tokens(
    japanese: str,
    tokens: Sequence[Token],
    items: Sequence[RubyItem],
    *,
    now: datetime,
) -> RubyComputation:
    """토큰 목록으로 ruby를 계산한다. 결과 span은 저장 전에 `validate_ruby_spans`를 통과한다.

    검증을 통과하지 못하면 `RubySpanError`를 그대로 던진다(호출자가 ruby_json = NULL로 둔다).
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware (UTC)")

    tappable = [(span.start_codepoint, span.end_codepoint) for item in items for span in item.spans]
    kanji_items = [item for item in items if has_kanji(_item_surface(japanese, item))]
    explained = [(item, _explanation_spans(japanese, item)) for item in kanji_items]
    explanation_spans = [span for _, spans in explained if spans for span in spans]

    final = _annotate_tokens(tokens, tappable, explanation_spans)
    spans = tuple(sorted([*explanation_spans, *final.spans], key=lambda span: span.start_codepoint))
    validate_ruby_spans(japanese, spans, tappable)

    analyzer_spans = _annotate_tokens(tokens, tappable, []).spans if kanji_items else []
    mismatches: list[ReadingMismatch] = []
    uncomparable = 0
    for item, item_explanation_spans in explained:
        analyzer = _analyzer_reading(japanese, item, analyzer_spans)
        if analyzer is None:
            uncomparable += 1
            continue
        if normalize_explanation_reading(item.explanation_reading) == analyzer:
            continue
        mismatches.append(
            ReadingMismatch(
                kind=(
                    MismatchKind.READING_MISMATCH
                    if item_explanation_spans is None
                    else MismatchKind.EXPLANATION_OVERRIDE
                ),
                sentence_item_id=item.sentence_item_id,
                surface=_item_surface(japanese, item),
                explanation=item.explanation_reading,
                analyzer=analyzer,
            )
        )

    table_rules = sum(final.rule_hits)
    ruby_json: dict[str, Any] = {
        "algorithm_version": ALGORITHM_VERSION,
        "analyzer": {"name": ANALYZER_NAME, "version": ANALYZER_VERSION},
        "dictionary": {"name": DICTIONARY_NAME, "version": DICTIONARY_VERSION},
        "split_mode": SPLIT_MODE,
        "computed_at": now.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "spans": [[span.start_codepoint, span.end_codepoint, span.reading] for span in spans],
        "omitted": {
            "tappable_boundary": final.omitted_tappable_boundary,
            "numeric": final.omitted_numeric,
            "no_reading": final.omitted_no_reading,
        },
        "corrected": {
            "explanation_tokens": final.corrected_explanation_tokens,
            "table_rules": table_rules,
        },
    }
    return RubyComputation(
        ruby_json=ruby_json,
        spans=spans,
        kanji_tokens=final.kanji_tokens,
        omitted_tappable_boundary=final.omitted_tappable_boundary,
        omitted_numeric=final.omitted_numeric,
        omitted_no_reading=final.omitted_no_reading,
        corrected_explanation_tokens=final.corrected_explanation_tokens,
        corrected_table_rules=table_rules,
        rule_hits=tuple(final.rule_hits),
        rescued_by_split=final.rescued_by_split,
        ambiguous_tokens=final.ambiguous_tokens,
        unaligned_tokens=final.unaligned_tokens,
        uncomparable_items=uncomparable,
        mismatches=tuple(mismatches),
    )


# --------------------------------------------------------------------------
# 사전 어댑터
# --------------------------------------------------------------------------


class Analyzer:
    """SudachiPy SplitMode.C tokenizer. mypy는 sudachipy 타입을 보지 않으므로 값을 명시해 받는다."""

    def __init__(self, tokenizer: Any) -> None:  # noqa: ANN401 (sudachipy에 타입 정보가 없다)
        self._tokenizer = tokenizer

    def tokenize(self, japanese: str) -> list[Token]:
        return [
            self._token(morpheme, split=True) for morpheme in self._tokenizer.tokenize(japanese)
        ]

    def _token(self, morpheme: Any, *, split: bool) -> Token:  # noqa: ANN401
        return Token(
            surface=str(morpheme.surface()),
            begin=int(morpheme.begin()),
            end=int(morpheme.end()),
            reading_form=str(morpheme.reading_form()),
            part_of_speech=tuple(str(part) for part in morpheme.part_of_speech()),
            split_a=(
                tuple(self._token(sub, split=False) for sub in morpheme.split(SplitMode.A))
                if split
                else ()
            ),
        )


@cache
def load_analyzer() -> Analyzer:
    """사전을 한 번 적재한다(프로세스 내 캐시). 실패하면 예외를 그대로 던진다(fail-closed).

    worker·seed·backfill 진입점이 시작에서 부른다. 분석기 부재를 문장별 NULL로 흡수하지 않는다.
    """
    return Analyzer(Dictionary(dict="core").create(SplitMode.C))


def compute_ruby(japanese: str, items: Sequence[RubyItem], *, now: datetime) -> RubyComputation:
    """문장 하나의 ruby를 계산한다. `items`는 그 문장의 tappable item 전부다."""
    return compute_ruby_from_tokens(japanese, load_analyzer().tokenize(japanese), items, now=now)


# --------------------------------------------------------------------------
# CLI 출력 (seed·backfill·fixture 생성 공용, 11_OBSERVABILITY.md)
# --------------------------------------------------------------------------


@dataclass
class RubySummary:
    """여러 문장의 계산 결과 누계. `label`은 seed_id 또는 sentence id다."""

    sentences: int = 0
    computed: int = 0
    failed: int = 0
    kanji_tokens: int = 0
    omitted_tappable_boundary: int = 0
    omitted_numeric: int = 0
    omitted_no_reading: int = 0
    corrected_explanation_tokens: int = 0
    corrected_table_rules: int = 0
    rule_hits: list[int] = field(default_factory=lambda: [0] * len(CORRECTION_RULES))
    mismatches: list[tuple[str, ReadingMismatch]] = field(default_factory=list)

    def add(self, label: str, computation: RubyComputation) -> None:
        self.sentences += 1
        self.computed += 1
        self.kanji_tokens += computation.kanji_tokens
        self.omitted_tappable_boundary += computation.omitted_tappable_boundary
        self.omitted_numeric += computation.omitted_numeric
        self.omitted_no_reading += computation.omitted_no_reading
        self.corrected_explanation_tokens += computation.corrected_explanation_tokens
        self.corrected_table_rules += computation.corrected_table_rules
        for index, hits in enumerate(computation.rule_hits):
            self.rule_hits[index] += hits
        self.mismatches.extend((label, mismatch) for mismatch in computation.mismatches)

    def add_failure(self) -> None:
        self.sentences += 1
        self.failed += 1


def escape_control(text: str) -> str:
    """C0(U+0000..U+001F), U+007F, C1(U+0080..U+009F)를 `\\uXXXX`로 바꾼다.

    불일치 목록의 표면형·설명 읽기는 LLM이 낸 문자열일 수 있다. 터미널 제어 시퀀스가 해석되거나
    한 항목이 여러 줄로 갈라져 목록을 위조하지 않게 한다.
    """
    return "".join(
        f"\\u{ord(char):04X}" if ord(char) <= 0x1F or 0x7F <= ord(char) <= 0x9F else char
        for char in text
    )


def format_rule(rule: CorrectionRule) -> str:
    """`私->わたし`. 조건이 있으면 `中->じゅう prev=今日`, `何->なに next=か|が|も|を`."""
    label = f"{rule.surface}->{rule.reading}"
    if rule.prev:
        label += " prev=" + ",".join(rule.prev)
    if rule.next_in:
        label += " next=" + "|".join(sorted(rule.next_in))
    return label


def format_summary_lines(summary: RubySummary) -> list[str]:
    """요약 한 줄 + 규칙별 적중(표 순서, 0이어도) + 불일치 목록."""
    reading_mismatches = sum(
        1 for _, mismatch in summary.mismatches if mismatch.kind is MismatchKind.READING_MISMATCH
    )
    overrides = len(summary.mismatches) - reading_mismatches
    lines = [
        f"ruby: algorithm_version={ALGORITHM_VERSION} sentences={summary.sentences} "
        f"computed={summary.computed} failed={summary.failed} "
        f"omitted_tappable_boundary={summary.omitted_tappable_boundary} "
        f"omitted_numeric={summary.omitted_numeric} "
        f"omitted_no_reading={summary.omitted_no_reading} "
        f"corrected_explanation_tokens={summary.corrected_explanation_tokens} "
        f"corrected_table_rules={summary.corrected_table_rules} "
        f"reading_mismatches={reading_mismatches} explanation_overrides={overrides} "
        f"kanji_tokens={summary.kanji_tokens}"
    ]
    lines.extend(
        f"rule {format_rule(rule)} hits={hits}"
        for rule, hits in zip(CORRECTION_RULES, summary.rule_hits, strict=True)
    )
    lines.extend(format_mismatch(label, mismatch) for label, mismatch in summary.mismatches)
    return lines


def format_mismatch(label: str, mismatch: ReadingMismatch) -> str:
    return (
        f"mismatch kind={mismatch.kind.value} sentence={escape_control(label)} "
        f"item={escape_control(str(mismatch.sentence_item_id))} "
        f"surface={escape_control(mismatch.surface)} "
        f"explanation={escape_control(mismatch.explanation)} "
        f"analyzer={escape_control(mismatch.analyzer)}"
    )
