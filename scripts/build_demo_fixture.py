#!/usr/bin/env python
"""Public Demo fixture 생성 CLI (`03_UI_UX_SPEC.md`의 `Demo`의 `fixture`).

    uv run python scripts/build_demo_fixture.py           # frontend/src/demo/fixture-data.ts를 쓴다
    uv run python scripts/build_demo_fixture.py --check   # 쓰지 않고 커밋된 파일과 비교한다

`seed/`의 YAML만 읽는다. DB·LLM에 닿지 않는다. 같은 `seed/`(와 같은 분석기·config)에서는 같은 파일이 나온다.

``` text
검사      span_mismatch        tappable span 문자열이 원문 [start, end)와 다르다 / item 사이 span 겹침
          missing_explanation  tappable item에 설명(또는 설명 필수 필드)이 없다
          tappable_count       문장의 tappable item 수가 1..learning.max_new_items_per_sentence 밖이다
선택      item을 difficulty_label -> frequency_rank(없으면 맨 뒤) -> seed_id 순으로 돌며, 덮지 않은
          item이면 검사를 통과한 미선택 문장 중 그 item을 tappable로 포함하고 덮지 않은 item을 가장
          많이 덮는 문장(동률은 문장 seed_id 순)을 고른다. 상한 DEMO_SENTENCE_CAP. 문장 순서 = 선택 순서
id        sentence_id = presentation_id = 순번(1..N), sentence_item_id = sentence_id * 10 + 문장 안
          tappable 순번(1부터), learning_item_id = items.yaml 순서(1부터)
ruby      seed 적재와 같은 compute_ruby + API와 같은 build_render_segments. 문장 하나의 계산 실패는 그
          문장을 ruby [] 로 넣고 `ruby_failed` 줄과 요약의 failed로 보고한다(exit 0)
식별자    fixture 데이터의 canonical JSON sha256 앞 16자 (진도 저장의 fixture 식별자)
```

-   seed 파일 구조가 틀리면(목록이 아님, seed_id 누락·중복, 모르는 item 참조, 타입이 틀린 필드 등) exit 2다.
    검사 3종에 걸린 문장은 제외 목록에 남기고 계속한다. 덮지 못한 item이 있어도 exit 0이다.
-   분석기를 적재하지 못하면 예외로 끝난다(fail-closed).
-   문장당 tappable 상한은 저장소의 `config/default.yaml`에서 읽는다. 운영 override 파일은 읽지 않는다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeGuard

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.config import DEFAULT_CONFIG_PATH, ConfigError, load_config  # noqa: E402
from app.furigana import (  # noqa: E402
    RubyItem,
    RubySummary,
    compute_ruby,
    escape_control,
    format_summary_lines,
    load_analyzer,
)
from app.models.enums import ContextStage, LearningItemType, PresentationRole  # noqa: E402
from app.render import (  # noqa: E402
    ItemSpan,
    RenderSegment,
    RenderSpanError,
    SpanRef,
    build_render_segments,
    validate_item_spans,
)
from app.schemas.study import (  # noqa: E402
    ExplanationResponse,
    PresentationPayload,
    RenderSegmentPayload,
    RubyPartPayload,
    TappableItemPayload,
)

EXIT_OK = 0
EXIT_FAILED = 2

DEFAULT_SEED_DIR = REPO_ROOT / "seed"
DEFAULT_OUTPUT = REPO_ROOT / "frontend" / "src" / "demo" / "fixture-data.ts"
ITEMS_FILE = "items.yaml"
SENTENCES_FILE = "sentences.yaml"

# 03_UI_UX_SPEC.md `fixture`의 상한. 학습 정책값이 아니라 fixture 크기 규칙이다.
DEMO_SENTENCE_CAP = 200

DIFFICULTY_ORDER = {"beginner": 0, "intermediate": 1, "advanced": 2}

REASON_SPAN_MISMATCH = "span_mismatch"
REASON_MISSING_EXPLANATION = "missing_explanation"
REASON_TAPPABLE_COUNT = "tappable_count"

# sentence_item_id = sentence_id * 10 + 순번. 순번이 이 값 이상이면 id가 겹친다.
_ITEM_ID_BASE = 10

# ruby_json을 싣지 않으므로 computed_at은 결과에 나타나지 않는다. 결정성을 위해 고정한다.
RUBY_COMPUTED_AT = datetime(2026, 1, 1, tzinfo=UTC)

# 생성 파일의 presentation 고정값. demo는 서버 선택이 없으므로 모든 문장이 같은 값이다.
# probe는 demo 화면이 진행 규칙에 따라 presentation 복사본에 채운다.
FIXED_PRESENTATION_ROLE = PresentationRole.NEW
FIXED_CONTEXT_STAGE = ContextStage.ANCHOR

HEADER = "// 생성 파일. 손으로 고치지 않는다. scripts/build_demo_fixture.py\n"
_ID_PREFIX = "export const DEMO_FIXTURE_ID = "
_DATA_PREFIX = "export const DEMO_SENTENCES: readonly DemoSentence[] = "
_ID_PATTERN = re.compile(r"^export const DEMO_FIXTURE_ID = '([0-9a-f]{16})'$", re.MULTILINE)


class FixtureError(Exception):
    """seed 파일 구조가 틀렸거나 생성 파일을 읽을 수 없다."""


@dataclass(frozen=True)
class SeedItem:
    seed_id: str
    type: LearningItemType
    lemma: str
    difficulty_label: str
    frequency_rank: int | None
    learning_item_id: int  # items.yaml 순서, 1부터


@dataclass(frozen=True)
class SeedExplanation:
    reading: str
    core_meaning: str
    meaning_in_context: str
    nuance: str
    example_sentence: str
    example_translation: str | None


@dataclass(frozen=True)
class SeedSentenceItem:
    item_seed_id: str
    surface_form: str
    is_tappable: bool
    spans: tuple[ItemSpan, ...]
    explanation: SeedExplanation | None  # 없거나 필수 필드가 틀리면 None (검사 2)


@dataclass(frozen=True)
class SeedSentence:
    seed_id: str
    japanese: str
    korean_translation: str
    items: tuple[SeedSentenceItem, ...]

    @property
    def tappable_items(self) -> tuple[SeedSentenceItem, ...]:
        return tuple(item for item in self.items if item.is_tappable)

    @property
    def tappable_item_seed_ids(self) -> frozenset[str]:
        return frozenset(item.item_seed_id for item in self.tappable_items)


@dataclass(frozen=True)
class BuildResult:
    data: list[dict[str, Any]]
    fixture_id: str
    excluded: list[tuple[str, str]]  # (sentence seed_id, reason)
    uncovered: list[SeedItem]
    covered_items: int
    total_items: int
    ruby_failed: list[tuple[str, str]]  # (sentence seed_id, 예외 타입 이름)
    ruby: RubySummary


# --------------------------------------------------------------------------
# YAML 파싱 (구조만 본다. 검사 3종은 check_sentence)
# --------------------------------------------------------------------------


def _entries(path: Path) -> list[Any]:
    if not path.is_file():
        raise FixtureError(f"seed file not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise FixtureError(f"{path.name}: invalid YAML") from exc
    if not isinstance(raw, list):
        raise FixtureError(f"{path.name}: top level must be a list of entries")
    return raw


def _mapping(value: object, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise FixtureError(f"{where}: expected a mapping")
    return {str(key): item for key, item in value.items()}


def _is_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _text(mapping: dict[str, Any], key: str, where: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise FixtureError(f"{where}: '{key}' must be a non-empty string")
    return value


def _is_int(value: object) -> TypeGuard[int]:
    # bool은 int의 하위 타입이다. YAML true를 1로 받지 않는다.
    return isinstance(value, int) and not isinstance(value, bool)


def _unique_seed_id(mapping: dict[str, Any], seen: set[str], where: str) -> str:
    seed_id = _text(mapping, "seed_id", where)
    if seed_id in seen:
        raise FixtureError(f"{where}: duplicate seed_id '{seed_id}'")
    seen.add(seed_id)
    return seed_id


def parse_items(path: Path) -> list[SeedItem]:
    items: list[SeedItem] = []
    seen: set[str] = set()
    for index, entry in enumerate(_entries(path)):
        where = f"{path.name}[{index}]"
        mapping = _mapping(entry, where)
        seed_id = _unique_seed_id(mapping, seen, where)
        raw_type = _text(mapping, "type", where)
        try:
            item_type = LearningItemType(raw_type)
        except ValueError:
            raise FixtureError(f"{where}: unknown type '{raw_type}'") from None
        difficulty = mapping.get("difficulty_label")
        if difficulty not in DIFFICULTY_ORDER:
            raise FixtureError(
                f"{where}: 'difficulty_label' must be one of {', '.join(DIFFICULTY_ORDER)}"
            )
        rank = mapping.get("frequency_rank")
        if rank is not None and not _is_int(rank):
            raise FixtureError(f"{where}: 'frequency_rank' must be an integer when present")
        items.append(
            SeedItem(
                seed_id=seed_id,
                type=item_type,
                lemma=_text(mapping, "lemma", where),
                difficulty_label=str(difficulty),
                frequency_rank=rank,
                learning_item_id=index + 1,
            )
        )
    return items


def _parse_explanation(value: object) -> SeedExplanation | None:
    if not isinstance(value, dict):
        return None
    required = ("reading", "core_meaning", "meaning_in_context", "nuance", "example_sentence")
    if not all(_is_text(value.get(key)) for key in required):
        return None
    translation = value.get("example_translation")
    if translation is not None and not _is_text(translation):
        return None
    return SeedExplanation(
        reading=value["reading"],
        core_meaning=value["core_meaning"],
        meaning_in_context=value["meaning_in_context"],
        nuance=value["nuance"],
        example_sentence=value["example_sentence"],
        example_translation=translation,
    )


def _parse_spans(value: object, where: str) -> tuple[ItemSpan, ...]:
    if not isinstance(value, list):
        raise FixtureError(f"{where}: 'spans' must be a list")
    spans: list[ItemSpan] = []
    for index, raw in enumerate(value):
        inner = f"{where}.spans[{index}]"
        mapping = _mapping(raw, inner)
        start, end, order = (
            mapping.get(key) for key in ("start_codepoint", "end_codepoint", "span_order")
        )
        if not (_is_int(start) and _is_int(end) and _is_int(order)):
            raise FixtureError(
                f"{inner}: start_codepoint/end_codepoint/span_order must be integers"
            )
        spans.append(ItemSpan(start, end, order))
    return tuple(spans)


def parse_sentences(path: Path, item_seed_ids: set[str]) -> list[SeedSentence]:
    sentences: list[SeedSentence] = []
    seen: set[str] = set()
    for index, entry in enumerate(_entries(path)):
        where = f"{path.name}[{index}]"
        mapping = _mapping(entry, where)
        seed_id = _unique_seed_id(mapping, seen, where)
        raw_items = mapping.get("items")
        if not isinstance(raw_items, list):
            raise FixtureError(f"{where}: 'items' must be a list")
        items: list[SeedSentenceItem] = []
        for item_index, raw_item in enumerate(raw_items):
            item_where = f"{where}.items[{item_index}]"
            item_mapping = _mapping(raw_item, item_where)
            item_seed_id = _text(item_mapping, "item_seed_id", item_where)
            if item_seed_id not in item_seed_ids:
                raise FixtureError(f"{item_where}: unknown item_seed_id '{item_seed_id}'")
            is_tappable = item_mapping.get("is_tappable")
            if not isinstance(is_tappable, bool):
                raise FixtureError(f"{item_where}: 'is_tappable' must be a boolean")
            items.append(
                SeedSentenceItem(
                    item_seed_id=item_seed_id,
                    surface_form=_text(item_mapping, "surface_form", item_where),
                    is_tappable=is_tappable,
                    spans=_parse_spans(item_mapping.get("spans"), item_where),
                    explanation=_parse_explanation(item_mapping.get("explanation")),
                )
            )
        sentences.append(
            SeedSentence(
                seed_id=seed_id,
                japanese=_text(mapping, "japanese", where),
                korean_translation=_text(mapping, "korean_translation", where),
                items=tuple(items),
            )
        )
    return sentences


# --------------------------------------------------------------------------
# 검사와 선택
# --------------------------------------------------------------------------


def _span_refs(items: Sequence[SeedSentenceItem], ids: Sequence[tuple[int, int]]) -> list[SpanRef]:
    """tappable item들의 span. `ids`는 item마다 (sentence_item_id, learning_item_id)."""
    return [
        SpanRef(
            sentence_item_id=sentence_item_id,
            learning_item_id=learning_item_id,
            is_tappable=True,
            start_codepoint=span.start_codepoint,
            end_codepoint=span.end_codepoint,
        )
        for item, (sentence_item_id, learning_item_id) in zip(items, ids, strict=True)
        for span in item.spans
    ]


def check_sentence(sentence: SeedSentence, max_tappable: int) -> str | None:
    """검사 3종을 순서대로 보고 처음 걸린 사유를 돌려준다. 통과하면 None."""
    tappable = sentence.tappable_items
    try:
        for item in sentence.items:
            validate_item_spans(sentence.japanese, item.surface_form, item.spans)
        # item 사이 겹침은 렌더링 함수가 터지는 조건 그대로 본다(seed_loader와 같다).
        indexes = [(index, index) for index in range(len(tappable))]
        build_render_segments(sentence.japanese, _span_refs(tappable, indexes))
    except RenderSpanError:
        return REASON_SPAN_MISMATCH
    if any(item.explanation is None for item in tappable):
        return REASON_MISSING_EXPLANATION
    if not 1 <= len(tappable) <= max_tappable:
        return REASON_TAPPABLE_COUNT
    return None


def item_sort_key(item: SeedItem) -> tuple[int, bool, int, str]:
    """difficulty_label -> frequency_rank(없으면 같은 difficulty의 맨 뒤) -> seed_id."""
    rank = item.frequency_rank
    return (DIFFICULTY_ORDER[item.difficulty_label], rank is None, rank or 0, item.seed_id)


def select_sentences(
    items: Sequence[SeedItem], passing: Sequence[SeedSentence], cap: int
) -> tuple[list[SeedSentence], list[SeedItem]]:
    """greedy set cover. (선택 순서대로의 문장, 정렬 키 순서의 덮지 못한 item)."""
    ordered = sorted(items, key=item_sort_key)
    covered: set[str] = set()
    chosen: set[str] = set()
    selected: list[SeedSentence] = []
    for item in ordered:
        if item.seed_id in covered:
            continue
        if len(selected) >= cap:
            break
        candidates = [
            sentence
            for sentence in passing
            if sentence.seed_id not in chosen and item.seed_id in sentence.tappable_item_seed_ids
        ]
        if not candidates:
            continue
        best = min(
            candidates,
            key=lambda sentence: (
                -len(sentence.tappable_item_seed_ids - covered),
                sentence.seed_id,
            ),
        )
        selected.append(best)
        chosen.add(best.seed_id)
        covered |= best.tappable_item_seed_ids
    uncovered = [item for item in ordered if item.seed_id not in covered]
    return selected, uncovered


# --------------------------------------------------------------------------
# 조립
# --------------------------------------------------------------------------


def _segment_payload(segment: RenderSegment) -> RenderSegmentPayload:
    return RenderSegmentPayload(
        text=segment.text,
        sentence_item_id=segment.sentence_item_id,
        ruby=[RubyPartPayload(text=part.text, reading=part.reading) for part in segment.ruby],
    )


def _sentence_entry(
    sentence_id: int,
    sentence: SeedSentence,
    items_by_seed_id: dict[str, SeedItem],
    summary: RubySummary,
    ruby_failed: list[tuple[str, str]],
) -> dict[str, Any]:
    tappable = sentence.tappable_items
    ids = [
        (sentence_id * _ITEM_ID_BASE + order, items_by_seed_id[item.item_seed_id].learning_item_id)
        for order, item in enumerate(tappable, start=1)
    ]
    refs = _span_refs(tappable, ids)
    ruby_items = [
        RubyItem(
            sentence_item_id=item.item_seed_id,
            spans=item.spans,
            explanation_reading=item.explanation.reading if item.explanation else None,
        )
        for item in tappable
    ]
    try:
        computation = compute_ruby(sentence.japanese, ruby_items, now=RUBY_COMPUTED_AT)
        segments = build_render_segments(sentence.japanese, refs, ruby=computation.spans)
    except Exception as exc:
        # 표시 보조의 실패는 문장을 막지 않는다(ADR-021). 예외 메시지는 싣지 않는다.
        summary.add_failure()
        ruby_failed.append((sentence.seed_id, type(exc).__name__))
        segments = build_render_segments(sentence.japanese, refs)
    else:
        summary.add(sentence.seed_id, computation)

    presentation = PresentationPayload(
        presentation_id=sentence_id,
        sentence_id=sentence_id,
        japanese=sentence.japanese,
        render_segments=[_segment_payload(segment) for segment in segments],
        presentation_role=FIXED_PRESENTATION_ROLE,
        review_reason=None,
        context_stage=FIXED_CONTEXT_STAGE,
        translation_revealed=False,
        tappable_items=[
            TappableItemPayload(sentence_item_id=sentence_item_id, learning_item_id=learning_id)
            for sentence_item_id, learning_id in ids
        ],
        probe=None,
    )
    explanations: dict[str, Any] = {}
    for item, (sentence_item_id, learning_item_id) in zip(tappable, ids, strict=True):
        explanation = item.explanation
        assert explanation is not None  # noqa: S101 (check_sentence가 걸렀다)
        learning_item = items_by_seed_id[item.item_seed_id]
        # JSON 객체 key는 문자열이다. 파일을 다시 읽은 값과 같은 모양으로 만든다.
        explanations[str(sentence_item_id)] = ExplanationResponse(
            sentence_item_id=sentence_item_id,
            learning_item_id=learning_item_id,
            canonical_form=learning_item.lemma,
            reading=explanation.reading,
            item_type=learning_item.type,
            core_meaning=explanation.core_meaning,
            meaning_in_context=explanation.meaning_in_context,
            nuance=explanation.nuance,
            example_sentence=explanation.example_sentence,
            example_translation=explanation.example_translation,
        ).model_dump(mode="json")
    return {
        "presentation": presentation.model_dump(mode="json"),
        "korean_translation": sentence.korean_translation,
        "explanations": explanations,
    }


def fixture_id(data: Sequence[dict[str, Any]]) -> str:
    canonical = json.dumps(list(data), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def build(seed_dir: Path, max_tappable: int) -> BuildResult:
    items = parse_items(seed_dir / ITEMS_FILE)
    sentences = parse_sentences(seed_dir / SENTENCES_FILE, {item.seed_id for item in items})

    excluded: list[tuple[str, str]] = []
    passing: list[SeedSentence] = []
    for sentence in sentences:
        reason = check_sentence(sentence, max_tappable)
        if reason is None:
            passing.append(sentence)
        else:
            excluded.append((sentence.seed_id, reason))

    selected, uncovered = select_sentences(items, passing, DEMO_SENTENCE_CAP)
    items_by_seed_id = {item.seed_id: item for item in items}
    summary = RubySummary()
    ruby_failed: list[tuple[str, str]] = []
    data = [
        _sentence_entry(sentence_id, sentence, items_by_seed_id, summary, ruby_failed)
        for sentence_id, sentence in enumerate(selected, start=1)
    ]
    return BuildResult(
        data=data,
        fixture_id=fixture_id(data),
        excluded=excluded,
        uncovered=uncovered,
        covered_items=len(items) - len(uncovered),
        total_items=len(items),
        ruby_failed=ruby_failed,
        ruby=summary,
    )


# --------------------------------------------------------------------------
# 생성 파일
# --------------------------------------------------------------------------


def render_ts(identifier: str, data: Sequence[dict[str, Any]]) -> str:
    lines = [json.dumps(entry, ensure_ascii=False, separators=(",", ":")) for entry in data]
    body = ",\n".join(lines)
    return (
        f"{HEADER}"
        "import type { DemoSentence } from './fixture'\n"
        "\n"
        f"{_ID_PREFIX}'{identifier}'\n"
        "\n"
        f"{_DATA_PREFIX}[\n{body}\n]\n"
    )


def read_fixture(path: Path) -> tuple[str, list[dict[str, Any]]]:
    """생성 파일에서 (fixture 식별자, 문장 데이터)를 읽는다. 테스트와 e2e가 쓴다."""
    text = path.read_text(encoding="utf-8")
    match = _ID_PATTERN.search(text)
    start = text.find(_DATA_PREFIX)
    if match is None or start < 0:
        raise FixtureError(f"{path}: not a generated demo fixture")
    try:
        data = json.loads(text[start + len(_DATA_PREFIX) :])
    except json.JSONDecodeError as exc:
        raise FixtureError(f"{path}: DEMO_SENTENCES is not valid JSON") from exc
    if not isinstance(data, list):
        raise FixtureError(f"{path}: DEMO_SENTENCES must be an array")
    return match.group(1), data


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _fail(message: str) -> int:
    sys.stderr.write(f"error: {message}\n")
    return EXIT_FAILED


def _out(message: str) -> None:
    sys.stdout.write(message)
    sys.stdout.flush()


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the Public Demo fixture from seed/.")
    parser.add_argument(
        "--seed-dir",
        type=Path,
        default=DEFAULT_SEED_DIR,
        help=f"items.yaml / sentences.yaml이 있는 디렉터리 (기본값 {DEFAULT_SEED_DIR}).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"생성 파일 경로 (기본값 {DEFAULT_OUTPUT}).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="쓰지 않고 --output의 파일과 재생성 결과를 비교한다. 다르면 exit 2.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    # 분석기 부재는 배포 결함이다. 문장별 실패로 흡수하지 않는다.
    load_analyzer()

    try:
        max_tappable = load_config(DEFAULT_CONFIG_PATH).learning.max_new_items_per_sentence
    except ConfigError as exc:
        return _fail(str(exc))
    if max_tappable >= _ITEM_ID_BASE:
        return _fail(
            f"learning.max_new_items_per_sentence={max_tappable} does not fit the fixture "
            f"sentence_item_id scheme (at most {_ITEM_ID_BASE - 1})"
        )

    try:
        result = build(args.seed_dir, max_tappable)
    except FixtureError as exc:
        return _fail(str(exc))

    _out(
        f"fixture: sentences={len(result.data)}/{DEMO_SENTENCE_CAP} "
        f"covered_items={result.covered_items}/{result.total_items} "
        f"excluded={len(result.excluded)} uncovered={len(result.uncovered)} "
        f"id={result.fixture_id}\n"
    )
    for seed_id, reason in result.excluded:
        _out(f"excluded sentence={escape_control(seed_id)} reason={reason}\n")
    for item in result.uncovered:
        _out(f"uncovered item={escape_control(item.seed_id)}\n")
    for seed_id, error in result.ruby_failed:
        _out(f"ruby_failed sentence={escape_control(seed_id)} error={error}\n")
    _out("".join(f"{line}\n" for line in format_summary_lines(result.ruby)))

    content = render_ts(result.fixture_id, result.data).encode("utf-8")
    if args.check:
        current = args.output.read_bytes() if args.output.is_file() else None
        if current != content:
            _out(f"check: differs {args.output}\n")
            return EXIT_FAILED
        _out("check: ok\n")
        return EXIT_OK

    args.output.write_bytes(content)
    _out(f"wrote {args.output}\n")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
