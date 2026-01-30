# syntax=docker/dockerfile:1
FROM python:3.11-slim

ARG APP_VERSION=dev
ARG BUILD_DATE=unknown

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_HOST=0.0.0.0 \
    APP_PORT=8000 \
    DB_PATH=/app/data/app.db \
    PYTHONPATH=/app \
    APP_VERSION=${APP_VERSION} \
    BUILD_DATE=${BUILD_DATE}

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./

RUN mkdir -p /app/data/cache/images \
    && date -u +"%Y-%m-%dT%H:%M:%SZ" > /app/BUILD_DATE \
    && python scripts/init_db.py \
    && python scripts/seed_demo.py

EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --host ${APP_HOST:-0.0.0.0} --port ${APP_PORT:-8000}"]
