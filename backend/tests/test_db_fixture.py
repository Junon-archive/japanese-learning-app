"""DB fixture 자체와 FastAPI↔Postgres 경로 (12_TEST_PLAN.md Integration).

fixture가 실제로 격리하지 못하면 아래 모든 integration 테스트가 서로를 오염시키면서
순서에 따라 다른 결과를 낸다. 그 상태를 먼저 배제한다.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import User
from tests import factories

pytestmark = pytest.mark.integration

# 두 테스트가 같은 login_id를 쓴다. 롤백이 안 되면 두 번째에서 unique 위반이 난다.
SHARED_LOGIN_ID = "rollback.probe"


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
