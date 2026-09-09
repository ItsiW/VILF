"""Smoke test: run the real site build against the repo's places/ and check its outputs."""

import json
import re
from pathlib import Path

import pytest
from click.testing import CliRunner

from scripts.build import build_vilf

REPO_ROOT = Path(__file__).resolve().parent.parent

# build.py reports a broken place with `print(place_md.name, e)` -> "<slug>.md <error>"
PLACE_ERROR = re.compile(r"^.+\.md( |$)")


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
