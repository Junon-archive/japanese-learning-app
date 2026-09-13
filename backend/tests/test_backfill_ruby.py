"""`scripts/backfill_ruby.py` --- 기존 문장 후리가나 backfill (04_DB_SPEC.md, 12_TEST_PLAN.md `backfill`).

DB는 테스트 pgserver의 일회용 DB, 백업은 `tmp_path`다. 대상 DB에는 seed(`seed_min`)와 학습 기록
몇 행을 넣고 `ruby_json`을 NULL로 되돌려 "migration 직후, backfill 전" 상태를 만든다.
"""

from __future__ import annotations

import importlib.util
import sys
import uuid
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pgserver
import pytest
import sqlalchemy as sa
import yaml
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.config import get_config
from app.furigana import RubyComputation, RubyItem, compute_ruby
from app.jobs import persistence
from app.jobs.persistence import NewSentence, Provenance
from app.llm.schemas import ExplanationPayload, ItemPayload, SentencePayload, SpanPayload
from app.models.content import Sentence
from app.models.enums import CandidateStatus, StartingLevel
from app.services.seed_loader import load_seed
from app.settings import get_settings
from tests import db_support, factories

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
SEED_MIN = Path(__file__).resolve().parent / "data" / "seed_min"
PG_BIN = Path(pgserver.__file__).parent / "pginstall" / "bin"

EXIT_OK = 0
EXIT_FAILED = 2
SENTENCES_TABLE = "sentences"
ALEMBIC_VERSION_TABLE = "alembic_version"


def load_script(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, SCRIPTS_DIR / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _failing_pg_bin(tmp_path: Path) -> Path:
    """호출되면 실패하는 pg_dump. 백업을 시도하지 않아야 하는 경로의 증거로도 쓴다."""
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
    """seed + 학습 기록이 있고 모든 문장의 `ruby_json`이 NULL인 DB. **커밋한다.**"""
    name = f"nc_backfill_{uuid.uuid4().hex[:12]}"
    dsn = db_support.recreate_database(postgres_admin_dsn, name)
    try:
        db_support.alembic_upgrade(dsn)
        engine = sa.create_engine(dsn, poolclass=NullPool)
        try:
            with Session(engine) as session:
                load_seed(session, SEED_MIN, now=datetime.now(UTC))
                sentence = session.scalars(sa.select(Sentence).order_by(Sentence.id)).first()
                assert sentence is not None
                user = factories.make_user(session)
                study = factories.make_study_session(
                    session, user, target_minutes=get_config().learning.default_session_minutes
                )
                candidate = factories.make_candidate(
                    session, user, sentence, status=CandidateStatus.SHOWN
                )
                factories.make_presentation(session, user, study, candidate, sentence)
                session.execute(sa.update(Sentence).values(ruby_json=None))
                session.commit()
        finally:
            engine.dispose()
        monkeypatch.setenv("DATABASE_URL", dsn.render_as_string(hide_password=False))
        get_settings.cache_clear()
        yield dsn
    finally:
        get_settings.cache_clear()
        db_support.drop_database(postgres_admin_dsn, name)


def _ruby(dsn: URL) -> dict[int, dict[str, Any] | None]:
    engine = sa.create_engine(dsn, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                sa.select(Sentence.id, Sentence.ruby_json).order_by(Sentence.id)
            ).all()
    finally:
        engine.dispose()
    return {int(sentence_id): value for sentence_id, value in rows}


def _execute(dsn: URL, statement: sa.Executable) -> None:
    engine = sa.create_engine(dsn, poolclass=NullPool)
    try:
        with engine.begin() as connection:
            connection.execute(statement)
    finally:
        engine.dispose()


def _tables_other_than_sentences(dsn: URL) -> dict[str, tuple[int, str]]:
    restore_check = load_script("db_restore_check")
    engine = sa.create_engine(dsn, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            tables: dict[str, tuple[int, str]] = restore_check.take_snapshot(connection).tables
    finally:
        engine.dispose()
    del tables[SENTENCES_TABLE]
    return tables


def _run(args: Sequence[str]) -> int:
    return int(load_script("backfill_ruby").main(list(args)))


def _apply(tmp_path: Path, pg_bin: Path = PG_BIN, *, backups: str = "backups") -> list[str]:
    """백업 이름은 초 단위라 한 테스트에서 두 번 백업하면 디렉터리를 나눈다."""
    return ["--apply", "--pg-bin", str(pg_bin), "--backup-dir", str(tmp_path / backups)]


def _backups(tmp_path: Path) -> list[Path]:
    directory = tmp_path / "backups"
    return sorted(directory.iterdir()) if directory.exists() else []


# --------------------------------------------------------------------------
# dry-run
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_dry_run_writes_nothing_and_prints_the_target_first(
    target_db: URL, capsys: pytest.CaptureFixture[str]
) -> None:
    code = _run([])

    out = capsys.readouterr().out
    assert code == EXIT_OK
    assert all(value is None for value in _ruby(target_db).values())
    assert out.index(f"database={target_db.database}") < out.index("algorithm_version=2\n")
    assert "ruby: algorithm_version=2 sentences=2 " in out, out
    assert out.index("algorithm_version=2\n") < out.index("ruby: algorithm_version=2 sentences=2")
    assert "sentences=2 computed=2 failed=0" in out
    assert out.rstrip().endswith("dry-run: nothing written")
    assert "rule 私->わたし hits=" in out
    password = target_db.password
    if password:
        assert str(password) not in out


# --------------------------------------------------------------------------
# --apply: 백업 강제, 쓰기, 멱등
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_apply_takes_a_verified_backup_then_fills_every_null_row(
    target_db: URL, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    learning_before = _tables_other_than_sentences(target_db)

    code = _run(_apply(tmp_path))

    out = capsys.readouterr().out
    assert code == EXIT_OK
    assert out.index("backup verified:") < out.index("updated 2 of 2 sentences")
    assert len(_backups(tmp_path)) == 1
    values = _ruby(target_db)
    assert all(value is not None for value in values.values())
    # 모든 행이 진입점이 한 번 읽은 같은 computed_at을 갖는다.
    assert len({value["computed_at"] for value in values.values() if value is not None}) == 1
    # 학습 테이블(과 sentences 밖의 모든 테이블)은 그대로다.
    assert _tables_other_than_sentences(target_db) == learning_before


@pytest.mark.integration
def test_apply_without_pg_bin_is_refused_before_anything(
    target_db: URL, capsys: pytest.CaptureFixture[str]
) -> None:
    code = _run(["--apply"])

    assert code == EXIT_FAILED
    assert "--pg-bin" in capsys.readouterr().err
    assert all(value is None for value in _ruby(target_db).values())


@pytest.mark.integration
def test_a_failed_backup_writes_nothing(
    target_db: URL, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = _run(_apply(tmp_path, _failing_pg_bin(tmp_path)))

    assert code == EXIT_FAILED
    assert "backup failed; nothing was written" in capsys.readouterr().err
    assert all(value is None for value in _ruby(target_db).values())
    assert _backups(tmp_path) == []


def test_there_is_no_option_to_skip_the_backup_or_recompute() -> None:
    script = load_script("backfill_ruby")
    with pytest.raises(SystemExit):
        script._parse_args(["--skip-backup"])
    with pytest.raises(SystemExit):
        script._parse_args(["--recompute"])
    namespace = script._parse_args([])
    assert set(vars(namespace)) == {"apply", "pg_bin", "backup_dir", "keep"}


@pytest.mark.integration
def test_the_second_apply_has_no_target_and_takes_no_backup(
    target_db: URL, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(_apply(tmp_path)) == EXIT_OK
    first = _ruby(target_db)
    capsys.readouterr()

    # pg_dump가 불리면 실패하므로 exit 0은 백업을 시도하지 않았다는 뜻이기도 하다.
    code = _run(_apply(tmp_path, _failing_pg_bin(tmp_path)))

    out = capsys.readouterr().out
    assert code == EXIT_OK
    assert "sentences with ruby_json IS NULL: 0" in out
    assert "nothing to write; no backup taken" in out
    assert _ruby(target_db) == first
    assert len(_backups(tmp_path)) == 1


@pytest.mark.integration
def test_rows_that_already_have_ruby_are_not_targets_even_with_an_older_version(
    target_db: URL, tmp_path: Path
) -> None:
    older = {"algorithm_version": 1, "spans": [], "marker": "older"}
    first_id = min(_ruby(target_db))
    _execute(target_db, sa.update(Sentence).where(Sentence.id == first_id).values(ruby_json=older))

    assert _run(_apply(tmp_path)) == EXIT_OK

    values = _ruby(target_db)
    assert values[first_id] == older
    assert all(value is not None for value in values.values())


# --------------------------------------------------------------------------
# 동시 실행
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_a_value_committed_between_compute_and_write_is_not_overwritten(
    target_db: URL,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """계산과 쓰기 사이에 worker(또는 다른 backfill)가 값을 커밋했다. 늦은 쪽은 0행 갱신이다."""
    script = load_script("backfill_ruby")
    real_backup = script.db_backup.create_backup
    concurrent = {"spans": [], "marker": "written by the worker meanwhile"}
    first_id = min(_ruby(target_db))

    def backup_then_race(*args: object, **kwargs: object) -> Path:
        _execute(
            target_db,
            sa.update(Sentence).where(Sentence.id == first_id).values(ruby_json=concurrent),
        )
        return Path(real_backup(*args, **kwargs))

    monkeypatch.setattr(script.db_backup, "create_backup", backup_then_race)

    code = script.main(_apply(tmp_path))

    assert code == EXIT_OK
    assert "updated 1 of 2 sentences" in capsys.readouterr().out
    values = _ruby(target_db)
    assert values[first_id] == concurrent
    assert all(value is not None for value in values.values())


@pytest.mark.integration
def test_two_overlapping_runs_end_in_the_same_state_and_the_late_one_updates_nothing(
    target_db: URL,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = load_script("backfill_ruby")
    real_backup = script.db_backup.create_backup
    calls: list[str] = []

    def overlapping(*args: object, **kwargs: object) -> Path:
        calls.append("backup")
        if len(calls) == 1:
            # 늦은 쪽(A)이 계산을 마친 순간 빠른 쪽(B)이 처음부터 끝까지 돈다.
            assert load_script("backfill_ruby").main(_apply(tmp_path, backups="early")) == EXIT_OK
        return Path(real_backup(*args, **kwargs))

    monkeypatch.setattr(script.db_backup, "create_backup", overlapping)

    code = script.main(_apply(tmp_path))

    out = capsys.readouterr().out
    assert code == EXIT_OK
    assert out.count("updated 2 of 2 sentences") == 1, "빠른 쪽이 전부 썼다"
    assert "updated 0 of 2 sentences" in out, "늦은 쪽은 아무것도 덮어쓰지 않았다"
    values = _ruby(target_db)
    assert all(value is not None for value in values.values())
    assert len({value["computed_at"] for value in values.values() if value is not None}) == 1


# --------------------------------------------------------------------------
# 계산 실패와 종료 코드
# --------------------------------------------------------------------------


def _fail_for(script: ModuleType, japanese_prefix: str, monkeypatch: pytest.MonkeyPatch) -> None:
    def flaky(japanese: str, items: Sequence[RubyItem], *, now: datetime) -> RubyComputation:
        if japanese.startswith(japanese_prefix):
            raise RuntimeError("simulated ruby failure")
        return compute_ruby(japanese, items, now=now)

    monkeypatch.setattr(script, "compute_ruby", flaky)


@pytest.mark.integration
def test_a_failure_makes_dry_run_exit_2(
    target_db: URL, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = load_script("backfill_ruby")
    _fail_for(script, "仕事", monkeypatch)

    code = script.main([])

    out = capsys.readouterr().out
    assert code == EXIT_FAILED
    assert "sentences=2 computed=1 failed=1" in out
    assert "dry-run: nothing written" in out


@pytest.mark.integration
def test_apply_writes_the_successes_then_exits_2_and_the_next_run_retries_only_the_failure(
    target_db: URL,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = load_script("backfill_ruby")
    _fail_for(script, "仕事", monkeypatch)

    code = script.main(_apply(tmp_path))

    assert code == EXIT_FAILED
    assert "updated 1 of 1 sentences" in capsys.readouterr().out
    values = _ruby(target_db)
    assert sorted(value is None for value in values.values()) == [False, True]

    monkeypatch.undo()
    monkeypatch.setenv("DATABASE_URL", target_db.render_as_string(hide_password=False))
    get_settings.cache_clear()
    assert _run(_apply(tmp_path, backups="retry")) == EXIT_OK
    out = capsys.readouterr().out
    assert "sentences with ruby_json IS NULL: 1" in out
    assert "updated 1 of 1 sentences" in out


@pytest.mark.integration
def test_all_failures_take_no_backup_and_exit_2(
    target_db: URL,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = load_script("backfill_ruby")
    _fail_for(script, "", monkeypatch)

    code = script.main(_apply(tmp_path, _failing_pg_bin(tmp_path)))

    assert code == EXIT_FAILED
    assert "nothing to write; no backup taken" in capsys.readouterr().out
    assert all(value is None for value in _ruby(target_db).values())


@pytest.mark.integration
def test_the_analyzer_must_load_before_touching_the_database(
    target_db: URL, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = load_script("backfill_ruby")

    def missing() -> None:
        raise ModuleNotFoundError("No module named 'sudachipy'")

    monkeypatch.setattr(script, "load_analyzer", missing)

    with pytest.raises(ModuleNotFoundError):
        script.main([])
    assert "database=" not in capsys.readouterr().out


# --------------------------------------------------------------------------
# 출력 이스케이프
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_control_characters_in_the_mismatch_list_are_escaped(
    target_db: URL, capsys: pytest.CaptureFixture[str]
) -> None:
    """설명 읽기는 LLM 출력일 수 있다. 제어문자가 터미널에서 해석되거나 줄을 가르지 않는다."""
    engine = sa.create_engine(target_db, poolclass=NullPool)
    try:
        with Session(engine) as session:
            item = factories.make_learning_item(session, lemma="明日")
            sentence = factories.make_sentence(session, japanese="明日は早い。")
            sentence_item = factories.make_sentence_item(
                session, sentence, item, surface_form="明日"
            )
            factories.make_span(session, sentence_item, start=0, end=2)
            explanation = factories.make_explanation(session, sentence_item)
            explanation.reading = "あ\x1b[2Jす\nmismatch kind=forged"
            session.commit()
            sentence_id = sentence.id
    finally:
        engine.dispose()

    assert _run([]) == EXIT_OK

    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if line.startswith("mismatch ")]
    assert len(lines) == 1
    (line,) = lines
    assert f"sentence={sentence_id} " in line
    assert "\x1b" not in out
    assert "explanation=あ\\u001B[2Jす\\u000Amismatch kind=forged" in line


# --------------------------------------------------------------------------
# 같은 계산 함수: seed 적재 · worker 저장 · backfill
# --------------------------------------------------------------------------


def _seed_payloads() -> list[SentencePayload]:
    entries: list[dict[str, Any]] = yaml.safe_load(
        (SEED_MIN / "sentences.yaml").read_text(encoding="utf-8")
    )
    return [
        SentencePayload(
            japanese=entry["japanese"],
            korean_translation=entry["korean_translation"],
            difficulty_label=StartingLevel.BEGINNER,
            items=tuple(
                ItemPayload(
                    item_ref=raw["item_seed_id"],
                    surface_form=raw["surface_form"],
                    is_tappable=raw["is_tappable"],
                    spans=tuple(SpanPayload(**span) for span in raw["spans"]),
                    explanation=ExplanationPayload(
                        **{
                            key: raw["explanation"].get(key)
                            for key in ExplanationPayload.model_fields
                        }
                    ),
                )
                for raw in entry["items"]
            ),
        )
        for entry in entries
    ]


@pytest.mark.integration
def test_seed_worker_and_backfill_produce_the_same_spans(
    postgres_admin_dsn: URL, target_db: URL, tmp_path: Path
) -> None:
    # seed 적재가 계산한 값 (fixture가 NULL로 되돌리기 전의 계산과 같은 입력)
    engine = sa.create_engine(target_db, poolclass=NullPool)
    name = f"nc_backfill_seed_{uuid.uuid4().hex[:12]}"
    seed_dsn = db_support.recreate_database(postgres_admin_dsn, name)
    try:
        db_support.alembic_upgrade(seed_dsn)
        seed_engine = sa.create_engine(seed_dsn, poolclass=NullPool)
        try:
            with Session(seed_engine) as session:
                load_seed(session, SEED_MIN, now=datetime.now(UTC))
                seed_spans = {
                    row.japanese: row.ruby_json["spans"]
                    for row in session.scalars(sa.select(Sentence)).all()
                    if row.ruby_json is not None
                }
                # 커밋하지 않는다. 같은 DB에 seed 문장이 남으면 아래 worker 저장이 duplicate로 걸린다.
                session.rollback()
        finally:
            seed_engine.dispose()

        # worker 저장이 계산한 값
        worker_dsn = seed_dsn
        worker_engine = sa.create_engine(worker_dsn, poolclass=NullPool)
        try:
            with Session(worker_engine) as session:
                job = factories.make_generation_job(
                    session,
                    idempotency_key="same-spans",
                    max_attempts=get_config().jobs.max_job_attempts,
                )
                sentences = []
                for payload in _seed_payloads():
                    item_ids = {
                        item.item_ref: factories.make_learning_item(
                            session, lemma=item.surface_form
                        ).id
                        for item in payload.items
                    }
                    sentences.append(
                        NewSentence(payload=payload, item_ids=item_ids, parent_sentence_id=None)
                    )
                session.commit()
                now = datetime.now(UTC)
                completion = persistence.save_sentences(
                    session,
                    job=job,
                    sentences=sentences,
                    rejected=[],
                    provenance=Provenance("stub", "test-model", "sentence_gen_v1", now),
                    now=now,
                )
                worker_spans = {
                    row.japanese: row.ruby_json["spans"]
                    for row in session.scalars(
                        sa.select(Sentence).where(Sentence.id.in_(completion.stored))
                    ).all()
                    if row.ruby_json is not None
                }
        finally:
            worker_engine.dispose()
    finally:
        db_support.drop_database(postgres_admin_dsn, name)

    # backfill이 계산한 값
    assert _run(_apply(tmp_path)) == EXIT_OK
    try:
        with engine.connect() as connection:
            backfill_spans = {
                japanese: value["spans"]
                for japanese, value in connection.execute(
                    sa.select(Sentence.japanese, Sentence.ruby_json)
                ).all()
            }
    finally:
        engine.dispose()

    assert len(seed_spans) == 2
    assert seed_spans == worker_spans == backfill_spans
