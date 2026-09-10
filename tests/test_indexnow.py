"""scripts/indexnow.py: submit only recently modified sitemap URLs, and never fail a deploy."""

from datetime import date, timedelta
from types import SimpleNamespace

import pytest
import requests
from click.testing import CliRunner

from scripts.indexnow import ENDPOINT, fresh_urls, main, submit

KEY = "0123456789abcdef0123456789abcdef"
TODAY = date.today()
FRESH = "https://vilf.org/places/fresh/"
STALE = "https://vilf.org/places/stale/"


def sitemap_xml(entries):
    urls = "".join(
        f"<url><loc>{loc}</loc><lastmod>{lastmod}</lastmod></url>" for loc, lastmod in entries
    )
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>'
    )


def setup(tmp_path, entries, key=KEY):
    """Lay out build/sitemap.xml and static/<key>.txt the way the repo has them."""
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "sitemap.xml").write_text(sitemap_xml(entries))
    (tmp_path / "static").mkdir()
    if key:
        (tmp_path / "static" / f"{key}.txt").write_text(key)


def fresh_and_stale():
    return [(FRESH, TODAY.isoformat()), (STALE, (TODAY - timedelta(days=30)).isoformat())]


@pytest.fixture
def posted(monkeypatch):
    """Record requests.post calls instead of hitting the network."""
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return SimpleNamespace(status_code=200, text="")

    monkeypatch.setattr(requests, "post", fake_post)
    return calls


def run(tmp_path, monkeypatch, *args):
    monkeypatch.chdir(tmp_path)
    return CliRunner().invoke(main, list(args))


def test_submits_only_fresh_urls(tmp_path, monkeypatch, posted):
    setup(tmp_path, fresh_and_stale())
    result = run(tmp_path, monkeypatch)
    assert result.exit_code == 0, result.output
    assert len(posted) == 1
    url, kwargs = posted[0]
    assert url == ENDPOINT
    assert kwargs["json"] == {
        "host": "vilf.org",
        "key": KEY,
        "keyLocation": f"https://vilf.org/{KEY}.txt",
        "urlList": [FRESH],
    }
    assert "submitted 1 URL" in result.output
    assert "HTTP 200" in result.output


def test_nothing_fresh_means_no_post(tmp_path, monkeypatch, posted):
    setup(tmp_path, [(STALE, (TODAY - timedelta(days=30)).isoformat())])
    result = run(tmp_path, monkeypatch)
    assert result.exit_code == 0, result.output
    assert not posted
    assert "nothing to submit" in result.output


def test_dry_run_prints_without_posting(tmp_path, monkeypatch, posted):
    setup(tmp_path, fresh_and_stale())
    result = run(tmp_path, monkeypatch, "--dry-run")
    assert result.exit_code == 0, result.output
    assert not posted
    assert FRESH in result.output
    assert STALE not in result.output


def test_http_error_still_exits_zero(tmp_path, monkeypatch):
    setup(tmp_path, fresh_and_stale())
    monkeypatch.setattr(
        requests, "post", lambda url, **kw: SimpleNamespace(status_code=422, text="Unprocessable")
    )
    result = run(tmp_path, monkeypatch)
    assert result.exit_code == 0, result.output
    assert "422" in result.output


def test_connection_error_still_exits_zero(tmp_path, monkeypatch):
    setup(tmp_path, fresh_and_stale())

    def boom(url, **kw):
        raise requests.ConnectionError("no network")

    monkeypatch.setattr(requests, "post", boom)
    result = run(tmp_path, monkeypatch)
    assert result.exit_code == 0, result.output
    assert "failed" in result.output


def test_missing_key_means_no_post(tmp_path, monkeypatch, posted):
    setup(tmp_path, fresh_and_stale(), key=None)
    result = run(tmp_path, monkeypatch)
    assert result.exit_code == 0, result.output
    assert not posted
    assert "key" in result.output


def test_missing_sitemap_means_no_post(tmp_path, monkeypatch, posted):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(main, [])
    assert result.exit_code == 0, result.output
    assert not posted


def test_fresh_urls_two_day_boundary(tmp_path):
    today = date(2026, 9, 9)
    entries = [
        ("https://vilf.org/a/", "2026-09-09"),
        ("https://vilf.org/b/", "2026-09-07"),  # exactly 2 days old: included
        ("https://vilf.org/c/", "2026-09-06"),  # 3 days old: excluded
        ("https://vilf.org/d/", "2026-09-08T10:00:00+00:00"),  # datetime lastmod still parses
    ]
    path = tmp_path / "sitemap.xml"
    path.write_text(sitemap_xml(entries))
    assert fresh_urls(path, today=today) == [
        "https://vilf.org/a/",
        "https://vilf.org/b/",
        "https://vilf.org/d/",
    ]


def test_submit_payload(posted):
    response = submit([FRESH, STALE], key=KEY, host="vilf.org")
    assert response.status_code == 200
    assert posted == [
        (
            ENDPOINT,
            {
                "json": {
                    "host": "vilf.org",
                    "key": KEY,
                    "keyLocation": f"https://vilf.org/{KEY}.txt",
                    "urlList": [FRESH, STALE],
                },
                "timeout": 30,
            },
        )
    ]


def test_submit_propagates_request_error(monkeypatch):
    def boom(url, **kw):
        raise requests.ConnectionError("no network")

    monkeypatch.setattr(requests, "post", boom)
    with pytest.raises(requests.ConnectionError):
        submit([FRESH], key=KEY)
