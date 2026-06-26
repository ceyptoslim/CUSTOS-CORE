FROM python:3.12-slim

WORKDIR /app

# Install curl for healthcheck (not present in slim by default)
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Install dependencies first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY custos/ ./custos/
COPY main.py .

# Non-root user for security
RUN adduser --disabled-password --gecos "" custos
USER custos

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
