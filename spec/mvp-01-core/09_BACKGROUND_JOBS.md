# Background Jobs

## 목적

사용자가 학습 중 LLM 응답을 기다리지 않게 콘텐츠를 미리 준비한다.

## MVP Infrastructure

-   PostgreSQL-backed job table
-   별도 Python worker process
-   Redis/Celery 없음

## Job Types

-   generate sentence batch
-   generate review contexts
-   generate missing explanations
-   pool replenishment
-   maintenance/cleanup as needed

## State

`queued → running → validated → completed`

실패: `running → retry → failed/dead-letter`

## Retry

-   transient API/network failure는 제한된 횟수 retry
-   schema/validation failure도 제한적으로 재생성 가능
-   무한 retry 금지
-   retry_count와 마지막 error 기록

## Ready Pool

Learning Engine은 다음 학습에 필요한 충분한 Sentence가 있는지 확인한다.
부족하면 background replenishment job을 만든다.

## Cost Guard

worker는 하루 token/request ceiling을 넘으면 신규 generation을 중단하고
기존 pool을 사용한다.
