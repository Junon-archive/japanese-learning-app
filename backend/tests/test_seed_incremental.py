"""증분 적재 (`04_DB_SPEC.md`의 `증분 적재 (MVP-03 확정)`, ADR-023 결정 4).

`backend/tests/test_seed_loader.py`는 기본(비-incremental) 모드를 이미 덮는다. 여기는
`--incremental`만 본다. seed 파일은 `tmp_path`에 직접 써서 "파일이 자라난" 시나리오
(round 1 -> round 2)를 만든다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
import yaml
from sqlalchemy.orm import Session

from app.models.content import LearningItem, Sentence
from app.models.enums import Language, LearningItemOrigin
from app.services.seed_loader import load_seed
from tests.factories import NOW


def _explanation(reading: str | None, *, meaning: str = "뜻") -> dict[str, Any]:
    result: dict[str, Any] = {
        "core_meaning": meaning,
        "meaning_in_context": f"{meaning} (문맥)",
        "nuance": "뉘앙스",
        "example_sentence": "例文です。",
        "example_translation": "예문입니다.",
    }
    if reading is not None:
        result["reading"] = reading
    return result


def _item(seed_id: str, *, lemma: str, reading: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "seed_id": seed_id,
        "type": "word",
        "lemma": lemma,
        "default_meaning": "뜻",
    }
    if reading is not None:
        result["reading"] = reading
    return result


def _sentence(
    seed_id: str, *, text: str, item_seed_id: str, surface_form: str, reading: str | None = None
) -> dict[str, Any]:
    return {
        "seed_id": seed_id,
        "text": text,
        "korean_translation": "번역.",
        "items": [
            {
                "item_seed_id": item_seed_id,
                "surface_form": surface_form,
                "is_tappable": True,
                "spans": [
                    {
                        "start_codepoint": text.index(surface_form),
                        "end_codepoint": text.index(surface_form) + len(surface_form),
                        "span_order": 0,
                    }
                ],
                "explanation": _explanation(reading),
            }
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


ROUND1_ITEMS = [
    _item("it_a", lemma="猫", reading="ねこ"),
    _item("it_b", lemma="犬", reading="いぬ"),
]
ROUND1_SENTENCES = [
    _sentence(
        "sn_a", text="猫が好きです。", item_seed_id="it_a", surface_form="猫", reading="ねこ"
    ),
    _sentence(
        "sn_b", text="犬が好きです。", item_seed_id="it_b", surface_form="犬", reading="いぬ"
    ),
]

# round 2: round 1과 같은 item/sentence를 그대로 두고(it_a의 lemma만 바꿔서 "고치지 않는다"를
# 검증한다) 새 item(it_c)과 그걸 가리키는 새 sentence(sn_c)를 끝에 붙인다.
ROUND2_ITEMS = [
    _item("it_a", lemma="猫さん", reading="ねこ"),  # lemma를 바꿔봤다. DB는 그대로여야 한다.
    _item("it_b", lemma="犬", reading="いぬ"),
    _item("it_c", lemma="鳥", reading="とり"),
]
ROUND2_SENTENCES = [
    *ROUND1_SENTENCES,
    _sentence(
        "sn_c", text="鳥が好きです。", item_seed_id="it_c", surface_form="鳥", reading="とり"
    ),
]


def _item_by_seed_id(session: Session, seed_id: str) -> LearningItem:
    return session.scalars(sa.select(LearningItem).where(LearningItem.seed_id == seed_id)).one()


def _sentence_by_seed_id(session: Session, seed_id: str) -> Sentence:
    return session.scalars(sa.select(Sentence).where(Sentence.seed_id == seed_id)).one()


def _count(session: Session, model: type) -> int:
    return session.scalar(sa.select(sa.func.count()).select_from(model)) or 0


# --------------------------------------------------------------------------
# 기본 모드는 그대로다
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_default_mode_still_rejects_a_reload(tmp_path: Path, db_session: Session) -> None:
    seed_dir = _write_seed_dir(tmp_path / "round1", items=ROUND1_ITEMS, sentences=ROUND1_SENTENCES)
    load_seed(db_session, seed_dir, now=NOW)

    with pytest.raises(Exception, match="db-reset"):
        load_seed(db_session, seed_dir, now=NOW)


# --------------------------------------------------------------------------
# --incremental: 새 seed_id만 넣고 기존 행은 고치지 않는다
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_incremental_inserts_only_new_seed_ids_and_does_not_touch_existing_rows(
    tmp_path: Path, db_session: Session
) -> None:
    round1 = _write_seed_dir(tmp_path / "round1", items=ROUND1_ITEMS, sentences=ROUND1_SENTENCES)
    load_seed(db_session, round1, now=NOW, incremental=True)

    round2 = _write_seed_dir(tmp_path / "round2", items=ROUND2_ITEMS, sentences=ROUND2_SENTENCES)
    summary = load_seed(db_session, round2, now=NOW, incremental=True)

    assert summary.items_inserted == 1
    assert summary.items_skipped == 2
    assert summary.sentences_inserted == 1
    assert summary.sentences_skipped == 2

    # 이미 있던 it_a는 고치지 않는다. round2가 lemma를 바꿔도 DB는 그대로다.
    assert _item_by_seed_id(db_session, "it_a").lemma == "猫"
    # 새 item은 들어온다.
    new_item = _item_by_seed_id(db_session, "it_c")
    assert new_item.lemma == "鳥"
    assert new_item.origin is LearningItemOrigin.SEED

    new_sentence = _sentence_by_seed_id(db_session, "sn_c")
    assert new_sentence.text == "鳥が好きです。"


@pytest.mark.integration
def test_a_sentence_can_reference_an_item_inserted_in_the_same_incremental_run(
    tmp_path: Path, db_session: Session
) -> None:
    """item -> sentence 순서: 문장이 같은 실행에서 방금 넣은 item을 참조할 수 있다."""
    round1 = _write_seed_dir(tmp_path / "round1", items=ROUND1_ITEMS, sentences=ROUND1_SENTENCES)
    load_seed(db_session, round1, now=NOW, incremental=True)

    round2 = _write_seed_dir(tmp_path / "round2", items=ROUND2_ITEMS, sentences=ROUND2_SENTENCES)
    load_seed(db_session, round2, now=NOW, incremental=True)

    new_item = _item_by_seed_id(db_session, "it_c")
    new_sentence = _sentence_by_seed_id(db_session, "sn_c")
    linked_item_id = db_session.execute(
        sa.text("SELECT learning_item_id FROM sentence_items WHERE sentence_id = :sid"),
        {"sid": new_sentence.id},
    ).scalar_one()
    assert linked_item_id == new_item.id


# --------------------------------------------------------------------------
# seed_order는 그 언어의 기존 최대값 다음부터 이어 붙인다
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_seed_order_continues_from_the_existing_maximum_and_is_not_reused(
    tmp_path: Path, db_session: Session
) -> None:
    round1 = _write_seed_dir(tmp_path / "round1", items=ROUND1_ITEMS, sentences=ROUND1_SENTENCES)
    load_seed(db_session, round1, now=NOW, incremental=True)
    assert _item_by_seed_id(db_session, "it_a").metadata_json["seed_order"] == 1
    assert _item_by_seed_id(db_session, "it_b").metadata_json["seed_order"] == 2

    round2 = _write_seed_dir(tmp_path / "round2", items=ROUND2_ITEMS, sentences=ROUND2_SENTENCES)
    load_seed(db_session, round2, now=NOW, incremental=True)

    # it_a/it_b는 그대로 1, 2다(고치지 않는다). 새 it_c는 3을 이어받는다(round2 파일 안에서의
    # 위치인 3이 아니라 "기존 최대값 다음"이라는 규칙과 우연히 같은 값이지만, 아래
    # 재배치 테스트가 둘을 가른다).
    assert _item_by_seed_id(db_session, "it_a").metadata_json["seed_order"] == 1
    assert _item_by_seed_id(db_session, "it_b").metadata_json["seed_order"] == 2
    assert _item_by_seed_id(db_session, "it_c").metadata_json["seed_order"] == 3


@pytest.mark.integration
def test_seed_order_is_not_the_new_items_position_in_the_file(
    tmp_path: Path, db_session: Session
) -> None:
    """새 item이 파일 맨 앞에 있어도 seed_order는 "기존 최대값 다음"이다. 파일 내 위치가 아니다."""
    round1 = _write_seed_dir(tmp_path / "round1", items=ROUND1_ITEMS, sentences=ROUND1_SENTENCES)
    load_seed(db_session, round1, now=NOW, incremental=True)

    # it_c를 파일 맨 앞에 둔다. 파일 내 위치(1번째)를 그대로 쓰면 seed_order=1이 되어
    # 기존 it_a(seed_order=1)와 충돌한다.
    reordered_items = [
        _item("it_c", lemma="鳥", reading="とり"),
        _item("it_a", lemma="猫", reading="ねこ"),
        _item("it_b", lemma="犬", reading="いぬ"),
    ]
    round2 = _write_seed_dir(tmp_path / "round2", items=reordered_items, sentences=ROUND1_SENTENCES)
    load_seed(db_session, round2, now=NOW, incremental=True)

    assert _item_by_seed_id(db_session, "it_c").metadata_json["seed_order"] == 3


@pytest.mark.integration
def test_seed_order_is_scoped_per_language(tmp_path: Path, db_session: Session) -> None:
    """다른 언어의 기존 최대값은 이 언어의 이어 붙이기에 영향을 주지 않는다.

    영어 item의 `reading`은 nullable이고(ADR-023 결정 3), `en`은 아예 `reading`
    키가 없어야 한다. 여기서는 언어별 `seed_order` 분리만 확인하면 되므로 `reading`을
    생략한다.
    """
    ja_dir = _write_seed_dir(tmp_path / "ja", items=ROUND1_ITEMS, sentences=ROUND1_SENTENCES)
    load_seed(db_session, ja_dir, now=NOW, language=Language.JA, incremental=True)

    en_items = [_item("en_it_a", lemma="cat")]
    en_sentences = [
        _sentence(
            "en_sn_a",
            text="I like cats.",
            item_seed_id="en_it_a",
            surface_form="cats",
        )
    ]
    en_dir = _write_seed_dir(tmp_path / "en", items=en_items, sentences=en_sentences)
    load_seed(db_session, en_dir, now=NOW, language=Language.EN, incremental=True)

    assert _item_by_seed_id(db_session, "en_it_a").metadata_json["seed_order"] == 1
    # ja 쪽 item의 번호는 영어 적재로 바뀌지 않는다.
    assert _item_by_seed_id(db_session, "it_a").metadata_json["seed_order"] == 1
    assert _item_by_seed_id(db_session, "it_b").metadata_json["seed_order"] == 2


# --------------------------------------------------------------------------
# 원자성: 하나라도 실패하면 전부 롤백
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_a_failure_rolls_back_the_entire_incremental_batch(
    tmp_path: Path, db_session: Session
) -> None:
    """새 item(it_c)과, explanation이 빠진 새 문장을 같은 파일에 둔다.

    문장 쪽 검증이 실패하면 **같은 호출에서 넣으려던 새 item(it_c)도** 남지 않아야
    한다 --- item을 먼저 넣고 문장을 나중에 검증하는 것이 아니라, 파일 전체를
    검증한 뒤에야 쓰기 시작한다(한 트랜잭션, 부분 적재 없음).
    """
    round1 = _write_seed_dir(tmp_path / "round1", items=ROUND1_ITEMS, sentences=ROUND1_SENTENCES)
    load_seed(db_session, round1, now=NOW, incremental=True)

    broken_sentence = _sentence(
        "sn_broken", text="鳥が好きです。", item_seed_id="it_c", surface_form="鳥", reading="とり"
    )
    del broken_sentence["items"][0]["explanation"]

    broken_items = [*ROUND1_ITEMS, _item("it_c", lemma="鳥", reading="とり")]
    broken_dir = _write_seed_dir(
        tmp_path / "broken", items=broken_items, sentences=[broken_sentence]
    )

    with pytest.raises(Exception, match="explanation"):
        load_seed(db_session, broken_dir, now=NOW, incremental=True)

    # it_c는 이 실패한 호출 안에서만 새로 생기려던 것이었다. 전혀 남지 않아야 한다.
    assert _count(db_session, LearningItem) == 2
    assert (
        db_session.scalar(
            sa.select(sa.func.count())
            .select_from(LearningItem)
            .where(LearningItem.seed_id == "it_c")
        )
        == 0
    )


# --------------------------------------------------------------------------
# 멱등: 두 번째 실행은 0건
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_the_second_incremental_run_with_the_same_file_inserts_nothing(
    tmp_path: Path, db_session: Session
) -> None:
    round1 = _write_seed_dir(tmp_path / "round1", items=ROUND1_ITEMS, sentences=ROUND1_SENTENCES)
    load_seed(db_session, round1, now=NOW, incremental=True)

    summary = load_seed(db_session, round1, now=NOW, incremental=True)

    assert (summary.items_inserted, summary.sentences_inserted) == (0, 0)
    assert (summary.items_skipped, summary.sentences_skipped) == (2, 2)


# --------------------------------------------------------------------------
# user_sentence_candidates를 만들지 않는다
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_incremental_does_not_create_candidates(tmp_path: Path, db_session: Session) -> None:
    round1 = _write_seed_dir(tmp_path / "round1", items=ROUND1_ITEMS, sentences=ROUND1_SENTENCES)
    load_seed(db_session, round1, now=NOW, incremental=True)

    count = db_session.execute(
        sa.text("SELECT count(*) FROM user_sentence_candidates")
    ).scalar_one()
    assert count == 0
