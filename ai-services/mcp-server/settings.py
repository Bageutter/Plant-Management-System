"""Environment-driven configuration for the shared MCP server.

The server is a plain local process (Release 1 forbids containerising it), so all
configuration comes from environment variables with localhost defaults. Every
feature service is reached through the nginx proxy on :3000, never directly.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit

DEFAULT_ALLOWED_HOSTS = ("127.0.0.1:*", "localhost:*", "host.docker.internal:*")


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def validate_service_url(url: str, name: str) -> str:
    """Accept only a bare http(s) origin (+ optional path prefix).

    Tools can never choose an origin, so this is the one place a URL is trusted.
    Credentials, query strings and fragments are rejected outright.
    """

    parsed = urlsplit(url)
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            f"{name} must be an http(s) URL without credentials, query or fragment: {url!r}"
        )
    return url.rstrip("/")


@dataclass(frozen=True)
class Settings:
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 5105
    allowed_hosts: tuple[str, ...] = field(default_factory=lambda: DEFAULT_ALLOWED_HOSTS)
    health_url: str = "http://127.0.0.1:3000/health"
    almanac_url: str = "http://127.0.0.1:3000/almanac"
    vgarden_url: str = "http://127.0.0.1:3000/vgarden"
    rag_url: str = "http://127.0.0.1:5106"
    rag_refresh_enabled: bool = False
    timeout: float = 10.0
    # A text assessment runs the vision model; allow the health service's own 180 s.
    assess_timeout: float = 200.0
    # Virtual Garden state is private per-owner (unlike the public Almanac catalogue
    # or Plant Health assessments), so its snapshot endpoints require this bearer
    # token — the same shared secret vgarden already uses for auth's server-to-server
    # calls (INTER_SERVICE_SECRET in docker-compose.yml / vgarden's own config).
    vgarden_service_token: str = "dev-inter-service-secret-change-me"

    def __post_init__(self) -> None:
        for name in ("health_url", "almanac_url", "vgarden_url", "rag_url"):
            object.__setattr__(self, name, validate_service_url(getattr(self, name), name))

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Settings":
        env = os.environ if env is None else env
        hosts = env.get("MCP_ALLOWED_HOSTS", "")
        allowed = tuple(h.strip() for h in hosts.split(",") if h.strip()) or DEFAULT_ALLOWED_HOSTS
        return cls(
            enabled=_as_bool(env.get("MCP_ENABLED"), True),
            host=env.get("MCP_HOST", "127.0.0.1"),
            port=int(env.get("MCP_PORT", "5105")),
            allowed_hosts=allowed,
            health_url=env.get("HEALTH_SERVICE_URL", "http://127.0.0.1:3000/health"),
            almanac_url=env.get("ALMANAC_SERVICE_URL", "http://127.0.0.1:3000/almanac"),
            vgarden_url=env.get("VGARDEN_SERVICE_URL", "http://127.0.0.1:3000/vgarden"),
            rag_url=env.get("RAG_SERVICE_URL", "http://127.0.0.1:5106"),
            rag_refresh_enabled=_as_bool(env.get("MCP_RAG_REFRESH_ENABLED"), False),
            timeout=float(env.get("SERVICE_TIMEOUT", "10")),
            assess_timeout=float(env.get("ASSESS_TIMEOUT", "200")),
            vgarden_service_token=env.get(
                "VGARDEN_SERVICE_TOKEN", "dev-inter-service-secret-change-me"
            ),
        )
