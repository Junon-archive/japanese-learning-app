"""테스트가 시각을 움직이는 유일한 수단 (ADR-007).

freezegun이나 `datetime` monkeypatch를 쓰지 않는다. 프로덕션 코드가 시각을
`now: datetime` **값**으로 받으므로 테스트는 그 값을 그냥 주면 된다. 전역 시계를
얼리는 도구는 애플리케이션이 시계를 몰래 읽어도 통과시켜 주므로 G8/G9 guard와
정반대 방향이다.

-   정책 함수는 `f(..., now=clock.now())`처럼 값을 직접 받는다.
-   API 경로는 `app.dependency_overrides[get_now] = clock.now`로 주입한다
    (`conftest.py`의 `study_clock`).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

# 테스트의 기준 시각. 과거가 아니라 미래로 잡아 "오늘"에 의존하는 코드가 실행일에
# 따라 결과를 바꾸지 않게 한다.
DEFAULT_START = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)


class MutableClock:
    """테스트가 손으로 움직이는 시계. 스스로는 흐르지 않는다."""

    def __init__(self, start: datetime = DEFAULT_START) -> None:
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> datetime:
        self._now += delta
        return self._now

    def set(self, moment: datetime) -> datetime:
        self._now = moment
        return self._now
