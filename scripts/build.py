#!/bin/python3
"""`./vilf build`: assemble snapshot-format rows and hand them to render.render_site.

`--source db` (default) renders database rows; `--snapshot PATH` renders a JSON backup.
Local media is copied when available.
"""

import json
import shutil
from pathlib import Path

import click

from .render import SITE_URL, RenderError, render_site  # noqa: F401  (SITE_URL re-exported)
from .schema import TASTE_LABELS


@click.command()
@click.option(
    "--source",
    type=click.Choice(["db", "snapshot"]),
    default=None,
    help="Where the rows come from [default: db, or snapshot when --snapshot is given].",
)
@click.option(
    "--snapshot",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help="Render this JSON list of snapshot rows (implies --source snapshot).",
)
@click.option("--out", default="build", show_default=True, help="Output directory (wiped first).")
@click.option(
    "--copy-media",
    type=click.Path(file_okay=False),
    default=None,
    help="Copy <DIR>/img into <out>/img after rendering [default with --source db: the local media storage].",
)
def build_vilf(source, snapshot, out, copy_media) -> None:
    """Build VILF locally."""
    from .config import settings

    print("Starting build of scripts...")
    source = source or ("snapshot" if snapshot else "db")

    if source == "snapshot":
        if not snapshot:
            raise click.UsageError("--source snapshot needs --snapshot PATH")
        rows = json.loads(Path(snapshot).read_text(encoding="utf-8"))
    else:
        from . import repo
        from .cli import open_db

        with open_db() as conn:
            rows = repo.all_rows(conn)
        media = settings().media_storage
        if copy_media is None and not media.startswith("gs://") and (Path(media) / "img").is_dir():
            copy_media = media

    try:
        stats = render_site(rows, Path(out), site_url=settings().site_url)
    except RenderError as e:
        for line in e.problems:
            print(line)
        print(f"Build failed: {len(e.problems)} problem(s)")
        raise SystemExit(1)

    if copy_media:
        shutil.copytree(Path(copy_media) / "img", Path(out) / "img", dirs_exist_ok=True)

    print(f"{stats.open} open, {stats.closed} closed")
    print(f"Done building VILF with {stats.open} places")

    open_rows = [row for row in rows if not row.get("closed")]
    if open_rows:
        for taste, label in enumerate(TASTE_LABELS):
            count = sum(1 for row in open_rows if row["taste"] == taste)
            print(f"{label}: {round(count / len(open_rows) * 100)}%")


if __name__ == "__main__":
    build_vilf()
