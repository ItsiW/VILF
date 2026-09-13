"""render_site over the snapshot fixture, plus the legacy `./vilf build` wrapper."""

import json
import re
import shutil
from datetime import date
from pathlib import Path

import pytest
from click.testing import CliRunner

from scripts.build import build_vilf, parse_git_dates
from scripts.render import SITE_URL, RenderError, enrich_place, render_site

REPO_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = REPO_ROOT / "tests" / "fixtures" / "snapshot.json"
TODAY = date(2026, 9, 9)

# build.py reports a broken place with "<slug>.md <error>"
PLACE_ERROR = re.compile(r"^.+\.md( |$)")

PLACES_JSON_KEYS = {
    "name", "slug", "url", "cuisine", "area", "city", "address", "lat", "lon",
    "taste", "taste_label", "value", "value_label", "drinks", "visited", "modified",
    "phone", "menu", "website", "image", "closed",
}

LD_JSON = re.compile(r'<script type="application/ld\+json">\s*(.*?)\s*</script>', re.DOTALL)
SITEMAP_ENTRY = re.compile(r"<loc>([^<]+)</loc>\s*<lastmod>([^<]+)</lastmod>")
# fabricated schema.org fields the Restaurant block used to emit
REMOVED_LD_KEYS = {
    "aggregateRating", "paymentAccepted", "currenciesAccepted",
    "openingHours", "acceptsReservations", "priceRange",
}


def load_rows():
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))


def make_site_root(root: Path) -> Path:
    """html/ and about.md from the repo, a static/ with only the top-level files (no img/ cache)."""
    (root / "html").symlink_to(REPO_ROOT / "html")
    (root / "about.md").symlink_to(REPO_ROOT / "about.md")
    (root / "static").mkdir()
    for file in (REPO_ROOT / "static").iterdir():
        if file.is_file():
            shutil.copy(file, root / "static" / file.name)
    return root


def render(rows, root: Path, **kw):
    out = root / "build"
    stats = render_site(
        rows,
        out,
        html_dir=root / "html",
        static_dir=root / "static",
        about_path=root / "about.md",
        today=TODAY,
        **kw,
    )
    return out, stats


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    root = make_site_root(tmp_path_factory.mktemp("site"))
    rows = load_rows()
    out, stats = render(rows, root)
    return rows, out, stats


def ld_blocks(page_text):
    """Every JSON-LD block on a page, parsed and keyed by @type."""
    blocks = {}
    for match in LD_JSON.findall(page_text):
        block = json.loads(match)
        blocks[block["@type"]] = block
    return blocks


def page(out, slug):
    return (out / "places" / slug / "index.html").read_text(encoding="utf-8")


def test_stats(site):
    _, _, stats = site
    assert (stats.open, stats.closed) == (5, 1)
    assert stats.pages > 0


def test_outputs_exist(site):
    rows, out, _ = site
    for name in [
        "index.html", "places.geojson", "sitemap.xml", "best/index.html", "latest/index.html",
        "error.html", "about/index.html", "robots.txt", "llms.txt", "llms-full.txt", "places.json",
        "cuisines/index.html", "neighborhoods/index.html", "favicon.ico",
    ]:
        assert (out / name).is_file(), name
    for row in rows:
        assert (out / "places" / row["slug"] / "index.html").is_file(), row["slug"]
        assert (out / "places" / f"{row['slug']}.md").is_file(), row["slug"]
    assert not (out / "img").exists()  # no static/img in the fixture root, and none was fabricated


def test_geojson_has_only_open_places(site):
    _, out, _ = site
    features = json.loads((out / "places.geojson").read_text())["features"]
    assert sorted(f["properties"]["name"] for f in features) == sorted(
        ["Test Place", "Brackets [Cafe]", "Bare Place", "Draft Place", "Phone Only"]
    )
    assert list(features[0]["properties"]) == [
        "name", "cuisine", "url", "taste_label", "taste_color", "value_label", "value_color",
        "food_image_path", "food_thumb_path",
    ]
    by_name = {f["properties"]["name"]: f for f in features}
    assert by_name["Test Place"]["properties"]["food_thumb_path"] == "/img/thumb/test-place.webp"
    assert by_name["Bare Place"]["properties"]["food_thumb_path"] is None
    assert by_name["Test Place"]["geometry"]["coordinates"] == [-122.4201, 37.7601]


def test_closed_place_keeps_page_but_leaves_lists(site):
    _, out, _ = site
    assert "Permanently closed." in page(out, "gone-place")
    assert "Permanently closed." not in page(out, "test-place")
    best = (out / "best" / "index.html").read_text()
    assert "Test Place" in best and "Gone Place" not in best
    assert "Gone Place" not in (out / "llms.txt").read_text()
    assert "Gone Place" not in (out / "llms-full.txt").read_text()
    data = {p["slug"]: p for p in json.loads((out / "places.json").read_text())}
    assert data["gone-place"]["closed"] is True and data["test-place"]["closed"] is False
    assert "- Status: permanently closed" in (out / "places" / "gone-place.md").read_text()
    assert "- Status:" not in (out / "places" / "test-place.md").read_text()
    assert f"{SITE_URL}/places/gone-place/" in (out / "sitemap.xml").read_text()


def test_llms_txt(site):
    rows, out, _ = site
    text = (out / "llms.txt").read_text(encoding="utf-8")
    assert text.startswith("# Vegans In Love with Food")
    for row in rows:
        if not row["closed"]:
            assert f"{SITE_URL}/places/{row['slug']}/" in text, row["slug"]
    assert "- [Brackets \\[Cafe\\]](" in text
    assert f"[markdown]({SITE_URL}/places/brackets-cafe.md)" in text
    # Draft Place is open in the snapshot; published_at is not consulted by the renderer
    assert "Draft Place" in text


def test_llms_full_and_review_markdown(site):
    _, out, _ = site
    full = (out / "llms-full.txt").read_text(encoding="utf-8")
    assert full.startswith("# Vegans In Love with Food")
    assert "**pad thai**" in full
    assert "## Test Place" in full
    md = (out / "places" / "test-place.md").read_text(encoding="utf-8")
    assert md.startswith("# Test Place\n")
    assert f"- URL: {SITE_URL}/places/test-place/" in md
    assert "- Address: 1 Main St, Mission District, San Francisco" in md
    assert "- Last visited: 31st March 2024" in md
    assert "- Verdict: Good taste, Fine value, booze available." in md
    assert md.endswith("Get the **pad thai**, it is the best thing here.\n")


def test_places_json(site):
    rows, out, _ = site
    data = json.loads((out / "places.json").read_text(encoding="utf-8"))
    assert len(data) == len(rows)
    assert all(set(entry) == PLACES_JSON_KEYS for entry in data)
    by_slug = {entry["slug"]: entry for entry in data}
    assert by_slug["test-place"]["modified"] == "2026-09-01"
    assert by_slug["draft-place"]["modified"] == "2026-09-05"
    assert by_slug["test-place"]["image"] == f"{SITE_URL}/img/food/test-place.jpg"
    assert by_slug["bare-place"]["image"] is None
    assert [entry["name"] for entry in data] == sorted((e["name"] for e in data), key=str.lower)


def test_verdict_and_markdown_alternate(site):
    _, out, _ = site
    html = page(out, "test-place")
    assert "Verdict:" not in html
    assert '<link rel="alternate" type="text/markdown" href="/places/test-place.md">' in html


def test_json_ld(site):
    rows, out, _ = site
    for row in rows:
        blocks = ld_blocks(page(out, row["slug"]))  # raises if any block is not valid JSON
        assert set(blocks) == {"Restaurant", "Article", "BreadcrumbList"}, row["slug"]
        restaurant, article = blocks["Restaurant"], blocks["Article"]
        assert not REMOVED_LD_KEYS & set(restaurant), row["slug"]
        locality = row["city"] or row["area"]
        assert restaurant["address"]["addressLocality"] == locality
        assert article["about"]["address"]["addressLocality"] == locality
        assert restaurant["review"]["datePublished"] == article["datePublished"] == row["visited"]
        assert article["dateModified"] == row["updated_at"][:10]
        if row["website"]:
            assert restaurant["sameAs"] == row["website"]
        else:
            assert "sameAs" not in restaurant


def test_sitemap_lastmod(site):
    rows, out, _ = site
    lastmods = dict(SITEMAP_ENTRY.findall((out / "sitemap.xml").read_text(encoding="utf-8")))
    for row in rows:
        assert lastmods[f"{SITE_URL}/places/{row['slug']}/"] == row["updated_at"][:10], row["slug"]
    for path in ["/", "/about/", "/best/", "/latest/", "/cuisines/"]:
        assert lastmods[f"{SITE_URL}{path}"] == "2026-09-09", path
    # the old build wrote sitemap.xml before appending the neighborhood URLs; kept for parity
    assert f"{SITE_URL}/neighborhoods/" not in lastmods


def test_menu_link_falls_back_to_website(site):
    _, out, _ = site
    # menu present: the Menu link goes to the menu page; there is never a separate Website link
    html = re.sub(r"\s+", " ", page(out, "test-place"))
    assert '<a href="https://example.com/menu" target="_blank">Menu</a> | <a href="tel:+14155551234">' in html
    assert "Website</a>" not in html
    # no menu: the Menu link falls back to the website; no phone, so no separators
    html = re.sub(r"\s+", " ", page(out, "brackets-cafe"))
    links = re.search(r'<p class="restaurant-links">(.*?)</p>', html).group(1)
    assert '<a href="https://example.org" target="_blank">Menu</a>' in links
    assert "|" not in links and "Website" not in links and "tel:" not in links


def test_images_follow_photo_key(site):
    _, out, _ = site
    assert "/img/food/test-place.webp" in page(out, "test-place")
    assert '<div class="food-image-container">' in page(out, "test-place")
    assert '<div class="food-image-container">' not in page(out, "bare-place")
    preload = re.search(r"preload\(\.\.\.(\[.*?\])\)", (out / "index.html").read_text()).group(1)
    assert "/img/thumb/test-place.webp" in json.loads(preload)
    assert "gone-place" not in preload and "bare-place" not in preload


def test_address_links_use_google_place_id_with_coordinates_fallback(site):
    from html import unescape
    from urllib.parse import parse_qs, urlparse

    rows, out, _ = site
    assert any(r.get("place_id") for r in rows)
    assert any(not r.get("place_id") for r in rows)
    for row in rows:
        html = page(out, row["slug"])
        href = unescape(re.search(r'<p class="address"><a href="([^"]+)"', html).group(1))
        url = urlparse(href)
        assert url.scheme == "https" and url.netloc == "www.google.com"
        assert url.path == "/maps/search/"
        query = parse_qs(url.query)
        assert query["api"] == ["1"]
        assert query["query"] == [f'{row["lat"]},{row["lon"]}']
        if row.get("place_id"):
            assert query["query_place_id"] == [row["place_id"]]
        else:
            assert "query_place_id" not in query
        assert "geo://" not in html


def test_media_base_url(tmp_path):
    root = make_site_root(tmp_path)
    out, _ = render(load_rows(), root, media_base_url="https://media.example")
    features = json.loads((out / "places.geojson").read_text())["features"]
    thumbs = {f["properties"]["name"]: f["properties"]["food_thumb_path"] for f in features}
    assert thumbs["Test Place"] == "https://media.example/img/thumb/test-place.webp"
    assert '<source srcset="https://media.example/img/food/test-place.webp"' in page(out, "test-place")


def test_robots_welcomes_ai_crawlers(site):
    _, out, _ = site
    text = (out / "robots.txt").read_text()
    assert "GPTBot" in text
    assert f"Sitemap: {SITE_URL}/sitemap.xml" in text


def test_latest_orders_by_review_age(site):
    _, out, _ = site
    latest = (out / "latest" / "index.html").read_text()
    assert latest.index("Draft Place") < latest.index("Test Place")


def test_render_error_on_duplicate_name(tmp_path):
    root = make_site_root(tmp_path)
    rows = load_rows()
    rows[1]["name"] = rows[0]["name"]
    with pytest.raises(RenderError) as info:
        render(rows, root)
    assert any("name 'Test Place' reused by" in line for line in info.value.problems)
    assert not (root / "build").exists()


def test_render_error_on_bad_row(tmp_path):
    root = make_site_root(tmp_path)
    rows = load_rows()
    rows[0]["slug"] = "bad-row"
    rows[0]["taste"] = 9
    rows[0]["cuisine"] = None
    with pytest.raises(RenderError) as info:
        render(rows, root)
    assert info.value.problems
    assert all(line.startswith("bad-row: ") for line in info.value.problems)
    assert "bad-row: cuisine: required" in info.value.problems


def test_render_error_on_unknown_key(tmp_path):
    root = make_site_root(tmp_path)
    rows = load_rows()
    rows[0]["foo"] = "bar"
    with pytest.raises(RenderError) as info:
        render(rows, root)
    assert "test-place: foo: unknown key" in info.value.problems


def test_enrich_place():
    row = load_rows()[0]
    place = enrich_place(row, today=TODAY, media_base_url="")
    assert place["phone_display"] == "(415) 555-1234"
    assert place["visited_display"] == "31st March 2024"
    assert place["review_age"] == (TODAY - date(2024, 3, 31)).days
    assert place["modified"] == "2026-09-01"
    assert place["md"] == "Get the **pad thai**, it is the best thing here."
    assert place["taste_label"] == "Good" and place["value_label"] == "Fine"
    assert place["food_image_path"] == "/img/food/test-place.webp"
    assert place["food_thumb_path"] == "/img/thumb/test-place.webp"
    assert "pad thai" in place["alt_text"]
    row["updated_at"] = None
    row["photo_key"] = None
    place = enrich_place(row, today=TODAY, media_base_url="")
    assert place["modified"] == "2024-03-31"
    assert place["food_image_path"] is None and place["food_thumb_path"] is None


def test_parse_git_dates_newest_first():
    # `git log --format=%cs --name-only` output: date, blank line, paths; newest commit first
    log = (
        "2026-06-11\n\nplaces/new.md\nplaces/old.md\n"
        "2025-09-08\n\nplaces/old.md\nplaces/other.md\n"
        "\n2022-10-08\n\nplaces/other.md\n"
    )
    assert parse_git_dates(log) == {
        "places/new.md": "2026-06-11",
        "places/old.md": "2026-06-11",
        "places/other.md": "2025-09-08",
    }
    assert parse_git_dates("") == {}


# --- the click wrapper ---

PLACE = (
    "---\n"
    "name: Test Place\n"
    "cuisine: Thai\n"
    "address: 1 Main St\n"
    "area: Mission District\n"
    "lat: 37.76\n"
    "lon: -122.42\n"
    "phone: \n"
    "menu: \n"
    "drinks: True\n"
    'visited: "2024-03-31"\n'
    "taste: 2\n"
    "value: 1\n"
    "instagram_published: False\n"
    "---\n"
    "\n"
    "Get the **pad thai**.\n"
)


@pytest.mark.skipif(not (REPO_ROOT / "places").is_dir(), reason="no places/ checkout")
def test_legacy_build():
    with pytest.MonkeyPatch.context() as mp:
        mp.chdir(REPO_ROOT)
        result = CliRunner().invoke(build_vilf, ["--source", "files"], catch_exceptions=False)
    assert result.exit_code == 0, result.output
    assert "220 open, 26 closed" in result.output
    assert "Done building VILF with 220 places" in result.output
    assert (REPO_ROOT / "build" / "places" / "a16" / "index.html").is_file()


def test_legacy_build_reports_bad_place(tmp_path):
    root = make_site_root(tmp_path)
    (root / "raw").mkdir()
    (root / "places").mkdir()
    (root / "places" / "test-place.md").write_text(PLACE)
    (root / "places" / "broken.md").write_text("---\nname: Broken\ntaste: 9\n---\n\nno metadata\n")
    with pytest.MonkeyPatch.context() as mp:
        mp.chdir(root)
        result = CliRunner().invoke(build_vilf, ["--source", "files"], catch_exceptions=False)
    assert result.exit_code == 1, result.output
    errors = [line for line in result.stdout.splitlines() if PLACE_ERROR.match(line)]
    assert errors, result.output
    assert all(line.startswith("broken.md ") for line in errors), errors
    assert "Build failed" in result.stdout


def test_snapshot_cli(tmp_path):
    root = make_site_root(tmp_path)
    media = tmp_path / "media" / "img" / "food"
    media.mkdir(parents=True)
    (media / "x.jpg").write_bytes(b"jpg")
    with pytest.MonkeyPatch.context() as mp:
        mp.chdir(root)
        result = CliRunner().invoke(
            build_vilf,
            ["--snapshot", str(SNAPSHOT), "--out", str(tmp_path / "out"), "--copy-media", str(tmp_path / "media")],
            catch_exceptions=False,
        )
    assert result.exit_code == 0, result.output
    assert "5 open, 1 closed" in result.output
    assert (tmp_path / "out" / "places" / "gone-place" / "index.html").is_file()
    assert (tmp_path / "out" / "img" / "food" / "x.jpg").read_bytes() == b"jpg"
