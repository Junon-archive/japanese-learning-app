# Observability

MVP는 거대한 analytics stack을 만들지 않지만, 개인 사용 중 문제와 비용을
추적할 수 있어야 한다.

## App Metrics

-   sessions/day
-   actual study minutes
-   sentences viewed
-   item clicks
-   explicit known/uncertain/unknown
-   mastery probes answered
-   reviews performed
-   meaningful exposures
-   content flags

## LLM Metrics

-   calls by task
-   input/output tokens
-   cached tokens if available
-   estimated/actual cost
-   generation failures
-   validation failures
-   retry count
-   ready pool size
-   job queue length

## Operational

-   FastAPI health
-   worker health
-   PostgreSQL health
-   disk usage
-   backup success/failure

## Logging

secret, password, raw auth token을 log하지 않는다. LLM debugging에
필요한 provenance는 content/job id 중심으로 추적한다.
