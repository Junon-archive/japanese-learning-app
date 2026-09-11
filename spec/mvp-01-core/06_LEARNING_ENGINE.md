# Learning Engine

## Inputs

due FSRS, exposure count, mastery, recent events, mix, topics, Ready
Pool, backlog.

## Outputs

target item(s), role, desired difficulty/topic, probe 여부, pool
replenishment 필요 여부.

초기 config: 70/20/10, 신규 1\~2, 12분, probe 2\~4, min exposure 5.

No-click만으로 mastery 상승 금지. Exploration은 희귀어 랜덤 공급이
아니라 mastery 정보가 부족한 적절한 item을 탐색하는 것. 다음 문장은
Ready Pool 우선, 부족하면 background job.
