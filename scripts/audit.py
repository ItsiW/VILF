"""
The `audit` command: which reviewed places does Google no longer list as OPERATIONAL?
"""

import subprocess
from datetime import date
from pathlib import Path

import click
import yaml
from tqdm.auto import tqdm

from . import auditlog
from .places import PlacesError, get_place
from .schema import load_place

BUCKET = {
    "CLOSED_PERMANENTLY": "Permanently closed",
    "CLOSED_TEMPORARILY": "Temporarily closed",
}


def remove_tracked(path: Path) -> None:
    """Delete a file, through git when it is tracked so the deletion is staged."""
    try:
        subprocess.run(
            ["git", "rm", "-q", "--", str(path.resolve())], check=True, capture_output=True, cwd=path.resolve().parent
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        path.unlink(missing_ok=True)


def delete_place(path: Path) -> list[Path]:
    """Remove a review and its raw photo (raw/food/<slug>.jpg next to places/)."""
    removed = [path]
    photo = path.resolve().parent.parent / "raw" / "food" / f"{path.stem}.jpg"
    if photo.exists():
        removed.append(photo)
    for item in removed:
        remove_tracked(item)
    return removed


@click.command()
@click.option(
    "--directory",
    default="./places/",
    show_default=True,
    type=click.Path(file_okay=False),
    help="Directory of place files to audit.",
)
@click.option(
    "--delete",
    is_flag=True,
    help="Delete reviews (and their raw/food photo) that Google marks CLOSED_PERMANENTLY. "
    "Temporarily closed places are only reported.",
)
@click.option("--log/--no-log", default=True, show_default=True, help="Append a line to AUDIT_LOG.md.")
def audit_places(directory, delete, log):
    """Report reviewed places Google no longer lists as OPERATIONAL.

    One Pro-tier Place Details call per file that has a place_id (a few hundred
    per run; free at monthly volume). Files without a place_id are only counted.
    Informational: always exits 0. Each run is appended to AUDIT_LOG.md so the
    next person can see when a re-audit is due.
    """
    previous = auditlog.last(directory, "audit")
    if previous:
        click.echo(f"Last audit: {previous} ({(date.today() - previous).days} days ago)")
    else:
        click.echo("No previous audit logged.")
    files = sorted(Path(directory).glob("*.md"))
    closed_paths = []
    groups = {
        "Permanently closed": [],
        "Temporarily closed": [],
        "Unknown status": [],
        "Could not check": [],
    }
    no_id = 0
    audited = 0
    # disable=None: the bar only shows on a TTY, so tests and CI logs stay clean
    for path in tqdm(files, desc="auditing places", disable=None):
        try:
            meta, _ = load_place(path)
        except (ValueError, yaml.YAMLError) as e:
            # YAML errors span several lines; keep one line per place
            groups["Could not check"].append(f"{path.stem}: {' '.join(str(e).split())}")
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
    click.echo(f"{audited} places audited, {no_id} without a place_id (cannot be audited).")

    deleted = []
    if delete and closed_paths:
        for path in closed_paths:
            deleted.extend(delete_place(path))
        click.echo(f"Deleted {len(closed_paths)} permanently closed place(s): "
                   + ", ".join(p.stem for p in closed_paths))

    if log:
        slugs = lambda key: ", ".join(line.split(":")[0] for line in groups[key]) or "none"
        summary = (
            f"{audited} audited, {no_id} without place_id; "
            f"permanently closed: {slugs('Permanently closed')}"
            + (" (deleted)" if delete and closed_paths else "")
            + f"; temporarily closed: {slugs('Temporarily closed')}"
        )
        if groups["Could not check"]:
            summary += f"; could not check: {slugs('Could not check')}"
        auditlog.append(directory, "audit", summary)
        click.echo(f"Logged to {auditlog.FILENAME}.")


if __name__ == "__main__":
    audit_places()
