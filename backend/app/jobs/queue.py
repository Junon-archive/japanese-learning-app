"""Job queue의 claim과 상태 전이 (09_BACKGROUND_JOBS.md, ADR-015).

이 모듈은 **provider를 모른다.** `app.llm`을 import하지 않고 payload의 내용도 읽지
않는다. 여기 있는 것은 "어느 job을 지금 실행해도 되는가"와 "그 결과를 어떤 상태로
적을 것인가"뿐이다. provider 호출은 `jobs/runner.py`, 콘텐츠 저장은
`jobs/persistence.py`다.

commit 지점(ADR-015의 `트랜잭션 경계`):

``` text
claim       queued|retry -> running     여기        provider 호출 **전**
usage       result_ref.usage 누적       여기        provider 응답 직후
validated   running -> validated        여기        진단 지점 (재개 지점이 아니다)
completed   -> completed                persistence.py 가 콘텐츠 저장과 같은 커밋에서
outcome     -> retry / failed / dead_letter         여기
```

`apply_completion()`만 commit하지 않는다. `completed`를 콘텐츠 저장과 나누면 저장은
됐는데 completed가 아닌 job이 재실행되어 콘텐츠를 두 번 만든다. 그래서 이 함수는
**같은 트랜잭션에 얹을 수 있는 형태**로만 제공되고, 커밋은 저장하는 쪽이 한다.

`retry_count` 증가는 claim 커밋에 들어간다. 실패 경로에서 올리면 crash한 job은
증가 없이 lease로 회수되기만 하므로 영원히 재시도된다.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.config import AppConfig
from app.models.enums import GenerationJobStatus
from app.models.jobs import GenerationJob

CLAIMABLE_STATUSES = (GenerationJobStatus.QUEUED, GenerationJobStatus.RETRY)

# lease 만료로 회수된 job의 `last_error` (09_BACKGROUND_JOBS.md의 stale running 회수).
LEASE_EXPIRED = "lease_expired"


class PermanentReason(enum.StrEnum):
    """attempt를 소진하지 않고 즉시 `dead_letter`로 보내는 오류.

    09_BACKGROUND_JOBS.md가 이 4개로 **한정**했다. 닫힌 집합을 타입으로 두는 이유는
    "이건 어차피 안 될 것 같으니 dead_letter"가 하나씩 늘어나는 것을 막기 위해서다.
    provider timeout / 5xx / rate limit / parsing 실패 / validation 전량 탈락 /
    인증 실패(401·403)는 전부 재시도 대상이고 소진하면 `failed`다 --- 특히 인증
    실패는 키 교체 중의 일시적 상태와 영구 설정 오류를 job 하나가 구분할 수 없다.
    """

    INVALID_PAYLOAD = "invalid_payload"
    MISSING_REFERENCE = "missing_reference"
    UNSUPPORTED_JOB_TYPE = "unsupported_job_type"
    NO_ACTIVE_PROMPT_VERSION = "no_active_prompt_version"


@dataclass(frozen=True)
class DailyUsage:
    """오늘(UTC) provider에 쓴 양. `generation_jobs.result_ref.usage`의 합이다.

    `jobs_with_unknown_tokens`는 오늘 호출한 job 중 **token 총량을 모르는** job 수다
    (provider가 usage를 주지 않은 호출이 하나라도 있었던 job). 그 수가 0이 아니면
    `input_tokens`/`output_tokens`는 총량이 아니라 **하한**이다.
    """

    provider_calls: int
    input_tokens: int
    output_tokens: int
    jobs_with_unknown_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def tokens_are_complete(self) -> bool:
        """token 합이 오늘의 **전부**인가. 아니면 한도와 비교할 수 없다."""
        return self.jobs_with_unknown_tokens == 0


# --------------------------------------------------------------------------
# claim
# --------------------------------------------------------------------------


def reclaim_stale_jobs(db: Session, *, now: datetime, cfg: AppConfig) -> int:
    """lease가 끊긴 `running`을 회수한다. worker loop에서 claim보다 **먼저** 부른다.

    worker가 실행 중에 죽으면 그 job은 `running`에 남고 claim 조건
    (`queued|retry`)에 걸리지 않아 아무도 집어가지 않는다.

    `retry_count`를 함께 증가시킨다. 증가시키지 않으면 실행할 때마다 죽는 job이
    "lease 만료 -> 재실행"을 영원히 반복한다. 증가분이 예산을 소진시키면 여기서
    바로 `failed`다 --- 회수된 job은 record_retryable_failure를 부를 주체가 이미
    없으므로(그 프로세스가 죽었다) 여기서 끝내지 않으면 소진 판정이 영영 오지 않는다.
    """
    deadline = now - timedelta(seconds=cfg.jobs.claim_lease_seconds)
    exhausted = GenerationJob.retry_count + 1 >= GenerationJob.max_attempts
    statement = (
        sa.update(GenerationJob)
        .where(
            GenerationJob.status == GenerationJobStatus.RUNNING,
            GenerationJob.started_at < deadline,
        )
        .values(
            status=sa.case(
                (exhausted, GenerationJobStatus.FAILED.value),
                else_=GenerationJobStatus.RETRY.value,
            ),
            retry_count=GenerationJob.retry_count + 1,
            next_attempt_at=now,
            last_error=LEASE_EXPIRED,
            finished_at=sa.case((exhausted, now), else_=None),
        )
        .returning(GenerationJob.id)
        .execution_options(synchronize_session=False)
    )
    reclaimed = len(db.execute(statement).scalars().all())
    db.commit()
    return reclaimed


def claim_statement(*, now: datetime) -> sa.Update:
    """claim의 SQL 하나. UPDATE와 SELECT를 나누지 않는다.

    나누면 worker가 하나뿐이어도 재시작 직후 두 프로세스가 잠깐 겹치는 순간에 같은
    job을 둘이 집고, provider 비용이 그대로 두 배가 된다. `FOR UPDATE SKIP LOCKED`가
    그것을 막는다 --- 다른 트랜잭션이 잡고 있는 행은 **기다리지 않고 건너뛴다**.

    문장을 따로 노출하는 이유는 하나다. 동시성 테스트가 "커넥션 A가 트랜잭션을 연 채
    claim한 상태"를 만들려면 커밋하지 않는 실행이 필요한데, 그 자리에 테스트가 SQL을
    베껴 쓰면 `SKIP LOCKED`를 지우는 회귀를 검사하지 못한다(양쪽이 갈린다).
    """
    candidate = (
        sa.select(GenerationJob.id)
        .where(
            GenerationJob.status.in_(CLAIMABLE_STATUSES),
            GenerationJob.next_attempt_at <= now,
        )
        .order_by(GenerationJob.next_attempt_at, GenerationJob.id)
        .with_for_update(skip_locked=True)
        .limit(1)
        .scalar_subquery()
    )
    statement = (
        sa.update(GenerationJob)
        .where(GenerationJob.id == candidate)
        .values(
            status=GenerationJobStatus.RUNNING.value,
            started_at=now,
            retry_count=GenerationJob.retry_count + 1,
        )
        .returning(GenerationJob.id)
        .execution_options(synchronize_session=False)
    )
    return statement


def claim_next_job(db: Session, *, now: datetime) -> GenerationJob | None:
    """실행할 job 하나를 `running`으로 잠그고 **커밋**한다. 없으면 None.

    `next_attempt_at > now`인 job은 집지 않는다. 그것이 backoff의 전부다.
    `retry_count`는 이 커밋에서 오른다 --- provider를 부르기 전에 예산을 소비해야
    실행 중에 죽은 job도 언젠가 예산을 소진한다.
    """
    job_id = db.execute(claim_statement(now=now)).scalar_one_or_none()
    if job_id is None:
        db.commit()  # 잠금을 잡지 않았어도 열린 트랜잭션을 남기지 않는다.
        return None
    job = db.get(GenerationJob, job_id, populate_existing=True)
    db.commit()
    return job


# --------------------------------------------------------------------------
# 상태 전이
# --------------------------------------------------------------------------


def release_read_transaction(db: Session) -> None:
    """provider를 부르기 **전에** 읽기 트랜잭션을 닫는다 (ADR-015의 `트랜잭션 경계`).

    `runner`가 컨텍스트를 모으는 동안 열린 트랜잭션은 커넥션과 snapshot을 붙든다.
    그대로 수 초짜리 HTTP를 타면 request 경로가 같은 pool에서 굶는다. 쓰기가 없으므로
    commit이 아니라 rollback이다 --- 컨텍스트 수집 단계가 실수로 남긴 변경까지 함께
    버린다.

    `runner`가 직접 부르지 못하는 이유는 G7이다. commit/rollback은 `queue.py`와
    `persistence.py`에만 있다.
    """
    db.rollback()


def mark_validated(db: Session, *, job: GenerationJob) -> None:
    """provider 응답이 deterministic validation을 통과했다.

    **재개 지점이 아니다.** raw 응답을 저장하지 않으므로 여기서 죽은 job을 다시
    돌리면 provider를 다시 부른다. 이 커밋이 사는 것은 "provider 실패 / validation
    실패 / 저장 실패"가 `status`로 갈린다는 것 하나뿐이다(ADR-015).
    """
    job.status = GenerationJobStatus.VALIDATED
    job.last_error = None
    db.commit()


def apply_completion(
    db: Session, *, job: GenerationJob, now: datetime, result: dict[str, Any]
) -> None:
    """`completed`로 적는다. **commit하지 않는다.**

    부르는 쪽(`jobs/persistence.py`)이 콘텐츠 INSERT와 **같은 트랜잭션**에서 커밋한다.
    나누면 저장은 됐는데 completed가 아닌 job이 남고, 그 job이 재실행되어 콘텐츠를 두
    번 만든다.

    `result`에 usage를 담지 않는다. 이미 기록된 `result_ref.usage`는 여기서 보존한다
    --- 실패한 호출도 비용이고, 성공 시점의 덮어쓰기로 사라지면 안 된다.
    """
    job.status = GenerationJobStatus.COMPLETED
    job.finished_at = now
    job.last_error = None
    job.result_ref = _merge_result(job.result_ref, result)
    db.flush()


def record_rejections(
    db: Session, *, job: GenerationJob, rejected: Sequence[Mapping[str, str]]
) -> None:
    """탈락 사유만 `result_ref`에 남긴다. **상태는 바꾸지 않는다.**

    통과한 문장이 하나도 없어 `completed`로 갈 수 없는 attempt의 진단 기록이다
    (`08_LLM_SPEC.md`의 `탈락한 콘텐츠의 처리`). 뒤따르는 `record_retryable_failure`가
    상태를 정하고, 그 사이에 rollback이 끼어도 사유는 남아야 하므로 여기서 커밋한다.
    """
    job.result_ref = _merge_result(job.result_ref, {"rejected": [dict(item) for item in rejected]})
    db.commit()


def record_retryable_failure(
    db: Session, *, job: GenerationJob, error: str, now: datetime, cfg: AppConfig
) -> GenerationJobStatus:
    """재시도할 수 있는 오류. 예산이 남았으면 `retry`, 소진했으면 `failed`.

    `retry_count`는 claim에서 이미 증가했다. 여기서 다시 올리지 않는다 --- 두 번
    올리면 예산이 절반이 되고, 여기서만 올리면 crash한 job이 예산을 쓰지 않는다.

    backoff는 `retry_backoff_base_seconds * 2 ** (retry_count - 1)`이다. 증가 없이
    다시 대기시키는 분기는 두지 않는다. 그 분기가 곧 무한 retry다.
    """
    job.last_error = error
    if job.retry_count >= job.max_attempts:
        job.status = GenerationJobStatus.FAILED
        job.finished_at = now
    else:
        job.status = GenerationJobStatus.RETRY
        job.next_attempt_at = now + retry_delay(retry_count=job.retry_count, cfg=cfg)
    db.commit()
    return job.status


def record_permanent_failure(
    db: Session, *, job: GenerationJob, reason: PermanentReason, now: datetime
) -> None:
    """재시도해도 결과가 같은 오류. attempt를 소진하지 않고 즉시 끝낸다.

    `failed`와 나누는 이유는 운영 판단이다. `failed`는 원인을 고친 뒤
    `retry_count`/`next_attempt_at`을 되돌리면 다시 도는 job이고, `dead_letter`는
    그렇게 해도 같은 결과가 나오는 job이다. 자동 재활성화 경로는 MVP에 없다.
    """
    job.status = GenerationJobStatus.DEAD_LETTER
    job.last_error = reason.value
    job.finished_at = now
    db.commit()


def retry_delay(*, retry_count: int, cfg: AppConfig) -> timedelta:
    """exponential backoff. `retry_count`는 이미 소비한 attempt 수(>= 1)다."""
    exponent = max(retry_count - 1, 0)
    return timedelta(seconds=cfg.jobs.retry_backoff_base_seconds * 2**exponent)


# --------------------------------------------------------------------------
# usage (09_BACKGROUND_JOBS.md의 `usage 기록과 일 경계`)
# --------------------------------------------------------------------------


def record_usage(
    db: Session,
    *,
    job: GenerationJob,
    provider_calls: int,
    input_tokens: int | None,
    output_tokens: int | None,
    now: datetime,
    estimated_cost_usd: float | None = None,
) -> None:
    """provider 응답 **직후** 부른다. 그 job이 나중에 실패해도 지우지 않는다.

    별도 usage 테이블을 만들지 않는다. attempt가 여러 번이면 누적하고
    (`last_call_at`만 마지막 값), 즉시 commit한다 --- 뒤따르는 실패의 rollback이
    이미 발생한 비용의 기록까지 지우면 안 된다.

    token 수가 `None`이면 그 키는 **`null`로 저장한다**(0이 아니다). `null`의 뜻은
    "이 job이 쓴 총량을 모른다"이고 한 번 모르면 이후 attempt에서도 총량을 알 수
    없으므로 계속 `null`이다 --- 아는 부분만 더해 숫자로 적으면 그 숫자가 총량처럼
    보이고 `daily_token_limit`이 조용히 무력해진다.

    `estimated_cost_usd`도 같은 성질이라 같은 함수로 누적한다. 마지막 attempt 값으로
    덮어쓰면 retry한 job의 비용이 실제의 1/attempt로 보인다. 다만 이 값은 관측
    항목이고 ceiling 판정에 쓰이지 않는다 --- 한도를 만드는 것은
    `daily_request_limit`과 `daily_token_limit`뿐이다.
    """
    previous = (job.result_ref or {}).get("usage") or {}
    usage = {
        "provider_calls": int(previous.get("provider_calls") or 0) + provider_calls,
        "input_tokens": _accumulate(previous, "input_tokens", input_tokens),
        "output_tokens": _accumulate(previous, "output_tokens", output_tokens),
        "estimated_cost_usd": _accumulate(previous, "estimated_cost_usd", estimated_cost_usd),
        "last_call_at": now.astimezone(UTC).isoformat(),
    }
    job.result_ref = _merge_result(job.result_ref, {"usage": usage})
    db.commit()


def daily_usage(db: Session, *, now: datetime) -> DailyUsage:
    """오늘 UTC 00:00 이후에 호출된 job들의 usage 합.

    **일 경계는 UTC다.** `users.timezone`을 쓰지 않는다. 이 한도는 사용자에게 보이는
    학습 경계가 아니라 provider 청구를 막는 전역 장치이고, job은 사용자 단위로 돌지
    않는다(사용자가 여럿이면 누구의 timezone인지에 답이 없다).

    한계: 하루를 걸쳐 실행된 job의 token은 `last_call_at`이 속한 날에 전부 계상된다.
    """
    usage = GenerationJob.result_ref["usage"]
    last_call_at = usage["last_call_at"].astext.cast(sa.DateTime(timezone=True))
    unknown_tokens = sa.or_(
        usage["input_tokens"].astext.is_(None),
        usage["output_tokens"].astext.is_(None),
    )
    totals = (
        sa.select(
            sa.func.coalesce(sa.func.sum(_usage_int(usage, "provider_calls")), 0),
            sa.func.coalesce(sa.func.sum(_usage_int(usage, "input_tokens")), 0),
            sa.func.coalesce(sa.func.sum(_usage_int(usage, "output_tokens")), 0),
            sa.func.coalesce(sa.func.sum(sa.case((unknown_tokens, 1), else_=0)), 0),
        )
        .select_from(GenerationJob)
        .where(last_call_at >= _utc_day_start(now))
    )
    calls, input_tokens, output_tokens, unknown = db.execute(totals).one()
    return DailyUsage(
        provider_calls=int(calls),
        input_tokens=int(input_tokens),
        output_tokens=int(output_tokens),
        jobs_with_unknown_tokens=int(unknown),
    )


def ceiling_reached(db: Session, *, now: datetime, cfg: AppConfig) -> bool:
    """오늘의 daily ceiling을 이미 넘었는가. `null` 한도는 꺼진 것이다.

    worker는 이것이 True면 **claim하지 않고** 다음 poll까지 쉰다. claim한 뒤 실패로
    끝내면 한도 때문에 `retry_count`가 소모되어, 다음 날 살아 있어야 할 job이
    `failed`가 된다.

    **token 총량을 모르면 token 한도는 도달한 것으로 본다.** provider가 usage를 주지
    않은 호출이 오늘 하나라도 있으면 `total_tokens`는 하한이고, 그것을 한도와
    비교하는 것은 한도를 지키는 척하는 것이다. 계속 부르는 쪽을 택하면
    `daily_token_limit`을 켜 둔 운영자가 상한 없는 청구서를 받는다 --- 그것이 이 키가
    막으라고 있는 유일한 사건이다. 멈추는 쪽은 눈에 보이고 되돌릴 수 있다: worker는
    쉬면서 `cost.ceiling_reached`에 `jobs_with_unknown_tokens`를 함께 남기고, 학습
    세션은 Ready Pool로 계속 돈다(불변식 #1). 한도를 끄려면 `null`로 두면 된다
    --- 그것이 `14_CONFIGURATION.md`가 정한 "limit disabled"이고 기본값이다.
    """
    request_limit = cfg.llm.daily_request_limit
    token_limit = cfg.llm.daily_token_limit
    if request_limit is None and token_limit is None:
        return False
    usage = daily_usage(db, now=now)
    if request_limit is not None and usage.provider_calls >= request_limit:
        return True
    if token_limit is None:
        return False
    return not usage.tokens_are_complete or usage.total_tokens >= token_limit


# --------------------------------------------------------------------------
# 내부
# --------------------------------------------------------------------------


def _utc_day_start(now: datetime) -> datetime:
    return now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


def _usage_int(usage: sa.ColumnElement[Any], key: str) -> sa.ColumnElement[Any]:
    return sa.func.coalesce(usage[key].astext.cast(sa.BigInteger), 0)


def _accumulate[Amount: (int, float)](
    previous: Mapping[str, Any], key: str, delta: Amount | None
) -> Amount | None:
    """누적 usage 값. `None`은 0이 아니라 "모른다"이고 한 번 모르면 계속 모른다.

    token과 `estimated_cost_usd`가 같은 규칙(sticky-null)이라 한 함수다. 같은 규칙을
    두 곳에 적으면 한쪽만 고쳐지고 갈린다.
    """
    if delta is None:
        return None
    stored = previous.get(key, 0)
    if stored is None:
        return None
    return type(delta)(stored) + delta


def _merge_result(result_ref: dict[str, Any] | None, update: dict[str, Any]) -> dict[str, Any]:
    """JSONB는 제자리 수정을 추적하지 않는다. 항상 새 dict를 대입한다."""
    return {**(result_ref or {}), **update}
