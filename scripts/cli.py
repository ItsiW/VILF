"""`./vilf`: every command reads its settings from scripts.config.settings()."""

import sys
from contextlib import contextmanager
from pathlib import Path

import click
import sqlalchemy as sa
from sqlalchemy.engine import make_url

from . import repo, runs
from .audit import audit_places
from .build import build_vilf
from .config import settings
from .cross_reference import cross_reference_md
from .db import init_db, make_engine
from .enrich import enrich
from .snapshot import dump_rows, load_rows
from .spatula import scrape_and_gen_md
from .storage import storage_from_url


NOT_INITIALISED = "database not initialised: confirm DATABASE_URL, then run `./vilf db init`; restore a current backup or add places in the admin"


def _engine():
    return make_engine(settings().database_url)


@contextmanager
def open_db():
    """A connection in a transaction, or a ClickException when `./vilf db init` has not run.

    The other commands import this lazily: it is the one place that knows how
    to turn settings() into a usable database.
    """
    url = make_url(settings().database_url)
    path = url.database if url.drivername.startswith("sqlite") else None
    if path and path != ":memory:" and not Path(path).exists():
        raise click.ClickException(NOT_INITIALISED)  # before make_engine creates an empty file
    engine = make_engine(settings().database_url)
    if not sa.inspect(engine).has_table("places"):
        raise click.ClickException(NOT_INITIALISED)
    with engine.begin() as conn:
        yield conn


def _media():
    return storage_from_url(settings().media_storage)


def _site():
    return storage_from_url(settings().site_storage)


@click.group()
def cli():
    """
    VILF CLI interface
    """
    pass


cli.add_command(build_vilf, "build")
cli.add_command(scrape_and_gen_md, "spatula")
cli.add_command(cross_reference_md, "check")
cli.add_command(audit_places, "audit")
cli.add_command(enrich, "enrich")


@cli.command()
@click.option("--force", is_flag=True, help="Delete stale site objects even when there are many.")
def publish(force):
    """Render the database and sync it into site storage (this is the deploy)."""
    from . import publish as publish_mod

    s = settings()
    cdn = None
    if s.google_cloud_project and s.url_map:
        cdn = publish_mod.GcpCdnInvalidator(s.google_cloud_project, s.url_map)
    try:
        with open_db() as conn:
            result = publish_mod.publish(
                conn, media=_media(), site=_site(), settings=s, cdn=cdn,
                by_email=s.dev_user, force=force,
            )
    except publish_mod.PublishRunning as e:
        raise click.ClickException(str(e))
    click.echo(
        f"{result.status}: {result.uploaded} uploaded, {result.deleted} deleted, "
        f"{result.unchanged} unchanged in {result.seconds:.1f}s"
    )
    if result.snapshot_key:
        click.echo(f"snapshot: {result.snapshot_key}")
    if result.changes is not None:
        d = result.changes
        click.echo(f"changes: +{len(d.added)} -{len(d.removed)} ~{len(d.changed)}")
    click.echo("cdn: " + ("invalidated" if result.cdn_invalidated else "skipped" if cdn is None else "failed"))
    if result.error:
        click.echo(result.error)
    if result.status == "failed":
        sys.exit(1)


@cli.command()
@click.option("--reload", is_flag=True, help="Restart on code changes.")
def serve(reload):
    """Run the admin app (uvicorn app.main:app) on settings().port."""
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=settings().port, reload=reload)


@cli.group()
def db():
    """Database maintenance: init, import-markdown, snapshot, restore-snapshot."""


@db.command()
def init():
    """Create the tables (idempotent)."""
    init_db(_engine())
    click.echo(f"Initialised {settings().database_url}")


@db.command("import-markdown")
@click.option("--places", default="places", show_default=True, help="Directory of place files.")
@click.option("--raw", default="raw/food", show_default=True, help="Directory of raw photos.")
@click.option("--dry-run", is_flag=True, help="Validate and report; write nothing.")
@click.option("--replace", is_flag=True, help="Empty the places table first.")
def import_markdown(places, raw, dry_run, replace):
    """Load places/*.md and raw/food/*.jpg into the database (photos into media storage)."""
    from .importer import import_markdown as run_import

    engine = _engine()
    init_db(engine)
    with engine.begin() as conn:
        report = run_import(
            conn, _media(), places_dir=places, raw_dir=raw, dry_run=dry_run, replace=replace
        )
    if report.errors:
        sys.exit(1)


@db.command()
@click.argument("path", required=False, type=click.Path(dir_okay=False))
def snapshot(path):
    """Dump every row as JSON to PATH (or stdout)."""
    with open_db() as conn:
        text = dump_rows(repo.all_rows(conn))
    if path:
        Path(path).write_text(text, encoding="utf-8")
        click.echo(f"Wrote {path}")
    else:
        click.echo(text, nl=False)


@db.command("restore-snapshot")
@click.argument("key_or_path")
@click.option("--publish", "do_publish", is_flag=True, help="Publish right after restoring.")
@click.pass_context
def restore_snapshot(ctx, key_or_path, do_publish):
    """Replace every row with the rows of a snapshot (a media storage key or a local file)."""
    media = storage_from_url(settings().backup_storage) if settings().backup_storage else _media()
    from_media = not Path(key_or_path).is_file()
    if from_media:
        try:
            text = media.get(key_or_path).decode("utf-8")
        except (FileNotFoundError, ValueError):
            raise click.ClickException(f"{key_or_path} is neither a local file nor a media storage key")
    else:
        text = Path(key_or_path).read_text(encoding="utf-8")
    rows = load_rows(text)
    engine = _engine()
    init_db(engine)
    with engine.begin() as conn:
        repo.from_snapshot_rows(conn, rows, replace=True)
        runs.append(
            conn, "restore", f"{len(rows)} places restored from {key_or_path}",
            snapshot_key=key_or_path if from_media else None,
        )
    click.echo(f"Restored {len(rows)} places from {key_or_path}")
    if do_publish:
        ctx.invoke(publish, force=False)


if __name__ == "__main__":
    cli()
