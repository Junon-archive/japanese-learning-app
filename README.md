# Nihongo Context --- Specification Repository

**Spec Version: v0.2**\
**Current Milestone: MVP-01 Core Learning**

개인용 일본어 학습 앱 Nihongo Context의 제품·학습·기술 명세다. 목표는
JLPT가 아니라 일본어 YouTube 이해와 일상 회화 능력이다.

## 문서 계층

-   `spec/00~06`: 장기적으로 유지할 제품/학습/기술 원칙
-   `spec/mvp-01-core/`: 현재 구현 범위
-   `spec/future/`: 지금 구현하지 않지만 보존할 장기 설계
-   `spec/reference/ui/`: 시각·인터랙션 reference

## 우선순위

``` text
MVP 구현 source of truth:
    spec/mvp-01-core/*

Global 문서 (spec/00~06):
    제품/기술 제약을 제공하지만 MVP Scope를 확대하지 않는다.

Future (spec/future/*):
    절대 구현 지시가 아니다.
```

충돌 시 다음 순서를 따른다.

1.  `spec/mvp-01-core/*`의 승인된 기능/상태 규칙
2.  Global principles (`spec/00~06`)
3.  UI reference (`spec/reference/ui/`)
4.  구현 편의

Future 문서는 MVP 범위를 넓히는 구현 지시가 아니다. Global/Future 문서에
숫자나 아이디어가 존재한다는 이유만으로 구현하지 않는다.

구현자가 명세 충돌을 발견하면 임의로 해석해 기능을 추가하지 않고, 충돌을
기록하고 최소 변경으로 해결한다.

MVP는 폐기용 prototype이 아니라 완성 제품의 첫 번째 작고 안정적인
조각이다.

## 개발 셋업

``` bash
cp .env.example .env     # 값을 채운다. .env는 Git에 넣지 않는다.
make install             # uv sync
make lint                # ruff check + ruff format --check
make typecheck           # mypy (strict)
make test                # pytest
make run                 # uvicorn, http://127.0.0.1:8000/api/health
make frontend-build      # frontend/ 에서 npm ci && npm run build
```

`lint` / `typecheck` / `test`는 **DB 없이 전부 통과한다.** 데이터베이스가
필요한 테스트는 아직 없다.

`/docs`, `/redoc`, `/openapi.json`은 `APP_ENV=development`일 때만 열린다.
기본값에서는 404다.

로컬 PostgreSQL:

-   docker가 있으면 `make db-up`이 `infra/docker-compose.yml`의
    `postgres:16`을 띄운다. 루트 `.env`가 있어야 한다.
-   docker가 없는 개발 머신의 로컬 DB는
    `docs/decisions/ADR-002-local-dev-database.md`(pgserver)를 따른다.

`make db-reset`과 `make seed`는 아직 동작하지 않는다. Alembic migration과
seed 적재가 들어오는 Wave 1에서 구현한다. 지금 실행하면 안내 메시지와 함께
실패한다.
