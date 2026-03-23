.PHONY: dev test migrate shell logs down up install

dev:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml up

up:
	docker compose up -d

down:
	docker compose down

test:
	pytest tests/ -v --cov=shared --cov-report=term-missing

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
