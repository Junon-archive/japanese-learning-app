"""`language` 축이 어디에 있고 어디에 **없는지**, 그리고 실제로 무엇을 거부하는지.

ADR-023 결정 1·3·5, 04_DB_SPEC.md의 `공통 규칙`, 불변식 21·23,
13_ACCEPTANCE_CRITERIA.md(MVP-03) 4~7.

`tests/factories.py`를 쓰지 않는다. factory가 `language`를 공급하게 되면 "값을 빠뜨린
INSERT가 실패하는가"를 factory가 가려 버려서, 여기서 보려는 것이 정확히 보이지 않는다.
ORM 생성자도 아니고 raw SQL로 넣는 이유도 같다 --- 모델의 기본값이나 타입 변환이 끼면
DB 제약이 아니라 SQLAlchemy를 검사하게 된다.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration

# language 축을 갖는 콘텐츠 엔티티 다섯(ADR-023 결정 1).
LANGUAGE_TABLES = (
    "learning_items",
    "sentences",
    "study_sessions",
    "prompt_versions",
    "generation_jobs",
)

# **language를 갖지 않는** 사용자별 학습 테이블 여덟. `learning_item_id`(또는
# `sentence_id`)가 이미 언어를 결정하므로 같은 값을 두 곳에 두면 한쪽만 고쳐지는 순간
# 갈라진다(불변식 21). 이름을 열거하는 이유는 나중에 누가 편의상(예: Ready Pool 조회의
# join을 줄이려고) 추가하는 것을 막는 것이 이 목록의 목적이기 때문이다.
USER_SCOPED_TABLES = (
    "user_mastery",
    "review_states",
    "user_item_learning_state",
    "item_exposures",
    "user_sentence_candidates",
    "user_sentence_candidate_targets",
    "study_presentations",
    "learning_events",
)

NOW = "2026-10-01T00:00:00Z"
RUBY_JSON = '{"algorithm_version": 2, "spans": [], "omitted": {}, "corrected": {}}'


# --------------------------------------------------------------------------
# raw SQL 헬퍼
# --------------------------------------------------------------------------


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _insert(session: Session, table: str, values: dict[str, object]) -> int:
    """`values` 그대로 INSERT하고 id를 돌려준다. 테이블 이름은 이 모듈의 상수에서만 온다."""
    columns = ", ".join(values)
    placeholders = ", ".join(f":{name}" for name in values)
    statement = f"INSERT INTO {table} ({columns}) VALUES ({placeholders}) RETURNING id"  # noqa: S608
    result: int = session.execute(sa.text(statement), values).scalar_one()
    return result


def _without(values: dict[str, object], key: str) -> dict[str, object]:
    return {name: value for name, value in values.items() if name != key}


def _user(session: Session) -> int:
    return _insert(
        session,
        "users",
        {
            "login_id": _unique("lang"),
            "password_hash": "x",
            "timezone": "Asia/Seoul",
            "starting_level": "beginner",
            "created_at": NOW,
        },
    )


def _learning_item_values(**overrides: object) -> dict[str, object]:
    return {
        "language": "ja",
        "type": "word",
        "lemma": _unique("lemma"),
        "reading": "よみ",
        "default_meaning": "뜻",
        "origin": "seed",
        "created_at": NOW,
    } | overrides


def _sentence_values(**overrides: object) -> dict[str, object]:
    return {
        "language": "ja",
        "text": "田中さんは来ます。",
        "korean_translation": "다나카 씨는 옵니다.",
        "source_type": "seed",
        "normalized_hash": _unique("hash"),
        "status": "validated",
        "created_at": NOW,
    } | overrides


def _prompt_version_values(**overrides: object) -> dict[str, object]:
    return {
        "task_type": "EXPLAIN_ITEM",
        "language": "ja",
        "version": _unique("explain_item_v"),
        "provider": "stub",
        "model": "test-model",
        "created_at": NOW,
    } | overrides


def _generation_job_values(**overrides: object) -> dict[str, object]:
    return {
        "language": "ja",
        "job_type": "EXPLAIN_ITEM",
        "status": "queued",
        "idempotency_key": _unique("job"),
        "max_attempts": 1,
        "next_attempt_at": NOW,
        "created_at": NOW,
    } | overrides


def _study_session_values(user_id: int, **overrides: object) -> dict[str, object]:
    return {
        "user_id": user_id,
        "language": "ja",
        "started_at": NOW,
        "last_activity_at": NOW,
        "target_minutes": 10,
    } | overrides


def _row_values(session: Session, table: str) -> dict[str, object]:
    """다섯 테이블 각각의 **유효한** 한 행. 여기서 `language`만 빼거나 바꿔 쓴다."""
    if table == "learning_items":
        return _learning_item_values()
    if table == "sentences":
        return _sentence_values()
    if table == "prompt_versions":
        return _prompt_version_values()
    if table == "generation_jobs":
        return _generation_job_values()
    if table == "study_sessions":
        return _study_session_values(_user(session))
    raise AssertionError(f"알 수 없는 테이블: {table}")


def _columns(engine: Engine, table: str) -> dict[str, sa.Row[Any]]:
    with engine.connect() as connection:
        rows = connection.execute(
            sa.text(
                "SELECT column_name, data_type, is_nullable, column_default, character_maximum_length "
                "FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = :table"
            ),
            {"table": table},
        )
        return {row.column_name: row for row in rows}


def _check_definitions(engine: Engine, table: str, column: str) -> dict[str, str]:
    """(제약 이름 -> 정의). 해당 컬럼을 포함하는 CHECK만 고른다."""
    with engine.connect() as connection:
        rows = connection.execute(
            sa.text(
                """
                SELECT con.conname AS name, pg_get_constraintdef(con.oid) AS definition
                FROM pg_constraint con
                JOIN pg_class cls ON cls.oid = con.conrelid
                JOIN pg_namespace ns ON ns.oid = cls.relnamespace
                JOIN unnest(con.conkey) AS key(attnum) ON TRUE
                JOIN pg_attribute att ON att.attrelid = cls.oid AND att.attnum = key.attnum
                WHERE con.contype = 'c' AND ns.nspname = 'public'
                  AND cls.relname = :table AND att.attname = :column
                """
            ),
            {"table": table, "column": column},
        )
        return {row.name: row.definition for row in rows}


# --------------------------------------------------------------------------
# 1. 다섯 테이블이 language를 갖는다
# --------------------------------------------------------------------------


@pytest.mark.parametrize("table", LANGUAGE_TABLES)
def test_content_tables_have_a_language_column_without_a_default(
    db_engine: Engine, table: str
) -> None:
    """04_DB_SPEC.md의 `공통 규칙`: NOT NULL, CHECK `ja|en`, **server_default 없음**.

    기본값이 있으면 언어를 빠뜨린 INSERT가 조용히 일본어가 된다 --- 영어 콘텐츠가 ja로
    쌓이고 그 뒤로는 어느 행이 잘못 들어왔는지 알 수 없다.
    """
    column = _columns(db_engine, table).get("language")
    assert column is not None, f"{table}.language가 없다"
    assert column.is_nullable == "NO", table
    assert column.column_default is None, table

    checks = _check_definitions(db_engine, table, "language")
    name = f"ck_{table}_language"
    assert name in checks, f"{table}: {sorted(checks)}"
    # PostgreSQL이 `IN (...)`을 `= ANY (ARRAY[...])`로 다시 쓰므로 값만 뽑아 비교한다.
    assert set(re.findall(r"'([^']*)'", checks[name])) == {"ja", "en"}, checks[name]


@pytest.mark.parametrize("table", LANGUAGE_TABLES)
def test_an_insert_without_language_is_rejected(db_session: Session, table: str) -> None:
    """값을 빠뜨린 INSERT는 **실패해야 한다.** 조용히 'ja'가 되면 안 된다."""
    values = _without(_row_values(db_session, table), "language")
    with pytest.raises(IntegrityError) as raised:
        _insert(db_session, table, values)
    assert "language" in str(raised.value)
    db_session.rollback()


@pytest.mark.parametrize("table", LANGUAGE_TABLES)
def test_a_language_outside_the_enum_is_rejected_by_the_check(
    db_session: Session, table: str
) -> None:
    """허용값은 `ja`와 `en` 둘뿐이다(ADR-023 결정 1의 `값`).

    `'ko'`를 쓰는 이유: 두 글자이므로 VARCHAR 길이에 걸리지 않는다. 길이로 걸러지면
    세 글자짜리 코드만 막히고 `ko`·`zh` 같은 두 글자 값은 그대로 들어간다. 거부의 출처가
    CHECK임을 제약 이름으로 확인한다.
    """
    values = _row_values(db_session, table) | {"language": "ko"}
    with pytest.raises(IntegrityError) as raised:
        _insert(db_session, table, values)
    assert f"ck_{table}_language" in str(raised.value)
    db_session.rollback()


# --------------------------------------------------------------------------
# 2. 사용자별 학습 테이블은 language를 갖지 않는다 (불변식 21)
# --------------------------------------------------------------------------


def test_user_scoped_learning_tables_have_no_language_column(db_engine: Engine) -> None:
    """`learning_item_id`/`sentence_id`가 이미 언어를 결정한다.

    같은 값을 두 곳에 두면 한쪽만 고쳐지는 순간 "sentence의 언어"와 "candidate의 언어"가
    다른 상태가 만들어지고, 그 상태에 의미가 없다. 테이블 이름을 열거하는 것이 이
    테스트의 요점이다 --- 나중에 join을 줄이려고 추가하는 것을 여기서 막는다.
    """
    offenders = []
    for table in USER_SCOPED_TABLES:
        columns = _columns(db_engine, table)
        assert columns, f"{table}이 없다 --- 목록이 schema와 어긋났다"
        if "language" in columns:
            offenders.append(table)
    assert offenders == []


# --------------------------------------------------------------------------
# 3. ruby_json은 일본어 전용이다 (불변식 23)
# --------------------------------------------------------------------------


def test_an_english_sentence_cannot_carry_ruby(db_session: Session) -> None:
    """영어 문장에 후리가나가 붙는 것은 어떤 경로로도 정상이 아니다.

    이 CHECK는 같은 행의 다른 컬럼 하나만 보므로 DB가 막을 수 있다. ruby **내용**의
    무결성(좌표·겹침·경계)은 여전히 CHECK로 두지 않는다 --- 다른 테이블과 대조해야 한다.
    """
    with pytest.raises(IntegrityError) as raised:
        _insert(
            db_session,
            "sentences",
            _sentence_values(language="en", text="Come on.", ruby_json=RUBY_JSON),
        )
    assert "ck_sentences_ruby_json_ja_only" in str(raised.value)
    db_session.rollback()


def test_an_english_sentence_with_null_ruby_is_allowed(db_session: Session) -> None:
    """영어 적재 경로는 분석기를 부르지 않고 `ruby_json`을 NULL로 둔다."""
    sentence_id = _insert(db_session, "sentences", _sentence_values(language="en", text="Come on."))
    assert sentence_id is not None


def test_a_japanese_sentence_with_ruby_is_allowed(db_session: Session) -> None:
    """MVP-02의 동작은 아무것도 바뀌지 않는다."""
    sentence_id = _insert(db_session, "sentences", _sentence_values(ruby_json=RUBY_JSON))
    assert sentence_id is not None


# --------------------------------------------------------------------------
# 4. reading은 NULL일 수 있다 (ADR-023 결정 3)
# --------------------------------------------------------------------------


def test_a_learning_item_can_have_no_reading(db_session: Session) -> None:
    """영어 item은 `reading = NULL`이다 --- 영어에 발음 표기를 하지 않는다.

    일본어에 대한 강제는 DB에서 seed loader와 생성 validation으로 내려갔다. 같은 규칙을
    `sentence_item_explanations`에는 CHECK로 걸 수 없어서(그 테이블에 language가 없다)
    강제 위치를 한 곳으로 모은 결과다.
    """
    item_id = _insert(
        db_session,
        "learning_items",
        _learning_item_values(language="en", reading=None, lemma=_unique("come on")),
    )
    assert item_id is not None


def test_an_explanation_can_have_no_reading(db_session: Session) -> None:
    item_id = _insert(
        db_session, "learning_items", _learning_item_values(language="en", reading=None)
    )
    sentence_id = _insert(db_session, "sentences", _sentence_values(language="en", text="Come on."))
    sentence_item_id = _insert(
        db_session,
        "sentence_items",
        {
            "sentence_id": sentence_id,
            "learning_item_id": item_id,
            "surface_form": "Come on",
            "is_tappable": True,
            "created_at": NOW,
        },
    )
    explanation_id = _insert(
        db_session,
        "sentence_item_explanations",
        {
            "sentence_item_id": sentence_item_id,
            "reading": None,
            "core_meaning": "재촉",
            "meaning_in_context": "어서",
            "nuance": "구어",
            "example_sentence": "Come on, we are late.",
            "generated_at": NOW,
            "status": "validated",
        },
    )
    assert explanation_id is not None


# --------------------------------------------------------------------------
# 5. seed_id partial unique (ADR-023 결정 4)
# --------------------------------------------------------------------------


@pytest.mark.parametrize("table", ["learning_items", "sentences"])
def test_the_same_seed_id_cannot_appear_twice(db_session: Session, table: str) -> None:
    """증분 적재가 "이미 있다"를 판단하는 키다. 중복되면 같은 seed 항목이 두 행이 된다."""
    seed_id = _unique("en_it")
    builder = _learning_item_values if table == "learning_items" else _sentence_values
    _insert(db_session, table, builder(seed_id=seed_id))
    with pytest.raises(IntegrityError) as raised:
        _insert(db_session, table, builder(seed_id=seed_id))
    assert f"uq_{table}_seed_id" in str(raised.value)
    db_session.rollback()


@pytest.mark.parametrize("table", ["learning_items", "sentences"])
def test_many_rows_can_have_no_seed_id(db_session: Session, table: str) -> None:
    """partial이어야 하는 이유. `origin = generated` 행은 전부 NULL이고 여럿이다."""
    builder = _learning_item_values if table == "learning_items" else _sentence_values
    first = _insert(db_session, table, builder(seed_id=None))
    second = _insert(db_session, table, builder(seed_id=None))
    assert first != second


# --------------------------------------------------------------------------
# 6. prompt_versions의 유일성이 언어별이다 (ADR-023 결정 5)
# --------------------------------------------------------------------------


def test_the_same_task_can_be_active_in_both_languages(db_session: Session) -> None:
    """이것이 이 변경의 요점이다.

    `(task_type) WHERE active`였다면 일본어 prompt를 active로 둔 순간 영어 prompt를
    active로 둘 수 없고, 영어 job은 전부 `dead_letter`가 된다.
    """
    _insert(
        db_session,
        "prompt_versions",
        _prompt_version_values(language="ja", version="explain_item_v2", active=True),
    )
    english = _insert(
        db_session,
        "prompt_versions",
        _prompt_version_values(language="en", version="explain_item_en_v1", active=True),
    )
    assert english is not None


def test_two_active_rows_for_one_task_and_language_are_rejected(db_session: Session) -> None:
    """조합당 active는 하나다. 둘이면 어느 prompt로 생성했는지가 사후에 결정 불가능해진다."""
    _insert(
        db_session,
        "prompt_versions",
        _prompt_version_values(language="en", version="explain_item_en_v1", active=True),
    )
    with pytest.raises(IntegrityError) as raised:
        _insert(
            db_session,
            "prompt_versions",
            _prompt_version_values(language="en", version="explain_item_en_v2", active=True),
        )
    assert "uq_prompt_versions_active" in str(raised.value)
    db_session.rollback()


def test_the_same_version_string_in_one_language_is_rejected(db_session: Session) -> None:
    """유일성은 `(task_type, language, version)`이다(MVP-03). 같은 version 재등록은 막는다 ---
    같은 행의 내용을 바꿔 재등록하면 `provenance_json.prompt_version`이 어떤 prompt를
    가리키는지 사후에 알 수 없다."""
    _insert(db_session, "prompt_versions", _prompt_version_values(version="explain_item_v2"))
    with pytest.raises(IntegrityError) as raised:
        _insert(db_session, "prompt_versions", _prompt_version_values(version="explain_item_v2"))
    assert "uq_prompt_versions_task_type_language_version" in str(raised.value)
    db_session.rollback()


def test_the_same_version_string_in_another_language_is_allowed(db_session: Session) -> None:
    """유일성이 `(task_type, version)`에 남아 있으면 여기가 빨개진다."""
    _insert(
        db_session,
        "prompt_versions",
        _prompt_version_values(language="ja", version="explain_item_v2"),
    )
    english = _insert(
        db_session,
        "prompt_versions",
        _prompt_version_values(language="en", version="explain_item_v2"),
    )
    assert english is not None
