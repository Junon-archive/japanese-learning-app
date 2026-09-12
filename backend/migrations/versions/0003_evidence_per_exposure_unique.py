"""evidence per exposure partial unique

07_SRS_SPEC.md의 `노출당 evidence 1건` --- "같은 `study_presentation` + 같은
`learning_item` = evidence 최대 1건"을 DB가 강제하게 한다. 0001은 `learning_events`에
`(user_id, client_event_id)` unique만 두었고, 이 상한은 `services/interactions.py`의
`SELECT ... LIMIT 1` 검사에만 있었다. 그 검사와 INSERT 사이에는 잠금이 없어 서로 다른
`client_event_id` 2건이 각자 "evidence 없음"을 읽고 둘 다 기록할 수 있다 --- 그러면 한
노출이 mastery EMA와 `reps`를 두 번 움직이고, 07_SRS_SPEC.md의 `정정은 하지 않는다`에
따라 그 결과는 되돌릴 수 없다. 프론트의 버튼 잠금으로는 재시도·두 탭·직접 호출에
뚫린다(ADR-018).

**전체 unique가 아니라 partial이다.** 조건절을 빼면 한 노출에 event를 2건 이상 남길 수
없어 click / reveal / probe 제시가 전부 막힌다.

predicate의 6종은 `app/services/presentation.py`의 `FSRS_RATING_EVENTS`와 같아야 한다
(self-report 3 + probe 응답 3). `mastery_probe_skipped`는 **없다** --- skip은 evidence가
아니므로(02_LEARNING_POLICY.md의 `Skip`) 한 노출에 skip과 evidence가 함께 있는 것이
정상이다. migration은 애플리케이션 코드를 import하지 않으므로 목록이 여기 literal로
박히고, 두 목록이 갈라지는지는 `tests/test_schema_invariants.py`가 DB의 indexdef를 읽어
단정한다.

`event_type`은 native enum이 아니라 VARCHAR + CHECK이므로(`models/base.py`의
`enum_column`) predicate가 문자열 비교로 끝난다. 값이 늘어도 이 index를 다시 만들 필요는
없다.

`learning_events`는 immutable log이고 이 index는 그 성질과 **충돌하지 않는다.** UPDATE를
요구하지도, 무효화 컬럼을 대신하지도 않는다. 막는 것은 두 번째 INSERT뿐이다.

기존 위반 행(한 노출에 evidence 2건)이 있으면 이 migration은 인덱스 생성 단계에서
**실패한다. 그대로 둔다.** 0002와 같은 판단이고 여기서는 더 강하다:

-   개인 사용 MVP이고 아직 배포 전이다. 위반 행을 만들 수 있는 경합은 위의 동시 요청
    하나뿐이고, `user_mastery` / `review_states`가 아직 없는 item에서는 그 두 번째 요청이
    자기 unique 위반으로 롤백되어 흔적을 남기지 못한다. 실제로 그런 행이 있을 가능성은
    없다.
-   있다면 그것은 데이터가 아니라 **진단해야 할 사건이다.** `learning_events`는 mastery
    알고리즘이 바뀌어도 과거를 replay하기 위해 원본을 보존하는 테이블이고(04_DB_SPEC.md),
    행을 지우는 것은 "사용자가 그렇게 답하지 않았다"는 거짓을 남기는 것이다. 무효화
    컬럼(`invalidated_at`)도 이 테이블에는 없다 --- 있는 쪽은 `item_exposures`다. 어느
    행을 남길지 고르는 판단도 migration이 할 일이 아니다.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-12

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index(
        "uq_learning_events_evidence",
        "learning_events",
        ["study_presentation_id", "learning_item_id"],
        unique=True,
        postgresql_where=sa.text(
            "event_type IN ("
            "'self_report_known', 'self_report_uncertain', 'self_report_unknown', "
            "'mastery_probe_known', 'mastery_probe_uncertain', 'mastery_probe_unknown')"
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("uq_learning_events_evidence", table_name="learning_events")
