"""Smoke test: run the real site build against the repo's places/ and check its outputs."""

import json
import re
from datetime import date
from pathlib import Path

import pytest
from click.testing import CliRunner

from scripts.build import SITE_URL, build_vilf, git_modified_dates, parse_git_dates
from scripts.schema import load_place

REPO_ROOT = Path(__file__).resolve().parent.parent

# build.py reports a broken place with `print(place_md.name, e)` -> "<slug>.md <error>"
PLACE_ERROR = re.compile(r"^.+\.md( |$)")

PLACES_JSON_KEYS = {
    "name", "slug", "url", "cuisine", "area", "city", "address", "lat", "lon",
    "taste", "taste_label", "value", "value_label", "drinks", "visited", "modified",
    "phone", "menu", "website", "image", "closed",
}


def place_slugs():
    return sorted(p.stem for p in (REPO_ROOT / "places").glob("*.md"))


@pytest.fixture(scope="module")
def build_result():
    # build.py uses cwd-relative paths (places/, html/, static/, build/), so run from the repo root
    with pytest.MonkeyPatch.context() as mp:
        mp.chdir(REPO_ROOT)
        return CliRunner().invoke(build_vilf, [], catch_exceptions=False)


def test_build_succeeds_without_place_errors(build_result):
    assert build_result.exit_code == 0, build_result.output
    errors = [line for line in build_result.stdout.splitlines() if PLACE_ERROR.match(line)]
    assert not errors, "places failed to build:\n" + "\n".join(errors)


def test_build_outputs_exist(build_result):
    build = REPO_ROOT / "build"
    for name in ["index.html", "places.geojson", "sitemap.xml", "best/index.html"]:
        assert (build / name).is_file(), name
    assert list(build.glob("places/*/index.html"))


def open_slugs():
    from scripts.schema import load_place

    return [p.stem for p in sorted((REPO_ROOT / "places").glob("*.md")) if not load_place(p)[0].get("closed")]


def test_geojson_feature_count_matches_places(build_result):
    # every review gets a page; only open ones are on the map
    n_md = len(list((REPO_ROOT / "places").glob("*.md")))
    n_built = len(list((REPO_ROOT / "build").glob("places/*/index.html")))
    features = json.loads((REPO_ROOT / "build" / "places.geojson").read_text())["features"]
    assert n_built == n_md
    assert len(features) == len(open_slugs())


def test_llms_txt_lists_every_place(build_result):
    text = (REPO_ROOT / "build" / "llms.txt").read_text(encoding="utf-8")
    assert text.startswith("# Vegans In Love with Food")
    for slug in open_slugs():
        assert f"{SITE_URL}/places/{slug}/" in text, slug


def test_llms_full_contains_review_dish(build_result):
    # first review (alphabetically) with a **bolded dish**; avoids hardcoding a restaurant
    for path in sorted((REPO_ROOT / "places").glob("*.md")):
        match = re.search(r"\*\*.+?\*\*", path.read_text(encoding="utf-8"))
        if match:
            break
    else:
        pytest.skip("no review with a bolded dish")
    full = (REPO_ROOT / "build" / "llms-full.txt").read_text(encoding="utf-8")
    assert match.group(0) in full, (path.name, match.group(0))


def test_places_json(build_result):
    build = REPO_ROOT / "build"
    data = json.loads((build / "places.json").read_text(encoding="utf-8"))
    assert isinstance(data, list)
    assert len(data) == len(list(build.glob("places/*/index.html")))
    assert set(data[0]) == PLACES_JSON_KEYS


def test_place_markdown_files(build_result):
    for slug in place_slugs():
        assert (REPO_ROOT / "build" / "places" / f"{slug}.md").is_file(), slug


def test_place_page_has_verdict_and_markdown_alternate(build_result):
    slug = place_slugs()[0]
    page = (REPO_ROOT / "build" / "places" / slug / "index.html").read_text(encoding="utf-8")
    assert "Verdict:" in page
    assert f'<link rel="alternate" type="text/markdown" href="/places/{slug}.md">' in page


def test_robots_welcomes_ai_crawlers(build_result):
    assert "GPTBot" in (REPO_ROOT / "build" / "robots.txt").read_text()


# Inline fixture (not a real places/*.md) so deleting or renaming a restaurant can't break this module.
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


def build_in_tmp_repo(tmp_path, place_files):
    """Run the real build in a scratch repo whose places/ holds only place_files (html/static/raw/about.md are symlinked)."""
    for name in ["html", "static", "raw", "about.md"]:
        (tmp_path / name).symlink_to(REPO_ROOT / name)
    (tmp_path / "places").mkdir()
    for name, text in place_files.items():
        (tmp_path / "places" / name).write_text(text)
    with pytest.MonkeyPatch.context() as mp:
        mp.chdir(tmp_path)
        return CliRunner().invoke(build_vilf, [], catch_exceptions=False)


def test_build_fails_on_invalid_place(tmp_path):
    result = build_in_tmp_repo(
        tmp_path,
        {"test-place.md": PLACE, "broken.md": "---\nname: Broken\ntaste: 9\n---\n\nno metadata\n"},
    )
    assert result.exit_code == 1, result.output
    # tqdm's progress bar goes to stderr with no newline, so match lines on stdout only
    errors = [line for line in result.stdout.splitlines() if PLACE_ERROR.match(line)]
    assert errors, result.output
    assert all(line.startswith("broken.md ") for line in errors), errors
    assert "Build failed" in result.stdout
    assert not any(line.startswith("test-place.md ") for line in result.stdout.splitlines())


def test_build_fails_on_duplicate_place(tmp_path):
    result = build_in_tmp_repo(tmp_path, {"test-place.md": PLACE, "test-place-again.md": PLACE})
    assert result.exit_code == 1, result.output
    assert "name 'Test Place' reused by" in result.stdout
    assert "Build failed" in result.stdout


# SEO markup: JSON-LD blocks, git-derived lastmod, website links

LD_JSON = re.compile(r'<script type="application/ld\+json">\s*(.*?)\s*</script>', re.DOTALL)
SITEMAP_ENTRY = re.compile(r"<loc>([^<]+)</loc>\s*<lastmod>([^<]+)</lastmod>")
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# fabricated schema.org fields the Restaurant block used to emit
REMOVED_LD_KEYS = {
    "aggregateRating", "paymentAccepted", "currenciesAccepted",
    "openingHours", "acceptsReservations", "priceRange",
}


def ld_blocks(page_text):
    """Every JSON-LD block on a page, parsed and keyed by @type."""
    blocks = {}
    for match in LD_JSON.findall(page_text):
        block = json.loads(match)
        blocks[block["@type"]] = block
    return blocks


def test_place_json_ld(build_result):
    for slug in place_slugs():
        meta, _ = load_place(REPO_ROOT / "places" / f"{slug}.md")
        page = (REPO_ROOT / "build" / "places" / slug / "index.html").read_text(encoding="utf-8")
        blocks = ld_blocks(page)  # raises if any block is not valid JSON
        assert set(blocks) == {"Restaurant", "Article", "BreadcrumbList"}, slug
        restaurant, article = blocks["Restaurant"], blocks["Article"]
        assert not REMOVED_LD_KEYS & set(restaurant), slug
        locality = meta["city"] or meta["area"]
        assert restaurant["address"]["addressLocality"] == locality, slug
        assert article["about"]["address"]["addressLocality"] == locality, slug
        assert restaurant["review"]["datePublished"] == article["datePublished"] == meta["visited"], slug
        assert ISO_DATE.match(article["dateModified"]), slug
        date.fromisoformat(article["dateModified"])
        if meta["website"]:
            assert restaurant["sameAs"] == meta["website"], slug
        else:
            assert "sameAs" not in restaurant, slug


def test_sitemap_place_lastmod_from_git(build_result):
    with pytest.MonkeyPatch.context() as mp:
        mp.chdir(REPO_ROOT)
        git_dates = git_modified_dates()
    sitemap = (REPO_ROOT / "build" / "sitemap.xml").read_text(encoding="utf-8")
    lastmods = dict(SITEMAP_ENTRY.findall(sitemap))
    for slug in place_slugs():
        meta, _ = load_place(REPO_ROOT / "places" / f"{slug}.md")
        lastmod = lastmods[f"{SITE_URL}/places/{slug}/"]
        assert ISO_DATE.match(lastmod), slug
        assert lastmod == git_dates.get(f"places/{slug}.md", meta["visited"]), slug
    # the old build clamped every place to this date; it must only appear if it is a real commit date
    if "2025-02-15" not in git_dates.values():
        clamped = [url for url, lastmod in lastmods.items() if "/places/" in url and lastmod == "2025-02-15"]
        assert not clamped, clamped


def test_places_json_modified(build_result):
    data = json.loads((REPO_ROOT / "build" / "places.json").read_text(encoding="utf-8"))
    for entry in data:
        assert ISO_DATE.match(entry["modified"]), entry["slug"]


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


PLACE_WITH_LINKS = (
    PLACE.replace("phone: \n", 'phone: "+14155551234"\n')
    .replace("menu: \n", "menu: https://example.com/menu\n")
    .replace("instagram_published: False\n", "instagram_published: False\nwebsite: https://example.com\n")
)

WEB_ONLY = (
    "---\n"
    "name: Web Only\n"
    "cuisine: Thai\n"
    "address: 2 Main St\n"
    "area: Mission District\n"
    "lat: 37.77\n"
    "lon: -122.43\n"
    "phone: \n"
    "menu: \n"
    "drinks: False\n"
    'visited: "2024-04-01"\n'
    "taste: 1\n"
    "value: 2\n"
    "instagram_published: False\n"
    "website: https://example.org\n"
    "---\n"
    "\n"
    "Try the **green curry**, it is different enough.\n"
)


def test_menu_link_fallback_and_git_dates(tmp_path):
    result = build_in_tmp_repo(tmp_path, {"test-place.md": PLACE_WITH_LINKS, "web-only.md": WEB_ONLY})
    assert result.exit_code == 0, result.output
    page = (tmp_path / "build" / "places" / "test-place" / "index.html").read_text(encoding="utf-8")
    # menu present: the Menu link goes to the menu page; there is never a separate Website link
    assert (
        '<a href="https://example.com/menu" target="_blank">Menu</a> | <a href="tel:+14155551234">'
    ) in re.sub(r"\s+", " ", page)
    assert "Website</a>" not in page
    blocks = ld_blocks(page)
    assert blocks["Restaurant"]["sameAs"] == "https://example.com"
    # tmp_path is not a git repo, so `modified` falls back to the visited date everywhere
    assert blocks["Article"]["dateModified"] == "2024-03-31"
    sitemap = (tmp_path / "build" / "sitemap.xml").read_text(encoding="utf-8")
    assert re.search(
        rf"<loc>{SITE_URL}/places/test-place/</loc>\s*<lastmod>2024-03-31</lastmod>", sitemap
    )
    data = {entry["slug"]: entry for entry in json.loads((tmp_path / "build" / "places.json").read_text())}
    assert data["test-place"]["modified"] == "2024-03-31"
    assert data["web-only"]["modified"] == "2024-04-01"
    # no menu: the Menu link falls back to the website; no phone, so no separators
    web_only = re.sub(r"\s+", " ", (tmp_path / "build" / "places" / "web-only" / "index.html").read_text())
    links = re.search(r'<p class="restaurant-links">(.*?)</p>', web_only).group(1)
    assert '<a href="https://example.org" target="_blank">Menu</a>' in links
    assert "|" not in links and "Website" not in links and "tel:" not in links


def test_closed_place_keeps_page_but_leaves_lists(tmp_path):
    closed = (
        PLACE.replace("name: Test Place", "name: Gone Place")
        .replace("lat: 37.76\n", "lat: 37.70\n")
        .replace("instagram_published: False\n", "instagram_published: False\nclosed: True\n")
        .replace("Get the **pad thai**.", "It had a great **larb** once.")
    )
    result = build_in_tmp_repo(tmp_path, {"test-place.md": PLACE, "gone-place.md": closed})
    assert result.exit_code == 0, result.output
    assert "1 open, 1 closed" in result.output
    build = tmp_path / "build"
    page = (build / "places" / "gone-place" / "index.html").read_text()
    assert "Permanently closed." in page
    assert "Permanently closed." not in (build / "places" / "test-place" / "index.html").read_text()
    features = json.loads((build / "places.geojson").read_text())["features"]
    assert [f["properties"]["name"] for f in features] == ["Test Place"]
    best = (build / "best" / "index.html").read_text()
    assert "Test Place" in best and "Gone Place" not in best
    assert "Gone Place" not in (build / "llms.txt").read_text()
    data = {p["slug"]: p for p in json.loads((build / "places.json").read_text())}
    assert data["gone-place"]["closed"] is True and data["test-place"]["closed"] is False
    assert "- Status: permanently closed" in (build / "places" / "gone-place.md").read_text()
    assert "/places/gone-place/" in (build / "sitemap.xml").read_text()


def test_llms_txt_links_markdown_and_escapes_brackets(tmp_path):
    bracketed = PLACE.replace("name: Test Place", "name: Test [Place]")
    result = build_in_tmp_repo(tmp_path, {"test-place.md": bracketed})
    assert result.exit_code == 0, result.output
    text = (tmp_path / "build" / "llms.txt").read_text()
    assert "- [Test \\[Place\\]](" in text
    assert f"[markdown]({SITE_URL}/places/test-place.md)" in text
