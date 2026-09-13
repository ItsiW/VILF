"""
The `audit` command: which reviewed places does Google no longer list as OPERATIONAL?
"""

from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date

import click

from . import repo, runs
from .places import PlacesError, get_place

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
    unlinked: int = 0


def audit_rows(rows: Iterable[tuple[str, dict]], *, get=get_place, workers: int = 8, on_problem=None) -> AuditReport:
    """Fetch the business status of every (slug, meta) row that has a place_id and is not closed.

    Rows are fetched concurrently when workers > 1. Optional on_problem receives
    failures as they arrive; the final report keeps row order either way.
    A PlacesError lands in 'Could not check'.
    """
    report = AuditReport()
    todo = []
    for slug, meta in rows:
        if meta.get("closed"):
            report.already_closed += 1
        elif meta.get("unlinked") and not meta.get("place_id"):
            report.unlinked += 1
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

    def report_problem(result):
        slug, name, status = result
        if on_problem and status != "OPERATIONAL":
            on_problem(f"{slug}: {name}: {status}")

    if workers > 1 and len(todo) > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(fetch, item): index for index, item in enumerate(todo)}
            results = [None] * len(todo)
            for future in as_completed(futures):
                result = future.result()
                results[futures[future]] = result
                report_problem(result)
    else:
        results = []
        for item in todo:
            result = fetch(item)
            results.append(result)
            report_problem(result)

    for slug, name, status in results:
        if isinstance(status, PlacesError):
            report.groups["Could not check"].append(f"{slug}: {name}: {status}")
        elif status != "OPERATIONAL":
            report.groups[BUCKET.get(status, "Unknown status")].append(f"{slug}: {name}: {status}")
            if status == "CLOSED_PERMANENTLY":
                report.closed_slugs.append(slug)
    return report


@click.command()
@click.argument("slugs", nargs=-1)
@click.option(
    "--mark-closed",
    is_flag=True,
    help="Set closed: True on reviews Google marks CLOSED_PERMANENTLY (page stays online with a "
    "banner, out of the map and lists). Temporarily closed places are only reported.",
)
@click.option("--log/--no-log", default=True, show_default=True, help="Record this run in the runs table.")
def audit_places(slugs, mark_closed, log):
    """Report reviewed places Google no longer lists as OPERATIONAL.

    Pass SLUGS to audit just those (e.g. a review you just added); with no
    SLUGS every place in the database is audited.

    One Pro-tier Place Details call per place that has a place_id (a few hundred
    per run; free at monthly volume). Places without a place_id are only counted.
    Informational: always exits 0. Each run is logged in the runs table so the
    next person can see when a re-audit is due.
    """
    from .cli import open_db

    with open_db() as conn:
        previous = runs.last(conn, "audit")
        if previous:
            day = previous.astimezone().date()
            click.echo(f"Last audit: {day} ({(date.today() - day).days} days ago)")
        else:
            click.echo("No previous audit logged.")
        if slugs:
            rows_db = []
            for slug in slugs:
                row = repo.get(conn, slug)
                if row is None:
                    raise click.ClickException(f"unknown slug {slug!r}")
                rows_db.append(row)
        else:
            rows_db = repo.all_rows(conn)
        rows = [(row["slug"], repo.row_to_meta(row)[0]) for row in rows_db]
        # get_place is looked up here so a monkeypatched module attribute is honoured
        report = audit_rows(rows, get=get_place, on_problem=click.echo)
        groups = report.groups
        audited, no_id, already_closed = report.audited, report.no_id, report.already_closed

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

        if mark_closed and report.closed_slugs:
            for slug in report.closed_slugs:
                repo.update(conn, slug, {"closed": True})
            click.echo(f"Marked {len(report.closed_slugs)} place(s) closed: " + ", ".join(report.closed_slugs))

        if report.unlinked:
            click.echo(f"{report.unlinked} intentionally unlinked from Google (skipped).")

        if log:
            names = lambda key: ", ".join(line.split(":")[0] for line in groups[key]) or "none"
            summary = (
                f"{audited} audited, {no_id} without place_id; "
                f"permanently closed: {names('Permanently closed')}"
                + (" (marked closed)" if mark_closed and report.closed_slugs else "")
                + f"; temporarily closed: {names('Temporarily closed')}"
            )
            if groups["Could not check"]:
                summary += f"; could not check: {names('Could not check')}"
            runs.append(conn, "audit", summary, scope=",".join(slugs) or "all", details=groups)
            click.echo("Logged.")


if __name__ == "__main__":
    audit_places()
