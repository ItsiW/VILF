from datetime import date
from html.parser import HTMLParser
import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
import pytest

from scripts.render import enrich_place, format_description, format_title, render_place_page


def review(**changes):
    return dict(name="Udon Mugizo", cuisine="Japanese", city="San Francisco",
                area="Japantown", taste=1, visited="2023-09-26", closed=False) | changes


def test_review_metadata_uses_specific_recorded_facts():
    meta = review(body="**Not a dish name**")
    assert format_title(meta) == "Udon Mugizo: Vegan Japanese review, San Francisco | VILF"
    assert format_description(meta) == (
        "Vegan Japanese food review of Udon Mugizo in Japantown, San Francisco. "
        "Rated Something Going For It for taste. Visited September 2023."
    )


@pytest.mark.parametrize("taste,label", list(enumerate([
    "Do Not Recommend", "Something Going For It", "Good", "Phenomenal",
])))
def test_description_preserves_each_taste_rating(taste, label):
    assert f"Rated {label} for taste." in format_description(review(taste=taste))


def test_closed_and_missing_fields_do_not_invent_facts():
    meta = review(city=None, closed=True, cuisine=None, visited=None, taste=None)
    assert format_title(meta) == "Udon Mugizo (closed): Vegan review, Japantown | VILF"
    assert format_description(meta) == (
        "Permanently closed. Archived vegan food review of Udon Mugizo in Japantown."
    )
    meta = review(city=None, area=None)
    assert format_title(meta) == "Udon Mugizo: Vegan Japanese review | VILF"
    assert " in " not in format_description(meta)


def test_description_does_not_repeat_city_as_neighborhood():
    assert "in San Francisco." in format_description(review(area="San Francisco"))
    assert "San Francisco, San Francisco" not in format_description(review(area="San Francisco"))


def test_metadata_is_escaped_and_consistent_across_channels():
    root = Path(__file__).resolve().parents[1]
    row = json.loads((root / "tests/fixtures/snapshot.json").read_text())[0]
    row["name"] = 'A "quoted" & <special> restaurant'
    place = enrich_place(row, today=date(2026, 9, 13))
    env = Environment(loader=FileSystemLoader(root / "html"))
    env.globals["SITE_URL"] = "https://vilf.org"
    output = render_place_page(env, place)

    class Metadata(HTMLParser):
        def __init__(self):
            super().__init__()
            self.values = {}

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == "meta":
                self.values[attrs.get("name", attrs.get("property"))] = attrs.get("content")

    parser = Metadata()
    parser.feed(output)
    for key in ("title", "og:title", "twitter:title"):
        assert parser.values[key] == format_title(place)
    for key in ("description", "og:description", "twitter:description"):
        assert parser.values[key] == format_description(place)
    assert '&lt;special&gt;' in output.split('</title>')[0]
