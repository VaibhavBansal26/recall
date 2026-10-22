.PHONY: prod-up prod-down prod-logs backup env dev down migrate revision test test-backend test-frontend e2e lint gen-api install

env:
	@test -f .env || cp .env.example .env

install: env
	cd backend && uv sync
	cd frontend && npm install

dev: env
	docker compose up --build

down:
	docker compose down

# Runs against the db published on localhost (docker compose up db).
migrate: env
	cd backend && uv run alembic upgrade head

revision:
	cd backend && uv run alembic revision --autogenerate -m "$(m)"

test: test-backend test-frontend

test-backend:
	cd backend && uv run pytest

test-frontend:
	cd frontend && npm test

# Needs the full stack running (make dev) and `npx playwright install chromium`.
e2e:
	cd frontend && npm run e2e

lint:
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy app
	cd frontend && npm run lint && npm run typecheck

# Regenerates frontend/lib/api-types.ts from the FastAPI OpenAPI schema.
gen-api:
	cd backend && uv run python -m scripts.dump_openapi > ../frontend/openapi.json
	cd frontend && npm run gen:api

# --- production (run on the VM; needs .env from .env.prod.example) ---
prod-up:
	docker compose -f docker-compose.prod.yml up -d --build

prod-down:
	docker compose -f docker-compose.prod.yml down

prod-logs:
	docker compose -f docker-compose.prod.yml logs -f --tail=100

backup:
	./scripts/backup.sh
