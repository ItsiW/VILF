"""Shared test setup: no test may reach the network."""

import pytest

import scripts.places as places


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(places, "_request", lambda *a, **k: pytest.fail("network call attempted"))
