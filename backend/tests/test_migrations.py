"""Alembic migration 검증 (12_TEST_PLAN.md "Alembic from empty DB").

04_DB_SPEC.md Migration Rule: "빈 DB에서 migration만으로 전체 schema를
재현할 수 있어야 한다."
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.engine import URL, Engine

from app.models import Base
from tests import db_support

pytestmark = pytest.mark.integration

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


def test_shared_test_database_is_at_head(db_engine: Engine) -> None:
    """모든 integration 테스트가 "빈 DB → migration" 경로로 만들어진 스키마를 쓴다."""
    head = ScriptDirectory.from_config(db_support.alembic_config(db_engine.url)).get_current_head()
    assert _current_revision(db_engine) == head
