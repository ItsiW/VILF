"""
The `check` command: re-resolve place rows against Google Places and diff them.

Rows with a place_id are looked up directly; the rest fall back to a text
search on "<name> <address>" (first result, noted in the output). Exits 1 on
any mismatch or error so it can gate a publish.
"""

import re
import sys
from dataclasses import dataclass

import click
from unidecode import unidecode

from . import repo, runs
from .places import CONTACT_FIELDS, CORE_FIELDS, Place, PlacesError, get_place, search_text
from .schema import validate_place

LAT_RES = 1e-4
LON_RES = 1e-4


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


_ABBREV = {
    "street": "st", "avenue": "ave", "boulevard": "blvd", "road": "rd", "drive": "dr",
    "plaza": "plz", "suite": "ste", "place": "pl", "court": "ct", "highway": "hwy",
    "north": "n", "south": "s", "east": "e", "west": "w",
}


def _norm_address(s: str) -> str:
    words = re.sub(r"[^a-z0-9 ]", " ", unidecode(s or "").lower()).split()
    return " ".join(_ABBREV.get(w, w) for w in words)


def has_street_number(place: Place) -> bool:
    """Google's street_address is number + route; without a number it's not an upgrade."""
    components = (place.raw or {}).get("addressComponents")
    if components:
        return any("street_number" in c.get("types", []) for c in components)
    return bool(re.match(r"\d+(-\d+)?\s", place.street_address or ""))


def same_street(file_address, google_address) -> bool:
    """True when the file's address is Google's, possibly with extra detail (unit, suite, floor).

    Google returns only number + street, so "800 Bancroft Way Suite #105" vs
    "800 Bancroft Way" is not a mismatch, and neither is "Avenue" vs "Ave".
    """
    a, b = _norm_address(file_address), _norm_address(google_address)
    return bool(b) and (b in a or a in b)


@dataclass
class CheckResult:
    """One place checked against Google: what was found, what differs, what was fixed."""

    place: Place | None
    note: str | None  # explains a search fallback for places without a place_id
    mismatches: list[str]
    info: list[str]
    changed: list[str]  # field names apply_fixes changed (empty unless fix)
    meta: dict  # the (possibly fixed) copy of the input meta


def resolve(meta: dict, fields, *, get=get_place, search=search_text) -> tuple[Place, str | None]:
    """Return (place, note); the note explains a search fallback for files without a place_id."""
    if meta.get("place_id"):
        return get(meta["place_id"], fields=fields), None
    results = search(f"{meta['name']} {meta['address']}", max_results=1, fields=fields)
    if not results:
        raise PlacesError("no search results")
    place = results[0]
    return place, f"(no place_id: matched by search to {place.name}, {place.place_id})"


def compare(meta: dict, place: Place, contact: bool) -> tuple[list[str], list[str]]:
    """Return (mismatches, info) lines for one file."""
    mismatches = []
    info = []

    def diff(label, current, determined):
        mismatches.append(f"Current {label}: {current} | Determined {label}: {determined}")

    if meta["name"] != place.name:
        diff("name", meta["name"], place.name)
    if not same_street(meta["address"], place.street_address):
        diff("address", meta["address"], place.street_address)
    for label, current, determined, res in (
        ("latitude", meta.get("lat"), place.lat, LAT_RES),
        ("longitude", meta.get("lon"), place.lon, LON_RES),
    ):
        if not _is_number(current):
            # e.g. a quoted "37.8" in the frontmatter; report it rather than crash on the subtraction
            diff(label, f"{current!r} (not a number)", determined)
        elif not _is_number(determined) or abs(current - determined) > res:
            diff(label, current, determined)
    if contact:
        if (meta.get("phone") or None) != (place.phone or None):
            diff("phone number", meta.get("phone"), place.phone)
        if meta.get("website") is None and place.website:
            info.append(f"Website (not in file): {place.website}")
    return mismatches, info


def apply_fixes(meta: dict, place: Place, contact: bool) -> list[str]:
    """Overwrite meta in place with Google's values; return the field names changed.

    Name is editorial and never touched. Website is only filled when absent.
    Coordinates are rounded to 7 decimals (about 1 cm) so files don't pick up float noise.
    """
    changed = []
    # Only a different street counts; Google drops unit/suite detail the file may carry,
    # and an address without a street number (e.g. "Ferry Plz") is never an upgrade.
    if (
        place.street_address
        and has_street_number(place)
        and not same_street(meta.get("address"), place.street_address)
    ):
        meta["address"] = place.street_address
        changed.append("address")
    if _is_number(place.lat) and _is_number(place.lon):
        lat, lon = round(place.lat, 7), round(place.lon, 7)
        if (
            not _is_number(meta.get("lat"))
            or not _is_number(meta.get("lon"))
            or abs(meta["lat"] - lat) > LAT_RES
            or abs(meta["lon"] - lon) > LON_RES
        ):
            meta["lat"], meta["lon"] = lat, lon
            changed.append("coordinates")
    if place.city and not meta.get("city"):
        meta["city"] = place.city
        changed.append("city")
    if contact:
        if (meta.get("phone") or None) != (place.phone or None):
            meta["phone"] = place.phone
            changed.append("phone")
        if place.website and not meta.get("website"):
            meta["website"] = place.website
            changed.append("website")
    return changed


def check_place(
    meta: dict, *, contact: bool, fix: bool, body: str | None = None, slug: str = "review", get=get_place, search=search_text
) -> CheckResult:
    """Resolve, compare and (with fix, for places with a place_id) correct one place's meta.

    Pure: no file IO, no output. The input dict is copied, never mutated; the fixed
    values are in the returned CheckResult.meta. Raises ValueError when name or
    address is missing and PlacesError when Google cannot resolve the place.
    """
    meta = dict(meta)
    if body is not None:
        problems = validate_place(meta, body, slug)
        if problems:
            raise ValueError("Review validation: " + "; ".join(problems))
    missing = [key for key in ("name", "address") if meta.get(key) is None]
    if missing:
        raise ValueError(f"missing {', '.join(missing)}")
    if meta.get("unlinked") and not meta.get("place_id"):
        return CheckResult(None, "intentionally unlinked from Google (skipped)", [], [], [], meta)
    fields = CONTACT_FIELDS if contact else CORE_FIELDS
    place, note = resolve(meta, fields, get=get, search=search)
    mismatches, info = compare(meta, place, contact)
    changed = []
    if fix and mismatches and meta.get("place_id"):
        changed = apply_fixes(meta, place, contact)
        if changed:
            info.append("fixed: " + ", ".join(changed))
        mismatches, _ = compare(meta, place, contact)
        if meta["name"] != place.name:
            # editorial; report but don't fail the run
            mismatches = [m for m in mismatches if not m.startswith("Current name")]
            info.append(f"name kept: {meta['name']} | Google: {place.name}")
    return CheckResult(place, note, mismatches, info, changed, meta)


@click.command()
@click.argument("slugs", nargs=-1)
@click.option(
    "--contact",
    is_flag=True,
    help="Also fetch phone and website (Enterprise billing tier, one call per place).",
)
@click.option(
    "--fix",
    is_flag=True,
    help="Write Google's address, coordinates, city (and with --contact: phone, website) "
    "back into places that have a place_id. Names are never changed. Logs a check run.",
)
def cross_reference_md(slugs, contact, fix):
    """Check places against Google Places.

    With no SLUGS, every place in the database is checked. Places with a
    place_id are looked up directly; others are matched by a text search on the
    name and address (noted in the output). Name and address must match
    exactly, coordinates within 1e-4 degrees. Exits 1 if any place mismatches
    or errors, so it can gate a publish. With --fix, places that have a
    place_id are corrected in the database and only remaining problems (name
    differences, unlinked places, errors) count as mismatches.
    """
    reports = {}
    from .cli import open_db

    with open_db() as conn:
        rows = load_rows(conn, slugs)
        if not rows:
            click.echo("No files to check.")
            return
        fixed = {}
        click.echo("\nTesting files:")
        for row in rows:
            slug = row["slug"]
            note = None
            info = []
            try:
                meta, body = repo.row_to_meta(row)
                # get/search are looked up here so a monkeypatched module attribute is honoured
                result = check_place(meta, body=body, slug=slug, contact=contact, fix=fix, get=get_place, search=search_text)
                note, info, mismatches = result.note, result.info, result.mismatches
                if result.changed:
                    fields = {k: v for k, v in result.meta.items() if v != meta.get(k)}
                    clashes = unique_clashes(repo.validate_for_save(conn, {**row, **fields}), fields)
                    if clashes:
                        mismatches = mismatches + ["not fixed: " + p for p in clashes]
                    else:
                        repo.update(conn, slug, fields)
                        fixed[slug] = result.changed
            except (PlacesError, ValueError) as e:
                mismatches = [str(e)]
            mark = "✘ " if mismatches else "✔ "
            click.echo(mark + slug + (" " + note if note else ""))
            for line in info:
                click.echo("  " + line)
            if mismatches:
                reports[slug] = mismatches

        if fix:
            counts = {}
            for changed in fixed.values():
                for field in changed:
                    counts[field] = counts.get(field, 0) + 1
            detail = ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) or "nothing"
            summary = f"{len(rows)} files checked, {len(fixed)} fixed ({detail}), {len(reports)} still flagged"
            runs.append(
                conn, "check", summary, scope=",".join(slugs) or "all",
                details={"fixed": fixed, "flagged": reports},
            )
            click.echo("\n" + summary + " (logged)")

        if reports:
            click.echo("\nThe following files may need inspection:\n")
            for slug, lines in reports.items():
                click.echo(slug)
                for line in lines:
                    click.echo(line)
                click.echo("")
    # exit only after the transaction committed: SystemExit inside it would roll fixes back
    if reports:
        sys.exit(1)
    click.echo("\nAll files look good.")


_UNIQUE_LABELS = {"lat": "coordinates", "lon": "coordinates", "name": "name", "menu": "menu", "phone": "phone"}


def unique_clashes(problems: list[str], fields: dict) -> list[str]:
    """The 'X reused by A and B' problems caused by the fields being written (a UNIQUE column would raise)."""
    touched = {_UNIQUE_LABELS[k] for k in fields if k in _UNIQUE_LABELS}
    return [p for p in problems if " reused by " in p and p.split(" ", 1)[0] in touched]


def load_rows(conn, slugs) -> list[dict]:
    """The rows for SLUGS (unknown ones abort with exit 1), or every row when none are given."""
    if not slugs:
        return repo.all_rows(conn)
    rows = []
    for slug in slugs:
        row = repo.get(conn, slug)
        if row is None:
            raise click.ClickException(f"unknown slug {slug!r}")
        rows.append(row)
    return rows


if __name__ == "__main__":
    cross_reference_md()
