# Base image ships Chromium + all OS deps for Playwright 1.48.0 (matches the
# pin in requirements.txt) on top of Python 3 — no `playwright install` dance.
FROM mcr.microsoft.com/playwright/python:v1.48.0-jammy

# - PYTHONUNBUFFERED: logs from both processes stream out immediately
# - STREAMLIT_URL: where the auth gateway proxies to (same container, loopback)
# - Browsers already live in the base image; point Playwright at them.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    STREAMLIT_URL=http://127.0.0.1:8501 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# Install deps first so the layer caches across code-only changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code. data/ and config.yaml are intentionally NOT copied — they are
# mounted at runtime (see docker-compose.yml / .dockerignore).
COPY . .

# Only the auth gateway is exposed. 8501 stays internal to the container.
EXPOSE 8000

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
