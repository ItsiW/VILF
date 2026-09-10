"""Place rows in and out of the `places` table.

Every public function takes a SQLAlchemy Connection. Rows crossing this API are
always in snapshot format (tests/fixtures/snapshot.json): schema fields plus slug,
body, photo_*, and ISO 8601 UTC timestamps ending in Z (or None); visited is
'YYYY-MM-DD'. Conversion to database types is private to this module.
"""

import re
from datetime import UTC, date, datetime

import sqlalchemy as sa
from mdplain import plain
from sqlalchemy import Connection

from . import schema
from .db import places

EXTRA_KEYS = [
    "slug",
    "body",
    "photo_key",
    "photo_width",
    "photo_height",
    "photo_crop_y",
    "created_at",
    "updated_at",
    "published_at",
]
ROW_KEYS = schema.KNOWN_KEYS + EXTRA_KEYS
TIMESTAMPS = ("created_at", "updated_at", "published_at")
FILTERS = ("dirty", "closed", "nophoto")
_TEXT_FIELDS = frozenset(f.name for f in schema.FIELDS if f.type in ("str", "url"))
_BOOL_FIELDS = frozenset(f.name for f in schema.FIELDS if f.type == "bool")


def _now() -> datetime:
    return datetime.now(UTC)


def _parse_dt(v) -> datetime | None:
    """None/str/datetime -> aware UTC datetime (SQLite hands back naive ones: treat as UTC)."""
    if v is None:
        return None
    if isinstance(v, str):
        v = datetime.fromisoformat(v.replace("Z", "+00:00"))
    if v.tzinfo is None:
        return v.replace(tzinfo=UTC)
    return v.astimezone(UTC)


def _iso(v) -> str | None:
    dt = _parse_dt(v)
    return None if dt is None else dt.isoformat().replace("+00:00", "Z")


def _to_db(row: dict) -> dict:
    """Snapshot-format values -> column values (only known columns)."""
    out = {}
    for key, v in row.items():
        if key not in places.c:
            continue
        if key == "visited" and isinstance(v, str):
            v = date.fromisoformat(v)
        elif key in TIMESTAMPS:
            v = _parse_dt(v)
        elif key in _TEXT_FIELDS and isinstance(v, str):
            v = v.strip() or None  # mirrors schema.load_place: '' means unset
        elif key in _BOOL_FIELDS and v is None:
            v = False
        out[key] = v
    return out


def _from_db(mapping) -> dict:
    row = {}
    for key in ROW_KEYS:
        v = mapping[key]
        if key == "visited" and isinstance(v, date):
            v = v.isoformat()
        elif key in _BOOL_FIELDS:
            v = bool(v)
        elif key in TIMESTAMPS:
            v = _iso(v)
        row[key] = v
    return row


def _blurb(body: str) -> str:
    """Same formula as build.py's format_blurb, so uniqueness agrees with the build."""
    return " ".join(plain(re.sub(r"\s+", " ", body.strip())).split(" ")[:50]) + "..."


def all_rows(conn: Connection) -> list[dict]:
    return [_from_db(m) for m in conn.execute(sa.select(places).order_by(places.c.slug)).mappings()]


def get(conn: Connection, slug: str) -> dict | None:
    m = conn.execute(sa.select(places).where(places.c.slug == slug)).mappings().first()
    return None if m is None else _from_db(m)


def search(conn: Connection, q: str = "", filter: str | None = None) -> list[dict]:
    """Case-insensitive substring on name/area/cuisine/address; filter in FILTERS."""
    if filter is not None and filter not in FILTERS:
        raise ValueError(f"unknown filter {filter!r}; expected one of {FILTERS}")
    needle = q.strip().casefold()
    rows = all_rows(conn)
    if needle:
        rows = [
            r for r in rows
            if any((r[k] or "").casefold().find(needle) >= 0 for k in ("name", "area", "cuisine", "address"))
        ]
    if filter == "dirty":
        rows = [r for r in rows if is_dirty(r)]
    elif filter == "closed":
        rows = [r for r in rows if r["closed"]]
    elif filter == "nophoto":
        rows = [r for r in rows if r["photo_key"] is None]
    return rows


def insert(conn: Connection, row: dict) -> dict:
    """Insert a new place; created_at/updated_at are set to now, published_at to None."""
    now = _now()
    values = _to_db(row)
    values.pop("id", None)
    values.update(created_at=now, updated_at=now, published_at=None)
    conn.execute(sa.insert(places).values(**values))
    return get(conn, values["slug"])


def update(conn: Connection, slug: str, fields: dict, *, touch: bool = True) -> dict:
    """Apply `fields` (snapshot format, may rename slug); touch bumps updated_at."""
    if get(conn, slug) is None:
        raise KeyError(slug)
    values = _to_db(fields)
    values.pop("id", None)
    if touch:
        values["updated_at"] = _now()
    if values:
        conn.execute(sa.update(places).where(places.c.slug == slug).values(**values))
    return get(conn, values.get("slug", slug))


def delete(conn: Connection, slug: str) -> None:
    row = get(conn, slug)
    if row is None:
        raise KeyError(slug)
    if row["published_at"] is not None:
        raise ValueError(f"{slug} has been published; never delete reviews (mark it closed instead)")
    conn.execute(sa.delete(places).where(places.c.slug == slug))


def unique_slug(conn: Connection, base: str) -> str:
    """base, base-0, base-1, ... (spatula.unique_path numbering).

    Quirk kept on purpose: a base already ending in -<digits> has that suffix
    replaced, so with 'route-66' taken the next slug is 'route-0'.
    """
    taken = set(conn.execute(sa.select(places.c.slug)).scalars())
    candidate = base
    n = 0
    while candidate in taken:
        candidate = re.split(r"-\d+$", candidate)[0] + f"-{n}"
        n += 1
    return candidate


def row_to_meta(row: dict) -> tuple[dict, str]:
    """(meta, body) shaped like schema.load_place output: exactly KNOWN_KEYS, DEFAULTS applied."""
    meta = {}
    for key in schema.KNOWN_KEYS:
        v = row.get(key)
        if isinstance(v, date):
            v = v.isoformat()
        elif isinstance(v, str):
            v = v.strip() or None
        if v is None:
            v = schema.DEFAULTS.get(key)
        meta[key] = v
    return meta, row.get("body") or ""


def meta_to_row(meta: dict, body: str, **extra) -> dict:
    """Full snapshot-shape row from (meta, body); slug/photo/timestamps come from `extra`."""
    row = {key: meta.get(key, schema.DEFAULTS.get(key)) for key in schema.KNOWN_KEYS}
    for key in _BOOL_FIELDS:
        row[key] = bool(row[key])
    row.update(
        slug=None, body=body, photo_key=None, photo_width=None, photo_height=None,
        photo_crop_y=0.5, created_at=None, updated_at=None, published_at=None,
    )
    row.update(extra)
    return row


def _unique_entry(row: dict) -> dict:
    meta, body = row_to_meta(row)
    return {
        "slug": row["slug"],
        "name": meta["name"],
        "menu": meta["menu"],
        "phone": meta["phone"],
        "lat": meta["lat"],
        "lon": meta["lon"],
        "blurb": _blurb(body),
    }


def validate_for_save(conn: Connection, row: dict, *, old_slug: str | None = None) -> list[str]:
    """validate_place + validate_unique over all rows with this slug's row replaced by `row`.

    Pass old_slug when the edit renames the place (row['slug'] differs from the
    stored slug) so the stored row is not compared against its own new version.
    """
    meta, body = row_to_meta(row)
    slug = row.get("slug") or ""
    problems = schema.validate_place(meta, body, slug)
    skip = {slug, old_slug} - {None}
    others = [_unique_entry(r) for r in all_rows(conn) if r["slug"] not in skip]
    problems += schema.validate_unique(others + [_unique_entry(row)])
    return problems


def is_dirty(row: dict) -> bool:
    published = _parse_dt(row.get("published_at"))
    if published is None:
        return True
    updated = _parse_dt(row.get("updated_at"))
    return updated is not None and updated > published


def dirty_rows(conn: Connection) -> list[dict]:
    return [r for r in all_rows(conn) if is_dirty(r)]


def mark_published(conn: Connection, slugs, now) -> None:
    slugs = list(slugs)
    if not slugs:
        return
    conn.execute(
        sa.update(places).where(places.c.slug.in_(slugs)).values(published_at=_parse_dt(now))
    )


def distinct_values(conn: Connection, column: str) -> list[str]:
    col = places.c[column]
    return sorted(conn.execute(sa.select(col).where(col.is_not(None)).distinct()).scalars())


def from_snapshot_rows(conn: Connection, rows: list[dict], *, replace: bool = False) -> None:
    """Insert snapshot rows keeping their timestamps; replace=True empties the table first."""
    if replace:
        conn.execute(sa.delete(places))
    now = _now()
    for row in rows:
        values = _to_db(row)
        values.pop("id", None)
        values.setdefault("created_at", None)
        values.setdefault("updated_at", None)
        values["created_at"] = values["created_at"] or now
        values["updated_at"] = values["updated_at"] or values["created_at"]
        conn.execute(sa.insert(places).values(**values))
