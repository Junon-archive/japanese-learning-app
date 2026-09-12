"""open presentation partial unique

04_DB_SPEC.md의 `study_presentations` 불변식 --- "한 `study_session_id`에
`completed_at IS NULL`인 row는 최대 1개"를 DB가 강제하게 한다. 0001은 이 조건에
대응하는 제약 없이 비유일 인덱스 2개만 두었고, 불변식은 `services/presentation.py`의
`SELECT ... LIMIT 1` 검사에만 있었다. 그 검사와 INSERT 사이에는 잠금이 없어 같은
세션에 대한 동시 `/next` 2건이 둘 다 presentation을 만들 수 있다 --- 그러면 어느 쪽이
"현재 문장"인지 정의되지 않고 exposure와 context stage 전이가 두 갈래로 갈라진다.

**전체 unique가 아니라 partial이다.** 조건절을 빼면 한 세션에 문장을 하나밖에 보여줄
수 없다.

기존 위반 행(한 세션에 열린 행 2개)이 있으면 이 migration은 인덱스 생성 단계에서
**실패한다. 그대로 둔다.** 위반 행을 지우거나 `completed_at`을 채워 넣는 정리 단계를
두지 않는 이유:

-   개인 사용 MVP이고 아직 배포 전이다. 위반 행을 만들 수 있는 경합은 `/next`
    하나뿐인데 그 경로는 `touch()`가 세션 행을 먼저 UPDATE하는 덕분에 우연히
    직렬화되어 왔다. 실제로 그런 행이 있을 가능성은 없다.
-   있다면 그것은 데이터가 아니라 **진단해야 할 사건**이다. `study_presentations`는
    `item_exposures` / `learning_events`가 FK로 가리키는 행이므로 migration이 조용히
    지우면 immutable log가 참조하는 대상이 사라진다. `completed_at`을 임의 시각으로
    채우는 것도 "그때 문장이 끝났다"는 없는 사실을 만드는 것이다. 둘 다 마이그레이션이
    할 일이 아니다.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-12

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index(
        "uq_study_presentations_open",
        "study_presentations",
        ["study_session_id"],
        unique=True,
        postgresql_where=sa.text("completed_at IS NULL"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("uq_study_presentations_open", table_name="study_presentations")
