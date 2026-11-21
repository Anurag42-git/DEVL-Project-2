# Developer and production commands for the FastAPI + React application.
# Python dependencies: pip install -r requirements.txt
# Frontend dependencies: npm --prefix frontend install

.PHONY: dev api web data test build serve docker docker-down help

help:
	@echo "make data         - generate the synthetic dataset"
	@echo "make api          - start FastAPI only (dev)"
	@echo "make web          - start Vite only (dev)"
	@echo "make dev          - start both dev servers"
	@echo "make build        - build the production frontend"
	@echo "make serve        - build + serve SPA and API from one process on :8000"
	@echo "make docker       - build and start the production container"
	@echo "make docker-down  - stop the container"
	@echo "make test         - run backend + frontend tests"

data:
	python -m src.generate_data

api:
	uvicorn api.main:app --reload --host 127.0.0.1 --port 8000

web:
	npm --prefix frontend run dev

dev:
	@uvicorn api.main:app --reload --host 127.0.0.1 --port 8000 & \
	 npm --prefix frontend run dev

test:
	python -m pytest -q
	npm --prefix frontend test

build:
	npm --prefix frontend run build

serve: build
	python -m uvicorn api.main:app --host 0.0.0.0 --port 8000

docker:
	docker compose up --build -d

docker-down:
	docker compose down
