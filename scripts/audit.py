"""
The `audit` command: which reviewed places does Google no longer list as OPERATIONAL?
"""

from datetime import date
from pathlib import Path

import click
import yaml
from tqdm.auto import tqdm

from . import auditlog
from .places import PlacesError, get_place
from .schema import load_place, write_place

BUCKET = {
    "CLOSED_PERMANENTLY": "Permanently closed",
    "CLOSED_TEMPORARILY": "Temporarily closed",
}


def set_closed(path: Path) -> None:
    """Set closed: True on a review; the build keeps its page but drops it from the map and lists."""
    meta, body = load_place(path)
    meta["closed"] = True
    write_place(path, meta, body)


@click.command()
@click.argument("files", type=click.Path(exists=True, dir_okay=False), nargs=-1)
@click.option(
    "--directory",
    default="./places/",
    show_default=True,
    type=click.Path(file_okay=False),
    help="Directory of place files to audit when no FILES are given.",
)
@click.option(
    "--mark-closed",
    is_flag=True,
    help="Set closed: True on reviews Google marks CLOSED_PERMANENTLY (page stays online with a "
    "banner, out of the map and lists). Temporarily closed places are only reported.",
)
@click.option("--log/--no-log", default=True, show_default=True, help="Append a line to AUDIT_LOG.md.")
def audit_places(files, directory, mark_closed, log):
    """Report reviewed places Google no longer lists as OPERATIONAL.

    Pass FILES to audit just those (e.g. a review you just added); with no
    FILES every file in --directory is audited.

    One Pro-tier Place Details call per file that has a place_id (a few hundred
    per run; free at monthly volume). Files without a place_id are only counted.
    Informational: always exits 0. Each run is appended to AUDIT_LOG.md so the
    next person can see when a re-audit is due.
    """
    if files:
        files = [Path(f) for f in files]
        directory = str(files[0].resolve().parent)
    else:
        files = sorted(Path(directory).glob("*.md"))
    previous = auditlog.last(directory, "audit")
    if previous:
        click.echo(f"Last audit: {previous} ({(date.today() - previous).days} days ago)")
    else:
        click.echo("No previous audit logged.")
    closed_paths = []
    groups = {
        "Permanently closed": [],
        "Temporarily closed": [],
        "Unknown status": [],
        "Could not check": [],
    }
    no_id = 0
    already_closed = 0
    audited = 0
    # disable=None: the bar only shows on a TTY, so tests and CI logs stay clean
    for path in tqdm(files, desc="auditing places", disable=None):
        try:
            meta, _ = load_place(path)
        except (ValueError, yaml.YAMLError) as e:
            # YAML errors span several lines; keep one line per place
            groups["Could not check"].append(f"{path.stem}: {' '.join(str(e).split())}")
            continue
        if meta.get("closed"):
            already_closed += 1
            continue
        if not meta.get("place_id"):
            no_id += 1
            continue
        audited += 1
        name = meta.get("name")  # load_place only defaults the optional keys
        try:
            place = get_place(meta["place_id"])
        except PlacesError as e:
            groups["Could not check"].append(f"{path.stem}: {name}: {e}")
            continue
        status = place.business_status
        if status == "OPERATIONAL":
            continue
        groups[BUCKET.get(status, "Unknown status")].append(f"{path.stem}: {name}: {status}")
        if status == "CLOSED_PERMANENTLY":
            closed_paths.append(path)

    for title, lines in groups.items():
        if lines:
            click.echo(f"{title} ({len(lines)}):")
            for line in lines:
                click.echo("  " + line)
    if audited and not any(groups.values()):
        click.echo(f"All {audited} audited places are OPERATIONAL.")
    click.echo(
        f"{audited} places audited, {no_id} without a place_id (cannot be audited), "
        f"{already_closed} already marked closed (skipped)."
    )

    if mark_closed and closed_paths:
        for path in closed_paths:
            set_closed(path)
        click.echo(f"Marked {len(closed_paths)} place(s) closed: " + ", ".join(p.stem for p in closed_paths))

    if log:
        slugs = lambda key: ", ".join(line.split(":")[0] for line in groups[key]) or "none"
        summary = (
            f"{audited} audited, {no_id} without place_id; "
            f"permanently closed: {slugs('Permanently closed')}"
            + (" (marked closed)" if mark_closed and closed_paths else "")
            + f"; temporarily closed: {slugs('Temporarily closed')}"
        )
        if groups["Could not check"]:
            summary += f"; could not check: {slugs('Could not check')}"
        auditlog.append(directory, "audit", summary)
        click.echo(f"Logged to {auditlog.FILENAME}.")


if __name__ == "__main__":
    audit_places()
