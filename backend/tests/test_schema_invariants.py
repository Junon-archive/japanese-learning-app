"""스키마 불변식. 각 테스트는 어느 명세/불변식을 지키는지 주석으로 근거를 남긴다.

여기 있는 것은 전부 "형태" 검사다. 제약이 실제로 거부하는지(동작)는
`test_db_constraints.py`가 본다.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Engine

from app.models import Base

REPO_ROOT = Path(__file__).resolve().parents[2]

# 04_DB_SPEC.md의 테이블 목록(`## <table>` 절). 19개다.
SPEC_TABLES = frozenset(
    {
        "users",
        "auth_sessions",
        "learning_items",
        "sentences",
        "sentence_items",
        "sentence_item_spans",
        "sentence_item_explanations",
        "user_mastery",
        "review_states",
        "user_item_learning_state",
        "item_exposures",
        "user_sentence_candidates",
        "user_sentence_candidate_targets",
        "study_presentations",
        "study_sessions",
        "learning_events",
        "generation_jobs",
        "content_flags",
        "prompt_versions",
    }
)


def _columns(engine: Engine) -> list[sa.Row[tuple[str, str, str, str | None]]]:
    with engine.connect() as connection:
        return list(
            connection.execute(
                sa.text(
                    "SELECT table_name, column_name, data_type, is_nullable "
                    "FROM information_schema.columns WHERE table_schema = 'public'"
                )
            )
        )


def _check_constraints(engine: Engine) -> list[sa.Row[tuple[str, str, str]]]:
    """(table, column, constraint_name). PostgreSQL 16의 NOT NULL은 pg_constraint에 없다."""
    with engine.connect() as connection:
        return list(
            connection.execute(
                sa.text(
                    """
                    SELECT cls.relname AS table_name,
                           att.attname AS column_name,
                           con.conname AS constraint_name
                    FROM pg_constraint con
                    JOIN pg_class cls ON cls.oid = con.conrelid
                    JOIN pg_namespace ns ON ns.oid = cls.relnamespace
                    JOIN unnest(con.conkey) AS key(attnum) ON TRUE
                    JOIN pg_attribute att
                      ON att.attrelid = cls.oid AND att.attnum = key.attnum
                    WHERE con.contype = 'c' AND ns.nspname = 'public'
                    """
                )
            )
        )


def _check_constraint_defs(engine: Engine) -> dict[tuple[str, str], str]:
    """(table, constraint_name) -> `CHECK (...)` 원문. enum 허용값을 확인하는 데 쓴다."""
    with engine.connect() as connection:
        rows = connection.execute(
            sa.text(
                """
                SELECT cls.relname AS table_name,
                       con.conname AS constraint_name,
                       pg_get_constraintdef(con.oid) AS definition
                FROM pg_constraint con
                JOIN pg_class cls ON cls.oid = con.conrelid
                JOIN pg_namespace ns ON ns.oid = cls.relnamespace
                WHERE con.contype = 'c' AND ns.nspname = 'public'
                """
            )
        )
        return {(row.table_name, row.constraint_name): row.definition for row in rows}


@pytest.mark.integration
def test_all_spec_tables_exist(db_engine: Engine) -> None:
    # 04_DB_SPEC.md. 테이블이 사라지거나, 명세에 없는 테이블(예: demo 전용)이
    # 늘어나는 것을 둘 다 잡는다.
    tables = set(sa.inspect(db_engine).get_table_names(schema="public")) - {"alembic_version"}
    assert tables == set(SPEC_TABLES)
    assert len(tables) == 19


@pytest.mark.integration
def test_identity_unique_constraints_exist_with_their_spec_names(db_engine: Engine) -> None:
    """이 6개는 "무엇이 같은 것인가"의 정의다(04_DB_SPEC.md의 Unique 절).

    이름까지 고정하는 이유: 이름 없는 제약은 Alembic downgrade에서 DROP할 수
    없고(04_DB_SPEC.md Migration Rule), ON CONFLICT 구문이 제약 이름을 참조한다.
    """
    expected = {
        "uq_user_mastery_user_id_learning_item_id",
        "uq_review_states_user_id_learning_item_id",
        "uq_user_item_learning_state_user_id_learning_item_id",
        # 불변식 5: presentation당 item 1회.
        "uq_item_exposures_study_presentation_id_learning_item_id",
        # 불변식 10: event POST의 idempotency.
        "uq_learning_events_user_id_client_event_id",
        "uq_generation_jobs_idempotency_key",
    }
    inspector = sa.inspect(db_engine)
    found = {
        constraint["name"]
        for table in SPEC_TABLES
        for constraint in inspector.get_unique_constraints(table, schema="public")
        if constraint["name"] is not None
    }
    assert expected <= found


@pytest.mark.integration
def test_no_naive_timestamp_columns(db_engine: Engine) -> None:
    # 불변식 9: 모든 timestamp는 UTC(timestamptz) 저장.
    # timestamp without time zone이 하나라도 있으면 서버 로컬 시각이 섞여 들어오고
    # 그 뒤로는 어떤 값이 UTC인지 알 수 없다.
    naive = [
        (row.table_name, row.column_name)
        for row in _columns(db_engine)
        if row.data_type == "timestamp without time zone"
    ]
    assert naive == []


@pytest.mark.integration
def test_sentences_is_global_content(db_engine: Engine) -> None:
    # 불변식 11: sentences에 user_id도, 사용자별 role도 두지 않는다.
    # 여기에 user_id가 생기면 같은 문장이 사용자 수만큼 복제되고 global content
    # 재사용이 불가능해진다.
    columns = {row.column_name for row in _columns(db_engine) if row.table_name == "sentences"}
    assert "user_id" not in columns
    assert columns.isdisjoint({"role", "presentation_role", "review_reason", "is_new_item"})


@pytest.mark.integration
def test_sentence_items_has_no_role_column(db_engine: Engine) -> None:
    # 04_DB_SPEC.md: new/review/exploration은 사용자별·시점별 속성이므로
    # 언어적 annotation 테이블에 두지 않는다(v0.2의 role = incidental 설계는 제거됨).
    columns = {row.column_name for row in _columns(db_engine) if row.table_name == "sentence_items"}
    assert "role" not in columns


@pytest.mark.integration
def test_review_states_follows_the_fsrs_binding(db_engine: Engine) -> None:
    # ADR-003: scheduled_days는 due - last_review의 파생값이라 저장하지 않고,
    # card_id는 canonical identity를 둘로 만들기 때문에 저장하지 않는다.
    columns = {row.column_name for row in _columns(db_engine) if row.table_name == "review_states"}
    assert "scheduled_days" not in columns
    assert "card_id" not in columns
    # 반대로 ADR-003이 유지하기로 한 것들은 있어야 한다.
    assert {"step", "reps", "lapses", "deferred_until"} <= columns


@pytest.mark.integration
def test_no_mode_column_and_no_demo_table(db_engine: Engine) -> None:
    # 불변식 8 / 04_DB_SPEC.md Demo Data: demo 전용 테이블·row·mode 컬럼을 두지 않는다.
    # exact match로 본다. prompt_versions.model과 sentence_item_explanations.model은
    # provider model 이름이며 LIKE '%mode%'로 검사하면 여기에 걸린다.
    columns = _columns(db_engine)
    assert [(row.table_name, row.column_name) for row in columns if row.column_name == "mode"] == []
    assert [row.table_name for row in columns if "demo" in row.table_name] == []
    assert [(row.table_name, row.column_name) for row in columns if "demo" in row.column_name] == []


@pytest.mark.integration
def test_enum_columns_are_backed_by_check_constraints(db_engine: Engine) -> None:
    """`sa.Enum(native_enum=False)`에 `create_constraint=True`를 빠뜨리면 CHECK 없는
    맨 varchar가 된다. 코드에는 Enum이 적혀 있으니 "enum을 적용했다"고 착각한 채
    DB 방어선만 사라진다. 그 상태를 잡는 테스트다.
    """
    checked = {(row.table_name, row.column_name) for row in _check_constraints(db_engine)}
    assert checked, "CHECK 제약이 하나도 없다"

    enum_columns = {
        (table.name, column.name)
        for table in Base.metadata.tables.values()
        for column in table.columns
        if isinstance(column.type, sa.Enum)
    }
    assert enum_columns, "모델에 Enum 컬럼이 하나도 없다 (테스트 전제가 깨졌다)"
    assert enum_columns <= checked


@pytest.mark.integration
def test_mastery_axes_are_nullable_scores_with_range_checks(db_engine: Engine) -> None:
    """02_LEARNING_POLICY.md: NULL은 "능력 0"이 아니라 "evidence 부족"이다.

    boolean Known/Unknown으로 구현하면 이 구분이 사라진다. 값은 0..1 실수이며
    범위는 DB가 강제한다(실제 거부 동작은 test_db_constraints.py).
    """
    axes = {
        row.column_name: row
        for row in _columns(db_engine)
        if row.table_name == "user_mastery"
        and row.column_name in {"comprehension_mastery", "listening_mastery"}
    }
    assert set(axes) == {"comprehension_mastery", "listening_mastery"}
    for row in axes.values():
        assert row.data_type == "double precision", row.column_name
        assert row.is_nullable == "YES", row.column_name

    ranged = {
        row.column_name
        for row in _check_constraints(db_engine)
        if row.table_name == "user_mastery" and row.constraint_name.endswith("_range")
    }
    assert ranged == {"comprehension_mastery", "listening_mastery"}


@pytest.mark.integration
def test_client_event_id_is_a_uuid_column(db_engine: Engine) -> None:
    # 불변식 10: event POST idempotency. 텍스트로 두면 대소문자/하이픈 표기 차이로
    # 같은 event가 두 행이 된다.
    row = next(
        row
        for row in _columns(db_engine)
        if row.table_name == "learning_events" and row.column_name == "client_event_id"
    )
    assert row.data_type == "uuid"
    assert row.is_nullable == "NO"


def test_app_tree_does_not_import_pgserver() -> None:
    """ADR-002: pgserver import는 테스트 fixture와 로컬 스크립트에만 존재한다.

    애플리케이션이 로컬 DB 기동을 알게 되는 순간 "두 경로를 분기하지 않는다"가
    깨진다. DB가 필요 없는 검사이므로 integration 마크를 붙이지 않는다.
    """
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in (REPO_ROOT / "backend" / "app").rglob("*.py")
        if "pgserver" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


# --------------------------------------------------------------------------
# flag → quarantine → evidence 무효화의 저장 메커니즘 (10_ERROR_HANDLING.md,
# Regression H). `compare_metadata`(test_migrations.py)는 모델과 migration에서
# **동시에** 컬럼을 지우면 통과한다. 그래서 여기서는 모델을 보지 않고
# information_schema가 실제로 무엇을 들고 있는지만 본다.
# --------------------------------------------------------------------------

# 04_DB_SPEC.md의 item_exposures 절. column_name -> is_nullable.
SPEC_ITEM_EXPOSURE_COLUMNS = {
    "id": "NO",
    "user_id": "NO",
    "learning_item_id": "NO",
    "study_presentation_id": "NO",
    "sentence_id": "NO",
    "modality": "NO",
    "context_stage": "NO",
    "created_at": "NO",
    # 10_ERROR_HANDLING.md: flag된 content에서 파생된 evidence를 재계산에서 제외한다.
    "invalidated_at": "YES",
}

# 04_DB_SPEC.md의 content_flags 절.
SPEC_CONTENT_FLAG_COLUMNS = {
    "id": "NO",
    "user_id": "NO",
    "sentence_id": "YES",
    "learning_item_id": "YES",
    "study_presentation_id": "YES",
    "reason": "NO",
    "note": "YES",
    "created_at": "NO",
    "resolved_at": "YES",
}

# quarantine 상태값을 들고 있어야 하는 status 컬럼들.
QUARANTINABLE_STATUS_COLUMNS = (
    ("sentences", "status"),
    ("sentence_item_explanations", "status"),
    ("user_sentence_candidates", "status"),
)


def _nullability(engine: Engine, table: str) -> dict[str, str]:
    return {
        row.column_name: row.is_nullable
        for row in _columns(engine)
        if row.table_name == table
        # is_nullable은 information_schema에서 'YES'/'NO' 문자열이다.
        and row.is_nullable is not None
    }


@pytest.mark.integration
def test_item_exposures_has_exactly_the_spec_columns(db_engine: Engine) -> None:
    """`invalidated_at`이 사라지면 Regression H가 기록될 곳이 없어진다.

    부분집합이 아니라 **완전 일치**로 본다. 컬럼이 늘어나는 것도(예: counter 컬럼을
    다시 도입해 canonical source를 둘로 만드는 것) 명세 위반이다.
    """
    assert _nullability(db_engine, "item_exposures") == SPEC_ITEM_EXPOSURE_COLUMNS


@pytest.mark.integration
def test_invalidated_at_is_a_nullable_timestamptz(db_engine: Engine) -> None:
    """boolean 플래그나 행 삭제로 바꾸면 "언제 무효화됐는지"를 잃는다.

    04_DB_SPEC.md: "이미 기록된 evidence를 삭제하거나 값을 바꾸지 않는다.
    무효화는 전용 컬럼으로 표현한다."
    """
    rows = [
        row
        for row in _columns(db_engine)
        if row.table_name == "item_exposures" and row.column_name == "invalidated_at"
    ]
    assert rows, "item_exposures.invalidated_at이 없다 (Regression H의 기록 위치가 사라졌다)"
    assert rows[0].data_type == "timestamp with time zone"
    assert rows[0].is_nullable == "YES"


@pytest.mark.integration
def test_content_flags_has_exactly_the_spec_columns(db_engine: Engine) -> None:
    """flag의 대상 세 가지(sentence / learning_item / presentation)가 모두 nullable로
    있어야 한다. 하나라도 없어지면 그 대상에 대한 flag를 기록할 수 없다.
    """
    assert _nullability(db_engine, "content_flags") == SPEC_CONTENT_FLAG_COLUMNS


@pytest.mark.integration
@pytest.mark.parametrize(("table", "column"), QUARANTINABLE_STATUS_COLUMNS)
def test_quarantined_is_an_allowed_status(db_engine: Engine, table: str, column: str) -> None:
    """quarantine 동작은 MVP 필수다(10_ERROR_HANDLING.md).

    CHECK 제약의 허용값 목록에서 `quarantined`가 빠지면 flag 처리가 런타임에
    IntegrityError로 죽는다. enum 상수만 보면(파이썬 쪽) DB가 실제로 받아주는지는
    알 수 없으므로 제약 원문을 읽는다.
    """
    definitions = {
        name: definition
        for (found_table, name), definition in _check_constraint_defs(db_engine).items()
        if found_table == table
    }
    matching = [
        definition
        for name, definition in definitions.items()
        if f"{column})::text" in definition or f" {column} " in definition
    ]
    assert matching, f"{table}.{column}에 CHECK 제약이 없다 (허용값이 강제되지 않는다)"
    assert all("quarantined" in definition for definition in matching), matching
