"""MVP-03 Wave 4 --- 실제 `seed/en/` 디렉터리가 깨끗하게 적재되는지 확인한다.

`seed/ja/`가 `test_db_migrate.py`/`test_restart_persistence.py`에서 실제로 로드되는 것과
같은 자리다 --- 1차 300개 영어 seed도 "파일이 실제로 유효하다"를 한 번은 실제 로더로
검증해야 한다(`load_seed`의 전체 검증 경로: reading 언어 규칙, ruby_json ja-only CHECK,
span 검증, explanation 필수 검사 전부를 통과해야 통과한다).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.config import get_config
from app.models.content import LearningItem, Sentence, SentenceItem, SentenceItemExplanation
from app.models.enums import Language
from app.services.seed_loader import load_seed

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
SEED_EN_DIR = REPO_ROOT / "seed" / "en"


def test_seed_en_loads_cleanly(db_session: Session) -> None:
    summary = load_seed(
        db_session, SEED_EN_DIR, now=datetime.now(UTC), cfg=get_config(), language=Language.EN
    )

    assert summary.items == 300
    assert summary.items_inserted == 300
    assert summary.items_skipped == 0
    assert summary.sentences == 876
    assert summary.sentences_inserted == 876
    assert summary.sentences_skipped == 0
    assert summary.explanations == summary.spans == 876


def test_seed_en_items_have_no_reading_and_sentences_have_no_ruby(db_session: Session) -> None:
    load_seed(
        db_session, SEED_EN_DIR, now=datetime.now(UTC), cfg=get_config(), language=Language.EN
    )

    items = (
        db_session.execute(sa.select(LearningItem).where(LearningItem.language == Language.EN))
        .scalars()
        .all()
    )
    assert len(items) == 300
    assert all(item.reading is None for item in items)
    assert all(item.seed_id is not None and item.seed_id.startswith("en_it_") for item in items)

    sentences = (
        db_session.execute(sa.select(Sentence).where(Sentence.language == Language.EN))
        .scalars()
        .all()
    )
    assert len(sentences) == len({s.seed_id for s in sentences})
    assert all(s.ruby_json is None for s in sentences)

    explanations = db_session.execute(sa.select(SentenceItemExplanation)).scalars().all()
    sentence_item_ids = {
        row.id
        for row in db_session.execute(
            sa.select(SentenceItem.id)
            .join(Sentence, SentenceItem.sentence_id == Sentence.id)
            .where(Sentence.language == Language.EN)
        )
    }
    en_explanations = [e for e in explanations if e.sentence_item_id in sentence_item_ids]
    assert en_explanations
    assert all(e.reading is None for e in en_explanations)
    assert all(e.core_meaning for e in en_explanations)
    assert all(e.example_sentence for e in en_explanations)
    assert all(e.example_translation for e in en_explanations)


def test_seed_en_frequency_rank_is_1_to_300(db_session: Session) -> None:
    load_seed(
        db_session, SEED_EN_DIR, now=datetime.now(UTC), cfg=get_config(), language=Language.EN
    )

    items = (
        db_session.execute(sa.select(LearningItem).where(LearningItem.language == Language.EN))
        .scalars()
        .all()
    )
    ranks = sorted(item.metadata_json["frequency_rank"] for item in items)
    assert ranks == list(range(1, 301))
