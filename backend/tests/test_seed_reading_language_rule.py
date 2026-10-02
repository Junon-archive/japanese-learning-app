"""`learning_items.reading` / explanation `reading`의 언어별 필수·금지 규칙.

Migration 0005가 DB 레벨 NOT NULL을 없앴지만(ADR-023 결정 3), seed 파서는 언어별로
여전히 규칙을 강제해야 한다: `ja`는 `reading` 필수, `en`은 `reading` 키가 아예 없어야
한다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from sqlalchemy.orm import Session

from app.models.enums import Language
from app.services.seed_loader import SeedError, load_seed
from tests.factories import NOW


def _item(reading: str | None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "seed_id": "it_a",
        "type": "word",
        "lemma": "lemma",
        "default_meaning": "meaning",
    }
    if reading is not None:
        result["reading"] = reading
    return result


def _sentence(reading: str | None) -> dict[str, Any]:
    explanation: dict[str, Any] = {
        "core_meaning": "m",
        "meaning_in_context": "m2",
        "nuance": "n",
        "example_sentence": "ex.",
        "example_translation": "tr.",
    }
    if reading is not None:
        explanation["reading"] = reading
    return {
        "seed_id": "sn_a",
        "text": "foo bar.",
        "korean_translation": "t.",
        "items": [
            {
                "item_seed_id": "it_a",
                "surface_form": "foo",
                "is_tappable": True,
                "spans": [{"start_codepoint": 0, "end_codepoint": 3, "span_order": 0}],
                "explanation": explanation,
            }
        ],
    }


def _write_seed_dir(path: Path, *, reading: str | None) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "items.yaml").write_text(
        yaml.safe_dump([_item(reading)], allow_unicode=True), encoding="utf-8"
    )
    (path / "sentences.yaml").write_text(
        yaml.safe_dump([_sentence(reading)], allow_unicode=True), encoding="utf-8"
    )
    return path


@pytest.mark.integration
def test_en_without_reading_loads_successfully(tmp_path: Path, db_session: Session) -> None:
    seed_dir = _write_seed_dir(tmp_path / "en", reading=None)
    summary = load_seed(db_session, seed_dir, now=NOW, language=Language.EN)
    assert summary.items_inserted == 1


@pytest.mark.integration
def test_ja_with_reading_loads_successfully(tmp_path: Path, db_session: Session) -> None:
    seed_dir = _write_seed_dir(tmp_path / "ja", reading="よみ")
    summary = load_seed(db_session, seed_dir, now=NOW, language=Language.JA)
    assert summary.items_inserted == 1


@pytest.mark.integration
def test_en_with_reading_is_rejected(tmp_path: Path, db_session: Session) -> None:
    seed_dir = _write_seed_dir(tmp_path / "en_bad", reading="よみ")
    with pytest.raises(SeedError, match="must not have 'reading'"):
        load_seed(db_session, seed_dir, now=NOW, language=Language.EN)


@pytest.mark.integration
def test_ja_without_reading_is_rejected(tmp_path: Path, db_session: Session) -> None:
    seed_dir = _write_seed_dir(tmp_path / "ja_bad", reading=None)
    with pytest.raises(SeedError, match="missing 'reading'"):
        load_seed(db_session, seed_dir, now=NOW, language=Language.JA)
