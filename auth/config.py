import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "sqlite:///" + os.path.join(BASE_DIR, "instance", "auth.db")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Server-to-server base URL (auth -> vgarden), e.g. the internal Docker network address.
    VGARDEN_URL = os.environ.get("VGARDEN_URL", "http://localhost:5002")
    # Browser-facing base URL, used in links rendered to the user.
    VGARDEN_PUBLIC_URL = os.environ.get("VGARDEN_PUBLIC_URL", "http://localhost:5002")

    # Shared with vgarden: signs the short-lived SSO handoff token (auth -> vgarden) and
    # authenticates auth's own server-to-server calls to vgarden's /gardens API.
    INTER_SERVICE_SECRET = os.environ.get(
        "INTER_SERVICE_SECRET", "dev-inter-service-secret-change-me"
    )

    # Browser-facing base URL of the plant health monitoring service.
    HEALTH_PUBLIC_URL = os.environ.get("HEALTH_PUBLIC_URL", "http://localhost:5003/plant-health-records")
    ALMANAC_PUBLIC_URL = os.environ.get("ALMANAC_PUBLIC_URL", "http://localhost:5004/")

    # Distinct per service so auth's and vgarden's cookies don't clobber each other
    # when both are served from the same origin (the nginx proxy).
    SESSION_COOKIE_NAME = "auth_session"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true"
