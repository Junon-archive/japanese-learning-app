UV ?= $(shell command -v uv || echo $(HOME)/.local/bin/uv)
# --env-file을 명시하지 않으면 compose가 infra/.env를 찾는다. 루트 .env를 쓴다.
COMPOSE ?= docker compose --env-file .env -f infra/docker-compose.yml

.PHONY: install lint format typecheck test frontend-build ci run db-up db-down db-reset seed

install:
	$(UV) sync

lint:
	$(UV) run ruff check backend
	$(UV) run ruff format --check backend

format:
	$(UV) run ruff format backend

typecheck:
	$(UV) run mypy

test:
	$(UV) run pytest

frontend-build:
	cd frontend && npm ci && npm run build

ci: lint typecheck test

run:
	$(UV) run uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000

db-up:
	$(COMPOSE) up -d postgres

db-down:
	$(COMPOSE) down

db-reset:
	@echo "make db-reset is not implemented yet: it needs the Alembic migrations introduced in Wave 1." >&2
	@exit 1

seed:
	@echo "make seed is not implemented yet: it needs the schema and the starter seed loader introduced in Wave 1." >&2
	@exit 1
