"""Shared test setup: no test may reach the network.

The guard sits on the HTTP library call so tests that exercise places._request itself can
still substitute their own fake at that level.
"""

import pytest

import scripts.places as places


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(places.requests, "request", lambda *a, **k: pytest.fail("network call attempted"))
    monkeypatch.setattr(places.requests, "get", lambda *a, **k: pytest.fail("network call attempted"))
    monkeypatch.setattr(places.requests, "post", lambda *a, **k: pytest.fail("network call attempted"))
