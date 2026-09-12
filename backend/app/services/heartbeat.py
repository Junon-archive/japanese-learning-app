"""worker 생존 신호의 쓰기와 판정 (09_BACKGROUND_JOBS.md의 `Worker Heartbeat`).

쓰는 쪽은 worker loop(`app/jobs/worker.py`)이고 읽는 쪽은 `GET /api/health`다. **두
주체가 한 모듈을 쓰는 이유는 stale 규칙이 한 곳에만 있어야 하기 때문이다** --- 규칙이
둘로 갈리면 worker가 살아 있는데 health가 `stale`이라고 답하는 형태로 조용히 어긋난다.

왜 `app/jobs/`가 아니라 여기인가.

``` text
G7   app/jobs/ 안의 commit 은 jobs/queue.py 와 jobs/persistence.py 에만 있다
G12  app/jobs/ 밖에서 import 가능한 jobs 모듈은 replenishment.py 뿐이다
```

heartbeat write는 **job 트랜잭션과 분리된 자체 commit**이 요구사항이므로(ADR-017)
`jobs/worker.py`에 둘 수 없고, `jobs/heartbeat.py`에 두면 `api/health.py`가 그것을
읽을 수 없다(G12). 반대로 쓰기를 `jobs/`에 두고 읽기만 여기 두면 위에서 말한 "규칙이
둘"이 된다. `services/`는 L2이므로 `jobs/`(L2)와 `api/`(L3) 양쪽이 합법적으로
import하고, service가 자기 트랜잭션을 닫는 것은 이 코드베이스의 기존 규약이다.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.jobs import WorkerHeartbeat

# MVP의 worker는 하나다. 그래도 이름이 있는 이유는 upsert에 대상 키가 필요하고,
# worker가 둘이 되는 날 migration 없이 행만 늘면 되기 때문이다 (04_DB_SPEC.md).
DEFAULT_WORKER_NAME = "default"

WorkerStatus = Literal["unknown", "ok", "stale"]


def write_heartbeat(db: Session, *, worker_name: str, now: datetime) -> None:
    """생존 신호를 적고 **즉시 commit한다.**

    이 commit은 job 트랜잭션에 얹지 않는다. 얹으면 job rollback이 생존 신호까지
    지우고, 그러면 health가 실패한 job 하나 때문에 worker를 죽은 것으로 판정한다
    (ADR-017). 호출부(worker loop)가 job과 **다른 세션**을 주는 것으로 그 분리를
    구조로 만든다.
    """
    statement = (
        pg_insert(WorkerHeartbeat)
        .values(worker_name=worker_name, last_heartbeat_at=now)
        .on_conflict_do_update(index_elements=["worker_name"], set_={"last_heartbeat_at": now})
    )
    db.execute(statement)
    db.commit()


def latest_heartbeat_at(connection: sa.Connection) -> datetime | None:
    """`last_heartbeat_at`의 **최대값 하나**. 행이 없으면 None (05_API_SPEC.md).

    `Session`이 아니라 `Connection`을 받는다. health check는 DB 확인에 이미 열어 둔
    커넥션을 재사용해야 한다 --- "worker 상태를 위해 별도 연결을 만들지 않는다"
    (05_API_SPEC.md). worker가 여럿이면 하나라도 살아 있으면 `ok`라는 뜻이 된다.
    """
    latest: datetime | None = connection.execute(
        sa.select(sa.func.max(WorkerHeartbeat.last_heartbeat_at))
    ).scalar_one_or_none()
    return latest


def worker_status(
    *, last_heartbeat_at: datetime | None, now: datetime, stale_seconds: int
) -> WorkerStatus:
    """heartbeat 하나로 `unknown | ok | stale`을 가른다.

    `unknown`은 "한 번도 쓴 적이 없다"(worker를 아직 띄우지 않은 환경)이고 그 자체로
    `degraded`가 아니다. `stale`은 degraded다 --- 05_API_SPEC.md가 canonical이며 이
    함수는 그 표를 그대로 옮긴 것뿐이다.
    """
    if last_heartbeat_at is None:
        return "unknown"
    if now - last_heartbeat_at <= timedelta(seconds=stale_seconds):
        return "ok"
    return "stale"
