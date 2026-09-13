"""Read-only backup dashboard; no restore or job execution endpoints."""

from fastapi import APIRouter, Depends, Request

from scripts.backup_history import overview
from ..deps import current_user, get_settings, render

router = APIRouter(dependencies=[Depends(current_user)])


@router.get("/backups")
def backups_page(request: Request, settings=Depends(get_settings)):
    return render(request, "backups/index.html", **overview(settings))
