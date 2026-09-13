"""SQLAlchemy Core schema: the `places` table mirrors schema.FIELDS, plus a `runs` log."""

import sqlalchemy as sa
from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    MetaData,
    SmallInteger,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.engine import make_url

from . import schema

metadata = MetaData()

_TYPES = {
    "str": Text,
    "url": Text,
    "float": Float(53),
    "int": SmallInteger,
    "bool": Boolean,
    "date": Date,
}


def _field_columns() -> list[Column]:
    columns = []
    for field in schema.FIELDS:
        if field.type == "bool":
            columns.append(Column(field.name, Boolean, nullable=False, server_default=sa.false()))
        else:
            columns.append(Column(field.name, _TYPES[field.type], nullable=not field.required))
    return columns


places = Table(
    "places",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("slug", Text, nullable=False, unique=True),
    *_field_columns(),
    Column("body", Text, nullable=False, server_default=""),
    Column("photo_key", Text),
    Column("photo_width", Integer),
    Column("photo_height", Integer),
    Column("photo_crop_y", Float, nullable=False, server_default=sa.text("0.5")),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("published_at", DateTime(timezone=True)),
    UniqueConstraint("name", name="uq_places_name"),
    UniqueConstraint("menu", name="uq_places_menu"),
    UniqueConstraint("phone", name="uq_places_phone"),
    UniqueConstraint("place_id", name="uq_places_place_id"),
    UniqueConstraint("lat", "lon", name="uq_places_lat_lon"),
    CheckConstraint("taste BETWEEN 0 AND 3", name="ck_places_taste"),
    CheckConstraint("value BETWEEN 0 AND 3", name="ck_places_value"),
    Index("ix_places_updated_at", "updated_at"),
    Index("ix_places_area", "area"),
    Index("ix_places_cuisine", "cuisine"),
)

runs = Table(
    "runs",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("kind", Text, nullable=False),
    Column("scope", Text, nullable=False, server_default="all"),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("finished_at", DateTime(timezone=True)),
    Column("status", Text, nullable=False),  # running | ok | failed
    Column("by_email", Text),
    Column("summary", Text, nullable=False, server_default=""),
    Column("details", JSON),
    Column("snapshot_key", Text),
    Column("error", Text),
)


def make_engine(url: str):
    """Engine for a sqlite:// or postgres URL (psycopg driver; psycopg2 is not installed)."""
    parsed = make_url(url)
    if parsed.drivername in ("postgres", "postgresql"):
        parsed = parsed.set(drivername="postgresql+psycopg")
    if parsed.drivername.startswith("sqlite"):
        engine = create_engine(parsed, connect_args={"check_same_thread": False})

        @event.listens_for(engine, "connect")
        def _foreign_keys(dbapi_connection, _record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        return engine
    return create_engine(parsed, pool_pre_ping=True)


def init_db(engine) -> None:
    metadata.create_all(engine)
    # Additive migration: existing reviews and old snapshots remain compatible.
    with engine.begin() as conn:
        if "unlinked" not in {c["name"] for c in sa.inspect(conn).get_columns("places")}:
            guard = "IF NOT EXISTS " if conn.dialect.name == "postgresql" else ""
            conn.execute(sa.text(f"ALTER TABLE places ADD COLUMN {guard}unlinked BOOLEAN NOT NULL DEFAULT FALSE"))
