"""Shared test setup: no test may reach the network.

The guard sits on the HTTP library call so tests that exercise places._request itself can
still substitute their own fake at that level.
"""

import pytest
import os

import scripts.places as places
from scripts import config, storage


@pytest.fixture(autouse=True)
def isolated_configuration(monkeypatch, tmp_path):
    """A developer's production .env/ADC must never become test configuration."""
    monkeypatch.setattr(config, "load_dotenv", lambda *args, **kwargs: False)
    for key in list(os.environ):
        if key.startswith("VILF_") or key in {"DATABASE_URL", "GOOGLE_CLOUD_PROJECT",
                                              "GOOGLE_PLACES_API_KEY", "GOOGLE_MAPS_EMBED_API_KEY"}:
            monkeypatch.delenv(key)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/isolated.db")
    monkeypatch.setenv("VILF_MEDIA_STORAGE", str(tmp_path / "media"))
    monkeypatch.setenv("VILF_SITE_STORAGE", str(tmp_path / "site"))
    monkeypatch.setattr(storage.GCSStorage, "__init__",
                        lambda *args, **kwargs: pytest.fail("real GCS access attempted"))
    config.settings.cache_clear()
    yield
    config.settings.cache_clear()


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(places.requests, "request", lambda *a, **k: pytest.fail("network call attempted"))
    monkeypatch.setattr(places.requests, "get", lambda *a, **k: pytest.fail("network call attempted"))
    monkeypatch.setattr(places.requests, "post", lambda *a, **k: pytest.fail("network call attempted"))
