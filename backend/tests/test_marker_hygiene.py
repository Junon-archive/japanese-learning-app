"""`integration` 마커 누락 감시.

`make test-unit`은 "DB 없이 도는 테스트"를 광고한다. DB fixture를 쓰면서 마크가
없는 테스트가 하나라도 생기면 그 약속이 깨지고, DB가 없는 환경에서 error로만
나타난다 --- 실제로 그렇게 23건이 새어 있었다.

마커를 자동으로 붙이지 않는다. 자동으로 붙이면 누락이 영영 드러나지 않고
`make test-unit`의 의미가 조용히 바뀐다. 누락은 실패로 드러낸다.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from .conftest import COLLECTED_ITEMS

# 모든 DB fixture는 이것 위에 쌓여 있다(`db_client` -> `db_session` -> `db_engine`
# -> `database_url` -> `postgres_admin_dsn`). pytest의 fixturenames는 전이 폐포라서
# 새 DB fixture가 추가돼도 이 목록을 손으로 늘릴 필요가 없다.
ROOT_DB_FIXTURE = "postgres_admin_dsn"

INTEGRATION_MARKER = "integration"


def _fixture_names(item: pytest.Item) -> tuple[str, ...]:
    return tuple(getattr(item, "fixturenames", ()))


def _requires_database(item: pytest.Item) -> bool:
    return ROOT_DB_FIXTURE in _fixture_names(item)


@pytest.mark.integration
def test_probe_that_uses_the_database(db_session: Session) -> None:
    """아래 검사들의 표본. 이 파일만 단독 실행해도 DB 테스트가 최소 한 건 수집된다.

    이것이 없으면 `pytest backend/tests/test_marker_hygiene.py`처럼 좁은 범위로
    돌릴 때 검사가 빈 목록 위에서 통과한다.
    """
    assert db_session.scalar(sa.select(sa.literal(1))) == 1


def test_collection_was_captured() -> None:
    """훅이 동작하지 않으면 아래 검사들이 빈 목록 위에서 통과한다."""
    assert COLLECTED_ITEMS


def test_the_fixture_closure_reaches_the_root_db_fixture() -> None:
    """`db_session`만 요구한 테스트도 폐포에 `postgres_admin_dsn`을 들고 있어야 한다.

    이 전제가 깨지면(pytest가 폐포 계산을 바꾸면) 아래 검사가 DB 테스트를 하나도
    보지 못한 채 통과한다.
    """
    probes = [item for item in COLLECTED_ITEMS if "db_session" in _fixture_names(item)]
    assert probes, "db_session을 쓰는 테스트가 하나도 수집되지 않았다"
    assert all(_requires_database(item) for item in probes)


def test_every_database_test_is_marked_integration() -> None:
    """`-m "not integration"`으로 걸러진 것까지 본다(conftest의 훅이 tryfirst다)."""
    offenders = sorted(
        item.nodeid
        for item in COLLECTED_ITEMS
        if _requires_database(item)
        and INTEGRATION_MARKER not in {mark.name for mark in item.iter_markers()}
    )
    assert offenders == []


def test_no_test_is_marked_integration_without_needing_the_database() -> None:
    """반대 방향. 과잉 마킹은 `make test-unit`을 조용히 빈껍데기로 만든다.

    DB가 필요 없는데 integration으로 표시된 테스트는 unit 실행에서 사라지면서도
    아무도 그것을 눈치채지 못한다. 모듈 전체에 `pytestmark`를 걸어 두고 DB를 쓰지
    않는 테스트를 하나 끼워 넣으면 이렇게 된다.

    고치는 법: 그 테스트를 DB를 쓰지 않는 모듈로 옮기거나, 모듈 `pytestmark` 대신
    DB를 쓰는 테스트에만 마크를 단다.
    """
    offenders = sorted(
        item.nodeid
        for item in COLLECTED_ITEMS
        if INTEGRATION_MARKER in {mark.name for mark in item.iter_markers()}
        and not _requires_database(item)
    )
    assert offenders == []
