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
