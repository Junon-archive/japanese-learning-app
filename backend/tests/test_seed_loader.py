"""seed loader (04_DB_SPEC.md Seed Data, 06_LEARNING_ENGINE.md seed_order).

DB를 쓰는 적재 테스트에만 `integration` 마커를 붙인다. 파일 전체에 걸면 아래의
순수 `_validate_spans` 테스트가 `make test-unit`에서 조용히 사라진다.

fixture는 `backend/tests/data/`에 따로 둔다. repo 루트의 `seed/`는 실 데이터이며
나중에 통째로 교체될 수 있으므로 단정의 근거로 삼지 않는다. 다만 마지막 테스트가
그 디렉터리도 한 번 적재해 포맷 오류를 조기에 잡는다.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.models.content import (
    LearningItem,
    Sentence,
    SentenceItem,
    SentenceItemExplanation,
    SentenceItemSpan,
)
from app.models.enums import LearningItemOrigin, SentenceSourceType
from app.services.seed_loader import SeedError, _Span, _validate_spans, load_seed
from tests.factories import NOW

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(__file__).resolve().parent / "data"
SEED_MIN = DATA_DIR / "seed_min"
REAL_SEED_DIR = REPO_ROOT / "seed"


def _items_by_lemma(session: Session) -> dict[str, LearningItem]:
    rows = session.scalars(sa.select(LearningItem)).all()
    return {row.lemma: row for row in rows}


def _count(session: Session, model: type) -> int:
    return session.scalar(sa.select(sa.func.count()).select_from(model)) or 0


@pytest.mark.integration
def test_loads_min_fixture_with_seed_origin_and_metadata(db_session: Session) -> None:
    summary = load_seed(db_session, SEED_MIN, now=NOW)

    assert (summary.items, summary.sentences, summary.spans, summary.explanations) == (3, 2, 4, 3)

    items = _items_by_lemma(db_session)
    assert all(item.origin is LearningItemOrigin.SEED for item in items.values())
    assert items["任せる"].metadata_json == {"seed_order": 1, "frequency_rank": 120}

    sentence = db_session.scalars(
        sa.select(Sentence).where(Sentence.source_id == "sn_min_0001")
    ).one()
    assert sentence.source_type is SentenceSourceType.SEED
    assert sentence.normalized_hash


@pytest.mark.integration
def test_seed_order_starts_at_one_and_follows_file_row_order(db_session: Session) -> None:
    """값은 1부터 1씩, 순서는 파일 내 행 순서다(06_LEARNING_ENGINE.md)."""
    load_seed(db_session, SEED_MIN, now=NOW)

    items = _items_by_lemma(db_session)
    orders = [items[lemma].metadata_json["seed_order"] for lemma in ("任せる", "仕事", "気が乗る")]
    assert orders == [1, 2, 3]


@pytest.mark.integration
def test_missing_frequency_rank_is_not_promoted_from_seed_order(db_session: Session) -> None:
    """seed_order를 frequency_rank로 승격시키지 않는다. 둘은 다른 척도다."""
    load_seed(db_session, SEED_MIN, now=NOW)

    metadata = _items_by_lemma(db_session)["仕事"].metadata_json
    assert metadata == {"seed_order": 2}


@pytest.mark.integration
def test_discontinuous_spans_are_stored_in_order(db_session: Session) -> None:
    load_seed(db_session, SEED_MIN, now=NOW)

    sentence = db_session.scalars(
        sa.select(Sentence).where(Sentence.source_id == "sn_min_0002")
    ).one()
    sentence_item = db_session.scalars(
        sa.select(SentenceItem).where(SentenceItem.sentence_id == sentence.id)
    ).one()
    spans = db_session.scalars(
        sa.select(SentenceItemSpan)
        .where(SentenceItemSpan.sentence_item_id == sentence_item.id)
        .order_by(SentenceItemSpan.span_order)
    ).all()

    covered = "".join(
        sentence.japanese[span.start_codepoint : span.end_codepoint] for span in spans
    )
    assert covered == sentence_item.surface_form


@pytest.mark.integration
def test_span_offset_mismatch_fails_and_leaves_nothing_behind(db_session: Session) -> None:
    with pytest.raises(SeedError, match="surface_form"):
        load_seed(db_session, DATA_DIR / "seed_bad_span", now=NOW)

    assert _count(db_session, LearningItem) == 0
    assert _count(db_session, Sentence) == 0
    assert _count(db_session, SentenceItem) == 0
    assert _count(db_session, SentenceItemSpan) == 0
    assert _count(db_session, SentenceItemExplanation) == 0


@pytest.mark.integration
def test_item_without_explanation_is_rejected(db_session: Session) -> None:
    """explanation이 없으면 tap 시 보여줄 데이터가 없다(불변식 6)."""
    with pytest.raises(SeedError, match="explanation"):
        load_seed(db_session, DATA_DIR / "seed_no_explanation", now=NOW)

    assert _count(db_session, LearningItem) == 0
    assert _count(db_session, Sentence) == 0


@pytest.mark.integration
def test_reloading_into_a_seeded_database_is_rejected(db_session: Session) -> None:
    load_seed(db_session, SEED_MIN, now=NOW)

    with pytest.raises(SeedError, match="db-reset"):
        load_seed(db_session, SEED_MIN, now=NOW)

    assert _count(db_session, LearningItem) == 3


@pytest.mark.integration
def test_missing_seed_directory_is_reported(db_session: Session, tmp_path: Path) -> None:
    with pytest.raises(SeedError, match="seed file not found"):
        load_seed(db_session, tmp_path, now=NOW)


@pytest.mark.integration
def test_real_seed_directory_loads(db_session: Session) -> None:
    """`seed/`의 포맷 오류를 여기서 잡는다. 건수는 단정하지 않는다."""
    summary = load_seed(db_session, REAL_SEED_DIR, now=NOW)

    assert summary.items > 0
    assert summary.sentences > 0
    # 모든 sentence item은 explanation을 하나씩 가진다.
    assert summary.explanations == _count(db_session, SentenceItem)


# --------------------------------------------------------------------------
# span offset 검증 (`_validate_spans`)
#
# 이 아래 테스트들은 DB를 쓰지 않는다(그래서 integration 마커도 없다).
# 각 테스트는 `_validate_spans`의 **특정 검사 한 줄을 지우면 빨개지도록** 짰다.
# --------------------------------------------------------------------------

SENTENCE = "仕事を任せる。"  # 7 code points: 仕 事 を 任 せ る 。


def _spans(*triples: tuple[int, int, int]) -> tuple[_Span, ...]:
    return tuple(
        _Span(start_codepoint=start, end_codepoint=end, span_order=order)
        for start, end, order in triples
    )


def test_span_order_must_be_zero_based_and_contiguous() -> None:
    """span_order 검사를 지우면 빨개진다.

    offset과 surface_form은 서로 맞으므로 span_order 검사만이 유일한 거부 사유다.
    """
    with pytest.raises(SeedError, match="span_order"):
        _validate_spans(SENTENCE, "仕事", _spans((0, 2, 1)), "where")


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
def test_span_offsets_outside_the_sentence_are_rejected(
    start: int, end: int, surface_form: str
) -> None:
    with pytest.raises(SeedError, match="out of range"):
        _validate_spans(SENTENCE, surface_form, _spans((start, end, 0)), "where")


def test_sentence_with_a_lone_surrogate_is_rejected() -> None:
    """lone surrogate 검사를 지우면 빨개진다.

    span은 문장과 정합하므로 그 검사가 사라지면 아무 예외도 나지 않는다.
    lone surrogate는 offset이 code point가 아니라 UTF-16 code unit이라는 신호다.
    """
    japanese = "仕事\ud800を任せる。"
    with pytest.raises(SeedError, match="lone surrogate"):
        _validate_spans(japanese, "仕事", _spans((0, 2, 0)), "where")


def test_overlapping_spans_are_rejected() -> None:
    """overlap 검사를 지우면 빨개진다.

    두 span이 `事`를 공유해도 이어붙인 결과가 surface_form과 같아서 다른 검사는
    전부 통과한다. 12_TEST_PLAN.md의 Unit 항목이 요구하는 거부다.
    """
    with pytest.raises(SeedError, match="overlap"):
        _validate_spans(SENTENCE, "仕事事を", _spans((0, 2, 0), (1, 3, 1)), "where")


def test_discontinuous_spans_are_allowed() -> None:
    """떨어져 있는(disjoint) span은 정상이다. 불연속 표현이 이 형태다.

    overlap 거부가 "붙어 있지 않으면 거부"로 과잉 구현되면 빨개진다.
    """
    _validate_spans("気が全然乗らない。", "気が乗らない", _spans((0, 2, 0), (4, 8, 1)), "where")
