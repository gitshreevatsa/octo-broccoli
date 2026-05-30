# ── Stage 1: Build React frontend ────────────────────────────────────────────
FROM node:20-alpine AS frontend-builder

WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci --silent
COPY frontend/ ./
RUN npm run build


# ── Stage 2: Python backend ───────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

# System deps (needed by some jobspy / httpx dependencies)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY *.py ./
COPY scrapers/ scrapers/

# Built frontend from stage 1
COPY --from=frontend-builder /frontend/dist ./frontend/dist

# Results directory — mount a persistent volume here on Render/Fly/etc.
RUN mkdir -p /app/results
ENV RESULTS_DIR=/app/results

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

# Single worker: in-memory SSE queues won't work across multiple workers.
# Scale via multiple containers (each handles its own searches) if needed.
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--log-level", "info"]
