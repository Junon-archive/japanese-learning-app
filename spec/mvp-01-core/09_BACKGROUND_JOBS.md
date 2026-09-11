# Background Jobs

PostgreSQL-backed queue + Python worker. Redis/Celery 없음.

Jobs: sentence batch, review context, missing explanation, pool
replenishment.

State: `queued → running → validated → completed`; 실패는 제한 retry 후
failed/dead-letter. 무한 retry 금지. daily token/request ceiling 적용
가능.
