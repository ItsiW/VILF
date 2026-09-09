"""Offline tests for scripts/places.py against hand-written Places API (New) fixtures."""

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.places as places
from scripts.places import CONTACT_FIELDS, CORE_FIELDS, Place, PlacesError, get_place, parse_place, search_text

FIXTURES = Path(__file__).parent / "fixtures" / "places"


def load(name):
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def capture(monkeypatch):
    """Replace places._request with a fake that records its args and returns capture.response."""
    cap = SimpleNamespace(calls=[], response={})

    def fake_request(method, path, *, body=None, field_mask):
        cap.calls.append({"method": method, "path": path, "body": body, "field_mask": field_mask})
        return cap.response

    monkeypatch.setattr(places, "_request", fake_request)
    return cap


def test_parse_place_full_fixture():
    data = load("details_full.json")
    p = parse_place(data)
    assert isinstance(p, Place)
    assert p.place_id == "ChIJfixtureLionDance"
    assert p.name == "Lion Dance Cafe"
    assert p.street_address == "380 17th St"  # route shortText, not '17th Street'
    assert p.city == "Oakland"
    assert p.state == "CA"
    assert p.postal_code == "94612"
    assert p.lat == 37.8061
    assert p.lon == -122.2683
    assert p.phone == "+15105550199"
    assert p.website == "https://example.com/lion-dance"
    assert p.business_status == "OPERATIONAL"
    assert p.maps_url == "https://maps.google.com/?cid=1"
    assert p.hours == data["regularOpeningHours"]["weekdayDescriptions"]
    assert len(p.hours) == 7
    assert p.price_level == "PRICE_LEVEL_MODERATE"
    assert p.types == ["vegan_restaurant", "restaurant", "food", "point_of_interest", "establishment"]
    assert p.raw is data


def test_phone_falls_back_to_national():
    data = copy.deepcopy(load("details_full.json"))
    del data["internationalPhoneNumber"]
    assert parse_place(data).phone == "+15105550199"
    data["nationalPhoneNumber"] = "1 (510) 555-0199"
    assert parse_place(data).phone == "+15105550199"


def test_closed_place_missing_fields_are_none():
    p = parse_place(load("details_closed.json"))
    assert p.business_status == "CLOSED_PERMANENTLY"
    assert p.phone is None
    assert p.website is None
    assert p.hours is None
    assert p.price_level is None
    assert p.name == "Shuttered Vegan Diner"
    assert p.street_address == "1234 Mission St"


def test_street_address_falls_back_to_formatted_address():
    data = copy.deepcopy(load("details_full.json"))
    data["addressComponents"] = [c for c in data["addressComponents"] if "route" not in c["types"]]
    # distinct from the component path so this proves the fallback ran
    data["formattedAddress"] = "380 Seventeenth St, Oakland, CA 94612, USA"
    assert parse_place(data).street_address == "380 Seventeenth St"

    data["addressComponents"] = []
    assert parse_place(data).street_address == "380 Seventeenth St"

    del data["formattedAddress"]
    assert parse_place(data).street_address is None

    data = copy.deepcopy(load("details_full.json"))
    for c in data["addressComponents"]:
        if "route" in c["types"]:
            del c["shortText"]
    assert parse_place(data).street_address == "380 17th Street"


def test_city_fallback_chain():
    data = copy.deepcopy(load("details_full.json"))
    locality = next(c for c in data["addressComponents"] if "locality" in c["types"])
    assert parse_place(data).city == "Oakland"

    locality["types"] = ["postal_town"]
    locality["longText"] = "Oaktown"
    assert parse_place(data).city == "Oaktown"

    locality["types"] = ["sublocality_level_1", "sublocality", "political"]
    locality["longText"] = "Uptown"
    assert parse_place(data).city == "Uptown"

    locality["types"] = ["neighborhood", "political"]
    assert parse_place(data).city is None


def test_search_text_sends_prefixed_mask_and_bias(capture):
    capture.response = load("search_text.json")
    query = "Lion Dance Cafe Oakland"
    result = search_text(query)
    assert [p.place_id for p in result] == ["ChIJfixtureLionDance", "ChIJfixtureBerkeley"]
    assert all(isinstance(p, Place) for p in result)
    assert result[0].name == "Lion Dance Cafe"

    call = capture.calls[0]
    assert call["method"] == "POST"
    assert call["path"] == "/places:searchText"
    assert call["body"]["textQuery"] == query
    assert call["body"]["pageSize"] == 5
    assert "maxResultCount" not in call["body"]
    rect = call["body"]["locationBias"]["rectangle"]
    for corner in ("low", "high"):
        assert set(rect[corner]) == {"latitude", "longitude"}
    assert rect["low"]["latitude"] < rect["high"]["latitude"]
    assert rect["low"]["longitude"] < rect["high"]["longitude"]
    assert call["field_mask"].split(",") == ["places." + f for f in CORE_FIELDS]

    search_text("x", fields=CONTACT_FIELDS, max_results=3)
    call = capture.calls[1]
    assert call["field_mask"].split(",") == ["places." + f for f in CONTACT_FIELDS]
    assert call["body"]["pageSize"] == 3

    capture.response = {}  # no matches: the API omits the 'places' key
    assert search_text("nothing") == []


def test_get_place_sends_unprefixed_mask(capture):
    capture.response = load("details_full.json")
    p = get_place("ChIJfixtureLionDance", fields=CONTACT_FIELDS)
    assert isinstance(p, Place)
    assert p.place_id == "ChIJfixtureLionDance"
    call = capture.calls[0]
    assert call["method"] == "GET"
    assert call["path"] == "/places/ChIJfixtureLionDance"
    assert call["body"] is None
    assert call["field_mask"] == ",".join(CONTACT_FIELDS)
    assert "places." not in call["field_mask"]

    get_place("ChIJfixtureLionDance")
    assert capture.calls[1]["field_mask"] == ",".join(CORE_FIELDS)


def test_missing_api_key_raises(monkeypatch, tmp_path):
    monkeypatch.delenv("GOOGLE_PLACES_API_KEY", raising=False)
    monkeypatch.setattr(places, "DOTENV_PATH", tmp_path / ".env")
    monkeypatch.setattr(places.requests, "request", lambda *a, **k: pytest.fail("network call attempted"))
    with pytest.raises(PlacesError, match="GOOGLE_PLACES_API_KEY"):
        search_text("x")


def test_non_2xx_raises_with_api_message(monkeypatch, tmp_path):
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "test-key")
    monkeypatch.setattr(places, "DOTENV_PATH", tmp_path / ".env")
    recorded = {}

    def fake_403(method, url, *, headers, json, timeout):
        recorded.update(method=method, url=url, headers=headers, json=json, timeout=timeout)
        return SimpleNamespace(
            ok=False,
            status_code=403,
            text='{"error": ...}',
            json=lambda: {"error": {"code": 403, "message": "The provided API key is invalid.", "status": "PERMISSION_DENIED"}},
        )

    monkeypatch.setattr(places.requests, "request", fake_403)
    with pytest.raises(PlacesError, match="API key is invalid"):
        get_place("abc")
    assert recorded["method"] == "GET"
    assert recorded["url"] == "https://places.googleapis.com/v1/places/abc"
    assert recorded["headers"]["X-Goog-Api-Key"] == "test-key"
    assert recorded["headers"]["X-Goog-FieldMask"] == ",".join(CORE_FIELDS)
    assert recorded["json"] is None
    assert recorded["timeout"] == 15

    def raise_value_error():
        raise ValueError("not json")

    fake_502 = lambda *a, **k: SimpleNamespace(ok=False, status_code=502, text="Bad Gateway", json=raise_value_error)
    monkeypatch.setattr(places.requests, "request", fake_502)
    with pytest.raises(PlacesError, match="502.*Bad Gateway"):
        get_place("abc")
