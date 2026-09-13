"""seed loader (04_DB_SPEC.md Seed Data, 06_LEARNING_ENGINE.md seed_order).

DB를 쓰는 적재 테스트에만 `integration` 마커를 붙인다.

item 단위 span 검증(`validate_item_spans`) 자체의 테스트는 `test_render.py`에 있다.
여기서는 seed 파일이 그 검증과 **문장 단위** overlap 검증을 실제로 통과/거부하는지만
본다.

fixture는 `backend/tests/data/`에 따로 둔다. repo 루트의 `seed/`는 실 데이터이며
나중에 통째로 교체될 수 있으므로 단정의 근거로 삼지 않는다. 다만 마지막 테스트가
그 디렉터리도 한 번 적재해 포맷 오류를 조기에 잡는다.
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Never

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker

from app.db import get_engine
from app.furigana import CORRECTION_RULES, RubyComputation, RubyItem, compute_ruby
from app.models.content import (
    LearningItem,
    Sentence,
    SentenceItem,
    SentenceItemExplanation,
    SentenceItemSpan,
)
from app.models.enums import LearningItemOrigin, SentenceSourceType
from app.normalization import normalized_sentence_hash
from app.render import ItemSpan
from app.services import seed_loader
from app.services.seed_loader import SeedError, load_seed
from app.settings import get_settings
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
# 문장 단위 tappable overlap (08_LLM_SPEC.md validation 8번)
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_tappable_spans_of_different_items_may_not_overlap(db_session: Session) -> None:
    """item 단위 검증은 통과하지만 문장 단위 검증이 거부한다.

    fixture의 두 item은 각각 span이 하나뿐이라 item 안에서는 겹칠 수가 없다.
    문장의 tappable span을 한 번에 보는 검사를 지우면 이 적재가 성공하고 빨개진다.
    같은 code point가 두 tap 대상에 속하면 사용자가 무엇을 tap했는지 정해지지 않는다.
    """
    with pytest.raises(SeedError, match="overlap"):
        load_seed(db_session, DATA_DIR / "seed_cross_item_overlap", now=NOW)

    assert _count(db_session, LearningItem) == 0
    assert _count(db_session, Sentence) == 0


@pytest.mark.integration
def test_disjoint_spans_of_different_items_still_load(db_session: Session) -> None:
    """문장 단위 검사가 "겹침"이 아니라 "붙어 있지 않음"을 거부하면 빨개진다.

    `sn_min_0001`은 서로 다른 두 item이 `[0,2)`와 `[3,6)`을 차지하고 사이가 비어
    있다. 이것은 정상 데이터다.
    """
    load_seed(db_session, SEED_MIN, now=NOW)

    sentence = db_session.scalars(
        sa.select(Sentence).where(Sentence.source_id == "sn_min_0001")
    ).one()
    items = db_session.scalars(
        sa.select(SentenceItem).where(SentenceItem.sentence_id == sentence.id)
    ).all()
    assert len(items) == 2


@pytest.mark.integration
def test_stored_normalized_hash_matches_the_shared_function(db_session: Session) -> None:
    """적재된 해시가 생성 경로가 쓸 함수의 값과 같다.

    seed loader가 자기만의 정규화로 돌아가면 빨개진다. 두 경로의 해시가 갈리면
    duplicate 검출은 예외 없이 조용히 실패한다.
    """
    load_seed(db_session, SEED_MIN, now=NOW)

    rows = db_session.scalars(sa.select(Sentence)).all()
    assert rows
    for row in rows:
        assert row.normalized_hash == normalized_sentence_hash(row.japanese)


# --------------------------------------------------------------------------
# 후리가나 계산 (MVP-02, ADR-021 결정 4, 04_DB_SPEC.md의 Seed Data)
# --------------------------------------------------------------------------

_RUBY_KEYS = {
    "algorithm_version",
    "analyzer",
    "dictionary",
    "split_mode",
    "computed_at",
    "spans",
    "omitted",
    "corrected",
}


def _ruby_by_seed_id(session: Session) -> dict[str | None, object]:
    return {row.source_id: row.ruby_json for row in session.scalars(sa.select(Sentence)).all()}


@pytest.mark.integration
def test_every_seed_sentence_gets_ruby_in_the_same_load(db_session: Session) -> None:
    summary = load_seed(db_session, SEED_MIN, now=NOW)

    ruby = _ruby_by_seed_id(db_session)
    assert set(ruby) == {"sn_min_0001", "sn_min_0002"}
    for value in ruby.values():
        assert isinstance(value, dict)
        assert set(value) == _RUBY_KEYS
        # 모든 행이 진입점이 읽은 같은 시각을 갖는다(ADR-007).
        assert value["computed_at"] == NOW.astimezone(UTC).isoformat().replace("+00:00", "Z")
    first = ruby["sn_min_0001"]
    second = ruby["sn_min_0002"]
    assert isinstance(first, dict) and isinstance(second, dict)
    # 仕事(설명 しごと), 任せる(설명 まかせる): explanation 읽기가 두 item을 덮는다.
    assert first["spans"] == [[0, 2, "しごと"], [3, 4, "まか"]]
    # 불연속 item 気が…乗ら 와 탭할 수 없는 今日·全然.
    assert second["spans"] == [[0, 2, "きょう"], [3, 4, "き"], [5, 7, "ぜんぜん"], [7, 8, "の"]]

    assert (summary.ruby.sentences, summary.ruby.computed, summary.ruby.failed) == (2, 2, 0)
    assert summary.ruby.corrected_explanation_tokens == 4
    assert len(summary.ruby.rule_hits) == len(CORRECTION_RULES)


@pytest.mark.integration
def test_seed_ruby_is_the_shared_computation(db_session: Session) -> None:
    """seed 적재가 자기만의 계산을 하지 않는다: 같은 입력의 `compute_ruby`와 같은 값이다."""
    load_seed(db_session, SEED_MIN, now=NOW)

    sentence = db_session.scalars(
        sa.select(Sentence).where(Sentence.source_id == "sn_min_0002")
    ).one()
    expected = compute_ruby(
        sentence.japanese,
        [RubyItem("it_min_kiganoru", (ItemSpan(3, 5, 0), ItemSpan(7, 9, 1)), "きがのら")],
        now=NOW,
    )
    assert sentence.ruby_json == expected.ruby_json


@pytest.mark.integration
def test_a_failed_ruby_computation_leaves_null_and_the_load_continues(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    def flaky(japanese: str, items: Sequence[RubyItem], *, now: datetime) -> RubyComputation:
        if japanese.startswith("仕事"):
            raise RuntimeError("simulated analyzer failure")
        return compute_ruby(japanese, items, now=now)

    monkeypatch.setattr(seed_loader, "compute_ruby", flaky)

    summary = load_seed(db_session, SEED_MIN, now=NOW)

    ruby = _ruby_by_seed_id(db_session)
    assert ruby["sn_min_0001"] is None
    # JSON `null`이 아니라 SQL NULL이어야 backfill 대상(`ruby_json IS NULL`)이다.
    assert (
        db_session.scalar(sa.select(Sentence.source_id).where(Sentence.ruby_json.is_(None)))
        == "sn_min_0001"
    )
    assert isinstance(ruby["sn_min_0002"], dict)
    # 문장·item·설명은 그대로 적재된다. 후리가나 실패가 적재를 막지 않는다.
    assert (summary.sentences, summary.explanations) == (2, 3)
    assert _count(db_session, SentenceItemExplanation) == 3
    assert (summary.ruby.sentences, summary.ruby.computed, summary.ruby.failed) == (2, 1, 1)


@pytest.mark.integration
def test_seed_ruby_does_not_change_the_text_or_spans(db_session: Session) -> None:
    load_seed(db_session, SEED_MIN, now=NOW)

    sentence = db_session.scalars(
        sa.select(Sentence).where(Sentence.source_id == "sn_min_0001")
    ).one()
    spans = db_session.execute(
        sa.select(SentenceItemSpan.start_codepoint, SentenceItemSpan.end_codepoint)
        .join(SentenceItem, SentenceItem.id == SentenceItemSpan.sentence_item_id)
        .where(SentenceItem.sentence_id == sentence.id)
        .order_by(SentenceItemSpan.start_codepoint)
    ).all()
    assert sentence.japanese == "仕事を任せる。"
    assert [tuple(row) for row in spans] == [(0, 2), (3, 6)]


# --------------------------------------------------------------------------
# CLI (`scripts/load_seed.py`)
# --------------------------------------------------------------------------


def _load_seed_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "load_seed", REPO_ROOT / "scripts" / "load_seed.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["load_seed"] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.integration
def test_cli_prints_the_ruby_summary(
    committed_db: sessionmaker[Session],
    database_url: URL,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("DATABASE_URL", database_url.render_as_string(hide_password=False))
    get_settings.cache_clear()

    try:
        code = _load_seed_script().main(["--seed-dir", str(SEED_MIN)])
    finally:
        engine = get_engine()
        if engine is not None:
            engine.dispose()

    output = capsys.readouterr().out.splitlines()
    assert code == 0
    assert output[1].startswith(
        "ruby: algorithm_version=2 sentences=2 computed=2 failed=0 omitted_tappable_boundary=0 "
    )
    assert output[2 : 2 + len(CORRECTION_RULES)] == [
        line for line in output if line.startswith("rule ")
    ]
    assert len([line for line in output if line.startswith("rule ")]) == len(CORRECTION_RULES)
    with committed_db() as check:
        assert all(row.ruby_json is not None for row in check.scalars(sa.select(Sentence)).all())


@pytest.mark.integration
def test_cli_fails_at_start_when_the_analyzer_cannot_load(
    committed_db: sessionmaker[Session],
    database_url: URL,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """분석기 부재는 문장별 NULL로 흡수하지 않는다. DB에 아무것도 쓰기 전에 끝난다."""
    monkeypatch.setenv("DATABASE_URL", database_url.render_as_string(hide_password=False))
    get_settings.cache_clear()
    script = _load_seed_script()

    def missing() -> Never:
        raise ModuleNotFoundError("No module named 'sudachidict_core'")

    monkeypatch.setattr(script, "load_analyzer", missing)

    with pytest.raises(ModuleNotFoundError):
        script.main(["--seed-dir", str(SEED_MIN)])

    with committed_db() as check:
        assert _count(check, Sentence) == 0
        assert _count(check, LearningItem) == 0
