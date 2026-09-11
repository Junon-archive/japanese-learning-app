# Background Jobs

PostgreSQL-backed queue + Python worker. Redis/Celery 없음.

`generation_jobs.job_type`의 허용값은 `GENERATE_SENTENCE_BATCH`,
`GENERATE_REVIEW_CONTEXT`, `EXPLAIN_ITEM` 3개뿐이다. **허용값 집합의
canonical 정의는 `04_DB_SPEC.md`의 `generation_jobs`에 있다.** pool
replenishment는 별도 job_type이 아니라 `GENERATE_SENTENCE_BATCH`를
enqueue하는 트리거이고, maintenance/cleanup은 MVP job_type에 없다.

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

## Worker Heartbeat (미결)

`GET /api/health`의 `components.worker`는 worker heartbeat를 보고한다
(`05_API_SPEC.md`). **heartbeat의 저장 위치는 아직 정해지지 않았고 Wave 3
job queue 구현 시점에 확정한다.** 확정 전까지 health는 `unknown`을
반환하며 전용 테이블/컬럼을 선반영하지 않는다.

## Ready Pool

Learning Engine은 다음 학습에 필요한 Ready candidate가 충분한지
확인한다. 부족하면 replenishment로 `GENERATE_SENTENCE_BATCH` job을
enqueue한다(`06_LEARNING_ENGINE.md`). replenishment 자체는 job_type이
아니다(위).

**worker는 `user_sentence_candidates` row를 만들지 않는다.** worker가
만드는 것은 global content(`sentences` 등)이고, 그것을 사용자별
candidate로 투영하는 일은 request 경로의 Learning Engine이 한다
(`06_LEARNING_ENGINE.md`의 `Candidate Materialization`이 canonical).
worker가 생성한 문장은 **다음 materialization 실행에서** candidate가
된다. 이 분리 덕분에 seed만 적재된 신규 사용자도 worker 없이 첫 세션을
시작할 수 있다.

## Cost Guard

worker는 하루 token/request ceiling을 넘으면 신규 generation을 중단하고
기존 pool을 사용한다. ceiling에 도달해도 학습 세션은 계속 진행되며,
review/reinforcement 중심의 저하 모드로 동작한다.
