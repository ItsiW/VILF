"""Smoke test: run the real site build against the repo's places/ and check its outputs."""

import json
import re
from pathlib import Path

import pytest
from click.testing import CliRunner

from scripts.build import SITE_URL, build_vilf

REPO_ROOT = Path(__file__).resolve().parent.parent

# build.py reports a broken place with `print(place_md.name, e)` -> "<slug>.md <error>"
PLACE_ERROR = re.compile(r"^.+\.md( |$)")

PLACES_JSON_KEYS = {
    "name", "slug", "url", "cuisine", "area", "city", "address", "lat", "lon",
    "taste", "taste_label", "value", "value_label", "drinks", "visited",
    "phone", "menu", "website", "image",
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


def test_geojson_feature_count_matches_places(build_result):
    n_md = len(list((REPO_ROOT / "places").glob("*.md")))
    n_built = len(list((REPO_ROOT / "build").glob("places/*/index.html")))
    features = json.loads((REPO_ROOT / "build" / "places.geojson").read_text())["features"]
    assert len(features) == n_built == n_md


def test_llms_txt_lists_every_place(build_result):
    text = (REPO_ROOT / "build" / "llms.txt").read_text(encoding="utf-8")
    assert text.startswith("# Vegans In Love with Food")
    for slug in place_slugs():
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
