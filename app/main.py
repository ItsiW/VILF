"""The VILF admin app: `uvicorn app.main:app`.

create_app(settings) wires the engine, storage and templates onto app.state and
includes whichever of app.routes.{places,photos,sync,publish} exist. The
module-level `app` is built lazily (PEP 562) so importing this module in tests
never touches the real DATABASE_URL.
"""

import importlib
import importlib.util
import hashlib
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader

from scripts import db, repo
from scripts.config import Settings
from scripts.config import settings as default_settings
from scripts.schema import TASTE_LABELS, VALUE_LABELS
from scripts.storage import guess_content_type, storage_from_url

from .deps import current_user, get_media
from .formatting import human_datetime

APP_DIR = Path(__file__).parent
ROUTERS = ("places", "photos", "sync", "publish", "backups")


def static_asset_url(name: str) -> str:
    """Change the asset URL when its contents change, avoiding stale browser CSS/JS."""
    version = hashlib.sha256((APP_DIR / "static" / name).read_bytes()).hexdigest()[:12]
    return f"/static/{name}?v={version}"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or default_settings()
    engine = db.make_engine(settings.database_url)
    db.init_db(engine)

    app = FastAPI(title="VILF admin")
    app.state.settings = settings
    app.state.engine = engine
    app.state.media = storage_from_url(settings.media_storage)
    app.state.site = storage_from_url(settings.site_storage)
    templates = Environment(loader=FileSystemLoader(str(APP_DIR / "templates")), autoescape=True)
    templates.globals.update(
        TASTE_LABELS=TASTE_LABELS, VALUE_LABELS=VALUE_LABELS, FILTERS=repo.FILTERS,
        is_dirty=repo.is_dirty, static_asset_url=static_asset_url, human_datetime=human_datetime,
    )
    app.state.templates = templates

    app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.get("/media/{key:path}", dependencies=[Depends(current_user)])
    def media_file(key: str, media=Depends(get_media)):
        """Serve a media blob (thumbs and previews in the admin); the site itself is served elsewhere."""
        try:
            data = media.get(key)
        except (FileNotFoundError, ValueError, IsADirectoryError):
            raise HTTPException(404, key)
        return Response(data, media_type=guess_content_type(key))

    for name in ROUTERS:
        if importlib.util.find_spec(f"app.routes.{name}") is None:
            continue
        _add_router(app, importlib.import_module(f"app.routes.{name}").router)
    return app


def _add_router(app: FastAPI, router: APIRouter) -> None:
    """Register a router's routes flat on the app (router-level dependencies merged in).

    FastAPI 0.141 made include_router lazy (app.routes holds _IncludedRouter
    objects without a path); flat APIRoutes keep app.routes introspectable.
    """
    for route in router.routes:
        app.add_api_route(
            route.path,
            route.endpoint,
            methods=sorted(route.methods),
            name=route.name,
            dependencies=[*router.dependencies, *route.dependencies],
            status_code=route.status_code,
            response_model=route.response_model,
            response_class=route.response_class,
            include_in_schema=route.include_in_schema,
        )


_app = None


def __getattr__(name):
    """`app.main:app` for uvicorn, created on first access from the real settings."""
    global _app
    if name == "app":
        if _app is None:
            _app = create_app()
        return _app
    raise AttributeError(name)
