"""
Small client for the Google Places API (New) REST endpoints.

Pure data access: no prompting, no markdown writing. Billing is decided by the
most expensive field in the X-Goog-FieldMask header, so masks are explicit and
minimal; use CONTACT_FIELDS (Enterprise SKU) only when you need contact info.

    uv run python -m scripts.places 'Lion Dance Cafe Oakland' [--details] [--id PLACE_ID]

The API key is read from GOOGLE_PLACES_API_KEY (a .env at the repo root works).
"""

import argparse
import json
import math
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

import requests
from dotenv import load_dotenv

BASE_URL = "https://places.googleapis.com/v1"
API_KEY_ENV = "GOOGLE_PLACES_API_KEY"
DOTENV_PATH = Path(__file__).resolve().parent.parent / ".env"
TIMEOUT = 15

# Bias (not restriction): out-of-area places still resolve, Bay Area ones rank first.
BAY_AREA_BIAS = {
    "rectangle": {
        "low": {"latitude": 37.2, "longitude": -122.8},
        "high": {"latitude": 38.2, "longitude": -121.7},
    }
}

# Billed at the Pro SKU on both endpoints. (Place Details: id/formattedAddress/
# addressComponents/location/types are Essentials, displayName/businessStatus/
# googleMapsUri/primaryType are Pro; Text Search: everything except id is Pro.)
CORE_FIELDS: tuple[str, ...] = (
    "id",
    "displayName",
    "formattedAddress",
    "addressComponents",
    "location",
    "businessStatus",
    "googleMapsUri",
    "types",
    "primaryType",
)

# Enterprise SKU on both endpoints; only request when the caller needs contact info.
CONTACT_FIELDS: tuple[str, ...] = CORE_FIELDS + (
    "nationalPhoneNumber",
    "internationalPhoneNumber",
    "websiteUri",
    "regularOpeningHours",
    "priceLevel",
)


class PlacesError(Exception):
    pass


@dataclass
class Place:
    place_id: str
    name: str | None
    street_address: str | None
    city: str | None
    state: str | None
    postal_code: str | None
    lat: float | None
    lon: float | None
    phone: str | None  # E.164, e.g. '+14155551234'
    website: str | None
    business_status: str | None  # OPERATIONAL / CLOSED_TEMPORARILY / CLOSED_PERMANENTLY
    maps_url: str | None
    hours: list[str] | None  # regularOpeningHours.weekdayDescriptions
    price_level: str | None
    types: list[str]
    raw: dict = field(repr=False, compare=False)


def _component(components: list[dict], type_: str, key: str = "longText") -> str | None:
    for comp in components:
        if type_ in comp.get("types", []):
            return comp.get(key)
    return None


def _e164(international: str | None, national: str | None) -> str | None:
    if international:
        digits = re.sub(r"\D", "", international)
        return "+" + digits if digits else None
    if national:
        digits = re.sub(r"\D", "", national)
        if not digits:
            return None
        if len(digits) == 11 and digits.startswith("1"):
            return "+" + digits
        return "+1" + digits
    return None


def parse_place(data: dict) -> Place:
    """Map one Places API place object onto a Place. Pure; never touches the network."""
    comps = data.get("addressComponents", [])
    number = _component(comps, "street_number")
    # shortText gives '17th St', matching the site's address convention
    route = _component(comps, "route", "shortText") or _component(comps, "route")
    if route:
        street_address = " ".join(x for x in (number, route) if x)
    else:
        street_address = data.get("formattedAddress", "").split(",")[0].strip() or None
    city = None
    for type_ in ("locality", "postal_town", "sublocality_level_1"):
        city = _component(comps, type_)
        if city:
            break
    loc = data.get("location") or {}
    return Place(
        place_id=data["id"],
        name=(data.get("displayName") or {}).get("text"),
        street_address=street_address,
        city=city,
        state=_component(comps, "administrative_area_level_1", "shortText"),
        postal_code=_component(comps, "postal_code"),
        lat=loc.get("latitude"),
        lon=loc.get("longitude"),
        phone=_e164(data.get("internationalPhoneNumber"), data.get("nationalPhoneNumber")),
        website=data.get("websiteUri"),
        business_status=data.get("businessStatus"),
        maps_url=data.get("googleMapsUri"),
        hours=(data.get("regularOpeningHours") or {}).get("weekdayDescriptions") or None,
        price_level=data.get("priceLevel"),
        types=list(data.get("types", [])),
        raw=data,
    )


def distance_m(lat1, lon1, lat2, lon2) -> float:
    """Equirectangular approximation in metres; fine for the sub-kilometre radii used here."""
    x = math.radians(lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2))
    y = math.radians(lat2 - lat1)
    return 6371000 * math.hypot(x, y)


def _api_key() -> str:
    load_dotenv(DOTENV_PATH)  # override=False: a real shell var wins over .env
    key = os.environ.get(API_KEY_ENV)
    if not key:
        raise PlacesError(
            f"Missing Google Places API key: set {API_KEY_ENV} in your environment or in {DOTENV_PATH}"
        )
    return key


def _request(method: str, path: str, *, body: dict | None = None, field_mask: str) -> dict:
    """The single HTTP chokepoint. Raises PlacesError on any failure."""
    headers = {"X-Goog-Api-Key": _api_key(), "X-Goog-FieldMask": field_mask}
    try:
        resp = requests.request(method, BASE_URL + path, headers=headers, json=body, timeout=TIMEOUT)
    except requests.RequestException as e:
        raise PlacesError(f"Places API request failed: {e}") from e
    if not resp.ok:
        try:
            message = resp.json()["error"]["message"]
        except (ValueError, KeyError, TypeError):
            message = resp.text[:300]
        raise PlacesError(f"Places API {resp.status_code}: {message}")
    return resp.json()


def search_text(query: str, *, max_results: int = 5, fields=CORE_FIELDS) -> list[Place]:
    """Text Search biased to the SF Bay Area. The mask needs a 'places.' prefix here."""
    # pageSize replaces the deprecated maxResultCount
    body = {"textQuery": query, "locationBias": BAY_AREA_BIAS, "pageSize": max_results}
    mask = ",".join("places." + f for f in fields)
    data = _request("POST", "/places:searchText", body=body, field_mask=mask)
    return [parse_place(p) for p in data.get("places", [])]


def get_place(place_id: str, *, fields=CORE_FIELDS) -> Place:
    return parse_place(_request("GET", f"/places/{place_id}", field_mask=",".join(fields)))


def _main(argv=None):
    parser = argparse.ArgumentParser(description="Query the Google Places API (New).")
    parser.add_argument("query", nargs="?", help="text search query")
    parser.add_argument("--details", action="store_true", help="fetch CONTACT fields for the first result")
    parser.add_argument("--id", help="look up a place id directly instead of searching")
    args = parser.parse_args(argv)
    try:
        if args.id:
            places = [get_place(args.id, fields=CONTACT_FIELDS if args.details else CORE_FIELDS)]
        else:
            if not args.query:
                parser.error("query or --id required")
            places = search_text(args.query)
            if args.details and places:
                places = [get_place(places[0].place_id, fields=CONTACT_FIELDS)]
    except PlacesError as e:
        print(e, file=sys.stderr)
        sys.exit(1)
    for p in places:
        d = asdict(p)
        d.pop("raw")
        print(json.dumps(d, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    _main()
