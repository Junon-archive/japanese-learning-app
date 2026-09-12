"""DB fixture 자체와 FastAPI↔Postgres 경로 (12_TEST_PLAN.md Integration).

fixture가 실제로 격리하지 못하면 아래 모든 integration 테스트가 서로를 오염시키면서
순서에 따라 다른 결과를 낸다. 그 상태를 먼저 배제한다.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.models import User
from tests import factories

pytestmark = pytest.mark.integration

# 두 테스트가 같은 login_id를 쓴다. 롤백이 안 되면 두 번째에서 unique 위반이 난다.
SHARED_LOGIN_ID = "rollback.probe"
COMMITTED_LOGIN_ID = "truncate.probe"


@pytest.mark.parametrize("run", [1, 2])
def test_each_test_starts_from_a_clean_transaction(db_session: Session, run: int) -> None:
    """실행 순서와 무관하다. 두 번 모두 "없음 → 삽입"이 성립해야 한다."""
    count = sa.select(sa.func.count()).select_from(User).where(User.login_id == SHARED_LOGIN_ID)
    assert db_session.scalar(count) == 0, f"앞선 테스트의 데이터가 남아 있다 (run={run})"
    factories.make_user(db_session, login_id=SHARED_LOGIN_ID)
    assert db_session.scalar(count) == 1


def test_commit_inside_the_test_is_still_rolled_back(db_session: Session) -> None:
    """서비스 코드가 commit을 호출해도 SAVEPOINT로 바뀌어 테스트 밖으로 새지 않는다.

    이것이 성립하지 않으면 애플리케이션 코드에서 commit을 빼는 식으로 테스트가
    구현을 왜곡하게 된다.
    """
    user = factories.make_user(db_session)
    db_session.commit()
    assert db_session.get(User, user.id) is not None


def test_health_endpoint_reports_a_real_database(db_client: TestClient) -> None:
    """FastAPI ↔ Postgres. 05_API_SPEC.md의 health component."""
    body = db_client.get("/api/health").json()
    assert body["components"]["database"]["status"] == "ok"
    assert body["components"]["database"]["latency_ms"] is not None
    assert body["status"] == "ok"


# --------------------------------------------------------------------------
# committed_db (Wave 3)
#
# 이 fixture는 진짜로 commit하므로 롤백으로 치울 수 없다. TRUNCATE가 한 번이라도
# 걸러지면 다음 테스트가 남은 행 위에서 **조용히** 오염된다. 그래서 먼저 검사한다.
# --------------------------------------------------------------------------


def test_a_committed_row_is_visible_from_another_connection(
    committed_db: sessionmaker[Session],
) -> None:
    """`db_session`과 정반대다. 여기서는 commit이 SAVEPOINT로 바뀌지 않는다.

    worker claim 테스트가 성립하려면 이 성질이 필요하다 --- 다른 커넥션이 보지
    못하는 "커밋"으로는 두 worker가 겹치는 순간을 재현할 수 없다.
    """
    with committed_db() as writer:
        factories.make_user(writer, login_id=COMMITTED_LOGIN_ID)
        writer.commit()

    with committed_db() as reader:
        assert reader.scalar(sa.select(sa.func.count()).select_from(User)) == 1


@pytest.mark.parametrize("run", [1, 2])
def test_the_truncate_leaves_nothing_for_the_next_test(
    committed_db: sessionmaker[Session], run: int
) -> None:
    """두 실행이 같은 login_id를 커밋한다. 정리가 걸러지면 두 번째가 unique 위반이다."""
    with committed_db() as session:
        count = sa.select(sa.func.count()).select_from(User)
        assert session.scalar(count) == 0, f"앞선 테스트의 커밋이 남아 있다 (run={run})"
        factories.make_user(session, login_id=COMMITTED_LOGIN_ID)
        session.commit()
