"""sentences.ruby_json

MVP-02 후리가나(ADR-021 결정 2, 04_DB_SPEC.md의 `ruby_json`). MVP-02의 schema 변경은 이
컬럼 하나다.

**additive다(불변식 19).** 운영 DB는 reset하지 않고 이 migration을 데이터 위에 올린다.
default가 없는 nullable 컬럼 추가는 PostgreSQL에서 테이블을 다시 쓰지 않고 기존 행을
건드리지 않는다. 기존 문장은 전부 NULL(= 미계산)로 남고, 값은 migration이 아니라
`scripts/backfill_ruby.py`가 채운다 --- 계산에는 형태소 분석기가 필요하고, migration은
애플리케이션 코드와 분석기를 import하지 않는다.

**server default를 두지 않는다.** `'{}'`나 `spans: []`를 기본값으로 두면 "계산했고 달
읽기가 없다"와 "계산하지 않았다"가 한 값이 되어 backfill 대상(`ruby_json IS NULL`)이
사라진다.

**CHECK를 두지 않는다.** 지켜야 하는 무결성(원문 길이 안, 겹침 없음, tappable 경계 안)은
`sentences.japanese`와 `sentence_item_spans`를 대조해야 해서 CHECK로 표현되지 않는다.
인덱스도 두지 않는다. 미계산 잔량 조회는 운영 점검용이고 문장 수가 작다.

downgrade는 컬럼을 DROP한다. 빈 DB 왕복 테스트용이며 운영 롤백 경로가 아니다
(04_DB_SPEC.md의 `운영 DB에 migration을 적용하는 경로`: 롤백은 백업 복원이다).

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-13

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "sentences",
        sa.Column("ruby_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("sentences", "ruby_json")
