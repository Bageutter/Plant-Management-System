# Cloud image only (bonus profile, infra/apps.bicep). Locally the MCP server stays a
# plain host process, as Release 1 requires; docker-compose.yml never builds this.
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

# Non-root, listening inside the container network only (ingress is internal).
RUN useradd --system --uid 10001 app && chown -R app /app
USER app
ENV PYTHONUNBUFFERED=1 MCP_HOST=0.0.0.0 MCP_PORT=5105
EXPOSE 5105
CMD ["python", "server.py"]
