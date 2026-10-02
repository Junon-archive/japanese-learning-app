"""seed loader의 적재 전 검증 (`mvp-03-english/01_ENGLISH_CONTENT.md`의 `검증`).

여기는 그 목록 중 4(`topic_tags` 고정 집합), 5(`frequency_rank`), 6(문장 길이 상한),
7(문장당 target 수), 11(`normalized_hash` 중복)만 본다. 1·2·3·8·9·10은
`test_seed_loader.py` / `test_seed_incremental.py` / `test_seed_reading_language_rule.py`가
이미 덮는다.

검사마다 **거부**와 **통과** 두 방향을 단언한다. 거부만 보면 모든 입력을 거부하는
구현도 통과한다. 상한이 있는 두 검사(6·7)는 `override_config`로 값을 바꿔 실제로
config를 읽는지도 확인한다 --- 기본값에만 기대면 숫자를 상수로 박은 구현이 통과한다.

seed 파일은 `tmp_path`에 직접 쓴다(`test_seed_incremental.py`와 같은 방식).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from sqlalchemy.orm import Session

from app.config import get_config
from app.models.enums import Language
from app.services.seed_loader import SeedError, SeedSummary, load_seed
from tests.conftest import override_config
from tests.factories import NOW


def _item(
    seed_id: str,
    *,
    lemma: str,
    reading: str | None = None,
    topic_tags: list[str] | None = None,
    frequency_rank: int | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "seed_id": seed_id,
        "type": "word",
        "lemma": lemma,
        "default_meaning": "뜻",
    }
    if reading is not None:
        result["reading"] = reading
    if topic_tags is not None:
        result["topic_tags"] = topic_tags
    if frequency_rank is not None:
        result["frequency_rank"] = frequency_rank
    return result


def _target(
    item_seed_id: str, surface_form: str, text: str, *, is_tappable: bool, reading: str | None
) -> dict[str, Any]:
    start = text.index(surface_form)
    explanation: dict[str, Any] = {
        "core_meaning": "뜻",
        "meaning_in_context": "문맥에서의 뜻",
        "nuance": "뉘앙스",
        "example_sentence": "Example.",
        "example_translation": "예문.",
    }
    if reading is not None:
        explanation["reading"] = reading
    return {
        "item_seed_id": item_seed_id,
        "surface_form": surface_form,
        "is_tappable": is_tappable,
        "spans": [
            {
                "start_codepoint": start,
                "end_codepoint": start + len(surface_form),
                "span_order": 0,
            }
        ],
        "explanation": explanation,
    }


def _sentence(
    seed_id: str,
    *,
    text: str,
    targets: list[tuple[str, str, bool]],
    reading: str | None = None,
) -> dict[str, Any]:
    return {
        "seed_id": seed_id,
        "text": text,
        "korean_translation": "번역.",
        "items": [
            _target(item_seed_id, surface_form, text, is_tappable=is_tappable, reading=reading)
            for item_seed_id, surface_form, is_tappable in targets
        ],
    }


def _write_seed_dir(
    path: Path, *, items: list[dict[str, Any]], sentences: list[dict[str, Any]]
) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "items.yaml").write_text(yaml.safe_dump(items, allow_unicode=True), encoding="utf-8")
    (path / "sentences.yaml").write_text(
        yaml.safe_dump(sentences, allow_unicode=True), encoding="utf-8"
    )
    return path


# 영어 기본 세트. `reading` 키가 없다(en 규칙).
EN_ITEMS = [_item("en_it_a", lemma="cat", frequency_rank=1)]
EN_SENTENCES = [
    _sentence("en_sn_a", text="I like cats.", targets=[("en_it_a", "cats", True)]),
]


def _load_en(session: Session, seed_dir: Path, *, incremental: bool = False) -> SeedSummary:
    return load_seed(
        session,
        seed_dir,
        now=NOW,
        cfg=get_config(),
        language=Language.EN,
        incremental=incremental,
    )


# --------------------------------------------------------------------------
# 검사 4: topic_tags 고정 집합. **영어 전용이다**(일본어 고정 집합은 명세에 없다).
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_en_tags_inside_the_fixed_set_load(tmp_path: Path, db_session: Session) -> None:
    items = [_item("en_it_a", lemma="cat", topic_tags=["phrasal-verb", "friends", "smalltalk"])]
    seed_dir = _write_seed_dir(tmp_path / "en", items=items, sentences=EN_SENTENCES)
    assert _load_en(db_session, seed_dir).items_inserted == 1


@pytest.mark.integration
def test_en_tag_outside_the_fixed_set_is_rejected(tmp_path: Path, db_session: Session) -> None:
    """영어는 `grammar`를 쓰지 않는다 --- 그 성격은 `type = grammar`가 이미 표현한다."""
    items = [_item("en_it_a", lemma="cat", topic_tags=["daily", "grammar"])]
    seed_dir = _write_seed_dir(tmp_path / "en_bad", items=items, sentences=EN_SENTENCES)
    with pytest.raises(SeedError, match=r"en_it_a.*unknown topic_tag 'grammar'"):
        _load_en(db_session, seed_dir)


@pytest.mark.integration
def test_the_fixed_set_is_not_enforced_on_japanese(tmp_path: Path, db_session: Session) -> None:
    """**검사 4는 영어 전용이다.** 일본어는 어떤 태그든 통과한다.

    고정 집합 표는 `01_ENGLISH_CONTENT.md`(영어 콘텐츠 기준 문서)의 것이고 같은 절이 "태그는
    두 언어가 공유하지 않는다"고 적는다. 일본어의 고정 집합은 **어느 명세에도 없으므로**,
    일본어에 집합을 강제하면 명세 근거 없는 정책값이 코드에 박히고 앞으로 일본어 seed에 새
    태그를 쓸 때 거부된다. 그래서 걸지 않는다(scope-guard 게이트의 판단 요청으로 정리했다).

    일본어용 고정 집합이 필요해지면 명세 결정이 먼저다(`updates/backlog.md`).
    """
    ja_sentences = [
        _sentence("sn_a", text="猫が好きです。", targets=[("it_a", "猫", True)], reading="ねこ")
    ]
    # 일본어 seed에 실제로 있는 태그(`grammar`)와 영어 고정 집합의 태그(`friends`)와
    # 어느 쪽에도 없는 새 태그를 한꺼번에 넣어도 적재된다.
    seed_dir = _write_seed_dir(
        tmp_path / "ja",
        items=[
            _item(
                "it_a",
                lemma="猫",
                reading="ねこ",
                topic_tags=["grammar", "friends", "brand-new-tag"],
            )
        ],
        sentences=ja_sentences,
    )
    summary = load_seed(db_session, seed_dir, now=NOW, cfg=get_config(), language=Language.JA)
    assert summary.items_inserted == 1


# --------------------------------------------------------------------------
# 검사 5: frequency_rank는 1 이상이고 파일 안에서 유일하다. 없는 것은 허용한다.
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_distinct_and_absent_frequency_ranks_load(tmp_path: Path, db_session: Session) -> None:
    items = [
        _item("en_it_a", lemma="cat", frequency_rank=1),
        _item("en_it_b", lemma="dog", frequency_rank=2),
        _item("en_it_c", lemma="bird"),  # 없어도 된다. seed_order를 승격시키지 않는다.
    ]
    seed_dir = _write_seed_dir(tmp_path / "en", items=items, sentences=EN_SENTENCES)
    assert _load_en(db_session, seed_dir).items_inserted == 3


@pytest.mark.integration
@pytest.mark.parametrize("rank", [0, -3])
def test_frequency_rank_below_one_is_rejected(
    tmp_path: Path, db_session: Session, rank: int
) -> None:
    items = [_item("en_it_a", lemma="cat", frequency_rank=rank)]
    seed_dir = _write_seed_dir(tmp_path / f"en_{rank}", items=items, sentences=EN_SENTENCES)
    with pytest.raises(SeedError, match=r"en_it_a.*frequency_rank"):
        _load_en(db_session, seed_dir)


@pytest.mark.integration
def test_duplicate_frequency_rank_in_the_file_is_rejected(
    tmp_path: Path, db_session: Session
) -> None:
    items = [
        _item("en_it_a", lemma="cat", frequency_rank=7),
        _item("en_it_b", lemma="dog", frequency_rank=7),
    ]
    seed_dir = _write_seed_dir(tmp_path / "en_bad", items=items, sentences=EN_SENTENCES)
    with pytest.raises(SeedError, match=r"en_it_b.*already used by seed_id 'en_it_a'"):
        _load_en(db_session, seed_dir)


# --------------------------------------------------------------------------
# 검사 6: 문장 길이 상한 content.max_sentence_length_chars[language]
# --------------------------------------------------------------------------


def _text_of_length(length: int) -> str:
    # "cats"를 target으로 쓸 수 있게 앞에 두고 뒤를 채운다.
    return "cats " + "a" * (length - 5)


@pytest.mark.integration
def test_a_sentence_at_the_language_limit_loads(tmp_path: Path, db_session: Session) -> None:
    limit = get_config().content.max_sentence_length_chars.en
    text = _text_of_length(limit)
    sentences = [_sentence("en_sn_a", text=text, targets=[("en_it_a", "cats", True)])]
    seed_dir = _write_seed_dir(tmp_path / "en", items=EN_ITEMS, sentences=sentences)
    assert _load_en(db_session, seed_dir).sentences_inserted == 1


@pytest.mark.integration
def test_a_sentence_over_the_language_limit_is_rejected(
    tmp_path: Path, db_session: Session
) -> None:
    limit = get_config().content.max_sentence_length_chars.en
    text = _text_of_length(limit + 1)
    sentences = [_sentence("en_sn_a", text=text, targets=[("en_it_a", "cats", True)])]
    seed_dir = _write_seed_dir(tmp_path / "en_bad", items=EN_ITEMS, sentences=sentences)
    with pytest.raises(SeedError, match=r"en_sn_a.*max_sentence_length_chars.en"):
        _load_en(db_session, seed_dir)


@pytest.mark.integration
def test_the_length_limit_comes_from_config(tmp_path: Path, db_session: Session) -> None:
    """기본 상한을 지키는 문장도 config를 낮추면 거부된다(상수가 아니라 config를 읽는다)."""
    seed_dir = _write_seed_dir(tmp_path / "en", items=EN_ITEMS, sentences=EN_SENTENCES)
    cfg = override_config(
        get_config(),
        content={"max_sentence_length_chars": {"ja": 60, "en": len("I like cats.") - 1}},
    )
    with pytest.raises(SeedError, match=r"en_sn_a.*max_sentence_length_chars.en"):
        load_seed(db_session, seed_dir, now=NOW, cfg=cfg, language=Language.EN)


# --------------------------------------------------------------------------
# 검사 7: 문장당 target(is_tappable)이 1개 이상 max_new_items_per_sentence 이하.
# 영어 전용이다 --- 일본어는 target과 tappable이 갈린다(아래 마지막 테스트).
# --------------------------------------------------------------------------


MULTI_TARGET_ITEMS = [
    _item("en_it_a", lemma="cat", frequency_rank=1),
    _item("en_it_b", lemma="dog", frequency_rank=2),
    _item("en_it_c", lemma="bird", frequency_rank=3),
]
MULTI_TARGET_TEXT = "cats dogs birds"


def _multi_target_sentences(tappable: int) -> list[dict[str, Any]]:
    targets = [
        ("en_it_a", "cats", tappable >= 1),
        ("en_it_b", "dogs", tappable >= 2),
        ("en_it_c", "birds", tappable >= 3),
    ]
    return [_sentence("en_sn_a", text=MULTI_TARGET_TEXT, targets=targets)]


@pytest.mark.integration
def test_two_tappable_items_load(tmp_path: Path, db_session: Session) -> None:
    assert get_config().learning.max_new_items_per_sentence == 2
    seed_dir = _write_seed_dir(
        tmp_path / "en", items=MULTI_TARGET_ITEMS, sentences=_multi_target_sentences(2)
    )
    assert _load_en(db_session, seed_dir).sentences_inserted == 1


@pytest.mark.integration
@pytest.mark.parametrize("tappable", [0, 3])
def test_tappable_count_outside_the_allowed_range_is_rejected(
    tmp_path: Path, db_session: Session, tappable: int
) -> None:
    seed_dir = _write_seed_dir(
        tmp_path / f"en_{tappable}",
        items=MULTI_TARGET_ITEMS,
        sentences=_multi_target_sentences(tappable),
    )
    with pytest.raises(SeedError, match=rf"en_sn_a' has {tappable} tappable items"):
        _load_en(db_session, seed_dir)


@pytest.mark.integration
def test_the_tappable_upper_bound_comes_from_config(tmp_path: Path, db_session: Session) -> None:
    """target 2개는 기본 설정에서 통과하지만 상한을 1로 낮추면 거부된다."""
    seed_dir = _write_seed_dir(
        tmp_path / "en", items=MULTI_TARGET_ITEMS, sentences=_multi_target_sentences(2)
    )
    cfg = override_config(
        get_config(),
        learning={"preferred_new_items_per_sentence": 1, "max_new_items_per_sentence": 1},
    )
    with pytest.raises(SeedError, match=r"max_new_items_per_sentence=1"):
        load_seed(db_session, seed_dir, now=NOW, cfg=cfg, language=Language.EN)


@pytest.mark.integration
def test_a_japanese_sentence_may_carry_non_target_tappable_items(
    tmp_path: Path, db_session: Session
) -> None:
    """일본어는 tappable 수에 이 상한을 걸지 않는다.

    `08_LLM_SPEC.md`의 `Ready invariant와 같은 범위`와 `12_TEST_PLAN.md`가 **target이
    아닌 tappable item**을 정식으로 허용하고, Core E2E fixture의 첫 문장
    (`seed_core_e2e/sentences.yaml`의 `sn_0001`)이 그 전제로 tappable을 셋 담는다.
    영어 상한을 일본어까지 끌고 가면 그 fixture가 적재되지 않는다.
    """
    text = "この仕事を田中さんに任せてもいい。"
    items = [
        _item("it_a", lemma="仕事", reading="しごと"),
        _item("it_b", lemma="任せる", reading="まかせる"),
        _item("it_c", lemma="てもいい", reading="てもいい"),
    ]
    sentences = [
        _sentence(
            "sn_a",
            text=text,
            targets=[("it_a", "仕事", True), ("it_b", "任せ", True), ("it_c", "てもいい", True)],
            reading="よみ",
        )
    ]
    seed_dir = _write_seed_dir(tmp_path / "ja", items=items, sentences=sentences)
    summary = load_seed(db_session, seed_dir, now=NOW, cfg=get_config(), language=Language.JA)
    assert summary.sentences_inserted == 1


# --------------------------------------------------------------------------
# 검사 11: normalized_hash가 파일 안에서, 그리고 DB의 기존 문장과 겹치지 않는다
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_different_sentences_in_one_file_load(tmp_path: Path, db_session: Session) -> None:
    sentences = [
        _sentence("en_sn_a", text="I like cats.", targets=[("en_it_a", "cats", True)]),
        _sentence("en_sn_b", text="Those cats are loud.", targets=[("en_it_a", "cats", True)]),
    ]
    seed_dir = _write_seed_dir(tmp_path / "en", items=EN_ITEMS, sentences=sentences)
    assert _load_en(db_session, seed_dir).sentences_inserted == 2


@pytest.mark.integration
def test_duplicate_normalized_hash_inside_the_file_is_rejected(
    tmp_path: Path, db_session: Session
) -> None:
    """en 정규화는 casefold + 공백 접기다. 대소문자만 다른 두 문장은 같은 문장이다."""
    sentences = [
        _sentence("en_sn_a", text="I like cats.", targets=[("en_it_a", "cats", True)]),
        _sentence("en_sn_b", text="i  like CATS.", targets=[("en_it_a", "CATS", True)]),
    ]
    seed_dir = _write_seed_dir(tmp_path / "en_bad", items=EN_ITEMS, sentences=sentences)
    with pytest.raises(SeedError, match=r"en_sn_b.*same normalized_hash as seed_id 'en_sn_a'"):
        _load_en(db_session, seed_dir)


@pytest.mark.integration
def test_duplicate_normalized_hash_against_the_database_is_rejected(
    tmp_path: Path, db_session: Session
) -> None:
    round1 = _write_seed_dir(tmp_path / "round1", items=EN_ITEMS, sentences=EN_SENTENCES)
    _load_en(db_session, round1, incremental=True)

    # 다른 seed_id, 대소문자만 다른 같은 문장.
    sentences = [_sentence("en_sn_b", text="I LIKE CATS.", targets=[("en_it_a", "CATS", True)])]
    round2 = _write_seed_dir(tmp_path / "round2", items=EN_ITEMS, sentences=sentences)
    with pytest.raises(SeedError, match=r"en_sn_b.*already in the database"):
        _load_en(db_session, round2, incremental=True)


@pytest.mark.integration
def test_the_hash_check_does_not_break_incremental_idempotency(
    tmp_path: Path, db_session: Session
) -> None:
    """이미 그 seed_id로 들어간 문장은 자기 자신과 충돌하지 않는다 (합격 기준 17번)."""
    seed_dir = _write_seed_dir(tmp_path / "en", items=EN_ITEMS, sentences=EN_SENTENCES)
    _load_en(db_session, seed_dir, incremental=True)

    summary = _load_en(db_session, seed_dir, incremental=True)
    assert (summary.sentences_inserted, summary.sentences_skipped) == (0, 1)


@pytest.mark.integration
def test_a_japanese_sentence_does_not_collide_with_an_english_one(
    tmp_path: Path, db_session: Session
) -> None:
    """DB 대조는 같은 언어 안에서만 한다(정규화 규칙이 언어별이다)."""
    en_dir = _write_seed_dir(tmp_path / "en", items=EN_ITEMS, sentences=EN_SENTENCES)
    _load_en(db_session, en_dir, incremental=True)

    ja_dir = _write_seed_dir(
        tmp_path / "ja",
        items=[_item("it_a", lemma="猫", reading="ねこ")],
        sentences=[
            _sentence("sn_a", text="I like cats.", targets=[("it_a", "cats", True)], reading="ねこ")
        ],
    )
    summary = load_seed(
        db_session, ja_dir, now=NOW, cfg=get_config(), language=Language.JA, incremental=True
    )
    assert summary.sentences_inserted == 1
