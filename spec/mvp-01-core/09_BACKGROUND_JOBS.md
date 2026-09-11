# Background Jobs

PostgreSQL-backed queue + Python worker. Redis/Celery 없음.

Jobs: sentence batch, review context, missing explanation, pool
replenishment, maintenance/cleanup as needed.

State: `queued → running → validated → completed`; 실패는 제한 retry 후
failed/dead-letter. 무한 retry 금지. daily token/request ceiling 적용
가능.

## 목적

사용자가 학습 중 LLM 응답을 기다리지 않게 콘텐츠를 미리 준비한다. 모든
provider 호출은 worker에서만 발생한다(`08_LLM_SPEC.md`).

## Idempotency / Retry

`generation_jobs`는 최소 다음 논리 필드를 가진다(`04_DB_SPEC.md`).

``` text
idempotency_key UNIQUE
retry_count
max_attempts
next_attempt_at
last_error
```

Worker execution은 **at-least-once**를 전제로 하고 **DB persistence는
idempotent**해야 한다.

초기 retry 기본값:

``` text
max_attempts = 3
exponential backoff
```

값은 config다(`14_CONFIGURATION.md`의 `max_job_attempts`).

-   transient API/network failure는 제한된 횟수만 retry한다.
-   schema/validation failure도 제한적으로 재생성할 수 있다.
-   무한 retry는 금지한다.
-   `retry_count`와 마지막 error를 기록한다.
-   한도를 넘으면 `failed` 또는 `dead_letter`로 종료한다.

provider call 성공 직후 worker가 crash하면 provider 비용이 다시 발생할
가능성을 **완전히 제거할 수 있다고 주장하지 않는다.** 대신 duplicate DB
insertion은 unique/idempotency constraint로 막는다.

## Ready Pool

Learning Engine은 다음 학습에 필요한 Ready candidate가 충분한지
확인한다. 부족하면 background replenishment job을 만든다
(`06_LEARNING_ENGINE.md`).

## Cost Guard

worker는 하루 token/request ceiling을 넘으면 신규 generation을 중단하고
기존 pool을 사용한다. ceiling에 도달해도 학습 세션은 계속 진행되며,
review/reinforcement 중심의 저하 모드로 동작한다.
