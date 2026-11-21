# Multi-stage build: compile the React app, then run the API + built SPA together.
FROM node:20-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    REVIEW_DB_PATH=/app/state/review.db

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config.yaml ./
COPY src ./src
COPY api ./api
COPY --from=frontend /app/frontend/dist ./frontend/dist

# Bake a deterministic dataset into the image; review outcomes live on the volume.
RUN python -m src.generate_data
RUN mkdir -p /app/state /app/reports

EXPOSE 8000
# $PORT lets the same image run on Render/Fly/Railway style platforms.
CMD python -m uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}
