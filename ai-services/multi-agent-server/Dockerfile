# Cloud image only (bonus profile, infra/apps.bicep). Locally the Multi-Agent Server
# stays a plain host process; docker-compose.yml never builds this.
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn==23.0.0
COPY . .

RUN useradd --system --uid 10001 app && mkdir -p /app/instance && chown -R app /app
USER app
ENV PYTHONUNBUFFERED=1
EXPOSE 8003
# One worker: the workflow store is one SQLite file. Threads serve status polls while
# a long Planner -> Worker -> Reviewer run is in progress.
CMD ["gunicorn", "--bind", "0.0.0.0:8003", "--workers", "1", "--threads", "8", "--timeout", "900", "--access-logfile", "-", "app:app"]
