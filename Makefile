.PHONY: up down backend frontend seed simulate evaluate test lint demo

up:
	docker compose up -d db

down:
	docker compose down

backend:
	cd backend && python -m uvicorn app.main:app --reload

frontend:
	cd frontend && npm run dev

seed:
	cd backend && python scripts/seed.py

simulate:
	cd backend && python scripts/simulate.py

evaluate:
	cd backend && python scripts/evaluate_detection.py

test:
	cd backend && python -m pytest

lint:
	cd backend && ruff check app tests scripts

demo:
	cd backend && python scripts/e2e_demo.py