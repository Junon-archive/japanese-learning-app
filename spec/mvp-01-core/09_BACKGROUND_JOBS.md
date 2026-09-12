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
-   한도를 넘으면 `failed`로 종료한다. 영구 오류는 한도와 무관하게
    `dead_letter`다(아래 경계).

### failed와 dead_letter의 경계 (MVP 확정)

``` text
failed       재시도할 수 있는 오류였지만 attempt를 소진했다
             (retry_count >= max_attempts)
dead_letter  재시도해도 결과가 같은 영구 오류다. attempt를 소진하지 않고
             즉시 이 상태로 끝낸다
```

`dead_letter`로 즉시 보내는 경우는 다음으로 **한정**한다.

``` text
payload_json이 그 job_type의 필수 key를 만족하지 않는다
payload가 참조하는 행이 없다 (user_id / learning_item_id / sentence_item_id)
job_type이 이 worker 버전에 구현되어 있지 않다
그 task_type에 active = true 인 prompt_versions 행이 없다
```

그 밖은 전부 재시도 대상이고 소진하면 `failed`다.

``` text
provider의 timeout / 5xx / rate limit / 연결 실패   -> retry
structured output parsing 실패                      -> retry
deterministic validation 전량 탈락                  -> retry
provider 인증 실패(401/403)                         -> retry
```

인증 실패를 `dead_letter`로 보내지 않는 이유는, 키 교체 중의 일시적
상태와 영구 설정 오류를 job 하나가 구분할 수 없기 때문이다. attempt
소진으로 `failed`가 되면 같은 신호를 얻으면서 복구 후 다시 돌릴 수 있는
상태로 남는다.

두 상태 모두 **worker가 다시 집어가지 않는다.** 차이는 운영 판단이다.
`failed`는 원인을 고친 뒤 `retry_count`와 `next_attempt_at`을 되돌려 다시
돌릴 수 있는 job이고, `dead_letter`는 그렇게 해도 같은 결과가 나오는
job이다. MVP에 자동 재활성화 경로는 없다.

provider call 성공 직후 worker가 crash하면 provider 비용이 다시 발생할
가능성을 **완전히 제거할 수 있다고 주장하지 않는다.** 대신 duplicate DB
insertion은 unique/idempotency constraint로 막는다.

## Claim과 lease (MVP 확정)

worker는 한 번에 job 하나를 claim한다.

``` text
대상   status IN ('queued', 'retry') AND next_attempt_at <= now
정렬   next_attempt_at ASC, id ASC
방법   단일 UPDATE ... WHERE id = (SELECT ... FOR UPDATE SKIP LOCKED LIMIT 1)
효과   status = running, started_at = now
```

SELECT 후 UPDATE를 나누어 하지 않는다. worker가 하나뿐인 MVP에서도
재시작 직후 두 프로세스가 잠깐 겹칠 수 있고, 그때 같은 job이 두 번
실행되면 provider 비용이 그대로 두 배가 된다.

### stale `running` 회수

worker가 job 실행 중에 crash하면 그 job은 `running`으로 남고 위 claim
조건에 걸리지 않아 **영원히 아무도 집어가지 않는다.** 그래서 lease를 둔다.

``` text
조건   status = 'running' AND started_at < now - jobs.claim_lease_seconds
동작   status = 'retry'
       retry_count = retry_count + 1
       next_attempt_at = now
       last_error = 'lease_expired'
실행   worker loop 매 회의 시작 시점 (claim보다 먼저)
```

-   `retry_count`를 **증가시킨다.** 증가시키지 않으면 실행할 때마다
    crash하는 job이 lease 만료 → 재실행을 영원히 반복한다. 증가시키면
    `max_attempts`에서 멈추고 `failed`가 된다(무한 retry 금지).
-   lease는 job 하나의 최대 실행 시간보다 넉넉해야 한다. 값은
    `14_CONFIGURATION.md`의 `jobs.claim_lease_seconds`다.
-   회수된 job이 실제로는 살아 있었을 가능성은 남는다. 그래서 DB
    persistence의 idempotency가 필요하다(위). 이 회수 규칙이 그 전제를
    없애지 않는다.

## Worker Heartbeat (MVP 확정)

`GET /api/health`의 `components.worker`가 읽을 heartbeat는 **전용 테이블
`worker_heartbeats`에 저장한다**(`04_DB_SPEC.md`). 근거와 버린 대안은
`docs/decisions/ADR-017-worker-heartbeat-storage.md`.

``` text
쓰기   worker가 loop를 한 번 돌 때마다, 최소 jobs.heartbeat_interval_seconds
       간격으로 upsert 한다. **처리할 job이 없어도 쓴다.** 이 신호의 뜻은
       "일이 있었다"가 아니라 "worker가 살아 있다"이다.
       heartbeat write는 job 트랜잭션과 분리해 즉시 commit 한다. job
       트랜잭션에 얹으면 rollback이 생존 신호까지 지운다.

읽기   /api/health가 last_heartbeat_at의 최대값 하나를 읽는다.
       행 없음                                                 -> unknown
       now - last_heartbeat_at <= jobs.heartbeat_stale_seconds -> ok
       그 밖                                                    -> stale
```

stale 임계값은 tuning 값이므로 `14_CONFIGURATION.md`에 두며 interval보다
커야 한다(config 로드 시 검증). health 응답이 이 판정을 어떻게 표현하는지는
`05_API_SPEC.md`가 canonical이다.

## Enqueue 트리거와 idempotency key (MVP 확정)

**누가 언제 job을 만드는지의 canonical 표는 여기다.** enqueue는 전부
request 경로(Learning Engine)에서 일어나고 **worker는 job을 만들지
않는다.**

``` text
job_type                 트리거
GENERATE_SENTENCE_BATCH  Pool Fallback 3단계. 0단계 materialization을 돌리고도
                         그 role의 ready candidate가 없을 때 role 하나당 1건
                         (06_LEARNING_ENGINE.md의 Pool Fallback)
GENERATE_REVIEW_CONTEXT  materialization의 review 분기가 `stage -> sentence`
                         조건을 만족하는 문장을 찾지 못해 그 stage의 candidate를
                         만들지 못했을 때, (item, stage) 하나당 1건
EXPLAIN_ITEM             materialization이 검사한 문장이 explanation 누락으로
                         Ready invariant를 만족하지 못할 때, 누락된
                         sentence_item 하나당 1건
```

``` text
job_type                 idempotency_key
GENERATE_SENTENCE_BATCH  replenish:GENERATE_SENTENCE_BATCH:{user_id}:{role}:{YYYY-MM-DD}
GENERATE_REVIEW_CONTEXT  review_ctx:{user_id}:{learning_item_id}:{context_stage}:{YYYY-MM-DD}
EXPLAIN_ITEM             explain:{sentence_item_id}:{YYYY-MM-DD}
```

``` text
job_type                 payload_json
GENERATE_SENTENCE_BATCH  {"user_id", "presentation_role"}
GENERATE_REVIEW_CONTEXT  {"user_id", "learning_item_id", "context_stage",
                          "anchor_sentence_id"}
EXPLAIN_ITEM             {"sentence_item_id"}
```

-   `{YYYY-MM-DD}`는 **UTC 날짜**다. 사용자 local day가 아니다. 이 창은
    사용자에게 보이는 경계가 아니라 생성 비용 억제 장치이고, 같은 이유로
    daily ceiling도 UTC 일 경계를 쓴다(아래 `Cost Guard`).
-   날짜를 넣는 이유는 두 방향의 실패를 동시에 막기 위해서다. 날짜가
    없으면 job이 끝난 뒤에도 재enqueue가 영원히 막히고, 시각·순번을 넣으면
    한 세션의 Pool Fallback 열 번이 job 열 개가 된다.
-   enqueue는 `ON CONFLICT (idempotency_key) DO NOTHING`이다. 먼저
    SELECT하고 없으면 INSERT하는 방식은 동시 요청에서 IntegrityError를 내고
    호출부의 학습 트랜잭션을 통째로 무효로 만든다.
-   enqueue는 호출한 service의 **같은 트랜잭션** 안에서 일어난다. 학습
    상태가 rollback되면 그에 대한 job도 함께 사라진다(ADR-007).
-   **`EXPLAIN_ITEM`은 그 실행에서 실제로 검사한 문장에 한해서만
    enqueue한다.** 누락 explanation을 찾겠다고 corpus 전체를 훑지 않는다.
-   **`GENERATE_SENTENCE_BATCH`의 payload에 item 목록을 넣지 않는다.**
    이유와 실행 시점 대상 선정 규칙은 `08_LLM_SPEC.md`의
    `GENERATE_SENTENCE_BATCH 대상 선정`이 canonical이다.

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

### usage 기록과 일 경계 (MVP 확정)

**새 테이블을 만들지 않는다.** per-job usage는
`generation_jobs.result_ref.usage`에 기록한다(`04_DB_SPEC.md`의
`result_ref 구조`).

``` json
"usage": {
  "provider_calls": 1,
  "input_tokens": 1234,
  "output_tokens": 567,
  "estimated_cost_usd": null,
  "last_call_at": "2026-09-12T04:05:06Z"
}
```

-   provider 응답을 받은 **직후** 기록하고 그 job이 나중에 실패해도 지우지
    않는다. 실패한 호출도 비용이다.
-   attempt가 여러 번이면 **누적**한다(`provider_calls` · token ·
    `estimated_cost_usd`는 합, `last_call_at`은 마지막 호출 시각).
-   **token 수를 모르면 `null`이다. 0이 아니다.** provider가 `usage`를 생략하는
    호출이 있으므로 `input_tokens` / `output_tokens`는 **정수 또는 `null`**이다. 0은
    "호출했는데 토큰을 안 썼다"는 거짓이고, 그 거짓이 그대로 아래 ceiling 판정에
    들어간다.
-   **한 번 모르면 그 job의 총계는 계속 `null`이다(sticky-null).** attempt 1의
    token을 알고 attempt 2를 모르면 아는 부분까지 집계에서 빠진다. 그렇게 기우는
    이유는 부분 합을 적으면 그 숫자가 **총계처럼** 보이기 때문이다. 손실은
    `max_job_attempts`로 유계이고, 정확히 하려면 호출 단위 기록이 필요하다 --- 아래
    `한계`와 같은 이유로 MVP는 만들지 않는다.
-   `estimated_cost_usd`는 provider가 값을 주거나 단가를 아는 경우에만
    채운다. 단가표를 명세에 박지 않는다. **누적과 unknown 처리는 token과 같은
    규칙이다**(attempt 합, 한 attempt를 모르면 sticky-null). 마지막 attempt 값으로
    덮어쓰면 retry한 job의 비용이 실제의 1/attempt로 보인다. 같은 규칙이므로 한
    함수로 구현한다 --- 두 곳에 적으면 한쪽만 고쳐지고 갈린다.
-   **`estimated_cost_usd`는 관측 항목이며 ceiling 판정에 들어가지 않는다.**
    한도를 만드는 것은 `daily_request_limit`과 `daily_token_limit` 둘뿐이고,
    아래 fail-closed는 `daily_token_limit` 전용이다. cost로 판정하면 단가표를
    모른다는 것만으로 생성이 멈추는데, 단가표는 명세가 담지 않기로 한 것이므로
    그 멈춤은 해소할 수단이 없다.

``` text
오늘 사용량 = usage.last_call_at 이 오늘 UTC 00:00 이후인 generation_jobs의
              provider_calls 합 / (input_tokens + output_tokens) 합
판정 시점   = job을 claim 하기 전
초과 시     = claim 하지 않고 다음 poll 까지 쉰다
```

-   **일 경계는 UTC다.** `users.timezone`을 쓰지 않는다. 이 한도는
    사용자에게 보이는 학습 경계가 아니라 provider 청구를 막는 전역 운영
    장치이고, job은 사용자 단위로 돌지 않는다(사용자가 여럿이면 누구의
    timezone인지에 답이 없다). `04_DB_SPEC.md` 공통 규칙의 "사용자 local
    day는 `users.timezone`으로 계산한다"는 학습 데이터 집계 규칙이며 여기에
    적용되지 않는다.
-   ceiling에 걸린 job은 **claim하지 않는다.** claim한 뒤 실패로 끝내면
    한도 때문에 `retry_count`가 소모되어, 다음 날 살아 있어야 할 job이
    `failed`가 된다.
-   `daily_request_limit` / `daily_token_limit`이 `null`이면 그 한도는 꺼져
    있다(`14_CONFIGURATION.md`).
-   **token 총량을 모르면 `daily_token_limit`은 도달한 것으로 본다
    (fail-closed).** 오늘 호출한 job 중 token이 `null`인 것이 하나라도 있으면 token
    합은 총계가 아니라 **하한**이고, 하한을 한도와 비교하는 것은 한도를 지키는 척하는
    것이다. `null`을 0으로 뭉개면 한도를 켜 둔 운영자가 상한 없는 청구서를 받는데,
    그것이 이 키가 막으라고 있는 유일한 사건이다. 멈추는 쪽은 눈에 보이고 되돌릴 수
    있다: UTC 자정에 해소되고, `daily_token_limit = null`이 문서화된 off-switch이며
    기본값이다. 학습 세션은 Ready Pool로 계속 진행된다(불변식 #1). 멈춘 이유가 한도
    자체가 아니라 unknown token일 수 있으므로 **멈춤 로그에 token이 `null`인 job 수를
    함께 남긴다**(`11_OBSERVABILITY.md`).
-   **`daily_request_limit`은 이 규칙의 영향을 받지 않는다.** 호출 수는 provider가
    `usage`를 주는지와 무관하게 항상 셀 수 있다.
-   **한계:** 하루를 걸쳐 실행된 job의 token은 `last_call_at`이 속한 날에
    전부 계상된다. 개인 사용 규모에서 무시할 만한 오차이고, 정확히 하려면
    호출 단위 테이블이 필요하다 --- MVP는 만들지 않는다.
