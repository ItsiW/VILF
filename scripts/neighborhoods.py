"""Offline SF neighborhood suggestions; never changes saved restaurant records."""

from functools import lru_cache
import json
import math
from pathlib import Path

ALIASES = {
    "Mission": "The Mission",
    "Castro": "The Castro",
    "Eureka Valley": "The Castro",
    "Northern Waterfront": "Embarcadero",
    "Aquatic Park / Ft. Mason": "Fort Mason",
    "Lincoln Park / Ft. Miley": "Outer Richmond",
    "Haight Ashbury": "Haight-Ashbury",
    "South of Market": "Soma",
    "Central Waterfront": "Dogpatch",
    "Lower Nob Hill": "Nob Hill",
    "Union Street": "Cow Hollow",
    "Downtown / Union Square": "Union Square",
    "Laurel Heights / Jordan Park": "Laurel Heights",
    "Lower Pacific Heights": "Pac Heights",
    "Pacific Heights": "Pac Heights",
    "Mint Hill": "Hayes Valley",
    "Apparel City": "Bayview",
    "Produce Market": "Bayview",
    "Peralta Heights": "Bernal Heights",
}

# Within each detailed area, use this broader boundary; otherwise the fallback.
AREA_SPLITS = {
    "Upper Market": ("Noe Valley", "Twin Peaks"),
    "University Mound": ("Excelsior", "Portola"),
    "Showplace Square": ("Mission Bay", "Soma"),
}

# NOPNA's Fell–Turk / Divisadero–Masonic core, plus the residential
# Fell–Fulton / Masonic–Stanyan extension. Include ~50 m of Divisadero's
# east-side frontage so businesses across the road get the same area.
# Corners derived from DataSF Street Intersections, gmfx-8h6i.
NOPA_RING = [
    [-122.437010624, 37.774061646], [-122.438140183, 37.779659630],
    [-122.447039806, 37.778622308], [-122.446470830, 37.775801592],
    [-122.454682648, 37.774755484], [-122.454083218, 37.771930404],
    [-122.445902366, 37.772995406], [-122.437010624, 37.774061646],
]


@lru_cache(maxsize=1)
def split_boundaries():
    data = json.loads((Path(__file__).parent / "data/sf-area-splits.geojson").read_text())
    return {f["properties"]["name"]: f for f in data["features"]}


@lru_cache(maxsize=1)
def boundaries():
    data = json.loads((Path(__file__).parent / "data/sf-neighborhoods.geojson").read_text())
    return data["features"]


def in_ring(x, y, ring):
    inside = False
    for (ax, ay), (bx, by) in zip(ring, ring[1:] + ring[:1]):
        # Include edges, with a tiny tolerance for floating-point arithmetic.
        cross = (x - ax) * (by - ay) - (y - ay) * (bx - ax)
        if abs(cross) < 1e-12 and min(ax, bx) <= x <= max(ax, bx) and min(ay, by) <= y <= max(ay, by):
            return True
        if (ay > y) != (by > y) and x < (bx - ax) * (y - ay) / (by - ay) + ax:
            inside = not inside
    return inside


def contains(feature, lon, lat):
    geometry = feature["geometry"]
    polygons = geometry["coordinates"] if geometry.get("type", "MultiPolygon") == "MultiPolygon" else [geometry["coordinates"]]
    return any(in_ring(lon, lat, polygon[0]) and not any(in_ring(lon, lat, hole) for hole in polygon[1:])
               for polygon in polygons)


def suggest_area(lat, lon):
    try:
        lat, lon = float(lat), float(lon)
    except (ValueError, TypeError):
        return None
    if not math.isfinite(lat) or not math.isfinite(lon):
        return None
    # Fast rejection outside SF; the actual decision uses polygon boundaries.
    if not (37.6 <= lat <= 37.9 and -123 <= lon <= -122.3):
        return None
    if in_ring(lon, lat, NOPA_RING):
        return "Nopa"
    for feature in boundaries():
        if contains(feature, lon, lat):
            name = feature["properties"]["name"]
            if name in AREA_SPLITS:
                area, fallback = AREA_SPLITS[name]
                return area if contains(split_boundaries()[area], lon, lat) else fallback
            return ALIASES.get(name, name)
    return None
