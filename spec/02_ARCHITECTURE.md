# Architecture

``` text
iPhone / Browser PWA
  ├─ Static → Cloudflare Workers Static Assets
  └─ API → Cloudflare Tunnel → Research Server
                               ├─ FastAPI
                               ├─ Worker
                               └─ PostgreSQL
                                     ↕
                                  OpenAI API
```

## 결정

-   Frontend: installable PWA, MVP offline 없음
-   Backend: Python + FastAPI
-   DB: PostgreSQL
-   ORM/Migration: SQLAlchemy + Alembic
-   Jobs: Postgres-backed worker, MVP Redis/Celery 없음
-   PostgreSQL은 인터넷 직접 노출 금지
-   Public Demo는 fixture 기반, paid LLM call 금지

## Future-safe providers

`ContentProvider = Generated[MVP] | Demo[MVP] | YouTube[Future] | ManualText[Future]`

구현 시 repo는 `frontend/ backend/ infra/ scripts/ data/`로 확장한다.
DB/backup/.env는 Git 제외.
