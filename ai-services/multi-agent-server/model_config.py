import os


def model_for(role):
    setting = "REVIEWER_MODEL" if role == "reviewer" else "OLLAMA_MODEL"
    return os.environ.get(setting, "qwen3:4b-instruct")
