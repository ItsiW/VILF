"""Publish: pending diff and problems, the Publish button, and the publish/restore/import history."""

from fastapi import APIRouter, Depends, Form, Request

from scripts import publish as publish_mod
from scripts import repo, runs
from scripts.config import REPO_ROOT
from scripts.publish import GcpCdnInvalidator, PublishRunning

from ..deps import current_user, get_conn, get_media, get_settings, get_site, render

router = APIRouter(dependencies=[Depends(current_user)])

HISTORY_KINDS = ("publish", "restore", "import")
# publish() defaults are cwd-relative; the app may be started from anywhere (tests point these at a tmp dir)
HTML_DIR = REPO_ROOT / "html"
STATIC_DIR = REPO_ROOT / "static"
ABOUT_PATH = REPO_ROOT / "about.md"


def _runs_of(conn, kinds, n: int = 500) -> list[dict]:
    return [r for r in runs.recent(conn, n) if r["kind"] in kinds]


def _pending(conn, media) -> dict:
    rows = repo.all_rows(conn)
    last = _runs_of(conn, ("publish",))
    return {
        "problems": publish_mod.validate_rows(rows),
        "diff": publish_mod.pending_diff(conn, media),
        "last": last[0] if last else None,
        "running": runs.running(conn, "publish"),
        "names": {r["slug"]: r["name"] for r in rows},
    }


@router.get("/publish")
def publish_page(request: Request, conn=Depends(get_conn), media=Depends(get_media)):
    template = "publish/_pending.html" if "hx-request" in request.headers else "publish/index.html"
    return render(request, template, **_pending(conn, media))


@router.post("/publish")
def run_publish(
    request: Request, force: str = Form("0"), conn=Depends(get_conn), media=Depends(get_media),
    site=Depends(get_site), settings=Depends(get_settings), user=Depends(current_user),
):
    cdn = None
    if settings.google_cloud_project and settings.url_map:
        cdn = GcpCdnInvalidator(settings.google_cloud_project, settings.url_map)
    try:
        # first write on this request's connection: publish() commits its own 'running' row separately
        result = publish_mod.publish(
            conn, media=media, site=site, settings=settings, cdn=cdn, by_email=user, force=force == "1",
            html_dir=HTML_DIR, static_dir=STATIC_DIR, about_path=ABOUT_PATH,
        )
    except PublishRunning as e:
        return render(request, "publish/_result.html", 409, running_error=str(e))
    counts = None
    if result.changes is not None:
        counts = (len(result.changes.added), len(result.changes.removed), len(result.changes.changed))
    return render(request, "publish/_result.html", result=result, cdn_configured=cdn is not None, counts=counts)


@router.get("/publishes")
def publish_history(request: Request, conn=Depends(get_conn)):
    return render(request, "publish/history.html", runs=_runs_of(conn, HISTORY_KINDS))
