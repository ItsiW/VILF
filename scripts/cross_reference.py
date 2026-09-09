"""
The `check` command: re-resolve place files against Google Places and diff them.

Files with a place_id are looked up directly; the rest fall back to a text
search on "<name> <address>" (first result, noted in the output). Exits 1 on
any mismatch or error so it can gate a commit.
"""

import sys

import click
import yaml

from .places import CONTACT_FIELDS, CORE_FIELDS, Place, PlacesError, get_place, search_text
from .schema import load_place

LAT_RES = 1e-4
LON_RES = 1e-4


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def resolve(meta: dict, fields) -> tuple[Place, str | None]:
    """Return (place, note); the note explains a search fallback for files without a place_id."""
    if meta.get("place_id"):
        return get_place(meta["place_id"], fields=fields), None
    results = search_text(f"{meta['name']} {meta['address']}", fields=fields)
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
    if meta["address"] != place.street_address:
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


@click.command()
@click.argument("files", type=click.Path(exists=True, dir_okay=False), nargs=-1)
@click.option(
    "--contact",
    is_flag=True,
    help="Also fetch phone and website (Enterprise billing tier, one call per file).",
)
def cross_reference_md(files, contact):
    """Check place files against Google Places.

    Files with a place_id are looked up directly; others are matched by a text
    search on the name and address (noted in the output). Name and address must
    match exactly, coordinates within 1e-4 degrees. Exits 1 if any file
    mismatches or errors, so it can gate a commit.
    """
    if not files:
        click.echo("No files to check.")
        return
    fields = CONTACT_FIELDS if contact else CORE_FIELDS
    reports = {}
    click.echo("\nTesting files:")
    for file in files:
        note = None
        info = []
        try:
            meta, _ = load_place(file)
            # load_place only defaults the optional keys; resolve/compare need these two
            missing = [key for key in ("name", "address") if meta.get(key) is None]
            if missing:
                raise ValueError(f"missing {', '.join(missing)}")
            place, note = resolve(meta, fields)
            mismatches, info = compare(meta, place, contact)
        except (PlacesError, ValueError, yaml.YAMLError) as e:
            mismatches = [str(e)]
        mark = "✘ " if mismatches else "✔ "
        click.echo(mark + file + (" " + note if note else ""))
        for line in info:
            click.echo("  " + line)
        if mismatches:
            reports[file] = mismatches

    if reports:
        click.echo("\nThe following files may need inspection:\n")
        for file, lines in reports.items():
            click.echo(file)
            for line in lines:
                click.echo(line)
            click.echo("")
        sys.exit(1)
    click.echo("\nAll files look good.")


if __name__ == "__main__":
    cross_reference_md()
