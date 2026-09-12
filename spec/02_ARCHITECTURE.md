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
-   Public Demo는 **static frontend fixture**이며 backend API/DB/provider를
    사용하지 않는다(`04_SECURITY_AND_DATA.md`)
-   모든 외부 LLM provider 호출은 **background worker에서만** 발생한다.
    FastAPI request handler는 provider를 synchronous 호출하지 않는다
    (`mvp-01-core/08_LLM_SPEC.md`)
-   provider **구현 선택**은 환경변수 `LLM_PROVIDER`(MVP 허용값 `openai`
    하나, 기본값 없음)이고 **모델명**은 `prompt_versions` 행에서 온다. 모델명을 코드나 config
    YAML에 고정하지 않는다(`mvp-01-core/08_LLM_SPEC.md`의
    `Provider 선택과 model 출처`, `04_SECURITY_AND_DATA.md`, ADR-016)

## Future-safe providers

`ContentProvider = Generated[MVP] | YouTube[Future] | ManualText[Future]`

Demo는 backend content provider가 아니라 frontend static fixture이므로
이 추상화에 포함하지 않는다. YouTube/ManualText는 Future 방향 표시이며
MVP에서 스텁을 선제 구현하지 않는다.

구현 시 repo는 `frontend/ backend/ infra/ scripts/ data/`로 확장한다.

``` text
frontend/
backend/
  app/{api,models,schemas,services,learning,srs,llm,jobs}/ main.py
  migrations/
  tests/
infra/
  docker-compose.yml
  Dockerfile.backend
  Dockerfile.worker
  cloudflared/
scripts/
data/
  postgres/
  backups/
```

`data/postgres`, `data/backups`, `.env`는 Git에 포함하지 않는다.
