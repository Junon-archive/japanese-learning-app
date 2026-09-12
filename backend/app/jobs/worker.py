"""worker loop (09_BACKGROUND_JOBS.md, ADR-015).

이 모듈은 **환경변수도 provider도 만들지 않는다.** provider와 job runner를 인자로
받고, 시각은 loop 1회전당 `clock.utc_now()`를 한 번 읽어 그 아래로 값으로만
흘린다(`app/jobs/`는 G9의 예외 진입점이다). 그래서 production은
`scripts/run_worker.py`가 `build_provider()`로 만든 client를, 테스트는
`backend/tests/provider_double.py`의 test double을 **같은 인자**에 넣는다
(ADR-016의 `개정`). 모듈 전역이나 import 시점에 provider를 만들지 않는다.

한 회전은 이렇다.

``` text
1  heartbeat upsert          job이 없어도. 자체 세션 + 자체 commit (ADR-017)
2  stale running 회수        claim 보다 먼저 (09_BACKGROUND_JOBS.md)
3  daily ceiling 판정        claim **직전**. 넘었으면 claim하지 않고 쉰다
4  claim 1건                 없으면 poll interval 만큼 쉰다
5  run_job                   provider 호출 지점. 여기서 트랜잭션을 붙들지 않는다
```

3번이 claim보다 뒤로 가면 안 된다. claim한 뒤 한도 때문에 실패로 끝내면
`retry_count`가 소모되어, 다음 날 살아 있어야 할 job이 `failed`가 된다. ceiling에
걸린 job은 `queued`로 남고 학습 세션은 Ready Pool로 계속 돈다 --- request 경로는
애초에 provider를 부르지 않기 때문이다(불변식 #1).

commit이 이 파일에 없다(G7). 상태 전이는 `jobs/queue.py`, 콘텐츠 저장은
`jobs/persistence.py`, heartbeat는 `services/heartbeat.py`가 각자 커밋한다. 실패
경로에서 **새 세션**을 여는 것도 같은 이유다 --- 실패한 job이 남긴 미확정 변경 위에
`record_retryable_failure`를 얹으면 그 쓰레기까지 함께 커밋된다.
"""

from __future__ import annotations

import signal
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from types import FrameType
from typing import Any, Protocol

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.clock import utc_now
from app.config import AppConfig
from app.jobs import observability, queue
from app.llm.provider import LlmProvider
from app.models.enums import CandidateStatus, GenerationJobStatus, LlmTaskType
from app.models.jobs import GenerationJob, PromptVersion
from app.models.learning import UserSentenceCandidate
from app.services.heartbeat import DEFAULT_WORKER_NAME, write_heartbeat

SessionFactory = Callable[[], Session]


class WorkerError(RuntimeError):
    """worker loop 자체가 계속할 수 없는 상태."""


class WorkerStartupError(WorkerError):
    """기동 조건이 갖춰지지 않았다. 조용히 도는 worker보다 즉시 실패가 낫다."""


class JobRunner(Protocol):
    """job 1건 실행 (`app/jobs/runner.py`).

    계약은 셋이다. **결과 상태를 적는 것은 runner다** --- 어떤 실패가 영구
    (`dead_letter`)이고 어떤 실패가 재시도인지는 payload와 provider 응답을 본
    쪽만 안다(09_BACKGROUND_JOBS.md의 `failed와 dead_letter의 경계`).

    ``` text
    입력   claim이 끝난 job (status = running) 과 provider, 그 회전의 now, cfg
    출력   그 job의 최종 상태. 상태 자체는 queue/persistence 를 통해 이미 DB에 적혔다
    예외   빠져나오면 worker가 재시도 가능한 실패로 간주하고 기록한다
    ```

    예외가 빠져나왔는데 job이 아직 `running`이면 worker가
    `record_retryable_failure`를 대신 적는다. 그러지 않으면 그 job은 lease가 만료될
    때까지(`claim_lease_seconds`) 아무도 집어가지 않는다.
    """

    def __call__(
        self,
        db: Session,
        *,
        job: GenerationJob,
        provider: LlmProvider,
        now: datetime,
        cfg: AppConfig,
    ) -> GenerationJobStatus: ...


@dataclass
class LoopState:
    """회전 사이에 남는 값. 지금은 ceiling 경고를 **상태 전이에서만** 내기 위한 것뿐이다.

    한도에 걸린 상태는 그날의 UTC 자정까지 이어진다. 매 poll마다 경고하면 개인 서버의
    디스크를 하루 수천 줄로 채우면서 정보량은 첫 줄과 같다.
    """

    ceiling_logged: bool = False


class ShutdownSignal:
    """SIGTERM / SIGINT를 받은 사실. 현재 job을 끝내고 loop를 벗어나는 데 쓴다.

    핸들러 안에서 하는 일은 flag를 세우는 것 하나다. job을 그 자리에서 끊으면
    provider 비용은 이미 나갔는데 결과가 저장되지 않은 job이 `running`으로 남는다.
    """

    def __init__(self) -> None:
        self._requested = False

    @property
    def requested(self) -> bool:
        return self._requested

    def request(self, signum: int | None = None, frame: FrameType | None = None) -> None:
        self._requested = True


def install_signal_handlers(shutdown: ShutdownSignal) -> None:
    """프로세스 진입점에서 부른다. loop 자체는 signal을 모른다(테스트가 직접 flag를 세운다)."""
    signal.signal(signal.SIGTERM, shutdown.request)
    signal.signal(signal.SIGINT, shutdown.request)


# --------------------------------------------------------------------------
# 기동 검사
# --------------------------------------------------------------------------


def check_active_prompt_versions(db: Session) -> None:
    """task 3종 전부에 `active = true` 행이 있어야 기동한다.

    없으면 그 task의 job은 전부 `dead_letter`가 된다(09_BACKGROUND_JOBS.md). 그것을
    job 단위로 발견하면 이미 enqueue된 job을 다 태운 뒤이므로, 기동 시점에 한 번
    확인하고 실패한다.
    """
    active = set(db.scalars(sa.select(PromptVersion.task_type).where(PromptVersion.active)).all())
    missing = sorted(task.value for task in LlmTaskType if task not in active)
    if missing:
        raise WorkerStartupError(
            "no active prompt_versions row for task_type: " + ", ".join(missing)
        )


def warn_if_cost_guard_disabled(cfg: AppConfig, *, api_key_configured: bool) -> None:
    """실키로 도는데 daily ceiling이 꺼져 있으면 기동 시 한 번 경고한다.

    `null = limit disabled`의 의미는 바꾸지 않는다(14_CONFIGURATION.md). 끄는 것은
    유효한 선택이고 기본값이기도 하다. 다만 **과금되는 키가 꽂힌 채** 꺼져 있는 것은
    운영자가 알고 있어야 하는 상태다. 키가 없으면(test double 주입 등) 경고하지
    않는다 --- 그 경로에는 청구서가 없다.
    """
    if not api_key_configured:
        return
    disabled = [
        name
        for name, value in (
            ("daily_request_limit", cfg.llm.daily_request_limit),
            ("daily_token_limit", cfg.llm.daily_token_limit),
        )
        if value is None
    ]
    if not disabled:
        return
    observability.logger.warning(
        observability.COST_GUARD_DISABLED,
        extra={"disabled_limits": disabled},
    )


# --------------------------------------------------------------------------
# loop
# --------------------------------------------------------------------------


def run_worker(
    *,
    session_factory: SessionFactory,
    provider: LlmProvider,
    run_job: JobRunner,
    cfg: AppConfig,
    worker_name: str = DEFAULT_WORKER_NAME,
    shutdown: ShutdownSignal | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """job이 있으면 계속 처리하고, 없으면 쉬고, 종료 신호를 받으면 나간다.

    쉬는 간격이 `poll_interval_seconds`와 `heartbeat_interval_seconds` 중 **작은
    쪽**인 이유: poll 간격을 heartbeat 간격보다 크게 잡은 설정에서도 생존 신호가
    `heartbeat_stale_seconds` 안에 들어와야 한다. 그러지 않으면 멀쩡한 worker가
    health에서 `stale`로 보인다.
    """
    shutdown = shutdown or ShutdownSignal()
    with session_factory() as db:
        check_active_prompt_versions(db)

    state = LoopState()
    idle_seconds = min(cfg.jobs.poll_interval_seconds, cfg.jobs.heartbeat_interval_seconds)
    while not shutdown.requested:
        # 이 회전이 보는 시각. 아래로는 값으로만 흐른다 (ADR-007).
        now = utc_now()
        handled = run_once(
            session_factory=session_factory,
            provider=provider,
            run_job=run_job,
            cfg=cfg,
            now=now,
            worker_name=worker_name,
            state=state,
        )
        if shutdown.requested:
            break
        if not handled:
            sleep(idle_seconds)


def run_once(
    *,
    session_factory: SessionFactory,
    provider: LlmProvider,
    run_job: JobRunner,
    cfg: AppConfig,
    now: datetime,
    worker_name: str = DEFAULT_WORKER_NAME,
    state: LoopState | None = None,
) -> bool:
    """loop 1회전. job을 하나 처리했으면 True.

    실패로 끝난 job도 True다 --- 반환값의 뜻은 "성공했다"가 아니라 "쉬지 않고 다음
    job으로 넘어가도 된다"이다.
    """
    state = state if state is not None else LoopState()

    with session_factory() as heartbeat_db:
        # job 트랜잭션과 **분리된 세션**이다. job이 롤백돼도 생존 신호는 남는다.
        write_heartbeat(heartbeat_db, worker_name=worker_name, now=now)

    with session_factory() as db:
        queue.reclaim_stale_jobs(db, now=now, cfg=cfg)
        if queue.ceiling_reached(db, now=now, cfg=cfg):
            _log_ceiling(db, now=now, state=state)
            return False
        state.ceiling_logged = False
        job = queue.claim_next_job(db, now=now)
        if job is None:
            return False
        job_id = job.id
        job_type = job.job_type.value
        observability.log_job_claimed(job_id=job_id, job_type=job_type, retry_count=job.retry_count)

    started = time.perf_counter()
    try:
        with session_factory() as db:
            claimed = _load_job(db, job_id)
            status = run_job(db, job=claimed, provider=provider, now=now, cfg=cfg)
            result_ref: dict[str, Any] = claimed.result_ref or {}
            retry_count = claimed.retry_count
            last_error = claimed.last_error
            if status is GenerationJobStatus.COMPLETED:
                _log_ready_pool_size(db, job=claimed)
    # runner가 무엇을 던지든 job은 끝나야 한다. 여기서 새면 그 job은 lease가 만료될
    # 때까지 `running`에 갇히고, worker는 그 사이에 다음 job도 집지 못한다.
    except Exception as error:
        _record_unhandled_failure(
            session_factory, job_id=job_id, job_type=job_type, error=error, now=now, cfg=cfg
        )
        return True

    if status is GenerationJobStatus.COMPLETED:
        observability.log_job_completed(
            job_id=job_id,
            job_type=job_type,
            duration_ms=int((time.perf_counter() - started) * 1000),
            sentences_persisted=len(result_ref.get("sentence_ids") or []),
            validation_failures=len(result_ref.get("rejected") or []),
        )
    else:
        observability.log_job_failed(
            job_id=job_id,
            job_type=job_type,
            retry_count=retry_count,
            next_status=status.value,
            error_type=_error_category(last_error),
        )
    return True


# --------------------------------------------------------------------------
# 내부
# --------------------------------------------------------------------------


def _load_job(db: Session, job_id: int) -> GenerationJob:
    job = db.get(GenerationJob, job_id)
    if job is None:
        raise WorkerError(f"claimed job {job_id} disappeared")
    return job


def _error_category(last_error: str | None) -> str:
    """runner가 적은 `last_error`에서 **분류만** 뽑는다.

    runner의 문자열은 `"<분류>: <상세>"` 꼴이고 앞부분은 고정 리터럴이다
    (`provider call failed`, `invalid response`, `no content accepted`,
    `PermanentReason` 값). 상세 쪽에는 provider 응답 조각이 들어갈 수 있으므로 로그에
    싣지 않는다 --- 그쪽은 `generation_jobs.last_error`에만 남는다.
    """
    if not last_error:
        return "unknown"
    return last_error.split(":", 1)[0].strip()[: observability.MAX_ERROR_LENGTH]


def _record_unhandled_failure(
    session_factory: SessionFactory,
    *,
    job_id: int,
    job_type: str,
    error: BaseException,
    now: datetime,
    cfg: AppConfig,
) -> None:
    """runner에서 빠져나온 예외를 재시도 가능한 실패로 적는다.

    **새 세션**을 쓴다. 실패한 세션에는 확정하면 안 되는 변경이 남아 있을 수 있고,
    그 위에서 커밋하면 절반만 저장된 콘텐츠가 completed 아닌 job과 함께 남는다.

    job이 이미 `running`이 아니면 아무것도 하지 않는다. runner가 결과를 적은 뒤에
    별개의 이유로 실패한 경우이고, 그 판정을 여기서 덮으면 `dead_letter`가
    `retry`로 되살아난다.
    """
    with session_factory() as db:
        job = _load_job(db, job_id)
        if job.status is not GenerationJobStatus.RUNNING:
            observability.log_job_failed(
                job_id=job_id,
                job_type=job_type,
                retry_count=job.retry_count,
                next_status=job.status.value,
                error_type=type(error).__name__,
            )
            return
        status = queue.record_retryable_failure(
            db, job=job, error=observability.describe_error(error), now=now, cfg=cfg
        )
        observability.log_job_failed(
            job_id=job_id,
            job_type=job_type,
            retry_count=job.retry_count,
            next_status=status.value,
            error_type=type(error).__name__,
        )


def _log_ceiling(db: Session, *, now: datetime, state: LoopState) -> None:
    """왜 멈췄는지를 한 줄로 남긴다.

    `jobs_with_unknown_tokens`가 0이 아니면 token 합은 총량이 아니라 **하한**이고, 그
    자체가 멈춘 이유일 수 있다(`queue.ceiling_reached`). 그 수를 함께 싣지 않으면
    "한도에 한참 못 미치는데 왜 쉬는가"에 답할 수 있는 값이 아무 데도 없다.
    """
    if state.ceiling_logged:
        return
    state.ceiling_logged = True
    usage = queue.daily_usage(db, now=now)
    observability.logger.warning(
        observability.COST_CEILING_REACHED,
        extra={
            "provider_calls": usage.provider_calls,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "jobs_with_unknown_tokens": usage.jobs_with_unknown_tokens,
        },
    )


def _log_ready_pool_size(db: Session, *, job: GenerationJob) -> None:
    """생성이 끝난 (사용자, role)의 ready pool 크기 (11_OBSERVABILITY.md).

    payload에 둘 다 없는 job_type(`EXPLAIN_ITEM` 등)은 건너뛴다. pool 크기는
    `user_sentence_candidates`에서 읽는 파생값이므로 저장하지 않는다.
    """
    payload = job.payload_json or {}
    user_id = payload.get("user_id")
    role = payload.get("presentation_role")
    if not isinstance(user_id, int) or not isinstance(role, str):
        return
    size = db.scalar(
        sa.select(sa.func.count())
        .select_from(UserSentenceCandidate)
        .where(
            UserSentenceCandidate.user_id == user_id,
            UserSentenceCandidate.presentation_role == role,
            UserSentenceCandidate.status == CandidateStatus.READY,
        )
    )
    observability.log_ready_pool_size(user_id=user_id, role=role, size=int(size or 0))
