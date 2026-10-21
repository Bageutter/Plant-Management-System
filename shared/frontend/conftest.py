"""Root-level so this directory lands on sys.path and tests can `import app`.

In the container, docker compose mounts shared/templates at /app/shared_templates.
Locally that folder is an empty mount point, so the tests add shared/templates to
the app's template search path instead.
"""

import importlib
import os

import pytest
from jinja2 import ChoiceLoader, FileSystemLoader

SHARED_TEMPLATES = os.path.join(os.path.dirname(__file__), "..", "templates")
URLS = {
    "AUTH_URL": "http://proxy.test/auth",
    "HEALTH_URL": "http://proxy.test/health/plant-health-records/",
    "ALMANAC_URL": "http://proxy.test/almanac/",
}


@pytest.fixture
def frontend(monkeypatch):
    for name, value in URLS.items():
        monkeypatch.setenv(name, value)
    import app as module

    module = importlib.reload(module)  # the URLs are read from the environment at import
    module.app.config["TESTING"] = True
    module.app.jinja_loader = ChoiceLoader([module.app.jinja_loader, FileSystemLoader(SHARED_TEMPLATES)])
    return module.app


@pytest.fixture
def client(frontend):
    return frontend.test_client()
