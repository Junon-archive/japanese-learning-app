# ADR-001 --- Backend Stack

Status: Accepted

Decision: Python, FastAPI, PostgreSQL, SQLAlchemy, Alembic,
Postgres-backed worker, Cloudflare Tunnel, Cloudflare Workers Static
Assets.

MVP에서는 Redis/Celery를 사용하지 않는다. 일본어 NLP/LLM/data analysis
확장성과 개인 프로젝트 운영 복잡도의 균형을 위한 선택이다.
