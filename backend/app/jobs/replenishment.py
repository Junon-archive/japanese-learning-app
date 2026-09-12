"""request 경로의 `generation_jobs` enqueue (09_BACKGROUND_JOBS.md, 06_LEARNING_ENGINE.md).

세 job_type의 트리거가 전부 여기 있다. `09_BACKGROUND_JOBS.md`의
`Enqueue 트리거와 idempotency key` 표가 canonical이다.

``` text
GENERATE_SENTENCE_BATCH  Pool Fallback 3단계. role 하나당 1건
GENERATE_REVIEW_CONTEXT  materialization의 review 분기가 그 stage의 문장을 못 찾음
EXPLAIN_ITEM             materialization이 검사한 문장의 explanation 누락
```

한 모듈에 모으는 이유는 G12다(ADR-015): `app/jobs/` 밖에서 import할 수 있는 jobs
모듈은 enqueue 모듈뿐이고, 그 allowlist를 늘리지 않는다.

**이 모듈은 `generation_jobs`에 INSERT만 한다.** provider client를 만들지 않고
`app.llm`을 import하지 않는다. request 경로에서 불리므로, 여기에 provider 호출이 한
줄이라도 생기면 모든 pool이 빈 사용자의 요청이 LLM 응답을 기다리게 된다(불변식 #1).
claim / retry backoff / provider 호출은 전부 worker다.

replenishment는 job_type이 아니다. `GENERATE_SENTENCE_BATCH`를 enqueue하는
트리거다(09_BACKGROUND_JOBS.md).

commit하지 않는다. 부르는 service의 같은 트랜잭션 안에서 일어나는 INSERT라서, 학습
상태가 롤백되면 그에 대한 job도 함께 사라진다(ADR-007의 `트랜잭션 경계`).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.config import AppConfig
from app.learning.selection import MaterializationGaps
from app.models.enums import ContextStage, GenerationJobStatus, JobType, PresentationRole
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
    return _enqueue(
        db,
        job_type=JobType.GENERATE_SENTENCE_BATCH,
        payload={"user_id": user_id, "presentation_role": role.value},
        idempotency_key=replenishment_idempotency_key(user_id=user_id, role=role, now=now),
        now=now,
        cfg=cfg,
    )


def explain_item_idempotency_key(*, sentence_item_id: int, now: datetime) -> str:
    """`explain:{sentence_item_id}:{UTC 날짜}` (09_BACKGROUND_JOBS.md).

    사용자가 들어가지 않는다. 설명은 global content이므로 같은 `sentence_item`을
    두 사용자가 같은 날 만나면 job은 하나여야 한다.
    """
    return f"explain:{sentence_item_id}:{now:%Y-%m-%d}"


def enqueue_explain_item(
    db: Session, *, sentence_item_id: int, now: datetime, cfg: AppConfig
) -> GenerationJob | None:
    """materialization이 explanation 누락으로 건너뛴 `sentence_item` 하나에 1건.

    이미 억제 창 안에 job이 있으면 None이다. 설명이 붙으면 그 문장이 Ready invariant를
    다시 만족하고, **다음 materialization 실행에서** candidate가 된다(08_LLM_SPEC.md).
    """
    return _enqueue(
        db,
        job_type=JobType.EXPLAIN_ITEM,
        payload={"sentence_item_id": sentence_item_id},
        idempotency_key=explain_item_idempotency_key(sentence_item_id=sentence_item_id, now=now),
        now=now,
        cfg=cfg,
    )


def review_context_idempotency_key(
    *, user_id: int, learning_item_id: int, context_stage: ContextStage, now: datetime
) -> str:
    """`review_ctx:{user_id}:{learning_item_id}:{context_stage}:{UTC 날짜}`.

    stage가 키에 들어간다. 빠지면 `varied`가 비어서 만든 job이 같은 날 `new_context`의
    생성을 막고, ladder를 올라간 item이 그날 내내 새 문맥을 못 얻는다.
    """
    return f"review_ctx:{user_id}:{learning_item_id}:{context_stage.value}:{now:%Y-%m-%d}"


def enqueue_review_context(
    db: Session,
    *,
    user_id: int,
    learning_item_id: int,
    context_stage: ContextStage,
    anchor_sentence_id: int,
    now: datetime,
    cfg: AppConfig,
) -> GenerationJob | None:
    """`(item, stage)` 하나당 1건. anchor는 payload에 실린다(09_BACKGROUND_JOBS.md).

    quarantined anchor를 걸러내는 것은 트리거 지점이다(`learning/selection.py`의
    `_record_review_context_gap`, 불변식 #7). 여기서 다시 조회하면 같은 판정이 두
    곳으로 갈린다.
    """
    return _enqueue(
        db,
        job_type=JobType.GENERATE_REVIEW_CONTEXT,
        payload={
            "user_id": user_id,
            "learning_item_id": learning_item_id,
            "context_stage": context_stage.value,
            "anchor_sentence_id": anchor_sentence_id,
        },
        idempotency_key=review_context_idempotency_key(
            user_id=user_id,
            learning_item_id=learning_item_id,
            context_stage=context_stage,
            now=now,
        ),
        now=now,
        cfg=cfg,
    )


def enqueue_materialization_gaps(
    db: Session, *, user_id: int, gaps: MaterializationGaps, now: datetime, cfg: AppConfig
) -> None:
    """materialization이 올린 gap을 job으로 바꾼다. 호출부의 트랜잭션에 INSERT만 얹는다.

    `app/learning/`(L1)이 이 모듈(L2)을 import할 수 없으므로 materialization은 사실만
    모아 올리고 enqueue는 여기서 일어난다(ADR-015). `services/`가 materialization을
    호출한 바로 그 자리에서 이 함수를 부른다 --- 학습 상태가 rollback되면 그에 대한
    job도 함께 사라져야 한다(09_BACKGROUND_JOBS.md).
    """
    for sentence_item_id in gaps.unexplained_sentence_item_ids:
        enqueue_explain_item(db, sentence_item_id=sentence_item_id, now=now, cfg=cfg)
    for gap in gaps.review_contexts:
        enqueue_review_context(
            db,
            user_id=user_id,
            learning_item_id=gap.learning_item_id,
            context_stage=gap.context_stage,
            anchor_sentence_id=gap.anchor_sentence_id,
            now=now,
            cfg=cfg,
        )


def _enqueue(
    db: Session,
    *,
    job_type: JobType,
    payload: dict[str, Any],
    idempotency_key: str,
    now: datetime,
    cfg: AppConfig,
) -> GenerationJob | None:
    """세 트리거가 공유하는 단 하나의 INSERT 지점. 중복이면 None이다.

    `ON CONFLICT (idempotency_key) DO NOTHING`이 **여기 한 줄뿐**이어야 한다. 트리거마다
    복제하면 한 곳에서 빠뜨리는 순간 그 job_type만 동시 요청에서 IntegrityError를 내고,
    호출부의 학습 트랜잭션을 통째로 무효로 만든다(09_BACKGROUND_JOBS.md).
    """
    statement = (
        pg_insert(GenerationJob)
        .values(
            job_type=job_type,
            status=GenerationJobStatus.QUEUED,
            payload_json=payload,
            idempotency_key=idempotency_key,
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
