import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


def _as_bool(value: str, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class Config:
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "sqlite:///" + os.path.join(BASE_DIR, "instance", "health.db")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Browser-facing base URL of the auth service, used in links rendered to the user.
    AUTH_PUBLIC_URL = os.environ.get("AUTH_PUBLIC_URL", "http://localhost:5001")

    # Locally hosted AI (Ollama). Nothing leaves the local network.
    OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434").rstrip("/")
    OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "gemma3:4b")
    OLLAMA_TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", "180"))
    # Pull the model on first use if it is not present in the Ollama instance yet.
    OLLAMA_AUTO_PULL = _as_bool(os.environ.get("OLLAMA_AUTO_PULL"), True)
    OLLAMA_PULL_TIMEOUT = int(os.environ.get("OLLAMA_PULL_TIMEOUT", "1800"))

    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_UPLOAD_BYTES", str(12 * 1024 * 1024)))
    ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
