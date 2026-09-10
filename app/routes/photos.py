"""Photo panel on the edit page: upload, crop preview, recrop, delete."""

import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response

from scripts import photos, repo
from scripts.images import PhotoError

from ..deps import current_user, get_conn, get_media, get_settings, render

router = APIRouter(dependencies=[Depends(current_user)])
log = logging.getLogger(__name__)


def _row_or_404(conn, slug: str) -> dict:
    row = repo.get(conn, slug)
    if row is None:
        raise HTTPException(404, f"no place {slug!r}")
    return row


def _panel(request, row: dict, error: str | None = None):
    # crop_box ignores crop_y for photos that are 16:9 or wider, so the slider only helps taller ones
    show_slider = bool(row["photo_width"] and row["photo_height"]) and (
        row["photo_width"] * 9 < row["photo_height"] * 16
    )
    return render(
        request, "photos/_panel.html", row=row, error=error, show_slider=show_slider, crop_y=row["photo_crop_y"]
    )


def _invalidate(settings, slug: str) -> None:
    """Purge the CDN copies of the variants after a replace, crop or delete; never fails the request."""
    if not (settings.google_cloud_project and settings.url_map):
        return
    try:
        from scripts.publish import GcpCdnInvalidator
    except ImportError:
        return
    paths = [p.format(slug=slug) for p in photos.VARIANT_PATHS]
    try:
        GcpCdnInvalidator(settings.google_cloud_project, settings.url_map).invalidate(paths)
    except Exception as e:  # noqa: BLE001 - a CDN hiccup must not lose the edit
        log.warning("CDN invalidation failed for %s: %s", slug, e)


@router.get("/places/{slug}/photo")
def photo_panel(request: Request, slug: str, conn=Depends(get_conn)):
    return _panel(request, _row_or_404(conn, slug))


@router.post("/places/{slug}/photo")
async def upload_photo(
    request: Request, slug: str, photo: UploadFile = File(...), conn=Depends(get_conn),
    media=Depends(get_media), settings=Depends(get_settings),
):
    row = _row_or_404(conn, slug)
    data = await photo.read()
    if not data:
        return _panel(request, row, error="Choose a photo first.")
    try:
        fields = photos.set_photo(media, slug, data)
    except PhotoError as e:
        return _panel(request, row, error=str(e))
    if row["photo_key"]:  # replacing rewrites the same variant keys, which the CDN may still hold
        _invalidate(settings, slug)
    return _panel(request, repo.update(conn, slug, fields))


@router.get("/places/{slug}/photo/preview")
def photo_preview(slug: str, crop_y: float = 0.5, conn=Depends(get_conn), media=Depends(get_media)):
    row = _row_or_404(conn, slug)
    if not row["photo_key"]:
        raise HTTPException(404, "no photo")
    data = photos.preview(media, row["photo_key"], crop_y)
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.post("/places/{slug}/photo/crop")
def crop_photo(
    request: Request, slug: str, crop_y: float = Form(...), conn=Depends(get_conn),
    media=Depends(get_media), settings=Depends(get_settings),
):
    row = _row_or_404(conn, slug)
    if not row["photo_key"]:
        return _panel(request, row, error="No photo to crop.")
    crop_y = min(max(crop_y, 0.0), 1.0)
    photos.recrop(media, row, crop_y)
    row = repo.update(conn, slug, {"photo_crop_y": crop_y})
    _invalidate(settings, slug)
    return _panel(request, row)


@router.post("/places/{slug}/photo/delete")
def delete_photo(
    request: Request, slug: str, conn=Depends(get_conn), media=Depends(get_media), settings=Depends(get_settings)
):
    row = _row_or_404(conn, slug)
    photos.delete_photo(media, slug, row["photo_key"])
    row = repo.update(conn, slug, {"photo_key": None, "photo_width": None, "photo_height": None})
    _invalidate(settings, slug)
    return _panel(request, row)
