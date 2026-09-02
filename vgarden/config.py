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

    # Distinct per service so auth's and vgarden's cookies don't clobber each other
    # when both are served from the same origin (the nginx proxy).
    SESSION_COOKIE_NAME = "vgarden_session"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true"
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
