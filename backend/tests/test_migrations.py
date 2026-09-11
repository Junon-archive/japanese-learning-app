"""Alembic migration 검증 (12_TEST_PLAN.md "Alembic from empty DB").

04_DB_SPEC.md Migration Rule: "빈 DB에서 migration만으로 전체 schema를
재현할 수 있어야 한다."
"""

from __future__ import annotations

import uuid

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
