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

`lint` / `typecheck` / `test`는 **DB를 따로 준비하지 않아도 전부 돈다.**
PostgreSQL이 필요한 테스트는 pgserver(ADR-002)로 `data/pgtest/`에 테스트 전용
서버를 스스로 띄운다. 브라우저 E2E는 `make test`에 들어가지 않고 `make test-e2e`로
따로 돈다.

`/docs`, `/redoc`, `/openapi.json`은 `APP_ENV=development`일 때만 열린다.
기본값에서는 404다.

로컬 PostgreSQL은 `make db-up-local`(pgserver,
`docs/decisions/ADR-002-local-dev-database.md`)을 쓴다. stdout에 DSN만 나온다.

``` bash
export DATABASE_URL="$(make db-up-local)"
make db-reset ARGS=--yes   # DROP -> CREATE -> alembic upgrade head. APP_ENV=production이면 거부한다
make seed
```

`make db-up`(docker compose)은 로컬 개발용이 아니다. compose 파일이
`NC_CONFIG_PATH`에 운영 정책 파일의 절대경로를 요구하므로, `.env.example`을 그대로
복사한 `.env`로는 실패한다.

운영 배포(compose, 터널, 프론트 배포, 백업, 업데이트)는 `infra/DEPLOY.md`를 따른다.
