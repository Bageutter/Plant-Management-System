import model_config


def test_ollama_timeout_defaults_to_two_minutes(monkeypatch):
    monkeypatch.delenv("OLLAMA_TIMEOUT", raising=False)
    assert model_config.timeout() == 120.0


def test_ollama_timeout_follows_the_environment(monkeypatch):
    # The cloud bonus profile sets 230 s, under the ingress's 240 s request limit.
    monkeypatch.setenv("OLLAMA_TIMEOUT", "230")
    assert model_config.timeout() == 230.0
