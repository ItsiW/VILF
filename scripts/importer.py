"""`./vilf db import-markdown`: load places/*.md and raw/food into the database.

Rows keep their git dates (or `visited`) as created/updated/published time, so
an imported review counts as already live, not dirty. Photos go through
scripts.photos.set_photo; when that module is missing the rows are imported
without photos (photo_key None) rather than pointing at originals that were
never stored, and a re-import with --replace picks them up later.
"""

from dataclasses import dataclass, field
from pathlib import Path

import click
from sqlalchemy import Connection

from . import build, publish, repo, runs
from .storage import Storage


@dataclass
class ImportReport:
    rows: int = 0
    photos: int = 0
    orphans: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    photos_skipped: bool = False


def import_markdown(
    conn: Connection,
    media: Storage,
    *,
    places_dir="places",
    raw_dir="raw/food",
    dry_run: bool = False,
    replace: bool = False,
    echo=click.echo,
) -> ImportReport:
    report = ImportReport()
    rows, errors = build.load_legacy_rows(places_dir, raw_dir, build.git_modified_dates(places_dir))
    if errors:
        report.errors = errors
        for line in errors:
            echo(line)
        return report
    rows.sort(key=lambda r: r["slug"])
    for row in rows:
        day = (row["updated_at"] or "")[:10] or row["visited"]
        row["created_at"] = row["updated_at"] = row["published_at"] = f"{day}T00:00:00Z"
    problems = publish.validate_rows(rows)
    if problems:
        report.errors = problems
        for line in problems:
            echo(line)
        return report
    existing = len(repo.all_rows(conn))
    if existing and not replace:
        report.errors = [f"database already holds {existing} places; use --replace"]
        echo(report.errors[0])
        return report

    try:
        from . import photos
    except ImportError:
        photos = None
        report.photos_skipped = True
        echo(
            "warning: scripts.photos not available, photos skipped: rows are imported "
            "without photos; re-run with --replace once it exists"
        )
    raw_files = {p.stem: p for p in Path(raw_dir).glob("*.jpg")}
    report.orphans = sorted(set(raw_files) - {row["slug"] for row in rows})
    for row in rows:
        raw = raw_files.get(row["slug"])
        if raw is None:
            continue
        if photos is None:
            row["photo_key"] = None  # the loader assumed one; nothing is stored without scripts.photos
            continue
        report.photos += 1
        if not dry_run:
            row.update(photos.set_photo(media, row["slug"], raw.read_bytes(), 0.5))
    report.rows = len(rows)

    if dry_run:
        echo(f"Dry run: would import {report.rows} places ({report.photos} photos) from {places_dir}")
    else:
        repo.from_snapshot_rows(conn, rows, replace=replace)
        runs.append(
            conn, "import", f"{report.rows} places, {report.photos} photos from {places_dir}",
            details={"orphans": report.orphans, "photos_skipped": report.photos_skipped},
        )
        echo(f"Imported {report.rows} places ({report.photos} photos)")
    if report.orphans:
        echo(f"Photos without a review ({len(report.orphans)}):")
        for stem in report.orphans:
            echo(f"  {stem}")
    return report
