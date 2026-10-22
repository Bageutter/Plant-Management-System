import os


def model_for(role):
    setting = "REVIEWER_MODEL" if role == "reviewer" else "OLLAMA_MODEL"
    return os.environ.get(setting, "qwen3:4b-instruct")


def timeout():
    """Seconds per Ollama call (OLLAMA_TIMEOUT); CPU-only cloud replicas need longer."""
    return float(os.environ.get("OLLAMA_TIMEOUT", "120"))
