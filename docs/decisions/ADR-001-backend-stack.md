# ADR-001 --- Backend Stack

## Status

Accepted

## Decision

MVP backend는 다음을 사용한다.

-   Python
-   FastAPI
-   PostgreSQL
-   SQLAlchemy
-   Alembic
-   PostgreSQL-backed background worker
-   Cloudflare Tunnel
-   Cloudflare Workers Static Assets

## Rationale

일본어 NLP, LLM pipeline, 향후 데이터 분석/ML 확장과 잘 맞으며, 개인
프로젝트에서 운영 복잡도를 낮춘다. MVP에서는 Redis/Celery를 도입하지
않는다.

## Consequence

DB migration과 background worker lifecycle을 처음부터 명확히 관리해야
한다.
