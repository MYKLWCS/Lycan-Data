.PHONY: dev test test-fast test-ci selfheal health migrate shell logs down up install api worker worker-fast

dev:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml up

up:
	docker compose up -d

down:
	docker compose down

test:
	.venv/bin/python -m pytest tests/ -v --tb=short

test-fast:
	.venv/bin/python -m pytest tests/ -q \
		--ignore=tests/test_crawlers \
		--ignore=tests/test_darkweb \
		--ignore=tests/test_government \
		-k "not integration and not playwright"

migrate:
	alembic upgrade head

migrate-create:
	alembic revision --autogenerate -m "$(MSG)"

shell:
	docker compose exec postgres psql -U lycan -d lycan

logs:
	docker compose logs -f

install:
	pip install poetry && poetry install
	python -m spacy download en_core_web_lg
	playwright install chromium

api:
	.venv/bin/python -m uvicorn api.main:app --reload --host 0.0.0.0 --port 8000 --log-level info --proxy-headers

worker:
	.venv/bin/python worker.py --workers 4

worker-fast:
	.venv/bin/python worker.py --workers 8

test-ci:
	.venv/bin/python -m pytest tests/ \
		--cov=. \
		--cov-report=xml \
		--cov-report=term-missing \
		--cov-fail-under=45 \
		-v --tb=short

selfheal:
	.venv/bin/python scripts/selfheal.py

health:
	.venv/bin/python scripts/selfheal.py --report
