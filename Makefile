UV ?= $(shell command -v uv || echo $(HOME)/.local/bin/uv)
# --env-file을 명시하지 않으면 compose가 infra/.env를 찾는다. 루트 .env를 쓴다.
COMPOSE ?= docker compose --env-file .env -f infra/docker-compose.yml

.PHONY: install lint format typecheck test test-unit frontend-build ci run db-up db-up-local db-down db-reset seed create-user

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
test-unit:
	$(UV) run pytest -m "not integration"

frontend-build:
	cd frontend && npm ci && npm run build

ci: lint typecheck test

run:
	$(UV) run uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000

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
