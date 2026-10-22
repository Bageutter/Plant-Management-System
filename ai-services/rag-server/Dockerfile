# Cloud image only (bonus profile, infra/apps.bicep). Locally the RAG server stays a
# plain host process; docker-compose.yml never builds this.
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn==23.0.0
COPY . .
# The page reuses the project header; azure-build-push.sh stages it as shared_templates/
# (app.py looks for it two levels above the app, i.e. /shared/templates).
RUN if [ -d shared_templates ]; then mkdir -p /shared && mv shared_templates /shared/templates; fi

RUN useradd --system --uid 10001 app && mkdir -p /app/instance && chown -R app /app
USER app
ENV PYTHONUNBUFFERED=1 RAG_HOST=0.0.0.0 RAG_PORT=5106
EXPOSE 5106
# cloud_start.py serves the app under gunicorn and keeps the index in step with the
# features' public APIs (the container's disk is fresh on every start).
CMD ["python", "cloud_start.py"]
