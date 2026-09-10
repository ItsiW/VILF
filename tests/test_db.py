"""Table shape, constraints and engine setup (plus Settings, which has no test file of its own)."""

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from scripts import schema
from scripts.config import Settings
from scripts.db import init_db, make_engine, places, runs

ROW = dict(
    slug="a", name="A", cuisine="Thai", address="1 St", area="X", lat=1.0, lon=2.0,
    drinks=True, visited=sa.text("'2024-01-01'"), taste=1, value=1,
    created_at=sa.text("'2024-01-01 00:00:00'"), updated_at=sa.text("'2024-01-01 00:00:00'"),
)


def _row(**over):
    from datetime import UTC, date, datetime

    row = dict(ROW, visited=date(2024, 1, 1), created_at=datetime.now(UTC), updated_at=datetime.now(UTC))
    row.update(over)
    return row


@pytest.fixture
def engine(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path}/t.db")
    init_db(engine)
    return engine


def test_places_columns_mirror_schema_fields():
    for field in schema.FIELDS:
        col = places.c[field.name]
        if field.type == "bool":
            assert col.nullable is False and col.server_default is not None
        else:
            assert col.nullable is (not field.required), field.name
    for name in ["id", "slug", "body", "photo_key", "photo_width", "photo_height",
                 "photo_crop_y", "created_at", "updated_at", "published_at"]:
        assert name in places.c
    assert places.c.slug.unique and places.c.slug.nullable is False


def test_create_all_makes_both_tables(engine):
    names = sa.inspect(engine).get_table_names()
    assert set(names) == {"places", "runs"}
    for col in ["kind", "scope", "started_at", "finished_at", "status", "by_email",
                "summary", "details", "snapshot_key", "error"]:
        assert col in runs.c


def test_duplicate_name_rejected(engine):
    with engine.begin() as conn:
        conn.execute(sa.insert(places).values(**_row()))
        with pytest.raises(IntegrityError):
            conn.execute(sa.insert(places).values(**_row(slug="b", lat=3.0)))


def test_taste_out_of_range_rejected(engine):
    with engine.begin() as conn:
        with pytest.raises(IntegrityError):
            conn.execute(sa.insert(places).values(**_row(taste=9)))


def test_bool_defaults_and_empty_phone_not_unique_violation(engine):
    with engine.begin() as conn:
        conn.execute(sa.insert(places).values(**_row(phone=None)))
        conn.execute(sa.insert(places).values(**_row(slug="b", name="B", lat=3.0, phone=None)))
        m = conn.execute(sa.select(places).where(places.c.slug == "a")).mappings().one()
        assert m["closed"] is False and m["instagram_published"] is False
        assert m["photo_crop_y"] == 0.5 and m["body"] == ""


def test_sqlite_foreign_keys_pragma(engine):
    with engine.connect() as conn:
        assert conn.execute(sa.text("PRAGMA foreign_keys")).scalar() == 1


@pytest.mark.parametrize("url", ["postgresql://u:p@h/db", "postgres://u:p@h/db"])
def test_postgres_urls_use_psycopg(url):
    engine = make_engine(url)
    assert engine.url.drivername == "postgresql+psycopg"
    assert engine.pool._pre_ping is True


def test_settings_defaults():
    s = Settings.from_env(env={})
    assert s.database_url == "sqlite:///./vilf.db"
    assert s.media_storage == "./.media" and s.site_storage == "./.site"
    assert s.site_url == "https://vilf.org" and s.dev_user == "dev@localhost"
    assert s.indexnow is False and s.port == 8000
    assert s.google_cloud_project is None and s.admin_email is None


def test_settings_parses_types():
    s = Settings.from_env(env={"PORT": "9000", "VILF_INDEXNOW": "true", "DATABASE_URL": "sqlite://",
                               "VILF_ADMIN_EMAIL": "  ", "VILF_URL_MAP": "vilf-lb"})
    assert s.port == 9000 and s.indexnow is True and s.database_url == "sqlite://"
    assert s.admin_email is None and s.url_map == "vilf-lb"
