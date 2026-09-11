"""Ready Pool replenishment enqueue (09_BACKGROUND_JOBS.md, 06_LEARNING_ENGINE.md).

**이 모듈은 `generation_jobs`에 INSERT만 한다.** provider client를 만들지 않고
`app.llm`을 import하지 않는다. request 경로(Pool Fallback 3단계)에서 불리므로, 여기에
provider 호출이 한 줄이라도 생기면 모든 pool이 빈 사용자의 요청이 LLM 응답을 기다리게
된다(불변식 #1). claim / retry backoff / provider 호출은 전부 Wave 3의 worker다.

replenishment는 job_type이 아니다. `GENERATE_SENTENCE_BATCH`를 enqueue하는
트리거다(09_BACKGROUND_JOBS.md).

commit하지 않는다. 부르는 service의 같은 트랜잭션 안에서 일어나는 INSERT라서, 학습
상태가 롤백되면 그에 대한 job도 함께 사라진다(ADR-007의 `트랜잭션 경계`).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.config import AppConfig
from app.models.enums import GenerationJobStatus, JobType, PresentationRole
from app.models.jobs import GenerationJob


def replenishment_idempotency_key(*, user_id: int, role: PresentationRole, now: datetime) -> str:
    """`(사용자, role, UTC 날짜)` 하나당 job 하나.

    형식은 명세에 없다. 요구는 둘이다: **결정적**이어야 하고(같은 입력이 같은 키),
    중복 enqueue를 **억제**해야 한다. 그래서 억제 창을 날짜로 둔다.

    -   사용자와 role을 넣는 이유: 어느 pool이 비었는지가 생성 요청의 내용이다. role이
        빠지면 review pool이 비어서 만든 job이 new pool의 job을 같은 날 내내 막는다.
    -   날짜를 넣는 이유: 키가 `(user, role)`뿐이면 job이 completed가 된 뒤에도 영원히
        재enqueue가 막힌다. 반대로 시각/순번을 넣으면 한 세션에서 Pool Fallback을 열 번
        만나면 job이 열 개 쌓인다 --- provider 비용이 그대로 열 배가 된다.
    -   UTC 날짜다. 사용자 local day가 아니다. 이 창은 사용자에게 보이는 경계가 아니라
        생성 비용 억제 장치이고, `user_id`만 받는 이 함수가 timezone을 읽으려면 users를
        조회해야 한다. 억제 창을 좁히려면 이 문자열의 해상도만 올린다.
    """
    return (
        f"replenish:{JobType.GENERATE_SENTENCE_BATCH.value}:{user_id}:{role.value}:{now:%Y-%m-%d}"
    )


def enqueue_replenishment(
    db: Session, *, user_id: int, role: PresentationRole, now: datetime, cfg: AppConfig
) -> GenerationJob | None:
    """Pool Fallback 3단계. 이미 억제 창 안에 job이 있으면 아무것도 하지 않고 None이다.

    `ON CONFLICT (idempotency_key) DO NOTHING`으로 판정한다. 먼저 SELECT해서 없으면
    INSERT하는 방식을 쓰지 않는다 --- 그 사이에 끼는 동시 요청이 IntegrityError를 내고
    호출부의 학습 트랜잭션 전체를 무효로 만든다.

    `next_attempt_at = now`이므로 worker가 바로 집어갈 수 있다. 실패했을 때의 backoff는
    worker가 정한다(`retry_backoff_base_seconds`).
    """
    statement = (
        pg_insert(GenerationJob)
        .values(
            job_type=JobType.GENERATE_SENTENCE_BATCH,
            status=GenerationJobStatus.QUEUED,
            payload_json={"user_id": user_id, "presentation_role": role.value},
            idempotency_key=replenishment_idempotency_key(user_id=user_id, role=role, now=now),
            max_attempts=cfg.jobs.max_job_attempts,
            next_attempt_at=now,
            created_at=now,
        )
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
        .returning(GenerationJob.id)
    )
    job_id = db.execute(statement).scalar_one_or_none()
    if job_id is None:
        return None
    return db.get(GenerationJob, job_id)
