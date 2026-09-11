"""시각 주입 배선 (ADR-007).

`test_module_boundaries.py`의 G8/G9는 "시계를 아무도 몰래 읽지 않는다"만 본다.
주입 경로가 **실제로 연결돼 있는지**는 여기서 본다. 둘 다 없으면 `get_now`가
어디에도 닿지 않는 죽은 dependency가 되어도 초록으로 남는다.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.api.deps import get_now
from tests.clock import MutableClock


def test_get_now_returns_an_aware_utc_instant() -> None:
    before = datetime.now(UTC)
    now = get_now()
    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)
    assert before <= now <= datetime.now(UTC)


def test_a_request_sees_the_injected_clock(client: TestClient, study_clock: MutableClock) -> None:
    """응답의 시각이 **주입된 값 그대로**여야 한다.

    handler가 시계를 따로 읽으면 여기서 어긋난다. 같은 요청 안에서 시각이 갈리는
    경로가 있는지를 이 한 줄이 고정한다.
    """
    body = client.get("/api/health").json()
    assert datetime.fromisoformat(body["checked_at"]) == study_clock.now()


def test_advancing_the_clock_moves_the_next_request(
    client: TestClient, study_clock: MutableClock
) -> None:
    """freezegun 없이 시간을 옮긴다. 테스트가 시계를 손으로 움직인다."""
    first = datetime.fromisoformat(client.get("/api/health").json()["checked_at"])
    study_clock.advance(timedelta(days=3))
    second = datetime.fromisoformat(client.get("/api/health").json()["checked_at"])
    assert second - first == timedelta(days=3)
