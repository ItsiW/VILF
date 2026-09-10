#!/bin/python3
"""`./vilf build`: assemble snapshot-format rows and hand them to render.render_site.

Legacy mode (default) reads places/*.md and raw/food/*.jpg from the current
directory, keeps the static/img cache up to date, and takes each page's
lastmod from git. `--snapshot` renders a JSON list of rows instead (the
database world), with `--copy-media` to drop pre-processed images into the
output.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import click
from tqdm import tqdm

from .images import open_photo, process_photo
from .render import SITE_URL, RenderError, render_site  # noqa: F401  (SITE_URL re-exported)
from .schema import TASTE_LABELS, load_place


def parse_git_dates(log: str) -> dict[str, str]:
    """Map each path in `git log --format=%cs --name-only` output to its newest commit date."""
    dates: dict[str, str] = {}
    current = None
    for line in log.splitlines():
        line = line.strip()
        if not line:
            continue
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", line):
            current = line
        elif current:
            dates.setdefault(line, current)  # the log is newest-first, so the first sighting wins
    return dates


def git_modified_dates(path="places") -> dict[str, str]:
    """Last commit date per file under path (repo-relative keys), or {} when git is unavailable."""
    try:
        log = subprocess.run(
            ["git", "log", "--format=%cs", "--name-only", "--", path],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return {}
    return parse_git_dates(log)


def load_legacy_rows(places_dir="places", raw_dir="raw/food", modified_dates=None):
    """Snapshot-format rows from places/*.md, plus '<file>.md <error>' lines for unreadable files.

    Files are taken in glob order (not sorted) so sitemap.xml keeps its historical order.
    """
    modified_dates = modified_dates or {}
    rows, errors = [], []
    for path in Path(places_dir).glob("*.md"):
        slug = path.stem
        try:
            meta, body = load_place(path)
        except Exception as e:
            errors.append(f"{path.name} {e}")
            continue
        row = dict(meta)
        row["slug"] = slug
        row["body"] = body
        row["photo_key"] = f"originals/{slug}.jpg" if (Path(raw_dir) / f"{slug}.jpg").exists() else None
        row["photo_width"] = None
        row["photo_height"] = None
        row["photo_crop_y"] = 0.5
        row["created_at"] = None
        row["updated_at"] = f"{modified_dates.get(str(path), meta.get('visited'))}T00:00:00Z"
        row["published_at"] = None
        rows.append(row)
    return rows, errors


def process_raw_photos(raw_dir="raw/food", static_dir="static") -> None:
    """Fill the static/img cache from raw/food; photos with all four outputs present are skipped."""
    food_dir = Path(static_dir) / "img" / "food"
    thumb_dir = Path(static_dir) / "img" / "thumb"
    food_dir.mkdir(parents=True, exist_ok=True)
    thumb_dir.mkdir(parents=True, exist_ok=True)
    for raw in tqdm(list(Path(raw_dir).glob("*.jpg")), desc="processing food images"):
        targets = {
            "food.jpg": food_dir / f"{raw.stem}.jpg",
            "food.webp": food_dir / f"{raw.stem}.webp",
            "thumb.jpg": thumb_dir / f"{raw.stem}.jpg",
            "thumb.webp": thumb_dir / f"{raw.stem}.webp",
        }
        if all(target.exists() for target in targets.values()):
            continue
        outputs = process_photo(open_photo(raw.read_bytes()), 0.5)
        for key, target in targets.items():
            target.write_bytes(outputs[key])


@click.command()
@click.option(
    "--snapshot",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help="Render this JSON list of snapshot rows instead of places/*.md.",
)
@click.option("--out", default="build", show_default=True, help="Output directory (wiped first).")
@click.option(
    "--copy-media",
    type=click.Path(file_okay=False),
    default=None,
    help="Copy <DIR>/img into <out>/img after rendering.",
)
def build_vilf(snapshot, out, copy_media) -> None:
    """Build VILF locally."""
    print("Starting build of scripts...")

    if snapshot:
        rows = json.loads(Path(snapshot).read_text(encoding="utf-8"))
    else:
        rows, load_errors = load_legacy_rows(modified_dates=git_modified_dates())
        if load_errors:
            for line in load_errors:
                print(line)
            print(f"Build failed: {len(load_errors)} problem(s)")
            raise SystemExit(1)
        process_raw_photos()

    slugs = {row["slug"] for row in rows}
    try:
        stats = render_site(rows, Path(out))
    except RenderError as e:
        for line in e.problems:
            head, sep, tail = line.partition(": ")
            # legacy mode reports per-file problems as '<slug>.md <problem>', like the old build
            print(f"{head}.md {tail}" if sep and head in slugs and not snapshot else line)
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
