.PHONY: up down backend frontend seed simulate evaluate test lint demo

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

test:
	cd backend && python -m pytest

lint:
	cd backend && ruff check app tests scripts

demo:
	cd backend && python -m scripts.e2e_demo