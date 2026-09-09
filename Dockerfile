FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/instance /app/static/uploads /app/faiss_index

# non-root user
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 4500

CMD ["sh", "-c", "exec gunicorn -w 1 --threads 8 --timeout 120 -b 0.0.0.0:4500 --access-logfile - --error-logfile - app:app"]