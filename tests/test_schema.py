"""Unit tests for scripts/schema.py plus a round-trip over every real place file."""

from datetime import date
from pathlib import Path

import pytest

from scripts.schema import (
    BOOLEAN_LABELS,
    FIELDS,
    KNOWN_KEYS,
    RATING_COLORS,
    TASTE_LABELS,
    VALUE_LABELS,
    dump_frontmatter,
    load_place,
    validate_place,
    validate_unique,
    write_place,
)

PLACES = Path(__file__).resolve().parent.parent / "places"

VALID = dict(
    name="Test Place",
    cuisine="Thai",
    address="1 Main St",
    area="Mission District",
    lat=37.76,
    lon=-122.42,
    phone="+14155551234",
    menu="https://example.com/menu",
    drinks=True,
    visited="2024-03-31",
    taste=2,
    value=1,
    instagram_published=False,
)
BODY = "\nGreat **pad thai**.\n"

A16 = (
    "---\n"
    "name: A16\n"
    "cuisine: Italian\n"
    "address: 1 Ferry Plaza\n"
    "area: Embarcadero\n"
    "lat: 37.7956450774278\n"
    "lon: -122.3935883506244\n"
    "phone: \n"
    "menu: \n"
    "drinks: False\n"
    'visited: "2024-03-31"\n'
    "taste: 1\n"
    "value: 1\n"
    "instagram_published: True\n"
    "---\n"
    "\n"
    "Get the **Marinara pizza**.\n"
)


def test_constants():
    assert TASTE_LABELS == ["DNR", "SGFI", "Good", "Phenomenal"]
    assert VALUE_LABELS == ["Bad", "Fine", "Good", "Phenomenal"]
    assert BOOLEAN_LABELS == ["Nah", "Yeah"]
    assert len(RATING_COLORS) == 4
    assert KNOWN_KEYS == [
        "name", "cuisine", "address", "area", "lat", "lon", "phone", "menu",
        "drinks", "visited", "taste", "value", "instagram_published",
        "city", "place_id", "website",
    ]
    required = {f.name for f in FIELDS if f.required}
    assert required == {
        "name", "cuisine", "address", "area", "lat", "lon", "drinks", "visited", "taste", "value"
    }


def test_valid_place_has_no_problems():
    assert validate_place(VALID, BODY, "test-place") == []
    extended = {**VALID, "city": "Oakland", "place_id": "ChIJabc123", "website": "https://x.example"}
    assert validate_place(extended, BODY, "test-place") == []


REQUIRED_MISSING = [
    ({key: bad}, key)
    for key in ["name", "cuisine", "address", "area", "lat", "lon", "drinks", "visited", "taste", "value"]
    for bad in [None, ""]
]


@pytest.mark.parametrize(
    "changes, needle",
    REQUIRED_MISSING
    + [
        ({"bogus": 1}, "unknown key"),
        ({"lat": 91}, "lat"),
        ({"lon": -181}, "lon"),
        ({"lat": "37"}, "lat"),
        ({"lat": True}, "lat"),
        ({"phone": "415-555-1234"}, "phone"),
        ({"phone": "+1415555123"}, "phone"),
        ({"menu": "example.com"}, "menu"),
        ({"website": "ftp://x"}, "website"),
        ({"drinks": "yes"}, "drinks"),
        ({"visited": "31/03/2024"}, "visited"),
        ({"visited": date(2024, 3, 31)}, "visited"),
        ({"taste": 4}, "taste"),
        ({"taste": "2"}, "taste"),
        ({"taste": True}, "taste"),
        ({"value": -1}, "value"),
        ({"instagram_published": "no"}, "instagram_published"),
    ],
)
def test_validate_place_reports(changes, needle):
    problems = validate_place({**VALID, **changes}, BODY, "test-place")
    assert any(needle in p for p in problems), problems


def test_bad_slug():
    for slug in ["Bad Slug", "Café"]:
        assert any("slug" in p for p in validate_place(VALID, BODY, slug)), slug
    assert not any("slug" in p for p in validate_place(VALID, BODY, "a16"))


def test_bold_dish_required_when_tasty():
    problems = validate_place({**VALID, "taste": 2}, "\nno bold\n", "x")
    assert any("**" in p for p in problems), problems
    assert validate_place({**VALID, "taste": 0}, "\nno bold\n", "x") == []
    problems = validate_place({**VALID, "taste": 1}, "\nlone ** marker\n", "x")
    assert any("**" in p for p in problems), problems


def test_load_place_strips_whitespace_and_defaults(tmp_path):
    p = tmp_path / "foo.md"
    p.write_text(
        "---\n"
        "name: Foo \n"
        'cuisine: "Taiwanese "\n'
        "address: 1 Main St\n"
        "area: Emeryville \n"
        "lat: 37.8\n"
        "lon: -122.3\n"
        "phone: \n"
        "menu: \n"
        "drinks: True\n"
        'visited: "2024-01-01"\n'
        "taste: 1\n"
        "value: 1\n"
        "---\n"
        "\nBody **dish**\n"
    )
    meta, body = load_place(p)
    assert meta["name"] == "Foo"
    assert meta["cuisine"] == "Taiwanese"
    assert meta["area"] == "Emeryville"
    assert meta["phone"] is None
    assert meta["menu"] is None
    assert meta["instagram_published"] is False
    assert meta["city"] is None
    assert meta["place_id"] is None
    assert meta["website"] is None
    assert body == "\nBody **dish**\n"
    assert validate_place(meta, body, "foo") == []


def test_load_place_turns_empty_strings_into_none(tmp_path):
    # `phone: ""` must mean the same as `phone: ` so the build and validate_unique see None
    p = tmp_path / "empty.md"
    p.write_text(
        "---\n"
        'name: ""\n'
        "cuisine: Thai\n"
        "address: 1 Main St\n"
        "area: Mission District\n"
        "lat: 37.8\n"
        "lon: -122.3\n"
        'phone: ""\n'
        'menu: "  "\n'
        "drinks: True\n"
        'visited: "2024-01-01"\n'
        "taste: 1\n"
        "value: 1\n"
        'website: ""\n'
        "---\n"
        "\nBody **dish**\n"
    )
    meta, body = load_place(p)
    assert meta["name"] is None
    assert meta["phone"] is None
    assert meta["menu"] is None
    assert meta["website"] is None
    problems = validate_place(meta, body, "empty")
    assert problems == ["name: required"], problems
    # two places with empty phone/menu are not duplicates of each other
    a = {**meta, "name": "A", "slug": "a", "blurb": "a"}
    b = {**meta, "name": "B", "slug": "b", "blurb": "b", "lat": 1.0, "lon": 2.0}
    assert validate_unique([a, b]) == []


def test_load_place_body_may_contain_dashes(tmp_path):
    body = "\nintro\n\n---\n\noutro **dish**\n\n---\nmore\n"
    p = tmp_path / "dashes.md"
    write_place(p, VALID, body)
    meta, got = load_place(p)
    assert got == body
    assert meta["name"] == "Test Place"
    assert meta["instagram_published"] is False
    assert validate_place(meta, got, "dashes") == []


def test_load_place_rejects_missing_frontmatter(tmp_path):
    p = tmp_path / "nofm.md"
    p.write_text("name: x\n\nbody\n")
    with pytest.raises(ValueError):
        load_place(p)
    p.write_text("---\n- not\n- a mapping\n---\n\nbody\n")
    with pytest.raises(ValueError):
        load_place(p)


def test_dump_frontmatter_order_and_quoting():
    meta = {
        "website": "https://x.example",
        "visited": "2024-03-31",
        "taste": 2,
        "phone": None,
        "name": "Panchitas Restaurant #2",
        "lon": -122.42,
        "city": "Oakland",
        "instagram_published": False,
        "menu": None,
        "drinks": True,
        "address": "Suite: B",
        "value": 1,
        "place_id": None,
        "area": "Mission District",
        "lat": 37.7956450774278,
        "cuisine": "Thai",
    }
    expected = (
        'name: "Panchitas Restaurant #2"\n'
        "cuisine: Thai\n"
        'address: "Suite: B"\n'
        "area: Mission District\n"
        "lat: 37.7956450774278\n"
        "lon: -122.42\n"
        "phone: \n"
        "menu: \n"
        "drinks: True\n"
        'visited: "2024-03-31"\n'
        "taste: 2\n"
        "value: 1\n"
        "instagram_published: False\n"
        "city: Oakland\n"
        "website: https://x.example\n"
    )
    assert dump_frontmatter(meta) == expected

    # no new keys -> exactly the original 13 lines
    assert len(dump_frontmatter(VALID).splitlines()) == 13

    def name_line(name):
        return dump_frontmatter({**VALID, "name": name}).splitlines()[0]

    assert name_line("Azalina's") == "name: Azalina's"
    assert name_line("Ladle & Leaf") == "name: Ladle & Leaf"
    assert name_line("yes") == 'name: "yes"'
    assert name_line("12") == 'name: "12"'

    # phone is always quoted
    assert 'phone: "+14155551234"' in dump_frontmatter(VALID)


def test_dump_frontmatter_rejects_unknown_keys():
    with pytest.raises(ValueError):
        dump_frontmatter({**VALID, "slug": "x"})


def test_write_place_reproduces_canonical_file(tmp_path):
    src = tmp_path / "a16.md"
    src.write_text(A16)
    meta, body = load_place(src)
    out = tmp_path / "a16-copy.md"
    write_place(out, meta, body)
    assert out.read_bytes() == A16.encode()


@pytest.mark.parametrize("path", sorted(PLACES.glob("*.md")), ids=lambda p: p.name)
def test_round_trip_every_place(path, tmp_path):
    meta, body = load_place(path)
    assert validate_place(meta, body, path.stem) == []
    tmp = tmp_path / path.name
    write_place(tmp, meta, body)
    meta2, body2 = load_place(tmp)
    assert meta2 == meta
    assert body2 == body


def test_validate_unique():
    def place(slug, **overrides):
        return {**VALID, "slug": slug, "blurb": f"blurb {slug}", **overrides}

    a = place("a", name="A", lat=1.0, lon=2.0, phone="+14155550001", menu="https://a.example")
    b = place("b", name="B", lat=3.0, lon=4.0, phone="+14155550002", menu="https://b.example")
    assert validate_unique([a, b]) == []

    assert any("name" in p for p in validate_unique([a, place("c", name="A", lat=5.0, lon=6.0, phone=None, menu=None)]))
    assert any("coordinates" in p for p in validate_unique([a, place("c", name="C", lat=1.0, lon=2.0, phone=None, menu=None)]))
    # same latitude but a different longitude is legal
    assert validate_unique([a, place("c", name="C", lat=1.0, lon=9.0, phone=None, menu=None)]) == []
    # None phone/menu on two places is not a duplicate
    assert validate_unique([
        place("c", name="C", lat=5.0, lon=6.0, phone=None, menu=None),
        place("d", name="D", lat=7.0, lon=8.0, phone=None, menu=None),
    ]) == []
    assert any("phone" in p for p in validate_unique([a, place("c", name="C", lat=5.0, lon=6.0, phone="+14155550001", menu=None)]))
    assert any("blurb" in p for p in validate_unique([a, {**place("c", name="C", lat=5.0, lon=6.0, phone=None, menu=None), "blurb": "blurb a"}]))
