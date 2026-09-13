"""Starter seed 적재.

`04_DB_SPEC.md`의 Seed Data와 `06_LEARNING_ENGINE.md`의 `seed_order` 규약을 구현한다.

규칙:
-   `learning_items.origin = seed`, `sentences.source_type = seed`,
    `sentences.source_id = <seed_id>`.
-   빈도 정보는 `learning_items.metadata_json.frequency_rank`로만 싣는다.
    frequency 전용 컬럼을 만들지 않는다.
-   `seed_order`는 1부터 1씩 증가하며 seed 파일명 오름차순 -> 파일 내 행 순서로
    부여한다. `frequency_rank`가 없어도 `seed_order`를 `frequency_rank`로
    승격시키지 않는다. 둘은 서로 다른 척도다.
-   explanation이 없는 sentence item은 거부한다. 설명이 없는 문장이 Ready Pool에
    들어가면 tap 시 보여줄 데이터가 없다(불변식 6).
-   재적재는 지원하지 않는다. `origin = seed` 행이 이미 있으면 거부한다.
    정상 절차는 `make db-reset && make seed`다.
-   검증 실패 시 DB에 아무것도 남기지 않는다. 적재는 한 트랜잭션이다.
-   (MVP-02) 문장마다 후리가나를 계산해 같은 트랜잭션에서 `sentences.ruby_json`에 넣는다
    (ADR-021 결정 4, 04_DB_SPEC.md의 Seed Data). **문장 하나의 계산이 실패하면 그 문장만
    `ruby_json = NULL`로 적재하고 계속한다.** 분석기 자체를 적재하지 못하면 이 모듈의 import가
    실패하고, CLI는 시작에서 `load_analyzer()`로 먼저 실패한다(fail-closed).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import sqlalchemy as sa
import yaml
from sqlalchemy.orm import Session

from app.furigana import RubyItem, RubySummary, compute_ruby
from app.models.content import (
    LearningItem,
    Sentence,
    SentenceItem,
    SentenceItemExplanation,
    SentenceItemSpan,
)
from app.models.enums import (
    ExplanationStatus,
    LearningItemOrigin,
    LearningItemType,
    SentenceSourceType,
    SentenceStatus,
)
from app.normalization import normalized_sentence_hash
from app.render import (
    ItemSpan,
    RenderSpanError,
    SpanRef,
    build_render_segments,
    validate_item_spans,
)

ITEMS_FILE = "items.yaml"
SENTENCES_FILE = "sentences.yaml"


class SeedError(Exception):
    """seed 파일이 규약을 어겼거나 DB 상태가 적재를 허용하지 않는다."""


@dataclass(frozen=True)
class SeedSummary:
    items: int
    sentences: int
    spans: int
    explanations: int
    # 후리가나 계산 누계. CLI가 `format_summary_lines`로 출력한다(11_OBSERVABILITY.md).
    ruby: RubySummary


@dataclass(frozen=True)
class _Explanation:
    reading: str
    core_meaning: str
    meaning_in_context: str
    nuance: str
    example_sentence: str
    example_translation: str | None


@dataclass(frozen=True)
class _SentenceItem:
    item_seed_id: str
    surface_form: str
    is_tappable: bool
    spans: tuple[ItemSpan, ...]
    explanation: _Explanation


@dataclass(frozen=True)
class _Item:
    seed_id: str
    type: LearningItemType
    lemma: str
    reading: str
    default_meaning: str
    difficulty_label: str | None
    topic_tags: list[str] | None
    frequency_rank: int | None
    seed_order: int


@dataclass(frozen=True)
class _Sentence:
    seed_id: str
    japanese: str
    korean_translation: str
    items: tuple[_SentenceItem, ...]


# --------------------------------------------------------------------------
# YAML 파싱 (타입 검사만 한다. 의미 검증은 아래 validate 단계다.)
# --------------------------------------------------------------------------


def _load_entries(path: Path) -> list[object]:
    if not path.is_file():
        raise SeedError(f"seed file not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise SeedError(f"{path.name}: top level must be a list of entries")
    return raw


def _mapping(value: object, where: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise SeedError(f"{where}: expected a mapping")
    return {str(key): item for key, item in value.items()}


def _text(mapping: dict[str, object], key: str, where: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SeedError(f"{where}: '{key}' must be a non-empty string")
    return value


def _optional_text(mapping: dict[str, object], key: str, where: str) -> str | None:
    value = mapping.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise SeedError(f"{where}: '{key}' must be a non-empty string when present")
    return value


def _optional_int(mapping: dict[str, object], key: str, where: str) -> int | None:
    value = mapping.get(key)
    if value is None:
        return None
    # bool은 int의 subclass다. frequency_rank: true를 1로 받아들이면 안 된다.
    if not isinstance(value, int) or isinstance(value, bool):
        raise SeedError(f"{where}: '{key}' must be an integer when present")
    return value


def _int(mapping: dict[str, object], key: str, where: str) -> int:
    value = _optional_int(mapping, key, where)
    if value is None:
        raise SeedError(f"{where}: '{key}' is required and must be an integer")
    return value


def _bool(mapping: dict[str, object], key: str, where: str) -> bool:
    value = mapping.get(key)
    if not isinstance(value, bool):
        raise SeedError(f"{where}: '{key}' must be a boolean")
    return value


def _tags(mapping: dict[str, object], where: str) -> list[str] | None:
    value = mapping.get("topic_tags")
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(tag, str) and tag for tag in value):
        raise SeedError(f"{where}: 'topic_tags' must be a list of non-empty strings")
    return list(value)


def _parse_items(path: Path) -> list[_Item]:
    """seed_order는 파일 내 행 순서대로 1부터 1씩 증가한다(06_LEARNING_ENGINE.md).

    learning_item은 `items.yaml` 한 파일에만 존재하므로 "파일명 오름차순"은
    이 파일의 행 순서로 축약된다. item 파일이 늘어나면 파일명 오름차순으로
    순회해야 한다.
    """
    items: list[_Item] = []
    seen: set[str] = set()
    for index, entry in enumerate(_load_entries(path)):
        where = f"{path.name}[{index}]"
        mapping = _mapping(entry, where)
        seed_id = _text(mapping, "seed_id", where)
        if seed_id in seen:
            raise SeedError(f"{where}: duplicate seed_id '{seed_id}'")
        seen.add(seed_id)
        raw_type = _text(mapping, "type", where)
        try:
            item_type = LearningItemType(raw_type)
        except ValueError:
            allowed = ", ".join(member.value for member in LearningItemType)
            raise SeedError(
                f"{where}: 'type' must be one of {allowed} (got '{raw_type}')"
            ) from None
        items.append(
            _Item(
                seed_id=seed_id,
                type=item_type,
                lemma=_text(mapping, "lemma", where),
                reading=_text(mapping, "reading", where),
                default_meaning=_text(mapping, "default_meaning", where),
                difficulty_label=_optional_text(mapping, "difficulty_label", where),
                topic_tags=_tags(mapping, where),
                frequency_rank=_optional_int(mapping, "frequency_rank", where),
                seed_order=index + 1,
            )
        )
    return items


def _parse_explanation(entry: dict[str, object], where: str) -> _Explanation:
    # explanation은 선택 항목이 아니다. 없으면 이 문장은 Ready가 될 수 없다.
    raw = entry.get("explanation")
    if raw is None:
        raise SeedError(f"{where}: 'explanation' is required for every seed sentence item")
    mapping = _mapping(raw, f"{where}.explanation")
    inner = f"{where}.explanation"
    return _Explanation(
        reading=_text(mapping, "reading", inner),
        core_meaning=_text(mapping, "core_meaning", inner),
        meaning_in_context=_text(mapping, "meaning_in_context", inner),
        nuance=_text(mapping, "nuance", inner),
        example_sentence=_text(mapping, "example_sentence", inner),
        example_translation=_optional_text(mapping, "example_translation", inner),
    )


def _parse_spans(entry: dict[str, object], where: str) -> tuple[ItemSpan, ...]:
    raw = entry.get("spans")
    if not isinstance(raw, list) or not raw:
        raise SeedError(f"{where}: 'spans' must be a non-empty list")
    spans: list[ItemSpan] = []
    for index, span_entry in enumerate(raw):
        inner = f"{where}.spans[{index}]"
        mapping = _mapping(span_entry, inner)
        spans.append(
            ItemSpan(
                start_codepoint=_int(mapping, "start_codepoint", inner),
                end_codepoint=_int(mapping, "end_codepoint", inner),
                span_order=_int(mapping, "span_order", inner),
            )
        )
    return tuple(spans)


def _parse_sentences(path: Path, item_seed_ids: set[str]) -> list[_Sentence]:
    sentences: list[_Sentence] = []
    seen: set[str] = set()
    for index, entry in enumerate(_load_entries(path)):
        where = f"{path.name}[{index}]"
        mapping = _mapping(entry, where)
        seed_id = _text(mapping, "seed_id", where)
        if seed_id in seen:
            raise SeedError(f"{where}: duplicate seed_id '{seed_id}'")
        seen.add(seed_id)
        japanese = _text(mapping, "japanese", where)
        raw_items = mapping.get("items")
        if not isinstance(raw_items, list) or not raw_items:
            raise SeedError(f"{where}: 'items' must be a non-empty list")

        parsed_items: list[_SentenceItem] = []
        for item_index, raw_item in enumerate(raw_items):
            item_where = f"{where}.items[{item_index}]"
            item_mapping = _mapping(raw_item, item_where)
            item_seed_id = _text(item_mapping, "item_seed_id", item_where)
            if item_seed_id not in item_seed_ids:
                raise SeedError(
                    f"{item_where}: unknown item_seed_id '{item_seed_id}' (not in {ITEMS_FILE})"
                )
            surface_form = _text(item_mapping, "surface_form", item_where)
            spans = _parse_spans(item_mapping, item_where)
            try:
                validate_item_spans(japanese, surface_form, spans)
            except RenderSpanError as error:
                raise SeedError(f"{item_where}: {error}") from error
            parsed_items.append(
                _SentenceItem(
                    item_seed_id=item_seed_id,
                    surface_form=surface_form,
                    is_tappable=_bool(item_mapping, "is_tappable", item_where),
                    spans=spans,
                    explanation=_parse_explanation(item_mapping, item_where),
                )
            )

        _reject_cross_item_overlap(japanese, parsed_items, where)
        sentences.append(
            _Sentence(
                seed_id=seed_id,
                japanese=japanese,
                korean_translation=_text(mapping, "korean_translation", where),
                items=tuple(parsed_items),
            )
        )
    return sentences


def _reject_cross_item_overlap(japanese: str, items: list[_SentenceItem], where: str) -> None:
    """서로 **다른** item의 tappable span이 겹치면 거부한다.

    `validate_item_spans`는 item 하나 안만 본다. 문장의 tappable span **전부를**
    `build_render_segments`에 한 번에 넣으면 그 함수가 span을 정렬한 뒤 이미 하는
    `start < cursor` 검사가 cross-item overlap까지 잡는다. 판정을 여기서 다시
    구현하지 않는 이유이기도 하다 --- 렌더링이 터지는 조건과 적재를 거부하는
    조건이 정의상 같아진다(08_LLM_SPEC.md validation 8번, "ambiguous tappable
    overlap 없음").

    `SpanRef.sentence_item_id`에는 아직 DB id가 없으므로 **문장 안 item의 순번**을
    넣는다. 오류 메시지의 숫자는 그 순번이다.
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
        raise SeedError(f"{where}: {error}") from error


# --------------------------------------------------------------------------
# 적재
# --------------------------------------------------------------------------


def _reject_if_already_seeded(session: Session) -> None:
    item_count = session.scalar(
        sa.select(sa.func.count())
        .select_from(LearningItem)
        .where(LearningItem.origin == LearningItemOrigin.SEED)
    )
    sentence_count = session.scalar(
        sa.select(sa.func.count())
        .select_from(Sentence)
        .where(Sentence.source_type == SentenceSourceType.SEED)
    )
    if item_count or sentence_count:
        raise SeedError(
            f"seed rows already exist (learning_items={item_count}, sentences={sentence_count}). "
            "re-loading is not supported; run `make db-reset` and then `make seed`."
        )


def load_seed(session: Session, seed_dir: Path, *, now: datetime) -> SeedSummary:
    """seed 디렉터리를 적재하고 요약을 돌려준다. commit은 호출자가 한다.

    `now`는 호출자(CLI 진입점)가 읽은 값이다. 여기서 시계를 읽지 않고, 이 적재로
    생기는 모든 `created_at` / `generated_at`이 **같은 순간**을 갖는다 (ADR-007).
    """
    items = _parse_items(seed_dir / ITEMS_FILE)
    sentences = _parse_sentences(seed_dir / SENTENCES_FILE, {item.seed_id for item in items})
    _reject_if_already_seeded(session)

    spans = 0
    explanations = 0
    ruby = RubySummary()

    # 검증은 위에서 끝났지만 적재 중 DB 제약 위반이 나도 부분 적재가 남지 않게 한다.
    with session.begin_nested():
        item_ids: dict[str, int] = {}
        for item in items:
            metadata: dict[str, Any] = {"seed_order": item.seed_order}
            if item.frequency_rank is not None:
                metadata["frequency_rank"] = item.frequency_rank
            row = LearningItem(
                type=item.type,
                lemma=item.lemma,
                reading=item.reading,
                default_meaning=item.default_meaning,
                difficulty_label=item.difficulty_label,
                topic_tags=item.topic_tags,
                origin=LearningItemOrigin.SEED,
                metadata_json=metadata,
                created_at=now,
            )
            session.add(row)
            session.flush()
            item_ids[item.seed_id] = row.id

        for sentence in sentences:
            sentence_row = Sentence(
                japanese=sentence.japanese,
                korean_translation=sentence.korean_translation,
                source_type=SentenceSourceType.SEED,
                source_id=sentence.seed_id,
                normalized_hash=normalized_sentence_hash(sentence.japanese),
                status=SentenceStatus.VALIDATED,
                ruby_json=_compute_ruby_json(sentence, ruby, now=now),
                created_at=now,
            )
            session.add(sentence_row)
            session.flush()

            for sentence_item in sentence.items:
                item_row = SentenceItem(
                    sentence_id=sentence_row.id,
                    learning_item_id=item_ids[sentence_item.item_seed_id],
                    surface_form=sentence_item.surface_form,
                    is_tappable=sentence_item.is_tappable,
                    created_at=now,
                )
                session.add(item_row)
                session.flush()

                for span in sentence_item.spans:
                    session.add(
                        SentenceItemSpan(
                            sentence_item_id=item_row.id,
                            start_codepoint=span.start_codepoint,
                            end_codepoint=span.end_codepoint,
                            span_order=span.span_order,
                        )
                    )
                    spans += 1

                explanation = sentence_item.explanation
                session.add(
                    SentenceItemExplanation(
                        sentence_item_id=item_row.id,
                        reading=explanation.reading,
                        core_meaning=explanation.core_meaning,
                        meaning_in_context=explanation.meaning_in_context,
                        nuance=explanation.nuance,
                        example_sentence=explanation.example_sentence,
                        example_translation=explanation.example_translation,
                        generated_at=now,
                        status=ExplanationStatus.VALIDATED,
                    )
                )
                explanations += 1
        session.flush()

    return SeedSummary(
        items=len(items),
        sentences=len(sentences),
        spans=spans,
        explanations=explanations,
        ruby=ruby,
    )


def _compute_ruby_json(
    sentence: _Sentence, summary: RubySummary, *, now: datetime
) -> dict[str, Any] | None:
    """tappable item의 span과 `explanation.reading`으로 계산한다. 실패하면 None(= 미계산).

    예외를 여기서 삼키는 이유: 후리가나는 표시 보조이고 계산 실패가 적재를 막지 않는다
    (10_ERROR_HANDLING.md의 `후리가나 계산 실패`). backfill이 NULL 행을 다시 시도한다.
    불일치 보고의 식별자는 seed의 `seed_id`와 `item_seed_id`다(아직 DB id가 없다).
    """
    items = [
        RubyItem(
            sentence_item_id=item.item_seed_id,
            spans=item.spans,
            explanation_reading=item.explanation.reading,
        )
        for item in sentence.items
        if item.is_tappable
    ]
    try:
        computation = compute_ruby(sentence.japanese, items, now=now)
    except Exception:
        summary.add_failure()
        return None
    summary.add(sentence.seed_id, computation)
    return computation.ruby_json
