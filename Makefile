# AcquireIntel — dev convenience wrapper.
#
#   make setup     one-time: write .env, start Postgres, apply migrations
#   make run       run the app  (JSON API + dashboard) at http://localhost:5000
#   make demo      crawl the harness (happy + block_after_n + captcha) so there's data
#   make test      full test suite
#
# `make run` is the whole app — the Flask process serves both the JSON API and the
# server-rendered dashboard, so there is no separate frontend/backend to start.

.DEFAULT_GOAL := help

DB_HOST_PORT ?= 5544
PORT ?= 5000
SOURCE ?= demo_rest
SCENARIOS ?= happy block_after_n captcha
HARNESS_PORT ?= 8080
HARNESS_PIDFILE := .harness.pid

.PHONY: help setup env db migrate run demo crawl harness test clean

help: ## show this help
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*?## "}{printf "  \033[36mmake %-9s\033[0m %s\n", $$1, $$2}'

setup: env ## one-time: .env + deps + Postgres + migrations
	uv sync
	DB_HOST_PORT=$(DB_HOST_PORT) docker compose up -d
	uv run alembic upgrade head
	@echo "setup done — try:  make demo   then   make run"

env: ## create a dev .env (dev-only values; git-ignored) if missing
	@if [ ! -f .env ]; then \
		printf 'DATABASE_URL=postgresql+psycopg://acquire:acquire@localhost:$(DB_HOST_PORT)/acquire\nFLASK_SECRET_KEY=dev-secret\nADMIN_TOKEN=dev-admin-token\n' > .env; \
		echo "wrote .env (dev defaults on port $(DB_HOST_PORT))"; \
	else echo ".env already exists — leaving it"; fi

db: ## start Postgres in the background
	DB_HOST_PORT=$(DB_HOST_PORT) docker compose up -d

migrate: ## apply DB migrations
	uv run alembic upgrade head

run: ## run the app (API + dashboard) at http://localhost:$(PORT)
	@echo "app on http://localhost:$(PORT)  (dashboard at /, API under /api/v1)"
	uv run flask --app acquire_intel.api run --port $(PORT)

demo: ## crawl the harness across scenarios so the dashboard has data to show
	@echo "starting adversarial harness on :$(HARNESS_PORT) ..."
	@uv run python -m harness.server --block-after 1 --port $(HARNESS_PORT) > .harness.log 2>&1 & echo $$! > $(HARNESS_PIDFILE)
	@sleep 3
	@for s in $(SCENARIOS); do \
		echo "== scenario: $$s =="; \
		uv run python scripts/demo_seed.py --scenario $$s --harness-base http://127.0.0.1:$(HARNESS_PORT); \
		uv run acquire-intel crawl $(SOURCE) || true; \
	done
	@kill `cat $(HARNESS_PIDFILE)` 2>/dev/null || true; rm -f $(HARNESS_PIDFILE)
	@echo ""
	@echo "demo done. now:  make run   → open http://localhost:$(PORT)"

crawl: ## crawl one source (SOURCE=demo_rest by default; seed it first)
	uv run acquire-intel crawl $(SOURCE)

harness: ## run the adversarial mock server in the foreground (Ctrl-C to stop)
	uv run python -m harness.server --block-after 1 --port $(HARNESS_PORT)

test: ## run the full test suite
	uv run pytest -q

clean: ## stop Postgres and remove local demo artifacts
	-docker compose down
	rm -f $(HARNESS_PIDFILE) .harness.log
