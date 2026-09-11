"""프로세스에서 시각을 읽는 **유일한** 지점 (ADR-007).

여기 말고 어디에서도 `datetime.now()` / `utcnow()` / `time.time()` /
`date.today()`를 부르지 않는다. 예외(allowlist)를 두지 않는다 --- 한 번 허용하면
"요청 하나가 시각 하나를 본다"는 규약이 무의미해진다.
`backend/tests/test_module_boundaries.py`의 G8이 이를 강제한다.

읽은 시각은 **값으로** 전달한다(`def f(..., *, now: datetime)`). clock 객체나
Protocol을 넘기지 않는다. 객체를 넘기면 호출부가 `clock.now()`를 여러 번 부를 수
있고, 그러면 한 요청 안에서 `deferred_until` / `next_review_at` / due 판정이 서로
다른 순간을 보게 된다. 값은 갈릴 수가 없다.
"""

from __future__ import annotations

from datetime import UTC, datetime


def utc_now() -> datetime:
    """timezone-aware UTC 현재 시각.

    naive datetime을 만들지 않는다. 모든 timestamp 컬럼이 `timestamptz`이고,
    사용자 local day는 `users.timezone`으로 따로 환산한다.
    """
    return datetime.now(UTC)
