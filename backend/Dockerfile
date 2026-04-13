FROM python:3.11-slim

WORKDIR /app

# System deps for LightGBM/XGBoost + curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libgomp1 curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Data + model dirs persist via Docker volumes
RUN mkdir -p /data ml/saved

ENV PYTHONPATH=/app
ENV DATABASE_URL=sqlite+aiosqlite:////data/sports_ai.db
ENV DATABASE_URL_SYNC=sqlite:////data/sports_ai.db

EXPOSE 8000

# Run DB init + setup if DB is empty, then start server
CMD ["sh", "-c", \
  "python scripts/setup.py --skip-live --skip-season 2>/dev/null || true && \
   uvicorn api.main:app --host 0.0.0.0 --port 8000 --workers 2"]
