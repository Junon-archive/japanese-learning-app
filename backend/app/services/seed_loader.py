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

from app.config import AppConfig
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
    Language,
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

# `mvp-03-english/01_ENGLISH_CONTENT.md`의 `topic_tags 고정 집합`. 그 절이 **"고정 집합
# 강제는 seed loader가 한다"**고 못박았다 --- DB CHECK로 배열 원소를 제약하면 집합을
# 늘릴 때마다 migration이 필요하다. 집합을 늘리는 것은 이 상수와 그 문서를 같은
# 커밋에서 고치는 일이다.
#
# 같은 절이 **"태그는 두 언어가 공유하지 않는다"**고 적고(소비처가 "최근 topic 반복
# 회피"뿐이며 그 비교는 세션 언어 안에서만 일어난다) 영어는 `grammar`를 쓰지 않는다.
# 그래서 허용 집합을 언어별로 나눈다.
_EN_TOPIC_TAGS: frozenset[str] = frozenset(
    {
        # 언어 성격
        "phrasal-verb",
        "idiom",
        "discourse-marker",
        "formulaic",
        "contraction",
        "colloquial",
        "slang",
        # 상황
        "daily",
        "friends",
        "work",
        "travel",
        "food",
        "shopping",
        "health",
        "phone",
        "smalltalk",
    }
)
# 일본어 집합의 canonical 목록은 어느 명세에도 없다. `seed/ja/items.yaml`에 **실제로
# 쓰인** 네 태그에서 뽑은 값이다(`grammar`는 일본어에만 있다). 일본어 seed에 새 태그를
# 쓰려면 이 상수를 같은 커밋에서 늘린다.
_JA_TOPIC_TAGS: frozenset[str] = frozenset({"daily", "work", "grammar", "emotion"})

ALLOWED_TOPIC_TAGS: dict[Language, frozenset[str]] = {
    Language.JA: _JA_TOPIC_TAGS,
    Language.EN: _EN_TOPIC_TAGS,
}


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
    # 증분 적재 요약(04_DB_SPEC.md의 `증분 적재`). 비-incremental 모드는 전량이
    # inserted이고 skipped는 0이다.
    items_inserted: int
    items_skipped: int
    sentences_inserted: int
    sentences_skipped: int


@dataclass(frozen=True)
class _Explanation:
    reading: str | None
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
    reading: str | None
    default_meaning: str
    difficulty_label: str | None
    topic_tags: list[str] | None
    frequency_rank: int | None


@dataclass(frozen=True)
class _Sentence:
    seed_id: str
    text: str
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
    """`metadata_json.seed_order`는 여기서 매기지 않는다. `load_seed`가 적재 순서대로

    (기본 모드는 파일 내 행 순서, 증분 모드는 그 언어의 기존 최대값 다음부터) 매긴다
    (06_LEARNING_ENGINE.md, 04_DB_SPEC.md의 `증분 적재`).

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
                reading=_optional_text(mapping, "reading", where),
                default_meaning=_text(mapping, "default_meaning", where),
                difficulty_label=_optional_text(mapping, "difficulty_label", where),
                topic_tags=_tags(mapping, where),
                frequency_rank=_optional_int(mapping, "frequency_rank", where),
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
        reading=_optional_text(mapping, "reading", inner),
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
        text = _text(mapping, "text", where)
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
                validate_item_spans(text, surface_form, spans)
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

        _reject_cross_item_overlap(text, parsed_items, where)
        sentences.append(
            _Sentence(
                seed_id=seed_id,
                text=text,
                korean_translation=_text(mapping, "korean_translation", where),
                items=tuple(parsed_items),
            )
        )
    return sentences


def _reject_cross_item_overlap(text: str, items: list[_SentenceItem], where: str) -> None:
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
        build_render_segments(text, spans)
    except RenderSpanError as error:
        raise SeedError(f"{where}: {error}") from error


# --------------------------------------------------------------------------
# 적재
# --------------------------------------------------------------------------


def _validate_reading_by_language(
    items: list[_Item], sentences: list[_Sentence], *, language: Language
) -> None:
    """`reading`이 언어 규칙을 지키는지 검증한다(ADR-023 결정 3, `01_ENGLISH_CONTENT.md`).

    일본어(`ja`)는 `learning_items.reading`과 explanation의 `reading`이 모두 필수다.
    영어(`en`)는 둘 다 금지다(YAML에 키가 있으면 안 된다). DB 레벨 NOT NULL 제약은
    migration 0005에서 이미 없앴으므로 이 파서 레벨에서 언어별 규약을 강제한다.
    """
    if language is Language.JA:
        for item in items:
            if item.reading is None:
                raise SeedError(
                    f"{ITEMS_FILE}: seed_id '{item.seed_id}' is missing 'reading' "
                    "(required for language=ja)"
                )
        for sentence in sentences:
            for sentence_item in sentence.items:
                if sentence_item.explanation.reading is None:
                    raise SeedError(
                        f"{SENTENCES_FILE}: seed_id '{sentence.seed_id}' "
                        f"item_seed_id '{sentence_item.item_seed_id}' explanation is "
                        "missing 'reading' (required for language=ja)"
                    )
    elif language is Language.EN:
        for item in items:
            if item.reading is not None:
                raise SeedError(
                    f"{ITEMS_FILE}: seed_id '{item.seed_id}' must not have 'reading' "
                    "(forbidden for language=en)"
                )
        for sentence in sentences:
            for sentence_item in sentence.items:
                if sentence_item.explanation.reading is not None:
                    raise SeedError(
                        f"{SENTENCES_FILE}: seed_id '{sentence.seed_id}' "
                        f"item_seed_id '{sentence_item.item_seed_id}' explanation must "
                        "not have 'reading' (forbidden for language=en)"
                    )


def _validate_topic_tags(items: list[_Item], *, language: Language) -> None:
    """검사 4: `topic_tags`의 모든 원소가 그 언어의 고정 집합 안에 있다."""
    allowed = ALLOWED_TOPIC_TAGS[language]
    for item in items:
        for tag in item.topic_tags or ():
            if tag not in allowed:
                raise SeedError(
                    f"{ITEMS_FILE}: seed_id '{item.seed_id}' has unknown topic_tag '{tag}' "
                    f"(language={language.value}, allowed: {', '.join(sorted(allowed))})"
                )


def _validate_frequency_rank(items: list[_Item]) -> None:
    """검사 5: `frequency_rank`가 1 이상이고 파일 안에서 유일하다.

    없는 것(`None`)은 허용한다 --- 일본어 seed에 빈도 정보가 없는 item이 있고,
    `seed_order`를 `frequency_rank`로 승격시키지 않는다는 규칙(이 모듈 docstring)이
    "빈 값"을 정상 상태로 둔다.
    """
    seen: dict[int, str] = {}
    for item in items:
        rank = item.frequency_rank
        if rank is None:
            continue
        if rank < 1:
            raise SeedError(
                f"{ITEMS_FILE}: seed_id '{item.seed_id}' has 'frequency_rank' {rank}; "
                "must be an integer >= 1"
            )
        previous = seen.get(rank)
        if previous is not None:
            raise SeedError(
                f"{ITEMS_FILE}: seed_id '{item.seed_id}' repeats 'frequency_rank' {rank} "
                f"(already used by seed_id '{previous}')"
            )
        seen[rank] = item.seed_id


def _validate_sentence_length(
    sentences: list[_Sentence], *, cfg: AppConfig, language: Language
) -> None:
    """검사 6: 문장 길이가 `content.max_sentence_length_chars[language]` 이하다.

    단위는 code point다(`str`의 길이). 상한은 언어별 맵에서 읽는다 ---
    `jobs/generate_sentence_batch.py`가 LLM 산출물에 쓰는 것과 같은 값이다.
    """
    limit: int = getattr(cfg.content.max_sentence_length_chars, language.value)
    for sentence in sentences:
        if len(sentence.text) > limit:
            raise SeedError(
                f"{SENTENCES_FILE}: seed_id '{sentence.seed_id}' text is {len(sentence.text)} "
                f"code points; exceeds content.max_sentence_length_chars.{language.value}={limit}"
            )


def _validate_tappable_count(
    sentences: list[_Sentence], *, cfg: AppConfig, language: Language
) -> None:
    """검사 7: 문장당 tappable item이 1개 이상 `learning.max_new_items_per_sentence` 이하다.

    상한의 출처는 `08_LLM_SPEC.md`의 deterministic validation 5번과 같은 config 키다.
    하한 1은 "target이 없는 문장은 가르칠 것이 없다"는 구조적 조건이다.

    **영어 전용이다.** 이 검사를 적는 문서가 `01_ENGLISH_CONTENT.md`의 `검증` 7번이고,
    거기서 "target"과 `is_tappable`을 같은 것으로 쓴다. 일본어는 둘이 갈린다 ---
    `08_LLM_SPEC.md`의 `Ready invariant와 같은 범위`와 `12_TEST_PLAN.md`가 **target이
    아닌 tappable item**을 정식으로 허용하고, Core E2E fixture
    (`backend/tests/data/seed_core_e2e/`)의 첫 문장은 그 전제 위에서 tappable을 셋
    담는다. 일본어에 같은 상한을 걸면 그 전제가 깨진다.
    """
    if language is not Language.EN:
        return
    maximum = cfg.learning.max_new_items_per_sentence
    for sentence in sentences:
        count = sum(1 for item in sentence.items if item.is_tappable)
        if count < 1 or count > maximum:
            raise SeedError(
                f"{SENTENCES_FILE}: seed_id '{sentence.seed_id}' has {count} tappable items; "
                f"must be between 1 and learning.max_new_items_per_sentence={maximum}"
            )


def _validate_normalized_hashes(
    session: Session,
    sentences: list[_Sentence],
    *,
    existing_sentence_seed_ids: set[str],
    language: Language,
) -> dict[str, str]:
    """검사 11: `normalized_hash`가 파일 안에서, 그리고 DB의 기존 문장과 겹치지 않는다.

    해시를 **적재 전에** 계산하고 그 값을 그대로 돌려준다 --- 적재 루프가 다시 계산하면
    검사한 값과 적재되는 값이 갈릴 수 있다. 정규화 규칙이 언어별이므로(ADR-024 결정 6)
    DB 대조도 같은 언어 안에서만 한다.

    이미 그 `seed_id`로 들어가 있는 문장은 대조 대상이 아니다. 아니면 같은 파일의 두 번째
    증분 실행이 자기 자신과 충돌해 멱등이 깨진다.
    """
    hashes: dict[str, str] = {}
    by_hash: dict[str, str] = {}
    for sentence in sentences:
        digest = normalized_sentence_hash(sentence.text, language.value)
        previous = by_hash.get(digest)
        if previous is not None:
            raise SeedError(
                f"{SENTENCES_FILE}: seed_id '{sentence.seed_id}' has the same normalized_hash "
                f"as seed_id '{previous}' (duplicate sentence)"
            )
        by_hash[digest] = sentence.seed_id
        hashes[sentence.seed_id] = digest

    pending = {
        digest: seed_id
        for digest, seed_id in by_hash.items()
        if seed_id not in existing_sentence_seed_ids
    }
    if pending:
        rows = session.execute(
            sa.select(Sentence.normalized_hash, Sentence.seed_id).where(
                Sentence.language == language,
                Sentence.normalized_hash.in_(list(pending)),
            )
        ).all()
        for digest, db_seed_id in rows:
            raise SeedError(
                f"{SENTENCES_FILE}: seed_id '{pending[str(digest)]}' duplicates the "
                f"normalized_hash of a sentence already in the database "
                f"(language={language.value}, seed_id={db_seed_id!r})"
            )
    return hashes


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


def _existing_item_seed_ids(session: Session) -> dict[str, int]:
    """DB에 이미 있는 `learning_items.seed_id` -> id. 증분 적재의 "이미 있다" 판정이다."""
    rows = session.execute(
        sa.select(LearningItem.seed_id, LearningItem.id).where(LearningItem.seed_id.is_not(None))
    ).all()
    return {str(seed_id): item_id for seed_id, item_id in rows}


def _existing_sentence_seed_ids(session: Session) -> set[str]:
    """DB에 이미 있는 `sentences.seed_id`. 증분 적재의 "이미 있다" 판정이다."""
    rows = session.scalars(sa.select(Sentence.seed_id).where(Sentence.seed_id.is_not(None))).all()
    return {str(seed_id) for seed_id in rows}


def _max_seed_order(session: Session, *, language: Language) -> int:
    """이 언어의 기존 `learning_items.metadata_json.seed_order` 최댓값. 없으면 0.

    증분 적재가 이어 붙이는 시작점이다(`04_DB_SPEC.md`의 `증분 적재`) --- 재사용하면
    exploration 정렬의 tie-break가 충돌한다.
    """
    rows = session.scalars(
        sa.select(LearningItem.metadata_json).where(
            LearningItem.language == language,
            LearningItem.origin == LearningItemOrigin.SEED,
        )
    ).all()
    orders = [
        value["seed_order"]
        for value in rows
        if isinstance(value, dict) and isinstance(value.get("seed_order"), int)
    ]
    return max(orders, default=0)


def load_seed(
    session: Session,
    seed_dir: Path,
    *,
    now: datetime,
    cfg: AppConfig,
    language: Language = Language.JA,
    incremental: bool = False,
) -> SeedSummary:
    """seed 디렉터리를 적재하고 요약을 돌려준다. commit은 호출자가 한다.

    `now`는 호출자(CLI 진입점)가 읽은 값이다. 여기서 시계를 읽지 않고, 이 적재로
    생기는 모든 `created_at` / `generated_at`이 **같은 순간**을 갖는다 (ADR-007).

    `cfg`는 필수다. 길이 상한과 문장당 target 상한이 정책값이며(`14_CONFIGURATION.md`)
    코드 기본값을 두지 않는다. 선택 인자로 두면 넘기지 않은 호출에서 검사가 조용히
    꺼진다.

    `incremental=False`(기본)는 빈 DB 전용이다 --- `origin = seed` 행이 하나라도 있으면
    거부한다. `incremental=True`는 파일의 `seed_id` 중 DB에 없는 것만 INSERT하고 이미
    있는 것은 건너뛴다. 기존 행은 고치지 않는다(`04_DB_SPEC.md`의 `증분 적재`).
    """
    items = _parse_items(seed_dir / ITEMS_FILE)
    sentences = _parse_sentences(seed_dir / SENTENCES_FILE, {item.seed_id for item in items})
    _validate_reading_by_language(items, sentences, language=language)
    _validate_topic_tags(items, language=language)
    _validate_frequency_rank(items)
    _validate_sentence_length(sentences, cfg=cfg, language=language)
    _validate_tappable_count(sentences, cfg=cfg, language=language)

    if incremental:
        existing_item_ids = _existing_item_seed_ids(session)
        existing_sentence_ids = _existing_sentence_seed_ids(session)
        seed_order = _max_seed_order(session, language=language)
    else:
        _reject_if_already_seeded(session)
        existing_item_ids = {}
        existing_sentence_ids = set()
        seed_order = 0

    # 해시는 적재 전 검증 단계에서 계산하고 그 값을 적재가 그대로 쓴다.
    normalized_hashes = _validate_normalized_hashes(
        session,
        sentences,
        existing_sentence_seed_ids=existing_sentence_ids,
        language=language,
    )

    spans = 0
    explanations = 0
    ruby = RubySummary()
    items_inserted = 0
    items_skipped = 0
    sentences_inserted = 0
    sentences_skipped = 0

    # 검증은 위에서 끝났지만 적재 중 DB 제약 위반이 나도 부분 적재가 남지 않게 한다.
    with session.begin_nested():
        item_ids: dict[str, int] = {}
        for item in items:
            if item.seed_id in existing_item_ids:
                # 이미 있는 item은 고치지 않는다. 문장이 가리킬 id만 가져온다.
                item_ids[item.seed_id] = existing_item_ids[item.seed_id]
                items_skipped += 1
                continue
            seed_order += 1
            metadata: dict[str, Any] = {"seed_order": seed_order}
            if item.frequency_rank is not None:
                metadata["frequency_rank"] = item.frequency_rank
            row = LearningItem(
                language=language,
                type=item.type,
                lemma=item.lemma,
                reading=item.reading,
                default_meaning=item.default_meaning,
                difficulty_label=item.difficulty_label,
                topic_tags=item.topic_tags,
                origin=LearningItemOrigin.SEED,
                seed_id=item.seed_id,
                metadata_json=metadata,
                created_at=now,
            )
            session.add(row)
            session.flush()
            item_ids[item.seed_id] = row.id
            items_inserted += 1

        for sentence in sentences:
            if sentence.seed_id in existing_sentence_ids:
                sentences_skipped += 1
                continue
            sentence_row = Sentence(
                language=language,
                text=sentence.text,
                korean_translation=sentence.korean_translation,
                source_type=SentenceSourceType.SEED,
                source_id=sentence.seed_id,
                seed_id=sentence.seed_id,
                normalized_hash=normalized_hashes[sentence.seed_id],
                status=SentenceStatus.VALIDATED,
                ruby_json=_compute_ruby_json(sentence, ruby, now=now, language=language),
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
            sentences_inserted += 1
        session.flush()

    return SeedSummary(
        items=len(items),
        sentences=len(sentences),
        spans=spans,
        explanations=explanations,
        ruby=ruby,
        items_inserted=items_inserted,
        items_skipped=items_skipped,
        sentences_inserted=sentences_inserted,
        sentences_skipped=sentences_skipped,
    )


def _compute_ruby_json(
    sentence: _Sentence, summary: RubySummary, *, now: datetime, language: Language = Language.JA
) -> dict[str, Any] | None:
    """tappable item의 span과 `explanation.reading`으로 계산한다. 실패하면 None(= 미계산).

    `language != ja`이면 계산 자체를 건너뛴다(ADR-024 결정 6) --- 영어 문장에는
    후리가나가 없고 분석기를 부르지 않는다. 이 경우는 "계산 실패"가 아니므로
    `summary`에 기록하지 않는다.

    예외를 여기서 삼키는 이유: 후리가나는 표시 보조이고 계산 실패가 적재를 막지 않는다
    (10_ERROR_HANDLING.md의 `후리가나 계산 실패`). backfill이 NULL 행을 다시 시도한다.
    불일치 보고의 식별자는 seed의 `seed_id`와 `item_seed_id`다(아직 DB id가 없다).
    """
    if language is not Language.JA:
        return None
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
        computation = compute_ruby(sentence.text, items, now=now)
    except Exception:
        summary.add_failure()
        return None
    summary.add(sentence.seed_id, computation)
    return computation.ruby_json
