# Architecture

## 목표 구조

``` text
Browser / iPhone PWA
        |
        +---- Public static app ----> Cloudflare Workers Static Assets
        |
        +---- API request ----------> Cloudflare
                                      |
                                Cloudflare Tunnel
                                      |
                              Research Lab Server
                                      |
                    +-----------------+-----------------+
                    |                                   |
                 FastAPI                            Worker
                    |                                   |
                    +-------------- PostgreSQL ---------+
                                      |
                                 OpenAI API
```

## 핵심 결정

-   Frontend: installable PWA. MVP에서 offline learning은 지원하지
    않는다.
-   Static hosting: Cloudflare Workers Static Assets.
-   Backend: Python + FastAPI.
-   DB: PostgreSQL.
-   ORM: SQLAlchemy.
-   Migration: Alembic.
-   Background jobs: PostgreSQL-backed job queue + 별도 worker process.
-   Redis/Celery는 MVP에서 사용하지 않는다.
-   연구실 서버는 Cloudflare Tunnel을 통해 FastAPI만 외부에 노출한다.
-   PostgreSQL 포트는 인터넷에 공개하지 않는다.
-   Public Demo는 정적/사전 준비된 데이터만 사용하고 실시간 LLM 호출을
    금지한다.

## 구현 시 예상 repository

``` text
frontend/
backend/
  app/
    api/
    models/
    schemas/
    services/
    learning/
    srs/
    llm/
    jobs/
    main.py
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

## Content Provider 추상화

``` text
ContentProvider
├─ GeneratedContentProvider   [MVP]
├─ DemoContentProvider        [MVP]
├─ YouTubeProvider            [Future]
└─ ManualTextProvider         [Future]
```

YouTube는 시스템의 필수 의존성이 아니다.
