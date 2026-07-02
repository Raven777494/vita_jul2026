# Production Docker image for vita-api (Logic Engine HTTP service).
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    curl \
    postgresql-client \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-docker.txt requirements-ci.txt ./
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -r requirements-docker.txt

COPY compose_env.py hardware_profile_loader.py vita_core_config.py ./
COPY app app/
COPY PersonalityModule PersonalityModule/
COPY config config/
COPY dict dict/

RUN mkdir -p /app/logs /app/cache /app/data /app/models

HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=20s \
    CMD curl -f http://localhost:8080/health || exit 1

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "4"]
