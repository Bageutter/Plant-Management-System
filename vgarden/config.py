import os
from datetime import timedelta

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    # Signs vgarden's own session cookie (separate from INTER_SERVICE_SECRET below).
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")

    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "sqlite:///" + os.path.join(BASE_DIR, "instance", "vgarden.db")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Browser-facing base URLs of the sibling services, used for the shared nav header and
    # to send a user to auth to log in when they hit vgarden with no session.
    AUTH_PUBLIC_URL = os.environ.get("AUTH_PUBLIC_URL", "http://localhost:5001")
    HEALTH_PUBLIC_URL = os.environ.get(
        "HEALTH_PUBLIC_URL", "http://localhost:5003/plant-health-records/"
    )
    ALMANAC_PUBLIC_URL = os.environ.get("ALMANAC_PUBLIC_URL", "http://localhost:5004/")

    # Shared with auth: verifies the SSO handoff token (auth -> vgarden) and authenticates
    # auth's server-to-server calls to the /gardens API.
    INTER_SERVICE_SECRET = os.environ.get(
        "INTER_SERVICE_SECRET", "dev-inter-service-secret-change-me"
    )

    # Locally hosted Ollama used by the "ask about this garden" AI assistant. Mirrors almanac.
    OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
    OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:4b-instruct")
    OLLAMA_TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", "120"))
    OLLAMA_AUTO_PULL = os.environ.get("OLLAMA_AUTO_PULL", "false").lower() == "true"

    # Agentic loop (Plan -> Act -> Observe -> Adapt). The reviewer is a second,
    # independent Ollama model that checks each draft answer. Empty -> loop runs
    # single-shot. See docs/agentic-ai-workflow.md.
    OLLAMA_REVIEW_MODEL = os.environ.get("OLLAMA_REVIEW_MODEL", "llama3.1:8b")
    AI_LOOP_MAX_ITERATIONS = int(os.environ.get("AI_LOOP_MAX_ITERATIONS", "2"))
    AI_LOOP_LOG_DIR = os.environ.get(
        "AI_LOOP_LOG_DIR", os.path.join(BASE_DIR, "..", "tools", "ai-loop", "logs")
    )

    # Open-Meteo (no API key): geocodes a garden's location and feeds current
    # conditions + a short forecast to the AI assistant.
    OPEN_METEO_GEOCODING_URL = os.environ.get(
        "OPEN_METEO_GEOCODING_URL", "https://geocoding-api.open-meteo.com/v1/search"
    )
    OPEN_METEO_FORECAST_URL = os.environ.get(
        "OPEN_METEO_FORECAST_URL", "https://api.open-meteo.com/v1/forecast"
    )
    WEATHER_TIMEOUT = int(os.environ.get("WEATHER_TIMEOUT", "10"))
    WEATHER_CACHE_TTL = int(os.environ.get("WEATHER_CACHE_TTL", "1800"))

    # Distinct per service so auth's and vgarden's cookies don't clobber each other
    # when both are served from the same origin (the nginx proxy).
    SESSION_COOKIE_NAME = "vgarden_session"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true"
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
