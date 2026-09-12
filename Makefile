UV ?= $(shell command -v uv || echo $(HOME)/.local/bin/uv)
# --env-file을 명시하지 않으면 compose가 infra/.env를 찾는다. 루트 .env를 쓴다.
COMPOSE ?= docker compose --env-file .env -f infra/docker-compose.yml

.PHONY: install lint format typecheck test test-unit test-e2e frontend-build frontend-test ci run worker-run db-up db-up-local db-down db-reset seed create-user prompts

install:
	$(UV) sync

# lint/format/typecheck 범위는 backend와 scripts 둘 다다. scripts/는 DSN과
# password를 다루므로 S105/S106 같은 규칙이 반드시 닿아야 한다.
lint:
	$(UV) run ruff check backend scripts
	$(UV) run ruff format --check backend scripts

format:
	$(UV) run ruff format backend scripts

typecheck:
	$(UV) run mypy

test:
	$(UV) run pytest

# 개발 중 단축 경로일 뿐이다. 보고 근거는 항상 `make test`다.
# e2e도 뺀다. `-m`은 명령줄 값이 addopts를 덮으므로 여기서 명시하지 않으면
# 브라우저 테스트가 unit 실행으로 새어 들어온다.
test-unit:
	$(UV) run pytest -m "not integration and not e2e"

frontend-build:
	cd frontend && npm ci && npm run build

frontend-test:
	cd frontend && npm ci && npm test

# 실제 Chrome으로 도는 브라우저 E2E. `make test`는 이것을 수집하지 않는다
# (pyproject의 addopts가 `-m "not e2e"`).
#
# frontend 빌드는 Makefile이 아니라 `backend/tests/e2e/conftest.py`가 한다 ---
# `VITE_API_BASE_URL`에 넣을 API 포트는 fixture 시점에야 정해진다. 그 빌드는 매
# 실행 `frontend/dist`를 **지우고** 다시 만들므로 옛 산출물이 검증될 수 없고,
# 빌드 실패는 그대로 테스트 실패가 된다. 여기서 하는 것은 의존성 설치뿐이다.
#
# NC_E2E_REQUIRED=1: Chrome이나 node가 없으면 skip이 아니라 **실패**다. skip이
# 초록으로 위장하면 이 하네스는 아무것도 지키지 못한다.
test-e2e:
	cd frontend && npm ci
	NC_E2E_REQUIRED=1 $(UV) run pytest -m e2e --capture=tee-sys

ci: lint typecheck test frontend-test test-e2e

run:
	$(UV) run uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000

# worker 프로세스. DATABASE_URL / LLM_PROVIDER / LLM_API_KEY는 셸에서 export 한다
# (애플리케이션은 .env를 직접 읽지 않는다). 값이 없거나 허용값이 아니면 즉시 종료한다.
worker-run:
	$(UV) run python scripts/run_worker.py

db-up:
	$(COMPOSE) up -d postgres

db-down:
	$(COMPOSE) down

# 로컬 개발용 PostgreSQL (ADR-002). docker가 없는 머신의 진입점이다.
# stdout에는 DSN만 나온다: export DATABASE_URL="$$(make db-up-local)"
db-up-local:
	@$(UV) run python scripts/pg_local.py $(ARGS)

# 되돌릴 수 없다. --yes 없이는 아무것도 하지 않는다.
# 예: make db-reset ARGS=--yes
db-reset:
	$(UV) run python scripts/db_reset.py $(ARGS)

# password는 argv로 받지 않는다. TTY면 프롬프트, 비대화형이면 --password-stdin이다.
# DATABASE_URL은 셸에서 export 한다 (애플리케이션은 .env를 직접 읽지 않는다).
# 예: make create-user ARGS="--login-id junon"
create-user:
	$(UV) run python scripts/create_user.py $(ARGS)

# seed/의 starter set을 적재한다. 재적재는 지원하지 않는다 (seed/README.md).
seed:
	$(UV) run python scripts/load_seed.py $(ARGS)

# prompt_versions 등록 (04_DB_SPEC.md의 등록 절차). worker는 task 3종에 active 행이
# 없으면 부팅에 실패하므로 배포에서 이 타깃을 먼저 돌린다. version은 코드의 registry가,
# provider/model은 운영자가 정한다 (08_LLM_SPEC.md).
# 예: make prompts ARGS="--provider openai --model <모델명>"
prompts:
	$(UV) run python scripts/load_prompts.py $(ARGS)
