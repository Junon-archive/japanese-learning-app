"""worker가 남기는 구조화 로그 (11_OBSERVABILITY.md의 `MVP 필수 범위`).

MVP가 수집하는 것은 여섯 개뿐이고 **전부 기존 테이블에서 읽을 수 있다**. 그래서
metrics 테이블도 대시보드도 만들지 않는다. 이 모듈이 하는 일은 그 여섯 개가 일어난
순간을 stdlib `logging`으로 한 줄씩 남기는 것뿐이다.

``` text
job count / failure / retry    job.claimed  job.completed  job.failed
provider call count / tokens   provider.call
estimated cost if available    provider.call 의 estimated_cost_usd (있을 때만)
ready pool size                pool.ready_size
```

금지 사항이 이 모듈의 존재 이유다(11_OBSERVABILITY.md, 04_SECURITY_AND_DATA.md).

-   **API key / auth token / password를 남기지 않는다.**
-   **prompt 원문과 provider 응답 원문을 남기지 않는다.** 남기는 것은 어느 prompt
    version과 어느 model이었는지(=provenance)까지다.
-   예외는 `describe_error()`로 **타입 + 정제된 짧은 메시지**로 줄인다. provider
    라이브러리의 예외 메시지에는 응답 본문이 그대로 들어 있을 수 있고, 그것이
    `generation_jobs.last_error`에 무제한으로 쌓이면 로그 금지 규칙을 우회하는
    경로가 된다.

`estimated_cost_usd`는 "if available"이다. provider가 값을 주지 않으면 **필드를
생략한다.** 단가표를 코드에 넣지 않는다(09_BACKGROUND_JOBS.md).
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger("app.jobs")

# `last_error`와 로그 메시지의 길이 상한. 정제된 한 줄이면 충분하고, 넘는 부분은
# 대개 provider 응답 본문이나 stack 조각이다.
MAX_ERROR_LENGTH = 200

# API key 꼴의 토큰. `sk-` 접두는 OpenAI와 그 앞에 놓이는 proxy(LiteLLM류의 가상 키)가
# 공유하는 형태다. 이 모듈은 **실제 키 값을 모른다** --- `app/llm/`이 환경을 읽지 않고
# (G11a) 키는 `scripts/run_worker.py`에서 `build_provider()`로만 들어가므로, 값을
# 여기까지 인자로 끌어오면 secret이 사는 프레임만 늘어난다(그것이 `OpenAiProvider`의
# `repr=False`가 막는 바로 그 위험이다). 그래서 값 대신 **모양**으로 지운다.
_SECRET_TOKEN = re.compile(r"sk-[A-Za-z0-9_-]{8,}")
_REDACTED = "[redacted]"

JOB_CLAIMED = "job.claimed"
JOB_COMPLETED = "job.completed"
JOB_FAILED = "job.failed"
PROVIDER_CALL = "provider.call"
POOL_READY_SIZE = "pool.ready_size"
COST_CEILING_REACHED = "cost.ceiling_reached"
COST_GUARD_DISABLED = "cost.guard_disabled"

# MVP-02 후리가나(11_OBSERVABILITY.md의 `MVP-02 추가: 후리가나 계산 결과`). 위 닫힌 집합과 별도
# 이름공간이다. **문장 텍스트와 읽기 문자열을 싣지 않는다** --- id와 숫자뿐이다.
RUBY_COMPUTED = "ruby.computed"
RUBY_FAILED = "ruby.failed"
RUBY_READING_MISMATCH = "ruby.reading_mismatch"
RUBY_EXPLANATION_OVERRIDE = "ruby.explanation_override"


def describe_error(error: BaseException) -> str:
    """예외를 한 줄로 줄인다. `last_error`와 로그가 같은 문자열을 쓴다.

    타입 이름을 남기는 이유는 그것이 retry/failure 분류의 근거이기 때문이다
    (`09_BACKGROUND_JOBS.md`의 `failed와 dead_letter의 경계`). 메시지는 개행을 접고
    상한에서 자른다 --- 자르는 쪽이 조용히 커지는 쪽보다 낫다.

    **key 꼴의 토큰은 상한보다 먼저 지운다.** 이 문자열은 `generation_jobs.last_error`로
    들어가고 그 행은 정기 `pg_dump`를 타고 다른 물리 디스크의 백업 매체까지 복제된다
    (`04_SECURITY_AND_DATA.md`의 `Backup`). 지금의 openai SDK는 예외 메시지에 키를 넣지
    않지만 이 자리는 SDK가 무엇을 넣든 그대로 받아 적는 seam이므로, 길이만 막고 내용을
    두면 "secret을 남기지 않는다"가 SDK 구현에 의존하게 된다. 자른 뒤에 지우면 잘린
    조각이 남으므로 순서를 바꾸지 않는다.
    """
    detail = _SECRET_TOKEN.sub(_REDACTED, " ".join(str(error).split()))
    described = f"{type(error).__name__}: {detail}" if detail else type(error).__name__
    if len(described) <= MAX_ERROR_LENGTH:
        return described
    return described[: MAX_ERROR_LENGTH - 1] + "…"


def log_job_claimed(*, job_id: int, job_type: str, retry_count: int) -> None:
    logger.info(
        JOB_CLAIMED,
        extra={"job_id": job_id, "job_type": job_type, "retry_count": retry_count},
    )


def log_job_completed(
    *,
    job_id: int,
    job_type: str,
    duration_ms: int,
    sentences_persisted: int,
    validation_failures: int,
) -> None:
    """저장 건수와 validation 탈락 건수는 `result_ref`에서 읽는다.

    두 값의 출처는 `04_DB_SPEC.md`의 `result_ref 구조`(`sentence_ids`, `rejected`)다.
    로그는 그 집계의 **사본**이므로 여기서 다시 계산하지 않는다.
    """
    logger.info(
        JOB_COMPLETED,
        extra={
            "job_id": job_id,
            "job_type": job_type,
            "duration_ms": duration_ms,
            "sentences_persisted": sentences_persisted,
            "validation_failures": validation_failures,
        },
    )


def log_job_failed(
    *, job_id: int, job_type: str, retry_count: int, next_status: str, error_type: str
) -> None:
    """`error_type`은 예외 **타입 이름**이다. 메시지 본문을 여기에 싣지 않는다."""
    logger.warning(
        JOB_FAILED,
        extra={
            "job_id": job_id,
            "job_type": job_type,
            "retry_count": retry_count,
            "next_status": next_status,
            "error_type": error_type,
        },
    )


def log_provider_call(
    *,
    task: str,
    prompt_version: str,
    model: str,
    input_tokens: int | None,
    output_tokens: int | None,
    estimated_cost_usd: float | None = None,
) -> None:
    """provider 응답 **직후** 부른다. `app/jobs/runner.py`가 부르는 자리다.

    `app/llm/`은 비용을 집계하지 않으므로(ADR-015) 이 값의 소유자는 job 쪽이다.

    호출이 **실패한 경우에는 부르지 않는다.** 실패에는 token 수가 없고, 그것을 0으로
    적으면 이 로그의 token 합이 DB(`result_ref.usage`)와 갈린다 --- 실패는
    `job.failed`와 `generation_jobs.last_error`가 남긴다.

    token 필드는 `None`이어도 **싣는다.** `11_OBSERVABILITY.md`가 input/output token을
    MVP 필수 수집 항목으로 요구하므로 필드는 항상 있어야 하고, `None`은 "provider가
    주지 않았다"는 사실이다(0은 거짓이다). `estimated_cost_usd`는 "if available"이라
    없으면 **필드 자체를 생략한다** --- 단가표를 코드에 넣지 않는다.
    """
    fields: dict[str, Any] = {
        "task": task,
        "prompt_version": prompt_version,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }
    if estimated_cost_usd is not None:
        fields["estimated_cost_usd"] = estimated_cost_usd
    logger.info(PROVIDER_CALL, extra=fields)


def log_ready_pool_size(*, user_id: int, role: str, size: int) -> None:
    """생성이 끝난 뒤 그 (사용자, role) pool이 실제로 얼마나 찼는지.

    worker는 candidate를 만들지 않는다(09_BACKGROUND_JOBS.md). 그래서 이 숫자는 "내가
    방금 만든 것"이 아니라 **다음 세션이 쓸 수 있는 양**이고, generation이 pool을
    실제로 회복시켰는지는 이 값으로만 보인다.
    """
    logger.info(POOL_READY_SIZE, extra={"user_id": user_id, "role": role, "size": size})


def log_ruby_computed(
    *,
    sentence_id: int,
    algorithm_version: int,
    spans: int,
    omitted_tappable_boundary: int,
    omitted_numeric: int,
    omitted_no_reading: int,
    corrected_explanation_tokens: int,
    corrected_table_rules: int,
) -> None:
    """`spans`는 ruby span **개수**다. 읽기 문자열을 싣지 않는다."""
    logger.info(
        RUBY_COMPUTED,
        extra={
            "sentence_id": sentence_id,
            "algorithm_version": algorithm_version,
            "spans": spans,
            "omitted_tappable_boundary": omitted_tappable_boundary,
            "omitted_numeric": omitted_numeric,
            "omitted_no_reading": omitted_no_reading,
            "corrected_explanation_tokens": corrected_explanation_tokens,
            "corrected_table_rules": corrected_table_rules,
        },
    )


def log_ruby_failed(*, sentence_id: int, error: BaseException) -> None:
    """계산 실패는 문장 채택을 막지 않는다. 그래서 이 로그가 실패를 드러내는 유일한 자리다."""
    logger.warning(RUBY_FAILED, extra={"sentence_id": sentence_id, "error": describe_error(error)})


def log_ruby_mismatch(*, event: str, sentence_id: int, sentence_item_id: int) -> None:
    """`event`는 `RUBY_READING_MISMATCH` 또는 `RUBY_EXPLANATION_OVERRIDE`다."""
    logger.info(event, extra={"sentence_id": sentence_id, "sentence_item_id": sentence_item_id})
