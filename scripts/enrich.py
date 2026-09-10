"""
The `enrich` command: fill city, place_id and website on existing reviews from Google Places.

Each file is matched by a Text Search on "<name> <address>"; the match is
accepted only when Google's coordinates are within MAX_DISTANCE_M of the file's.
Names are printed but never compared (punctuation and accents differ too often).
All Google access goes through scripts.places; GOOGLE_PLACES_API_KEY must be set.
"""

from pathlib import Path

import click
import yaml

from . import places
from .places import CONTACT_FIELDS, Place, PlacesError, distance_m, get_place, search_text
from .schema import load_place, write_place

MAX_DISTANCE_M = 150
MAX_RESULTS = 3


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def nearest(lat, lon, candidates: list[Place]) -> tuple[Place, float] | None:
    """The candidate closest to (lat, lon) and its distance; None if none has coordinates."""
    scored = [
        (p, distance_m(lat, lon, p.lat, p.lon))
        for p in candidates
        if _is_number(p.lat) and _is_number(p.lon)
    ]
    return min(scored, key=lambda pair: pair[1]) if scored else None


def _describe(p: Place) -> str:
    return f"{p.name!r} at {p.street_address}, {p.city}"


def resolve(meta: dict, *, search=search_text) -> tuple[Place | None, str]:
    """Search for the file's place; returns (place, note) or (None, why it was not accepted)."""
    if meta.get("name") is None or meta.get("address") is None:
        raise ValueError("missing name/address")
    query = f"{meta['name']} {meta['address']}"
    results = search(query, max_results=MAX_RESULTS)
    if not results:
        return None, f"no search results for {query!r}"
    top = _describe(results[0])
    if not (_is_number(meta.get("lat")) and _is_number(meta.get("lon"))):
        return None, f"no coordinates in file; top candidate {top}"
    best = nearest(meta["lat"], meta["lon"], results)
    if best is None:
        return None, f"no candidate has coordinates; top candidate {top} (distance n/a)"
    place, d = best
    if d > MAX_DISTANCE_M:
        return None, f"nearest candidate {_describe(place)} is {d:.0f} m away (limit {MAX_DISTANCE_M} m)"
    return place, f"{d:.0f} m"


def enrich_meta(
    meta: dict, *, search=search_text, get=get_place, force: bool = False, contact: bool = False
) -> tuple[str, str, dict]:
    """Work out what Google can add to one place's meta.

    Pure: no file IO, no output. Returns (status, detail, changes) with status
    updated/unchanged/unresolved and changes the fields to set (place_id, city,
    website); changes is empty unless status is 'updated'.
    """
    if meta.get("place_id") and not force:
        return "unchanged", "already has a place_id (use --force to re-resolve)", {}
    place, note = resolve(meta, search=search)
    if place is None:
        return "unresolved", note, {}

    changes = {}
    if place.place_id != meta.get("place_id"):
        changes["place_id"] = place.place_id
    if place.city and (meta.get("city") is None or force) and place.city != meta.get("city"):
        changes["city"] = place.city
    if contact and meta.get("website") is None:
        detail = get(place.place_id, fields=CONTACT_FIELDS)
        if detail.website:
            changes["website"] = detail.website

    name_note = f" (Google name: {place.name!r})" if place.name != meta["name"] else ""
    if not changes:
        return "unchanged", "already up to date" + name_note, {}
    return "updated", ", ".join(f"{k}={v}" for k, v in changes.items()) + f" [{note}]" + name_note, changes


def enrich_file(path, *, force: bool, contact: bool, dry_run: bool) -> tuple[str, str]:
    """Enrich one file; returns (status, detail) with status updated/unchanged/unresolved."""
    meta, body = load_place(path)
    # search/get are looked up here so a monkeypatched module attribute is honoured
    status, detail, changes = enrich_meta(
        meta, search=search_text, get=get_place, force=force, contact=contact
    )
    if status == "updated" and not dry_run:
        write_place(path, {**meta, **changes}, body)
    return status, detail


@click.command()
@click.argument("files", nargs=-1, type=click.Path(exists=True, dir_okay=False))
@click.option("--dry-run", is_flag=True, help="Print what would change; write nothing.")
@click.option(
    "--contact",
    is_flag=True,
    help=(
        "Also fetch the website when the file has none "
        "(Enterprise billing tier, one Place Details call per accepted file)."
    ),
)
@click.option(
    "--force", is_flag=True, help="Re-resolve files that already have a place_id and overwrite city."
)
@click.option(
    "--directory",
    default="./places/",
    show_default=True,
    type=click.Path(file_okay=False),
    help="Directory of place files to enrich when no FILES are given.",
)
def enrich(files, dry_run, contact, force, directory):
    """Fill city, place_id and website on existing reviews from Google Places.

    Each file is matched by a text search on its name and address; the match is
    accepted only when Google's coordinates are within 150 m of the file's
    (names are printed but not compared). name, address, lat, lon, phone, area
    and the ratings are never changed; the review body is preserved verbatim.

    One Pro-tier Text Search per file (about 230 for a full run; free at
    monthly volume), plus one Enterprise-tier Place Details call per accepted
    file with --contact. Informational: always exits 0, except 1 when
    GOOGLE_PLACES_API_KEY is missing.
    """
    try:
        places._api_key()
    except PlacesError as e:
        raise click.ClickException(str(e))

    paths = [Path(f) for f in files] or sorted(Path(directory).glob("*.md"))
    if not paths:
        click.echo("No files to enrich.")
        return
    if dry_run:
        click.echo("Dry run: nothing will be written.")

    counts = {"updated": 0, "unchanged": 0, "unresolved": 0, "error": 0}
    unresolved = []
    for path in paths:
        try:
            status, detail = enrich_file(path, force=force, contact=contact, dry_run=dry_run)
        # TypeError: write_place rejects unsupported value types
        except (PlacesError, ValueError, yaml.YAMLError, KeyError, TypeError) as e:
            status, detail = "error", " ".join(str(e).split())
        counts[status] += 1
        if status == "unresolved":
            unresolved.append(f"{path.name}: {detail}")
        click.echo(f"{status:<10} {path.name}: {detail}")

    if unresolved:
        click.echo(f"Unresolved ({len(unresolved)}):")
        for line in unresolved:
            click.echo("  " + line)
    summary = (
        f"{len(paths)} files: {counts['updated']} updated, {counts['unchanged']} unchanged, "
        f"{counts['unresolved']} unresolved, {counts['error']} errors"
    )
    if dry_run:
        summary += " (dry run: nothing written)"
    click.echo(summary)


if __name__ == "__main__":
    enrich()
