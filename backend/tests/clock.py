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

# 테스트의 기준 시각. **고정값**이며 실행일과 무관하다 --- 그것이 요점이고, 실제
# 시각보다 앞이냐 뒤냐는 중요하지 않다(이 값은 이미 과거다). 시각을 값으로만 흘리는
# 코드에서는 이 상수 하나가 모든 판정의 기준이 되므로 실행일에 따라 결과가 바뀌지
# 않는다. 실클록과 이 시계를 **섞어 쓰는** 테스트만 실행일에 취약해진다 --- 한쪽을
# `datetime.now(UTC)`로 세우고 다른 쪽을 이 시계로 비교하면 두 값의 차이가 날마다
# 달라진다. 그런 테스트는 양쪽을 같은 출처로 맞춘다.
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
