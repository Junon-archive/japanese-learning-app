"""job 1건 실행 파이프라인 (ADR-015).

``` text
claim        queue.claim_next_job         호출자(worker)가 이미 했다
prepare      handler.prepare              DB 읽기만. 대상 재계산과 요청 조립
release      queue.release_read_transaction   provider 호출 **전에** 트랜잭션을 닫는다
call         provider.generate_structured 트랜잭션 밖
log          observability.log_provider_call  응답 직후. token은 provider가 준 값
usage        queue.record_usage           응답 직후. 실패해도 지우지 않는다
validate     handler(plan).complete       순수 검증 -> mark_validated
persist      persistence                  콘텐츠 저장 + completed (같은 커밋)
outcome      queue.record_*_failure       retry / failed / dead_letter
```

-   **provider를 인자로 받는다.** 전역 싱글턴도 import 시점 생성도 아니다. 그 자리가
    test double이 들어갈 자리다(`08_LLM_SPEC.md`의 `Provider 선택과 model 출처`).
-   **provider 호출 중에 DB 트랜잭션을 열어 두지 않는다.** 수 초짜리 HTTP가 커넥션과
    행 잠금을 붙들면 request 경로가 같은 pool에서 굶는다. 그래서 컨텍스트 수집(DB
    읽기) -> 트랜잭션 닫기 -> provider 호출 -> validation -> 새 트랜잭션에서 영속화다.
-   **commit하지 않는다**(G7). 이 파일에 commit이 하나라도 생기면 위 순서가 무의미해
    진다. 상태 전이는 `queue.py`, 콘텐츠 저장과 `completed`는 `persistence.py`다.
-   `now`를 인자로 받는다. `clock.utc_now()`를 부르지 않는다 --- 진입점은 worker다(G9).
-   **`last_error`에 예외 메시지를 그대로 싣지 않는다.** provider SDK의 예외와 pydantic
    `ValidationError`에는 응답 본문 조각이 들어 있고, SQLAlchemy의 예외에는 bind
    parameter(=방금 만든 문장)가 들어 있다. `observability.describe_error()`로 한 줄로
    접고 상한에서 자른다 --- `generation_jobs.last_error`가 무제한으로 자라면 그것이
    "응답 원문을 남기지 않는다"를 우회하는 경로가 된다(`11_OBSERVABILITY.md`,
    `04_SECURITY_AND_DATA.md`). 앞의 분류 리터럴은 유지한다(worker의 `_error_category`).

`08_LLM_SPEC.md`가 정한 실패 분류를 그대로 쓴다.

``` text
payload 필수 key 불만족 / 참조 행 없음 / 미구현 job_type /
active prompt_versions 없음                       -> dead_letter (attempt 소진 없이)
provider timeout·5xx·rate limit·인증 실패 /
structured output parsing 실패 / validation 전량 탈락 /
저장 실패                                          -> retry, 소진하면 failed
```
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Protocol

from sqlalchemy.orm import Session

from app.config import AppConfig
from app.jobs import explain_item, generate_sentence_batch, observability, queue, review_context
from app.jobs.persistence import Completion, PersistenceError, Provenance
from app.llm.provider import LlmError, LlmProvider, ProviderRequest, ProviderResult
from app.models.enums import GenerationJobStatus, JobType
from app.models.jobs import GenerationJob


class JobPlan(Protocol):
    """handler가 prepare 단계에서 만든 실행 계획.

    `request`가 None이면 provider를 부를 일이 없는 job이다(대상 0건, 이미 채워진
    explanation, quarantined anchor). 그 경우 `complete`는 곧바로 `completed`로 끝낸다.
    `provenance`는 `request`와 **함께 있거나 함께 없다** --- handler는 active
    `prompt_versions` 행으로 요청을 조립하므로, 부를 요청이 있으면 그 행도 있다.

    `provenance`를 계획이 들고 있는 이유는 `provider.call` 로그가 요구하는
    prompt_version/model의 출처가 그 행이기 때문이다(`11_OBSERVABILITY.md`). 응답에서
    읽지 않는다.

    `complete`가 아무것도 저장하지 못했으면(`Completion.stored`가 빈 tuple) 그 job은
    `completed`가 **아니다.** 상태 전이는 이 모듈이 `queue`에 맡긴다.
    """

    @property
    def request(self) -> ProviderRequest | None: ...

    @property
    def provenance(self) -> Provenance | None: ...

    def complete(
        self,
        db: Session,
        *,
        job: GenerationJob,
        response: ProviderResult | None,
        now: datetime,
    ) -> Completion: ...


Prepare = Callable[..., JobPlan | queue.PermanentReason]

# job_type -> handler. dict 하나이며 동적 등록 지점이 아니다(ADR-015의 추상화 상한).
HANDLERS: Mapping[JobType, Prepare] = {
    JobType.GENERATE_SENTENCE_BATCH: generate_sentence_batch.prepare,
    JobType.GENERATE_REVIEW_CONTEXT: review_context.prepare,
    JobType.EXPLAIN_ITEM: explain_item.prepare,
}


def run_job(
    db: Session,
    *,
    job: GenerationJob,
    provider: LlmProvider,
    cfg: AppConfig,
    now: datetime,
) -> GenerationJobStatus:
    """claim된 job 하나를 끝까지 실행하고 최종 상태를 돌려준다.

    예외를 밖으로 흘리지 않는다. worker loop가 job 하나 때문에 죽으면 그 job은
    `running`으로 남아 lease 만료를 기다리고, 그 사이 대기열 전체가 멈춘다.
    """
    prepare = HANDLERS.get(job.job_type)
    if prepare is None:
        # enum이 닫혀 있어 지금은 도달하지 않는다. 새 job_type이 추가될 때 조용한
        # KeyError로 worker를 죽이지 않기 위한 자리다.
        return _permanent(db, job=job, reason=queue.PermanentReason.UNSUPPORTED_JOB_TYPE, now=now)

    plan = prepare(db, job=job, cfg=cfg, now=now)
    if isinstance(plan, queue.PermanentReason):
        return _permanent(db, job=job, reason=plan, now=now)

    # provider 호출 전에 읽기 트랜잭션을 닫는다(ADR-015).
    queue.release_read_transaction(db)

    request = plan.request
    provenance = plan.provenance
    if request is None or provenance is None:
        # provider를 부를 계획이 아니다. 두 값은 함께 있거나 함께 없다(`JobPlan`).
        plan.complete(db, job=job, response=None, now=now)
        return GenerationJobStatus.COMPLETED

    try:
        response = provider.generate_structured(request)
    except LlmError as error:
        return _retryable(
            db,
            job=job,
            error=f"provider call failed: {observability.describe_error(error)}",
            now=now,
            cfg=cfg,
        )

    # 응답을 받은 직후 기록한다. 뒤에서 실패해도 지우지 않는다 --- 실패한 호출도 비용이다.
    # token 수를 provider가 주지 않으면 `None`이 그대로 올라간다(0으로 적지 않는다).
    observability.log_provider_call(
        task=job.job_type.value,
        prompt_version=provenance.prompt_version,
        model=provenance.model,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
    )
    queue.record_usage(
        db,
        job=job,
        provider_calls=1,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        now=now,
    )

    try:
        completion = plan.complete(db, job=job, response=response, now=now)
    except LlmError as error:
        # structured output parsing 실패. 재시도 대상이다.
        return _retryable(
            db,
            job=job,
            error=f"invalid response: {observability.describe_error(error)}",
            now=now,
            cfg=cfg,
        )
    except PersistenceError as error:
        # 저장 실패를 성공처럼 적지 않는다.
        return _retryable(db, job=job, error=observability.describe_error(error), now=now, cfg=cfg)

    if not completion.stored:
        # deterministic validation 전량 탈락. 사유는 이미 `result_ref.rejected`에 있다.
        reasons = ", ".join(sorted({item.reason.value for item in completion.rejected}))
        return _retryable(db, job=job, error=f"no content accepted: {reasons}", now=now, cfg=cfg)
    return GenerationJobStatus.COMPLETED


def _permanent(
    db: Session, *, job: GenerationJob, reason: queue.PermanentReason, now: datetime
) -> GenerationJobStatus:
    queue.record_permanent_failure(db, job=job, reason=reason, now=now)
    return GenerationJobStatus.DEAD_LETTER


def _retryable(
    db: Session, *, job: GenerationJob, error: str, now: datetime, cfg: AppConfig
) -> GenerationJobStatus:
    return queue.record_retryable_failure(db, job=job, error=error, now=now, cfg=cfg)
