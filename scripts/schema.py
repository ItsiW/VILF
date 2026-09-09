"""Single source of truth for the place/review data model.

Every places/<slug>.md file is a YAML frontmatter block followed by the review
body. This module defines the frontmatter fields once (order, type, required),
the label/colour constants the build uses, and the load/validate/dump helpers.
Only pyyaml and the standard library are used here.
"""

import json
import re
from datetime import date
from pathlib import Path
from typing import NamedTuple

import yaml


class Field(NamedTuple):
    name: str
    type: str  # one of: str, float, int, bool, date, url
    required: bool
    description: str


# Canonical frontmatter order. The first 13 keys are the original schema and are
# always written; the last three are newer optional keys written only when set.
FIELDS: list[Field] = [
    Field("name", "str", True, "restaurant name"),
    Field("cuisine", "str", True, "cuisine label, drives /cuisines/ pages"),
    Field("address", "str", True, "street address"),
    Field("area", "str", True, "neighborhood (not city), drives /neighborhoods/ pages"),
    Field("lat", "float", True, "latitude in degrees, -90..90"),
    Field("lon", "float", True, "longitude in degrees, -180..180"),
    Field("phone", "str", False, 'E.164 US number like "+14155551234"; validated by PHONE_RE'),
    Field("menu", "url", False, "menu URL, http(s)"),
    Field("drinks", "bool", True, "does it serve alcohol"),
    Field("visited", "date", True, 'quoted ISO date string like "2024-03-31"'),
    Field("taste", "int", True, "0..3 index into TASTE_LABELS"),
    Field("value", "int", True, "0..3 index into VALUE_LABELS"),
    Field("instagram_published", "bool", False, "default False; set by the instagram poster"),
    Field("city", "str", False, "new; city name, not yet used by the build"),
    Field("place_id", "str", False, "new; Google Places ID"),
    Field("website", "url", False, "new; restaurant website, http(s)"),
]

KNOWN_KEYS = [f.name for f in FIELDS]
REQUIRED_KEYS = [f.name for f in FIELDS if f.required]
DEFAULTS = {
    f.name: (False if f.name == "instagram_published" else None)
    for f in FIELDS
    if not f.required
}
# The three keys added in 2026 are only written when set, so old files keep their shape.
_ALWAYS_WRITTEN = frozenset(KNOWN_KEYS) - {"city", "place_id", "website"}
_ALWAYS_QUOTED = frozenset({"visited", "phone"})

TASTE_LABELS = ["DNR", "SGFI", "Good", "Phenomenal"]
VALUE_LABELS = ["Bad", "Fine", "Good", "Phenomenal"]
RATING_COLORS = ["#ef422b", "#efa72b", "#32af2d", "#2b9aef"]
FADED_COLOR = "#cecece"
BOOLEAN_LABELS = ["Nah", "Yeah"]
BOOLEAN_COLORS = ["#ef422b", "#2b9aef"]

SLUG_RE = r"^[0-9a-z-]+$"
PHONE_RE = r"^\+1\d{10}$"

# Only the leading block counts as frontmatter, so a `---` in the body is fine.
_FRONTMATTER_RE = re.compile(r"^---[ \t]*\n(.*?)\n---[ \t]*(?:\n(.*))?\Z", re.DOTALL)
# No DOTALL: build.py extracts dishes with r"\*\*(.*?)\*\*", which does not cross lines.
_BOLD_RE = re.compile(r"\*\*.+?\*\*")


def load_place(path) -> tuple[dict, str]:
    """Read a place file and return (meta, body).

    String values are stripped and empty strings become None (so `phone: ""`
    means the same as `phone: `), missing optional keys get their default, and
    the body is returned verbatim (it starts with the newline after `---`).
    """
    text = Path(path).read_text(encoding="utf-8")
    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError(f"{path}: no leading frontmatter block")
    meta = yaml.safe_load(match.group(1))
    if not isinstance(meta, dict):
        raise ValueError(f"{path}: frontmatter is not a mapping")
    meta = {k: ((v.strip() or None) if isinstance(v, str) else v) for k, v in meta.items()}
    for key, default in DEFAULTS.items():
        meta.setdefault(key, default)
    return meta, match.group(2) or ""


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def validate_place(meta: dict, body: str, slug: str) -> list[str]:
    """Return a list of human-readable problems; empty means valid. Never raises."""
    problems = []
    if not re.match(SLUG_RE, slug):
        problems.append(f"slug: must match {SLUG_RE}, got {slug!r}")
    for key in meta:
        if key not in KNOWN_KEYS:
            problems.append(f"{key}: unknown key")

    for field in FIELDS:
        v = meta.get(field.name)
        if v is None or v == "":
            if field.required:
                problems.append(f"{field.name}: required")
            continue
        if field.type == "str" and not isinstance(v, str):
            problems.append(f"{field.name}: must be a string, got {v!r}")
        elif field.type == "float" and not _is_number(v):
            problems.append(f"{field.name}: must be a number, got {v!r}")
        elif field.type == "int" and not _is_int(v):
            problems.append(f"{field.name}: must be an integer, got {v!r}")
        elif field.type == "bool" and not isinstance(v, bool):
            problems.append(f"{field.name}: must be True or False, got {v!r}")
        elif field.type == "url" and not (
            isinstance(v, str) and v.startswith(("http://", "https://"))
        ):
            problems.append(f"{field.name}: must start with http:// or https://, got {v!r}")
        elif field.type == "date":
            if not isinstance(v, str):
                problems.append(
                    f'{field.name}: must be a quoted ISO date string like "2024-03-31", got {v!r}'
                )
            else:
                try:
                    date.fromisoformat(v)
                except ValueError:
                    problems.append(f"{field.name}: must be an ISO date like 2024-03-31, got {v!r}")

    lat, lon = meta.get("lat"), meta.get("lon")
    if _is_number(lat) and not -90 <= lat <= 90:
        problems.append(f"lat: must be within -90..90, got {lat!r}")
    if _is_number(lon) and not -180 <= lon <= 180:
        problems.append(f"lon: must be within -180..180, got {lon!r}")

    phone = meta.get("phone")
    if isinstance(phone, str) and phone and not re.match(PHONE_RE, phone):
        problems.append(f"phone: must look like +14155551234, got {phone!r}")

    for key in ["taste", "value"]:
        v = meta.get(key)
        if _is_int(v) and not 0 <= v <= 3:
            problems.append(f"{key}: must be 0..3, got {v!r}")

    taste = meta.get("taste")
    if _is_int(taste) and taste >= 1 and not _BOLD_RE.search(body):
        problems.append("taste: highlight a dish in bold (**...**) when taste >= 1")

    return problems


def validate_unique(places: list[dict]) -> list[str]:
    """Cross-place uniqueness: name, menu, phone, blurb and the (lat, lon) pair."""
    problems = []
    checks = ["name", "menu", "phone", "blurb", "coordinates"]
    seen = {label: {} for label in checks}  # label -> {value: first slug}
    for place in places:
        this = place.get("slug") or place.get("name")
        values = {label: place.get(label) for label in checks[:-1]}
        values["coordinates"] = None
        if place.get("lat") is not None and place.get("lon") is not None:
            values["coordinates"] = (place["lat"], place["lon"])
        for label, value in values.items():
            if value is None:
                continue
            if value in seen[label]:
                problems.append(f"{label} {value!r} reused by {seen[label][value]} and {this}")
            else:
                seen[label][value] = this
    return problems


def _scalar(key: str, v) -> str:
    """Render one frontmatter value in the house style."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "True" if v else "False"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    if not isinstance(v, str):
        raise TypeError(f"{key}: unsupported value {v!r}")
    if key in _ALWAYS_QUOTED:
        return json.dumps(v, ensure_ascii=False)
    # Bare only if YAML would read the bare form back as the same string;
    # this covers ': ', ' #', leading quotes/#/[/{, numbers, bools, dates...
    try:
        bare_ok = yaml.safe_load(f"k: {v}") == {"k": v}
    except yaml.YAMLError:
        bare_ok = False
    return v if bare_ok else json.dumps(v, ensure_ascii=False)


def dump_frontmatter(meta: dict) -> str:
    """Emit frontmatter lines in canonical order (without the `---` fences)."""
    extra = set(meta) - set(KNOWN_KEYS)
    if extra:
        raise ValueError(f"unknown keys: {sorted(extra)}")
    lines = []
    for name in KNOWN_KEYS:
        v = meta.get(name)
        if name not in _ALWAYS_WRITTEN and v is None:
            continue
        lines.append(f"{name}: {_scalar(name, v)}")
    return "\n".join(lines) + "\n"


def write_place(path, meta: dict, body: str) -> None:
    """Write a place file; the body is written verbatim after the closing `---`."""
    Path(path).write_text(
        "---\n" + dump_frontmatter(meta) + "---\n" + body, encoding="utf-8"
    )
