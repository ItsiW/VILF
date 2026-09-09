"""
The `audit` command: which reviewed places does Google no longer list as OPERATIONAL?
"""

from pathlib import Path

import click
import yaml
from tqdm.auto import tqdm

from .places import PlacesError, get_place
from .schema import load_place

BUCKET = {
    "CLOSED_PERMANENTLY": "Permanently closed",
    "CLOSED_TEMPORARILY": "Temporarily closed",
}


@click.command()
@click.option(
    "--directory",
    default="./places/",
    show_default=True,
    type=click.Path(file_okay=False),
    help="Directory of place files to audit.",
)
def audit_places(directory):
    """Report reviewed places Google no longer lists as OPERATIONAL.

    One Pro-tier Place Details call per file that has a place_id (a few hundred
    per run; free at monthly volume). Files without a place_id are only counted.
    Informational: always exits 0.
    """
    files = sorted(Path(directory).glob("*.md"))
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

    for title, lines in groups.items():
        if lines:
            click.echo(f"{title} ({len(lines)}):")
            for line in lines:
                click.echo("  " + line)
    if audited and not any(groups.values()):
        click.echo(f"All {audited} audited places are OPERATIONAL.")
    click.echo(f"{audited} places audited, {no_id} without a place_id (cannot be audited).")


if __name__ == "__main__":
    audit_places()
