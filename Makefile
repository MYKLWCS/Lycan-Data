.PHONY: dev test test-fast test-ci selfheal health migrate shell logs down up install api worker worker-fast scraper-health search

# ── Infrastructure ──────────────────────────────────────────────────────────

dev:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml up

up:
	docker compose up -d

down:
	docker compose down

# ── Tests ───────────────────────────────────────────────────────────────────

test:
	.venv/bin/python -m pytest tests/ -v --tb=short

test-fast:
	.venv/bin/python -m pytest tests/ -q \
		--ignore=tests/test_crawlers \
		--ignore=tests/test_darkweb \
		--ignore=tests/test_government \
		-k "not integration and not playwright"

test-ci:
	.venv/bin/python -m pytest tests/ \
		--cov=. \
		--cov-report=xml \
		--cov-report=term-missing \
		--cov-fail-under=45 \
		-v --tb=short

test-load:
	.venv/bin/python -m pytest tests/test_load_concurrent_search.py -v --tb=short

# ── Database ────────────────────────────────────────────────────────────────

migrate:
	alembic upgrade head

migrate-create:
	alembic revision --autogenerate -m "$(MSG)"

shell:
	docker compose exec postgres psql -U lycan -d lycan

# ── Logs & monitoring ───────────────────────────────────────────────────────

logs:
	docker compose logs -f

# ── Installation ────────────────────────────────────────────────────────────

install:
	pip install poetry && poetry install
	python -m spacy download en_core_web_lg
	playwright install chromium

# ── Runtime ─────────────────────────────────────────────────────────────────

api:
	.venv/bin/python -m uvicorn api.main:app --reload --host 0.0.0.0 --port 8000 --log-level info --proxy-headers

worker:
	.venv/bin/python worker.py --workers 4

worker-fast:
	.venv/bin/python worker.py --workers 8

# ── Diagnostics ─────────────────────────────────────────────────────────────

selfheal:
	.venv/bin/python scripts/selfheal.py

health:
	.venv/bin/python scripts/selfheal.py --report

## Check health of all registered scrapers (circuit breaker + last-run status).
## Requires a running API: make api
scraper-health:
	@echo "Checking scraper health via API..."
	@curl -sf -H "Authorization: Bearer $(shell echo $${API_KEYS} | cut -d, -f1)" \
	  http://localhost:8000/system/health | python3 -m json.tool
	@echo ""
	@echo "Crawler registry stats:"
	@.venv/bin/python -c "\
import asyncio, sys; \
sys.path.insert(0, '.'); \
from modules.crawlers.registry import registry_stats, list_platforms; \
stats = registry_stats(); \
total = sum(stats.values()); \
print(f'Total registered crawlers: {total}'); \
[print(f'  {cat}: {n}') for cat, n in sorted(stats.items())]; \
"

## Run a single test search from the command line.
## Usage: make search QUERY="John Doe" or QUERY="john@example.com"
## Requires: make up && make api (in another terminal)
search:
	@QUERY=$(or $(QUERY),John Doe); \
	echo "Searching for: $$QUERY"; \
	curl -sf -X POST http://localhost:8000/search/persons \
	  -H "Content-Type: application/json" \
	  -H "Authorization: Bearer $(shell echo $${API_KEYS} | cut -d, -f1)" \
	  -d "{\"query\": \"$$QUERY\", \"max_results\": 10}" \
	  | python3 -m json.tool

# ── Dependency management ──────────────────────────────────────────────────
requirements.txt: pyproject.toml poetry.lock
	poetry export --format requirements.txt --output requirements.txt --without-hashes
