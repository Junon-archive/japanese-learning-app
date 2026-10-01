"""Alembic migration 검증 (12_TEST_PLAN.md "Alembic from empty DB").

04_DB_SPEC.md Migration Rule: "빈 DB에서 migration만으로 전체 schema를
재현할 수 있어야 한다."
"""

from __future__ import annotations

import ast
import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.engine import URL, Engine

from app.models import Base
from tests import db_support

# 모듈 `pytestmark` 대신 **DB를 쓰는 테스트에만** 마크를 단다. 아래
# `test_upgrade_never_drops_tables_or_columns`는 migration 소스만 읽으므로 DB가 필요
# 없고, 모듈 전체에 마크가 걸려 있으면 그것이 `make test-unit`에서 조용히 사라진다
# (`test_marker_hygiene.py`의 `test_no_test_is_marked_integration_without_needing_the_database`).

# 04_DB_SPEC.md가 정의하는 테이블 전부. alembic_version은 Alembic 자신의 것이다.
ALEMBIC_BOOKKEEPING_TABLE = "alembic_version"


def _app_tables(engine: Engine) -> set[str]:
    return {
        name
        for name in sa.inspect(engine).get_table_names(schema="public")
        if name != ALEMBIC_BOOKKEEPING_TABLE
    }


def _current_revision(engine: Engine) -> str | None:
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


@pytest.mark.integration
def test_upgrade_downgrade_upgrade_on_an_empty_database(postgres_admin_dsn: URL) -> None:
    """공유 테스트 DB를 쓰면 안 된다. downgrade가 그것을 파괴한다."""
    database = f"nc_migration_{uuid.uuid4().hex[:12]}"
    dsn = db_support.recreate_database(postgres_admin_dsn, database)
    head = ScriptDirectory.from_config(db_support.alembic_config(dsn)).get_current_head()
    engine = sa.create_engine(dsn)
    try:
        assert _app_tables(engine) == set(), "테스트는 항상 빈 DB에서 시작해야 한다"

        db_support.alembic_upgrade(dsn)
        after_upgrade = _app_tables(engine)
        assert after_upgrade == set(Base.metadata.tables)
        assert _current_revision(engine) == head

        db_support.alembic_downgrade(dsn, "base")
        # downgrade가 남기는 것은 Alembic 자신의 bookkeeping 테이블뿐이다.
        assert _app_tables(engine) == set()

        # 재-upgrade. 한 방향으로만 동작하는 migration(예: downgrade가 제약을
        # 지우지 못해 재생성이 실패)을 여기서 잡는다.
        db_support.alembic_upgrade(dsn)
        assert _app_tables(engine) == after_upgrade
    finally:
        engine.dispose()
        db_support.drop_database(postgres_admin_dsn, database)


# --------------------------------------------------------------------------
# MVP-02 additive migration (불변식 19, ADR-021 결정 2, 13_ACCEPTANCE_CRITERIA.md 26).
# 운영 DB는 reset하지 않고 0003 상태의 데이터 위에 0004를 올린다. 그래서 "빈 DB 왕복"만으로는
# 부족하다 --- 데이터가 있는 DB에서 행이 보존되는지와, 0004가 명세 밖의 것을 바꾸지 않는지를
# 따로 본다.
# --------------------------------------------------------------------------

PRE_MVP02_REVISION = "0003"
RUBY_JSON_REVISION = "0004"

# 학습 기록 테이블. 이 테이블들이 비어 있으면 보존 검사가 아무것도 보지 않는다.
LEARNING_RECORD_TABLES = frozenset(
    {
        "item_exposures",
        "learning_events",
        "user_mastery",
        "review_states",
        "user_item_learning_state",
        "study_sessions",
        "study_presentations",
    }
)

# 0003 스키마에 raw SQL로 넣는다. ORM 모델은 이미 head(ruby_json 포함)를 가리키므로 0003
# DB에 쓸 수 없다. 값은 서로 참조하는 한 사용자의 학습 흐름 하나다.
_SEED_0003_STATEMENTS = (
    """
    INSERT INTO users (id, login_id, password_hash, timezone, starting_level, created_at)
    VALUES (1, 'migration-user', 'x', 'Asia/Seoul', 'beginner', '2026-09-01T00:00:00Z')
    """,
    """
    INSERT INTO learning_items (id, type, lemma, reading, default_meaning, origin, created_at)
    VALUES (1, 'word', '田中', 'たなか', '다나카', 'seed', '2026-09-01T00:00:00Z')
    """,
    """
    INSERT INTO sentences (id, japanese, korean_translation, source_type, provenance_json,
                           normalized_hash, status, created_at)
    VALUES (1, '田中さんは来ます。', '다나카 씨는 옵니다.', 'seed', '{}', 'h1', 'validated',
            '2026-09-01T00:00:00Z'),
           (2, '田中さんが来た。', '다나카 씨가 왔다.', 'generated',
            '{"provider": "test", "model": "m"}', 'h2', 'quarantined', '2026-09-02T00:00:00Z')
    """,
    """
    INSERT INTO sentence_items (id, sentence_id, learning_item_id, surface_form, is_tappable,
                                created_at)
    VALUES (1, 1, 1, '田中', true, '2026-09-01T00:00:00Z')
    """,
    """
    INSERT INTO sentence_item_spans (id, sentence_item_id, start_codepoint, end_codepoint,
                                     span_order)
    VALUES (1, 1, 0, 2, 0)
    """,
    """
    INSERT INTO sentence_item_explanations (id, sentence_item_id, reading, core_meaning,
                                            meaning_in_context, nuance, example_sentence,
                                            generated_at, status)
    VALUES (1, 1, 'たなか', '다나카', '다나카', '', '田中です。', '2026-09-01T00:00:00Z',
            'validated')
    """,
    """
    INSERT INTO study_sessions (id, user_id, started_at, last_activity_at, target_minutes,
                                active_seconds)
    VALUES (1, 1, '2026-09-03T00:00:00Z', '2026-09-03T00:05:00Z', 10, 300)
    """,
    """
    INSERT INTO user_sentence_candidates (id, user_id, sentence_id, presentation_role,
                                          context_stage, status, created_at, updated_at)
    VALUES (1, 1, 1, 'new', 'anchor', 'consumed', '2026-09-03T00:00:00Z',
            '2026-09-03T00:01:00Z')
    """,
    """
    INSERT INTO user_sentence_candidate_targets (id, candidate_id, learning_item_id, is_new_item)
    VALUES (1, 1, 1, true)
    """,
    """
    INSERT INTO study_presentations (id, study_session_id, user_id, candidate_id, sentence_id,
                                     presentation_role, context_stage, shown_at, completed_at)
    VALUES (1, 1, 1, 1, 1, 'new', 'anchor', '2026-09-03T00:01:00Z', '2026-09-03T00:02:00Z')
    """,
    """
    INSERT INTO item_exposures (id, user_id, learning_item_id, study_presentation_id, sentence_id,
                                modality, context_stage, created_at)
    VALUES (1, 1, 1, 1, 1, 'reading', 'anchor', '2026-09-03T00:01:00Z')
    """,
    """
    INSERT INTO learning_events (id, user_id, study_session_id, study_presentation_id,
                                 sentence_id, learning_item_id, event_type, payload_json,
                                 client_event_id, created_at)
    VALUES (1, 1, 1, 1, 1, 1, 'item_clicked', '{}',
            '00000000-0000-4000-8000-000000000001', '2026-09-03T00:01:10Z'),
           (2, 1, 1, 1, 1, 1, 'self_report_known', '{"source": "sheet"}',
            '00000000-0000-4000-8000-000000000002', '2026-09-03T00:01:20Z')
    """,
    """
    INSERT INTO user_mastery (id, user_id, learning_item_id, comprehension_mastery,
                              evidence_count, mastery_algorithm_version, last_updated_at)
    VALUES (1, 1, 1, 0.7, 1, 'v1', '2026-09-03T00:01:20Z')
    """,
    """
    INSERT INTO review_states (id, user_id, learning_item_id, stability, difficulty, state, step,
                               last_review_at, next_review_at, reps, fsrs_params_version)
    VALUES (1, 1, 1, 2.5, 5.0, 2, NULL, '2026-09-03T00:01:20Z', '2026-09-05T00:01:20Z', 1,
            'fsrs-6')
    """,
    """
    INSERT INTO user_item_learning_state (id, user_id, learning_item_id, anchor_sentence_id,
                                          context_stage, updated_at)
    VALUES (1, 1, 1, 1, 'anchor', '2026-09-03T00:01:20Z')
    """,
    """
    INSERT INTO content_flags (id, user_id, sentence_id, reason, created_at)
    VALUES (1, 1, 2, 'unnatural', '2026-09-03T00:03:00Z')
    """,
)


@contextmanager
def _throwaway_database(postgres_admin_dsn: URL) -> Iterator[tuple[URL, Engine]]:
    """downgrade와 중간 revision을 쓰므로 공유 테스트 DB를 쓰면 안 된다."""
    database = f"nc_migration_{uuid.uuid4().hex[:12]}"
    dsn = db_support.recreate_database(postgres_admin_dsn, database)
    engine = sa.create_engine(dsn)
    try:
        yield dsn, engine
    finally:
        engine.dispose()
        db_support.drop_database(postgres_admin_dsn, database)


def _table_rows(engine: Engine) -> dict[str, list[dict[str, Any]]]:
    """테이블마다 전 행을 jsonb로 직렬화한다. 순서는 직렬화 문자열로 고정한다."""
    rows: dict[str, list[dict[str, Any]]] = {}
    with engine.connect() as connection:
        for table in sorted(_app_tables(engine)):
            # 테이블 이름은 inspector에서 온다. 사용자 입력이 아니다.
            query = f'SELECT to_jsonb(t) FROM "{table}" t ORDER BY to_jsonb(t)::text'  # noqa: S608
            rows[table] = list(connection.scalars(sa.text(query)))
    return rows


def _schema_shape(engine: Engine) -> dict[str, set[tuple[str | None, ...]]]:
    """컬럼(타입·NULL·default), 인덱스 정의, 제약 정의. 0003과 0004의 차이를 보는 데 쓴다."""
    queries = {
        "columns": (
            "SELECT table_name, column_name, data_type, is_nullable, column_default "
            "FROM information_schema.columns WHERE table_schema = 'public' "
            "AND table_name <> 'alembic_version'"
        ),
        "indexes": (
            "SELECT tablename, indexname, indexdef FROM pg_indexes "
            "WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
        ),
        "constraints": (
            "SELECT cls.relname, con.conname, pg_get_constraintdef(con.oid) "
            "FROM pg_constraint con "
            "JOIN pg_class cls ON cls.oid = con.conrelid "
            "JOIN pg_namespace ns ON ns.oid = cls.relnamespace "
            "WHERE ns.nspname = 'public' AND cls.relname <> 'alembic_version'"
        ),
    }
    with engine.connect() as connection:
        return {
            kind: {tuple(row) for row in connection.execute(sa.text(query))}
            for kind, query in queries.items()
        }


@pytest.mark.integration
def test_upgrade_to_ruby_json_preserves_existing_learning_records(
    postgres_admin_dsn: URL,
) -> None:
    """불변식 19: 학습 기록이 있는 0003 DB를 올려도 기존 행이 그대로이고 ruby_json은 NULL이다.

    NULL이어야 하는 이유: NULL이 "미계산"이고 backfill의 유일한 대상 조건이다. migration이
    기본값을 채우면 기존 문장이 전부 "계산했고 읽기 없음"으로 보여 영원히 ruby를 받지 못한다.
    """
    with _throwaway_database(postgres_admin_dsn) as (dsn, engine):
        db_support.alembic_upgrade(dsn, PRE_MVP02_REVISION)
        assert _current_revision(engine) == PRE_MVP02_REVISION
        with engine.begin() as connection:
            for statement in _SEED_0003_STATEMENTS:
                connection.execute(sa.text(statement))
        before = _table_rows(engine)
        empty_learning_tables = sorted(t for t in LEARNING_RECORD_TABLES if not before[t])
        assert empty_learning_tables == [], "보존 검사가 빈 테이블을 보고 있다"

        db_support.alembic_upgrade(dsn, RUBY_JSON_REVISION)
        assert _current_revision(engine) == RUBY_JSON_REVISION
        after = _table_rows(engine)

        assert set(after) == set(before)
        for table in sorted(before):
            if table == "sentences":
                continue
            assert after[table] == before[table], table

        assert len(after["sentences"]) == len(before["sentences"]) == 2
        assert [row["ruby_json"] for row in after["sentences"]] == [None, None]
        # ruby_json 키가 더해져 직렬화 문자열 순서가 바뀔 수 있으므로 id로 맞춰 비교한다.
        after_without_ruby = {
            row["id"]: {key: value for key, value in row.items() if key != "ruby_json"}
            for row in after["sentences"]
        }
        assert after_without_ruby == {row["id"]: row for row in before["sentences"]}


@pytest.mark.integration
def test_ruby_json_migration_changes_only_that_column(postgres_admin_dsn: URL) -> None:
    """ADR-021 결정 2: MVP-02 migration은 `ADD COLUMN ruby_json JSONB NULL`(default 없음)뿐이다.

    `compare_metadata`는 모델과 migration에 **함께** 인덱스·CHECK를 더하면 통과한다. 그래서
    모델을 보지 않고 0003과 0004의 실제 DB 스키마 차이를 본다. 되돌린 뒤 0003과 같은지도 본다.
    """
    with _throwaway_database(postgres_admin_dsn) as (dsn, engine):
        db_support.alembic_upgrade(dsn, PRE_MVP02_REVISION)
        at_0003 = _schema_shape(engine)

        db_support.alembic_upgrade(dsn, RUBY_JSON_REVISION)
        at_0004 = _schema_shape(engine)

        assert at_0004["columns"] - at_0003["columns"] == {
            ("sentences", "ruby_json", "jsonb", "YES", None)
        }
        assert at_0003["columns"] - at_0004["columns"] == set()
        assert at_0004["indexes"] == at_0003["indexes"]
        assert at_0004["constraints"] == at_0003["constraints"]

        db_support.alembic_downgrade(dsn, PRE_MVP02_REVISION)
        assert _current_revision(engine) == PRE_MVP02_REVISION
        assert _schema_shape(engine) == at_0003


@pytest.mark.integration
def test_migrated_schema_matches_the_models(db_engine: Engine) -> None:
    """migration과 SQLAlchemy 모델이 어긋나지 않는다.

    이 테스트가 없으면 모델에만 있는 컬럼이 DB에 없어도 아무도 모른다
    (fixture가 create_all()이 아니라 migration으로 스키마를 만들기 때문에
    모델 쪽 정의는 런타임에 검증되지 않는다).
    """
    with db_engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        diffs = compare_metadata(context, Base.metadata)
    assert diffs == []


@pytest.mark.integration
def test_shared_test_database_is_at_head(db_engine: Engine) -> None:
    """모든 integration 테스트가 "빈 DB → migration" 경로로 만들어진 스키마를 쓴다."""
    head = ScriptDirectory.from_config(db_support.alembic_config(db_engine.url)).get_current_head()
    assert _current_revision(db_engine) == head


# --------------------------------------------------------------------------
# MVP-03 다언어 migration (불변식 26, ADR-023, 13_ACCEPTANCE_CRITERIA.md 1·4).
# MVP-02와 같은 이유로 "빈 DB 왕복"만으로는 부족하다. 여기서는 더 강하다 --- 0005는
# 컬럼을 더하기만 하는 것이 아니라 **리네임하고 NOT NULL을 푼다.** 데이터가 있는 DB에서
# 행이 보존되는지, 명세 밖의 schema를 건드리지 않는지, 그리고 어떤 upgrade()도 테이블·
# 컬럼을 DROP하지 않는지를 각각 본다.
# --------------------------------------------------------------------------

PRE_MVP03_REVISION = "0004"
MULTILINGUAL_REVISION = "0005"

# language 축을 갖는 콘텐츠 엔티티 다섯(ADR-023 결정 1). 보존 검사가 의미를 가지려면 이
# 다섯이 전부 비어 있지 않아야 한다 --- 빈 테이블의 language는 무엇이든 'ja'다.
MULTILINGUAL_TABLES = frozenset(
    {
        "learning_items",
        "sentences",
        "study_sessions",
        "prompt_versions",
        "generation_jobs",
    }
)

# 0004 스키마에 raw SQL로 넣는다. 0003 분량에 prompt_versions / generation_jobs를 더한
# 것이다 --- 그 둘이 0005에서 language를 얻는데 `_SEED_0003_STATEMENTS`에는 없다.
# generation_jobs가 맨 앞인 이유는 `sentences.generation_job_id` FK다.
_SEED_0004_STATEMENTS = (
    """
    INSERT INTO generation_jobs (id, job_type, status, payload_json, idempotency_key,
                                 max_attempts, next_attempt_at, created_at)
    VALUES (1, 'GENERATE_SENTENCE_BATCH', 'completed', '{"target_item_ids": [1]}',
            'batch-migration-1', 3, '2026-09-02T00:00:00Z', '2026-09-02T00:00:00Z')
    """,
    *_SEED_0003_STATEMENTS,
    """
    INSERT INTO prompt_versions (id, task_type, version, provider, model, created_at, active)
    VALUES (1, 'GENERATE_SENTENCE_BATCH', 'sentence_gen_v1', 'stub', 'test-model',
            '2026-09-01T00:00:00Z', true)
    """,
)


def _comparable(rows: list[dict[str, Any]], *, drop: set[str], rename: dict[str, str]) -> list[str]:
    """비교 가능한 투영. 0005가 더한 컬럼을 빼고 리네임된 컬럼을 옛 이름에 맞춘다.

    정렬을 다시 하는 이유: `_table_rows`는 직렬화 문자열로 정렬하는데 컬럼이 늘거나 이름이
    바뀌면 그 문자열이 달라져 행 순서가 뒤집힐 수 있다.
    """
    return sorted(
        json.dumps(
            {rename.get(key, key): value for key, value in row.items() if key not in drop},
            sort_keys=True,
            ensure_ascii=False,
        )
        for row in rows
    )


def _projection(rows: list[dict[str, Any]]) -> list[str]:
    return _comparable(rows, drop={"language", "seed_id"}, rename={"japanese": "text"})


@pytest.mark.integration
def test_upgrade_to_multilingual_preserves_existing_rows(postgres_admin_dsn: URL) -> None:
    """불변식 26: 0004의 데이터 위에 0005를 올려도 모든 행이 그대로다.

    컬럼 리네임과 NOT NULL 완화가 섞여 있어 MVP-02보다 위험하다. `japanese`가 `text`로
    옮겨가며 값을 잃으면 운영 DB의 문장 전체가 사라지고, 되돌릴 방법은 백업뿐이다.

    기존 행의 `language`는 전부 `'ja'`여야 한다(기존 콘텐츠는 전부 일본어다). `seed_id`는
    전부 NULL이어야 한다 --- 값을 채우는 것은 migration이 아니라 `backfill_seed_id.py`이고,
    migration이 추측해서 채우면 그 추측이 영어 seed의 증분 적재 판단을 오염시킨다.
    """
    with _throwaway_database(postgres_admin_dsn) as (dsn, engine):
        db_support.alembic_upgrade(dsn, PRE_MVP03_REVISION)
        assert _current_revision(engine) == PRE_MVP03_REVISION
        with engine.begin() as connection:
            for statement in _SEED_0004_STATEMENTS:
                connection.execute(sa.text(statement))
        before = _table_rows(engine)
        guarded = LEARNING_RECORD_TABLES | MULTILINGUAL_TABLES
        assert sorted(t for t in guarded if not before[t]) == [], (
            "보존 검사가 빈 테이블을 보고 있다"
        )

        db_support.alembic_upgrade(dsn, MULTILINGUAL_REVISION)
        assert _current_revision(engine) == MULTILINGUAL_REVISION
        after = _table_rows(engine)

        assert set(after) == set(before)
        for table in sorted(before):
            assert _projection(after[table]) == _projection(before[table]), table

        # 다섯 테이블의 기존 행은 전부 일본어다.
        for table in sorted(MULTILINGUAL_TABLES):
            assert [row["language"] for row in after[table]] == ["ja"] * len(after[table]), table
        # seed_id는 migration이 채우지 않는다.
        for table in ("learning_items", "sentences"):
            assert [row["seed_id"] for row in after[table]] == [None] * len(after[table]), table
        # 리네임이 값을 보존했다.
        assert sorted(row["text"] for row in after["sentences"]) == sorted(
            row["japanese"] for row in before["sentences"]
        )
        # NOT NULL을 풀었다고 기존 값이 비워지지 않는다.
        assert [row["reading"] for row in after["learning_items"]] == [
            row["reading"] for row in before["learning_items"]
        ]
        assert [row["reading"] for row in after["sentence_item_explanations"]] == [
            row["reading"] for row in before["sentence_item_explanations"]
        ]


# 0005가 더하는 컬럼. `column_default`가 전부 None이어야 한다 --- `language`에
# server_default가 있으면 언어를 빠뜨린 INSERT가 조용히 일본어가 된다(04_DB_SPEC.md의
# `공통 규칙`). 아래 테스트가 그 자리(튜플의 5번째)를 따로 단언한다.
EXPECTED_ADDED_COLUMNS = {
    *((table, "language", "character varying", "NO", None) for table in MULTILINGUAL_TABLES),
    ("learning_items", "seed_id", "text", "YES", None),
    ("sentences", "seed_id", "text", "YES", None),
    # 리네임과 NOT NULL 완화는 "없던 (table, column, ...) 조합"으로 나타난다.
    ("sentences", "text", "text", "NO", None),
    ("learning_items", "reading", "text", "YES", None),
    ("sentence_item_explanations", "reading", "text", "YES", None),
}
EXPECTED_REMOVED_COLUMNS = {
    ("sentences", "japanese", "text", "NO", None),
    ("learning_items", "reading", "text", "NO", None),
    ("sentence_item_explanations", "reading", "text", "NO", None),
}
EXPECTED_ADDED_INDEXES = {
    "uq_learning_items_seed_id",
    "uq_sentences_seed_id",
    "uq_prompt_versions_task_type_language_version",
}
EXPECTED_REMOVED_INDEXES = {"uq_prompt_versions_task_type_version"}
EXPECTED_ADDED_CONSTRAINTS = {
    *(f"ck_{table}_language" for table in MULTILINGUAL_TABLES),
    "ck_sentences_ruby_json_ja_only",
    "uq_prompt_versions_task_type_language_version",
}
EXPECTED_REMOVED_CONSTRAINTS = {"uq_prompt_versions_task_type_version"}


def _names(shape: dict[str, set[tuple[str | None, ...]]], kind: str) -> set[str | None]:
    """인덱스·제약을 **이름 집합**으로 본다.

    정의 문자열 전체를 비교하지 않는 이유: PostgreSQL이 `IN (...)`을 `= ANY (ARRAY[...])`로
    다시 쓰는 등 저장 형태를 정규화하므로, 원문 비교는 migration이 무엇을 바꿨는지가 아니라
    PostgreSQL 버전의 출력 규칙을 검사하게 된다. 정의가 맞는지는
    `test_schema_invariants.py`와 `test_language_scope.py`가 본다.
    """
    return {row[1] for row in shape[kind]}


@pytest.mark.integration
def test_multilingual_migration_changes_only_the_spec_schema(postgres_admin_dsn: URL) -> None:
    """0005는 04_DB_SPEC.md의 `한 migration이 하는 일` 여섯 단계 **만** 한다.

    `compare_metadata`(아래 `test_migrated_schema_matches_the_models`)는 모델과 migration에
    **함께** 무언가를 더하면 통과한다. 그래서 모델을 보지 않고 0004와 0005의 실제 DB 스키마
    차이를 본다. 되돌린 뒤 0004와 같은지도 본다 --- 한 방향으로만 도는 migration은 빈 DB
    왕복 테스트를 깨뜨린다.
    """
    with _throwaway_database(postgres_admin_dsn) as (dsn, engine):
        db_support.alembic_upgrade(dsn, PRE_MVP03_REVISION)
        at_0004 = _schema_shape(engine)

        db_support.alembic_upgrade(dsn, MULTILINGUAL_REVISION)
        at_0005 = _schema_shape(engine)

        added_columns = at_0005["columns"] - at_0004["columns"]
        assert added_columns == EXPECTED_ADDED_COLUMNS
        assert at_0004["columns"] - at_0005["columns"] == EXPECTED_REMOVED_COLUMNS
        # server_default가 하나라도 생기면 언어 누락이 조용히 'ja'가 된다.
        assert [column for column in added_columns if column[4] is not None] == []

        assert _names(at_0005, "indexes") - _names(at_0004, "indexes") == EXPECTED_ADDED_INDEXES
        assert _names(at_0004, "indexes") - _names(at_0005, "indexes") == EXPECTED_REMOVED_INDEXES
        assert (
            _names(at_0005, "constraints") - _names(at_0004, "constraints")
            == EXPECTED_ADDED_CONSTRAINTS
        )
        assert (
            _names(at_0004, "constraints") - _names(at_0005, "constraints")
            == EXPECTED_REMOVED_CONSTRAINTS
        )

        db_support.alembic_downgrade(dsn, PRE_MVP03_REVISION)
        assert _current_revision(engine) == PRE_MVP03_REVISION
        assert _schema_shape(engine) == at_0004


MIGRATIONS_DIR = db_support.REPO_ROOT / "backend" / "migrations" / "versions"
DROP_IN_SQL = ("DROP TABLE", "DROP COLUMN")


def _upgrade_body(path: Path) -> ast.FunctionDef:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    functions = [
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "upgrade"
    ]
    assert len(functions) == 1, f"{path.name}에 upgrade()가 하나가 아니다"
    return functions[0]


def test_upgrade_never_drops_tables_or_columns() -> None:
    """불변식 26: 어떤 migration의 `upgrade()`도 테이블·컬럼을 DROP하지 않는다.

    운영 DB는 reset하지 않고 데이터 위에 upgrade만 올린다(04_DB_SPEC.md의 `운영 DB에
    migration을 적용하는 경로`). upgrade 방향의 DROP은 되돌릴 수 없는 데이터 손실이며,
    백업 복원 외에 복구 수단이 없다.

    **`downgrade()`는 대상이 아니다.** 그쪽은 빈 DB 왕복 테스트를 위해 DROP을 포함할
    수밖에 없고, 운영 경로에 downgrade 명령은 없다.

    소스를 AST로 읽는다 --- 문자열 검색은 주석과 docstring("DROP TABLE을 하지 않는다")에
    걸린다. `op.execute`에 실린 raw SQL은 호출 안의 문자열 리터럴을 따로 본다.
    """
    paths = sorted(MIGRATIONS_DIR.glob("*.py"))
    assert len(paths) >= 5, f"migration 파일을 {len(paths)}개밖에 못 봤다 --- 경로가 틀렸다"

    offenders: list[str] = []
    for path in paths:
        for node in ast.walk(_upgrade_body(path)):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr in {"drop_table", "drop_column"}:
                offenders.append(f"{path.name}: op.{node.func.attr}()")
            if node.func.attr != "execute":
                continue
            for literal in ast.walk(node):
                if not isinstance(literal, ast.Constant) or not isinstance(literal.value, str):
                    continue
                statement = " ".join(literal.value.upper().split())
                offenders += [
                    f"{path.name}: op.execute(... {keyword} ...)"
                    for keyword in DROP_IN_SQL
                    if keyword in statement
                ]
    assert offenders == []
