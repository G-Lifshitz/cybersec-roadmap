# Roadmap service image. Built in CI from services/roadmap only (its own build context).
FROM python:3.12-slim

# Commit the image was built from; GET /health reports it as "version".
ARG GIT_SHA=dev
ENV GIT_SHA=${GIT_SHA} \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app

# Dependencies first, so a code change doesn't reinstall them (layer cache).
# pymssql's wheel bundles FreeTDS, so no system packages are needed.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Never run as root inside the container.
RUN useradd --system --uid 10001 app && chown -R app /app
USER app

EXPOSE 8000

# Container Apps and compose both restart the container if this keeps failing.
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/health', timeout=4)"

# Migrations first (waits for the database to resume, applies pending files),
# then the API: one worker process, 4 threads, each thread with its own DB connection.
CMD ["sh", "-c", "python migrate.py && exec gunicorn --bind 0.0.0.0:${PORT} --workers 1 --threads 4 --timeout 60 'app:create_app()'"]
