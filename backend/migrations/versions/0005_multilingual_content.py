"""multilingual content model

MVP-03 다언어 모델(ADR-023, 04_DB_SPEC.md의 `MVP-03: 다언어 migration과 seed_id backfill`).
학습 대상 언어를 콘텐츠 엔티티의 축으로 넣고, 일본어 전용 이름과 일본어 전용 NOT NULL을
언어 중립으로 바꾼다.

**비파괴다(불변식 26).** 운영 DB는 reset하지 않고 0004 상태의 데이터 위에 이것을 올린다.
`upgrade()`에 DROP TABLE도 DROP COLUMN도 없다 --- 컬럼 추가, 컬럼 리네임, NOT NULL 완화,
제약·index 교체까지다. rename과 NOT NULL 완화는 additive가 아니지만 데이터를 잃지 않는다.

`upgrade()`가 하는 일은 04_DB_SPEC.md의 `한 migration이 하는 일` 여섯 단계 그대로다.

1 RENAME        sentences.japanese -> sentences.text
2 ADD           다섯 테이블의 language (NULL로 추가 -> UPDATE 'ja' -> NOT NULL + CHECK)
3 ADD           learning_items.seed_id, sentences.seed_id + partial unique
4 DROP NOT NULL learning_items.reading, sentence_item_explanations.reading
5 ADD CHECK     sentences: language = 'ja' OR ruby_json IS NULL
6 REPLACE       prompt_versions의 유일성 둘을 언어별로

**`language`에 server_default를 두지 않는다.** 기본값이 있으면 언어를 빠뜨린 INSERT가 조용히
일본어가 된다. 2단계의 UPDATE가 기존 행을 채우므로 기본값이 필요 없다. 그래서 세 단계가 한
migration 안에 함께 있다.

**5의 CHECK는 기존 행에서 바로 성립한다.** 기존 문장은 2단계를 거쳐 전부 `language = 'ja'`다.

**`seed_id` 값을 채우는 것은 이 migration이 아니라 `scripts/backfill_seed_id.py`이며, 영어
seed의 증분 적재보다 먼저 돈다**(04_DB_SPEC.md의 `migration이 하지 않는 것`). migration은
schema만 바꾸고 콘텐츠를 넣지 않는다.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-01

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# `app.models.base.enum_column`과 같은 물리 타입(VARCHAR + 명명 CHECK)이다. migration은
# 애플리케이션 코드를 import하지 않으므로 값이 여기 literal로 박힌다.
#
# `create_constraint=False`로 둔다. True면 `add_column`이 CHECK를 함께 만들어 이름이
# SQLAlchemy의 생성 규칙에 맡겨지고, 아래에서 `op.f()`로 고정한 이름과 갈라진다. CHECK는
# 이름을 명시해 따로 만든다 --- 이름 없는 제약은 downgrade에서 DROP할 수 없다.
LANGUAGE = sa.Enum("ja", "en", name="language", native_enum=False, create_constraint=False)

# language 축을 갖는 콘텐츠 엔티티 다섯(ADR-023 결정 1). 사용자별 학습 테이블은 여기 없다 ---
# `learning_item_id`/`sentence_id`가 이미 언어를 결정한다(불변식 21).
LANGUAGE_TABLES = (
    "learning_items",
    "sentences",
    "study_sessions",
    "prompt_versions",
    "generation_jobs",
)

# 영어에는 발음 표기를 하지 않으므로 NULL이다(ADR-023 결정 3). 일본어에 대한 강제는 DB가
# 아니라 seed loader와 생성 validation이 한다 --- 같은 규칙을 sentence_item_explanations에는
# CHECK로 걸 수 없기 때문이다(그 테이블에 language가 없다).
READING_COLUMNS = (("learning_items", "reading"), ("sentence_item_explanations", "reading"))

# 일본어 전용 컬럼이다(불변식 23). 영어 문장에 ruby가 붙는 것은 어떤 경로로도 정상이 아니다.
RUBY_JA_ONLY = "language = 'ja' OR ruby_json IS NULL"

SEED_ID_TABLES = ("learning_items", "sentences")


def upgrade() -> None:
    """Upgrade schema."""
    # 1. 데이터를 보존하는 리네임이다(ADR-023 결정 2).
    op.alter_column("sentences", "japanese", new_column_name="text")

    # 2. NULL로 추가 -> 기존 행을 'ja'로 채움 -> NOT NULL + CHECK.
    for table in LANGUAGE_TABLES:
        op.add_column(table, sa.Column("language", LANGUAGE, nullable=True))
        # 테이블 이름은 위 상수에서만 온다. 사용자 입력이 아니다.
        op.execute(f"UPDATE {table} SET language = 'ja'")  # noqa: S608
        op.alter_column(table, "language", nullable=False)
        op.create_check_constraint(op.f(f"ck_{table}_language"), table, "language IN ('ja','en')")

    # 3. seed 파일의 안정 키. 증분 적재가 "이미 있다"를 판단하는 근거다(ADR-023 결정 4).
    #    partial이어야 한다 --- origin = generated 행은 전부 NULL이고 전체 unique면 그런
    #    행을 둘 이상 둘 수 없다.
    for table in SEED_ID_TABLES:
        op.add_column(table, sa.Column("seed_id", sa.Text(), nullable=True))
        op.create_index(
            f"uq_{table}_seed_id",
            table,
            ["seed_id"],
            unique=True,
            postgresql_where=sa.text("seed_id IS NOT NULL"),
        )

    # 4. 영어 item·설명의 reading은 NULL이다.
    for table, column in READING_COLUMNS:
        op.alter_column(table, column, existing_type=sa.Text(), nullable=True)

    # 5. 같은 행의 컬럼 하나만 보는 CHECK이므로 DB가 막을 수 있다. ruby **내용**의
    #    무결성(좌표·겹침·경계)은 여전히 CHECK로 두지 않는다 --- 다른 테이블과 대조해야 한다.
    op.create_check_constraint(op.f("ck_sentences_ruby_json_ja_only"), "sentences", RUBY_JA_ONLY)

    # 6. 유일성을 언어별로 넓힌다. 넓히지 않으면 같은 task_type의 두 언어 prompt를 등록할 수
    #    없고, active도 한 언어밖에 가질 수 없다(ADR-023 결정 5).
    op.drop_constraint("uq_prompt_versions_task_type_version", "prompt_versions", type_="unique")
    op.create_unique_constraint(
        op.f("uq_prompt_versions_task_type_language_version"),
        "prompt_versions",
        ["task_type", "language", "version"],
    )
    # 이름은 유지하고 컬럼만 바꾼다. 이 이름은 구현에서 상수다(models/study.py의 주석).
    op.drop_index("uq_prompt_versions_active", table_name="prompt_versions")
    op.create_index(
        "uq_prompt_versions_active",
        "prompt_versions",
        ["task_type", "language"],
        unique=True,
        postgresql_where=sa.text("active"),
    )


def downgrade() -> None:
    """Downgrade schema. 빈 DB 왕복 테스트용이며 운영 롤백 경로가 아니다.

    **두 가지를 잃는다.**

    (a) `language`와 `seed_id` 컬럼을 DROP하므로 그 값이 사라진다. 영어 콘텐츠가 들어간
        뒤라면 "이 행이 영어였다"는 사실 자체가 없어지고, 다시 upgrade해도 전부 `'ja'`가
        된다.
    (b) 영어 행이 하나라도 들어간 뒤에는 `reading` NOT NULL 복원이 **실패한다**. 영어
        item·설명의 `reading`은 NULL이기 때문이다. 즉 이 downgrade는 영어 콘텐츠가 없는
        DB에서만 끝까지 돈다.

    **운영 롤백은 downgrade가 아니라 백업 복원이다**(04_DB_SPEC.md의 `운영 DB에 migration을
    적용하는 경로`). 운영 경로에 downgrade 명령을 두지 않는다.
    """
    op.drop_index("uq_prompt_versions_active", table_name="prompt_versions")
    op.create_index(
        "uq_prompt_versions_active",
        "prompt_versions",
        ["task_type"],
        unique=True,
        postgresql_where=sa.text("active"),
    )
    op.drop_constraint(
        op.f("uq_prompt_versions_task_type_language_version"), "prompt_versions", type_="unique"
    )
    op.create_unique_constraint(
        op.f("uq_prompt_versions_task_type_version"), "prompt_versions", ["task_type", "version"]
    )

    op.drop_constraint(op.f("ck_sentences_ruby_json_ja_only"), "sentences", type_="check")

    for table, column in reversed(READING_COLUMNS):
        op.alter_column(table, column, existing_type=sa.Text(), nullable=False)

    for table in reversed(SEED_ID_TABLES):
        op.drop_index(f"uq_{table}_seed_id", table_name=table)
        op.drop_column(table, "seed_id")

    for table in reversed(LANGUAGE_TABLES):
        op.drop_constraint(op.f(f"ck_{table}_language"), table, type_="check")
        op.drop_column(table, "language")

    op.alter_column("sentences", "text", new_column_name="japanese")
