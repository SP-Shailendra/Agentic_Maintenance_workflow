.PHONY: up down backend frontend seed simulate evaluate baseline test lint hooks demo

up:
	docker compose up -d db

down:
	docker compose down

backend:
	cd backend && python -m uvicorn app.main:app --reload

frontend:
	docker compose up frontend

seed:
	cd backend && alembic upgrade head && python -m scripts.seed

simulate:
	cd backend && python -m scripts.simulate

evaluate:
	cd backend && python -m scripts.evaluate_detection

baseline:
	cd backend && python -m scripts.baseline_report

test:
	cd backend && python -m pytest

lint:
	cd backend && ruff check app tests scripts alembic

hooks:
	pre-commit run --all-files

demo:
	cd backend && python -m scripts.e2e_demo
