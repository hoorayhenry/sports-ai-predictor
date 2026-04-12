FROM python:3.11-slim

WORKDIR /app

# Install system deps for LightGBM/XGBoost
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONPATH=/app
ENV DATABASE_URL=sqlite+aiosqlite:///./sports.db
ENV DATABASE_URL_SYNC=sqlite:///./sports.db

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
