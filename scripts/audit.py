"""
The `audit` command: which reviewed places does Google no longer list as OPERATIONAL?
"""

from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import click
import yaml

from . import auditlog
from .places import PlacesError, get_place
from .schema import load_place, write_place

BUCKET = {
    "CLOSED_PERMANENTLY": "Permanently closed",
    "CLOSED_TEMPORARILY": "Temporarily closed",
}
GROUPS = ("Permanently closed", "Temporarily closed", "Unknown status", "Could not check")


@dataclass
class AuditReport:
    """Outcome of audit_rows: '<slug>: <name>: <STATUS>' lines per group, in row order."""

    groups: dict[str, list[str]] = field(default_factory=lambda: {g: [] for g in GROUPS})
    closed_slugs: list[str] = field(default_factory=list)  # CLOSED_PERMANENTLY, not yet marked
    audited: int = 0
    no_id: int = 0
    already_closed: int = 0


def audit_rows(rows: Iterable[tuple[str, dict]], *, get=get_place, workers: int = 8) -> AuditReport:
    """Fetch the business status of every (slug, meta) row that has a place_id and is not closed.

    Pure: no file IO, no output. Rows are fetched concurrently when workers > 1;
    lines keep row order either way. A PlacesError lands in 'Could not check'.
    """
    report = AuditReport()
    todo = []
    for slug, meta in rows:
        if meta.get("closed"):
            report.already_closed += 1
        elif not meta.get("place_id"):
            report.no_id += 1
        else:
            report.audited += 1
            # load_place only defaults the optional keys, so name may be absent
            todo.append((slug, meta.get("name"), meta["place_id"]))

    def fetch(item):
        slug, name, place_id = item
        try:
            return slug, name, get(place_id).business_status
        except PlacesError as e:
            return slug, name, e

    if workers > 1 and len(todo) > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(fetch, todo))
    else:
        results = [fetch(item) for item in todo]

    for slug, name, status in results:
        if isinstance(status, PlacesError):
            report.groups["Could not check"].append(f"{slug}: {name}: {status}")
        elif status != "OPERATIONAL":
            report.groups[BUCKET.get(status, "Unknown status")].append(f"{slug}: {name}: {status}")
            if status == "CLOSED_PERMANENTLY":
                report.closed_slugs.append(slug)
    return report


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
    rows = []
    load_errors = {}
    for path in files:
        try:
            meta, _ = load_place(path)
        except (ValueError, yaml.YAMLError) as e:
            # YAML errors span several lines; keep one line per place
            load_errors[path] = f"{path.stem}: {' '.join(str(e).split())}"
            continue
        rows.append((path.stem, meta))
    # get_place is looked up here so a monkeypatched module attribute is honoured
    report = audit_rows(rows, get=get_place)
    groups = report.groups
    if load_errors:
        # interleave load failures with the API failures (already in file order) by file order
        api_errors = iter(groups["Could not check"])
        pending = next(api_errors, None)
        merged = []
        for path in files:
            if path in load_errors:
                merged.append(load_errors[path])
            elif pending is not None and pending.startswith(f"{path.stem}: "):
                merged.append(pending)
                pending = next(api_errors, None)
        groups["Could not check"] = merged
    audited, no_id, already_closed = report.audited, report.no_id, report.already_closed
    by_stem = {p.stem: p for p in files}
    closed_paths = [by_stem[slug] for slug in report.closed_slugs]

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
