# Universal Website Replication Engine - production image
# (Hugging Face Spaces / any Docker host). Serves the API + built UI on $PORT.

# ---------- 1. Frontend build ----------
FROM node:22-bookworm-slim AS frontend
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------- 2. Runtime: Python + Playwright Chromium ----------
# Same Playwright version as backend/requirements.txt (browsers preinstalled).
FROM mcr.microsoft.com/playwright/python:v1.63.0-noble

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    HOST=0.0.0.0 \
    PORT=7860 \
    PROJECTS_DIR=/data/projects \
    PAGE_CONCURRENCY=2 \
    MAX_PAGES=30

WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --break-system-packages -r backend/requirements.txt

COPY backend/ backend/
COPY --from=frontend /src/frontend/dist frontend/dist

# Hugging Face Spaces runs the container as uid 1000.
RUN mkdir -p /data/projects && chown -R 1000:1000 /data /app
USER 1000

EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request,os;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"7860\")}/api/health')" || exit 1

CMD ["python", "backend/run.py"]
