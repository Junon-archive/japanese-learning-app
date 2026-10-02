"""`scripts/backfill_seed_id.py` --- 기존 seed 행의 `seed_id` backfill
(04_DB_SPEC.md의 `증분 적재`의 `기존 일본어 seed 행의 seed_id backfill`, ADR-023 결정 4,
12_TEST_PLAN.md `seed_id backfill`).

형태는 `test_backfill_ruby.py`와 같다. DB는 테스트 pgserver의 일회용 DB, 백업은
`tmp_path`다. 대상 DB에는 `seed_min` fixture를 적재한 뒤 `seed_id`를 NULL로 되돌려
"migration 직후, backfill 전" 상태를 만든다(Wave 3 이후의 loader는 적재 시점에 이미
`seed_id`를 채우므로, 레거시 상태를 재현하려면 명시적으로 지워야 한다).
"""

from __future__ import annotations

import importlib.util
import sys
import uuid
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import pgserver
import pytest
import sqlalchemy as sa
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.config import get_config
from app.models.content import LearningItem, Sentence
from app.services.seed_loader import load_seed
from app.settings import get_settings
from tests import db_support

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
SEED_MIN = Path(__file__).resolve().parent / "data" / "seed_min"
PG_BIN = Path(pgserver.__file__).parent / "pginstall" / "bin"

EXIT_OK = 0
EXIT_FAILED = 2


def load_script(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, SCRIPTS_DIR / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _failing_pg_bin(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "failing-pg-bin"
    bin_dir.mkdir()
    script = bin_dir / "pg_dump"
    script.write_text(
        f'#!/bin/sh\nif [ "$1" = "--version" ]; then exec "{PG_BIN / "pg_dump"}" --version; fi\n'
        "echo 'pg_dump: error: simulated' >&2\nexit 1\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    (bin_dir / "pg_restore").symlink_to(PG_BIN / "pg_restore")
    return bin_dir


@pytest.fixture
def target_db(postgres_admin_dsn: URL, monkeypatch: pytest.MonkeyPatch) -> Iterator[URL]:
    """`seed_min`을 적재하고 `seed_id`를 NULL로 되돌린 DB. **커밋한다.**"""
    name = f"nc_backfill_seed_id_{uuid.uuid4().hex[:12]}"
    dsn = db_support.recreate_database(postgres_admin_dsn, name)
    try:
        db_support.alembic_upgrade(dsn)
        engine = sa.create_engine(dsn, poolclass=NullPool)
        try:
            with Session(engine) as session:
                load_seed(session, SEED_MIN, now=datetime.now(UTC), cfg=get_config())
                session.execute(sa.update(LearningItem).values(seed_id=None))
                session.execute(sa.update(Sentence).values(seed_id=None))
                session.commit()
        finally:
            engine.dispose()
        monkeypatch.setenv("DATABASE_URL", dsn.render_as_string(hide_password=False))
        get_settings.cache_clear()
        yield dsn
    finally:
        get_settings.cache_clear()
        db_support.drop_database(postgres_admin_dsn, name)


def _seed_ids(dsn: URL) -> tuple[dict[int, str | None], dict[int, str | None]]:
    engine = sa.create_engine(dsn, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            items: dict[int, str | None] = dict(
                tuple(row)
                for row in connection.execute(sa.select(LearningItem.id, LearningItem.seed_id))
            )
            sentences: dict[int, str | None] = dict(
                tuple(row) for row in connection.execute(sa.select(Sentence.id, Sentence.seed_id))
            )
    finally:
        engine.dispose()
    return items, sentences


def _run(args: Sequence[str]) -> int:
    return int(load_script("backfill_seed_id").main(list(args)))


def _base_args() -> list[str]:
    return ["--seed-dir", str(SEED_MIN)]


def _apply(tmp_path: Path, pg_bin: Path = PG_BIN, *, backups: str = "backups") -> list[str]:
    return [
        *_base_args(),
        "--apply",
        "--pg-bin",
        str(pg_bin),
        "--backup-dir",
        str(tmp_path / backups),
    ]


def _backups(tmp_path: Path) -> list[Path]:
    directory = tmp_path / "backups"
    return sorted(directory.iterdir()) if directory.exists() else []


# --------------------------------------------------------------------------
# dry-run
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_dry_run_writes_nothing(target_db: URL, capsys: pytest.CaptureFixture[str]) -> None:
    code = _run(_base_args())

    out = capsys.readouterr().out
    assert code == EXIT_OK, out
    items, sentences = _seed_ids(target_db)
    assert all(value is None for value in items.values())
    assert all(value is None for value in sentences.values())
    assert "learning_items to backfill: 3" in out
    assert "sentences to backfill: 2" in out
    assert out.rstrip().endswith("dry-run: nothing written")


# --------------------------------------------------------------------------
# --apply: 백업 강제, 쓰기, 멱등
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_apply_takes_a_verified_backup_then_fills_every_row(
    target_db: URL, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = _run(_apply(tmp_path))

    out = capsys.readouterr().out
    assert code == EXIT_OK, out
    assert len(_backups(tmp_path)) == 1
    items, sentences = _seed_ids(target_db)
    assert set(items.values()) == {"it_min_makaseru", "it_min_shigoto", "it_min_kiganoru"}
    assert set(sentences.values()) == {"sn_min_0001", "sn_min_0002"}
    assert "updated 3 of 3 learning_items, 2 of 2 sentences" in out


@pytest.mark.integration
def test_apply_without_pg_bin_is_refused_before_anything(
    target_db: URL, capsys: pytest.CaptureFixture[str]
) -> None:
    code = _run([*_base_args(), "--apply"])

    assert code == EXIT_FAILED
    assert "--pg-bin" in capsys.readouterr().err
    items, sentences = _seed_ids(target_db)
    assert all(value is None for value in items.values())
    assert all(value is None for value in sentences.values())


@pytest.mark.integration
def test_a_failed_backup_writes_nothing(
    target_db: URL, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = _run(_apply(tmp_path, _failing_pg_bin(tmp_path)))

    assert code == EXIT_FAILED
    assert "backup failed; nothing was written" in capsys.readouterr().err
    items, sentences = _seed_ids(target_db)
    assert all(value is None for value in items.values())
    assert all(value is None for value in sentences.values())
    assert _backups(tmp_path) == []


@pytest.mark.integration
def test_the_second_apply_has_no_target_and_takes_no_backup(
    target_db: URL, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(_apply(tmp_path)) == EXIT_OK
    first_items, first_sentences = _seed_ids(target_db)
    capsys.readouterr()

    # pg_dump가 불리면 실패하므로 exit 0은 백업을 시도하지 않았다는 뜻이기도 하다.
    code = _run(_apply(tmp_path, _failing_pg_bin(tmp_path)))

    out = capsys.readouterr().out
    assert code == EXIT_OK
    assert "learning_items to backfill: 0" in out
    assert "sentences to backfill: 0" in out
    assert "nothing to write; no backup taken" in out
    assert _seed_ids(target_db) == (first_items, first_sentences)
    assert len(_backups(tmp_path)) == 1


# --------------------------------------------------------------------------
# 대조 실패: 하나라도 다르면 아무것도 쓰지 않는다
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_a_lemma_mismatch_writes_nothing_and_exits_2(
    target_db: URL, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """DB의 lemma가 파일과 다르면(드리프트) 전체가 실패한다. 한 행만 건너뛰지 않는다."""
    engine = sa.create_engine(target_db, poolclass=NullPool)
    try:
        with engine.begin() as connection:
            # seed_min의 seed_order=1 item(it_min_makaseru)의 lemma는 "任せる"다.
            connection.execute(
                sa.update(LearningItem)
                .where(LearningItem.lemma == "任せる")
                .values(lemma="drifted")
            )
    finally:
        engine.dispose()

    code = _run(_apply(tmp_path))

    out = capsys.readouterr().out
    assert code == EXIT_FAILED
    assert "mismatch" in out
    items, sentences = _seed_ids(target_db)
    assert all(value is None for value in items.values())
    assert all(value is None for value in sentences.values())
    assert _backups(tmp_path) == []


@pytest.mark.integration
def test_a_sentence_text_mismatch_writes_nothing_and_exits_2(
    target_db: URL, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    engine = sa.create_engine(target_db, poolclass=NullPool)
    try:
        first_id = min(_seed_ids(target_db)[1])
        with engine.begin() as connection:
            connection.execute(
                sa.update(Sentence).where(Sentence.id == first_id).values(text="drifted text")
            )
    finally:
        engine.dispose()

    code = _run(_apply(tmp_path))

    out = capsys.readouterr().out
    assert code == EXIT_FAILED
    assert "mismatch" in out
    items, sentences = _seed_ids(target_db)
    assert all(value is None for value in items.values())
    assert all(value is None for value in sentences.values())
    assert _backups(tmp_path) == []


def test_there_is_no_option_to_skip_the_backup() -> None:
    script = load_script("backfill_seed_id")
    with pytest.raises(SystemExit):
        script._parse_args(["--skip-backup"])
    namespace = script._parse_args([])
    assert set(vars(namespace)) == {"seed_dir", "apply", "pg_bin", "backup_dir", "keep"}


@pytest.mark.integration
def test_the_printed_target_masks_a_real_password(
    target_db: URL, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    secret = "nc-backfill-seed-id-secret"
    with_password = target_db.set(password=secret)
    monkeypatch.setenv("DATABASE_URL", with_password.render_as_string(hide_password=False))
    get_settings.cache_clear()

    code = _run(_base_args())

    out = capsys.readouterr().out
    assert code == EXIT_OK, out
    assert secret not in out
    assert "***" in out
