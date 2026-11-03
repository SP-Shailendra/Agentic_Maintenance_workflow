.PHONY: sync up down backend frontend seed simulate evaluate baseline test lint hooks demo

sync:
	uv sync --locked --extra dev --project backend

up:
	docker compose up -d db

down:
	docker compose down

backend:
	cd backend && uv run --locked python -m uvicorn app.main:app --reload

frontend:
	docker compose up frontend

seed:
	cd backend && uv run --locked alembic upgrade head && uv run --locked python -m scripts.seed

simulate:
	cd backend && uv run --locked python -m scripts.simulate

evaluate:
	cd backend && uv run --locked python -m scripts.evaluate_detection

baseline:
	cd backend && uv run --locked python -m scripts.baseline_report

test:
	cd backend && uv run --locked python -m pytest

lint:
	cd backend && uv run --locked ruff check app tests scripts alembic

hooks:
	uv run --locked --project backend pre-commit run --all-files

demo:
	cd backend && uv run --locked python -m scripts.e2e_demo
