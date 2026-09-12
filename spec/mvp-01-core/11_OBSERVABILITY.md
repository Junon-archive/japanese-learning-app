# Observability

App: sessions/day, study minutes, sentences, clicks, self-report,
probes, reviews, meaningful exposures, flags.

LLM: calls/task, input/output/cached tokens, cost, failures, validation
failures, retry, pool size, queue length.

Cost efficiency: cost/session, cost/generated sentence, cost/learned
item, tokens/learning minute.

Ops: FastAPI/worker/Postgres health, disk, backup success. secret/auth
token log 금지.

MVP는 거대한 analytics stack을 만들지 않지만, 개인 사용 중 문제와 비용을
추적할 수 있어야 한다. secret, password, raw auth token을 log하지 않으며
LLM debugging에 필요한 provenance는 content/job id 중심으로 추적한다.

## MVP 필수 범위

MVP에서 반드시 수집하는 것은 다음으로 제한한다.

``` text
job count
provider call count
input/output tokens
estimated cost if available
failure/retry count
ready pool size
```

앱 지표(sessions/day, study minutes, sentences, clicks, self-report,
probes, reviews, meaningful exposures, flags)는 `learning_events`와
`item_exposures`에서 집계할 수 있으면 충분하며 별도 대시보드를 만들지
않는다.

### 저장 위치 (MVP 확정)

**metrics 전용 테이블을 만들지 않는다.** 위 항목은 전부 기존 테이블에서
읽는다.

``` text
job count / status         generation_jobs
provider call count        generation_jobs.result_ref.usage.provider_calls
input/output tokens        generation_jobs.result_ref.usage.*_tokens
estimated cost             generation_jobs.result_ref.usage.estimated_cost_usd
failure / retry count      generation_jobs.status / retry_count / last_error
validation failure 사유    generation_jobs.result_ref.rejected + 로그
                           (사유 코드 집합은 08_LLM_SPEC.md가 canonical)
ready pool size            user_sentence_candidates의 status = ready 건수
queue length               generation_jobs의 status IN ('queued','retry') 건수
worker liveness            worker_heartbeats.last_heartbeat_at (05_API_SPEC.md)
```

`usage` 기록 규칙과 집계의 **UTC 일 경계**는 `09_BACKGROUND_JOBS.md`의
`usage 기록과 일 경계`가 canonical이다. 그 규칙에 따라 `usage.*_tokens`는
`null`일 수 있고 **`null`은 0이 아니다**. 필수 수집 항목이므로 로그의 token
필드는 값이 `null`이어도 싣는다. 또 daily ceiling으로 생성을 멈춘 것이 한도
자체가 아니라 unknown token 때문일 수 있으므로, **멈춤 로그에 token이 `null`인
job 수를 함께 싣는다.**

`cached tokens`는 **MVP 필수가 아니다.** 위 `MVP 필수 범위` 목록이 닫힌
집합이고 거기에 없다. MVP는 기록하지 않으며 `usage` 구조에 키를 추가하지
않는다(`04_DB_SPEC.md`의 `result_ref 구조`가 MVP 확정이다). 문서 맨 위
`LLM:` 줄의 `cached tokens`는 장기 지표 쪽이고, prompt caching 최적화 자체도
MVP 의무가 아니다(`spec/06_LLM_ENGINEERING_PRINCIPLES.md`). 필요해지면
`result_ref 구조`를 먼저 고친다.

## Future

위의 Cost efficiency 지표 중 `cost/learned item`, `tokens/learning
minute` 같은 고급 지표는 **장기 지표**다. "learned item"의 정의가 실제
사용 데이터로 확정되기 전까지 MVP 합격 조건으로 쓰지 않는다.

대시보드, 고급 analytics, admin UI는 Future다
(`spec/future/ADMIN_AND_DATA.md`).

**로그인 실패 시도 로그와 알림도 Future다.** MVP는 실패마다 로그를 남기지
않는다. 온라인 추측 공격 상황에서는 초당 수십 건이 들어와 로그 자체가 디스크
압박이 되기 때문이다. 근거는 `spec/04_SECURITY_AND_DATA.md`의
`온라인 무차별 대입 방어 (MVP 확정)`.
