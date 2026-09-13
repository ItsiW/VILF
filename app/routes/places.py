"""Places: list, create (with Google lookup), edit, delete, preview, relink."""

from datetime import date

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from jinja2 import Environment, FileSystemLoader

from scripts import photos, repo, schema
from scripts.config import REPO_ROOT
from scripts.neighborhoods import suggest_area
from scripts.places import CONTACT_FIELDS, PlacesError, get_place, search_text
from scripts.render import enrich_place, render_place_page
from scripts.spatula import BOLD_PROBLEM, find_duplicate, place_to_meta, query_from_maps_url, slugify

from ..deps import current_user, get_conn, get_media, get_settings, render

router = APIRouter(dependencies=[Depends(current_user)])

FLASHES = {"created": "Created", "relinked": "Relinked to Google"}


# --- helpers ---


def _form_meta(form) -> tuple[dict, str]:
    """Every schema field from a posted form, plus the body.

    Empty strings become None; numbers that do not parse stay as strings so
    validate_place reports them instead of a crash.
    """
    meta = {}
    for field in schema.FIELDS:
        if field.type == "bool":
            meta[field.name] = field.name in form
            continue
        raw = (form.get(field.name) or "").strip()
        if raw == "":
            meta[field.name] = None
        elif field.type == "float":
            try:
                meta[field.name] = float(raw)
            except ValueError:
                meta[field.name] = raw
        elif field.type == "int":
            try:
                meta[field.name] = int(raw)
            except ValueError:
                meta[field.name] = raw
        else:
            meta[field.name] = raw
    body = (form.get("body") or "").replace("\r\n", "\n")
    return meta, body


def _validate(conn, row: dict, *, old_slug: str | None = None) -> tuple[list[str], list[str]]:
    """(errors, warnings): the missing-bold-dish problem is only a warning while drafting.

    place_id is unique in the database but not covered by schema.validate_unique,
    so it is checked here rather than surfacing as an IntegrityError.
    """
    problems = repo.validate_for_save(conn, row, old_slug=old_slug)
    if row.get("place_id"):
        skip = {row.get("slug"), old_slug}
        for other in repo.all_rows(conn):
            if other["slug"] not in skip and other["place_id"] == row["place_id"]:
                problems.append(f"place_id {row['place_id']!r} reused by {other['slug']}")
    errors = [p for p in problems if p != BOLD_PROBLEM]
    warnings = [p for p in problems if p == BOLD_PROBLEM]
    return errors, warnings


def _lists(conn) -> dict:
    return {"cuisines": repo.distinct_values(conn, "cuisine"), "areas": repo.distinct_values(conn, "area")}


def _candidates(conn, results, *, exclude: str | None = None) -> list[tuple]:
    rows = [r for r in repo.all_rows(conn) if r["slug"] != exclude]
    return [
        (p, find_duplicate({"place_id": p.place_id, "lat": p.lat, "lon": p.lon}, rows)) for p in results
    ]


def _row_or_404(conn, slug: str) -> dict:
    row = repo.get(conn, slug)
    if row is None:
        raise HTTPException(404, f"no place {slug!r}")
    return row


def _edit_page(request, conn, row, *, meta=None, body=None, status_code=200, flash=None,
               problems=None, warnings=None) -> HTMLResponse:
    if meta is None:
        meta, body = repo.row_to_meta(row)
    if problems is None:
        problems, warnings = _validate(conn, dict(row, **meta, body=body), old_slug=row["slug"])
    return render(
        request, "places/edit.html", status_code, mode="edit", slug=row["slug"], row=row, meta=meta,
        body=body, problems=problems, warnings=warnings, flash=flash, **_lists(conn),
    )


# --- routes; /places/new must be registered before /places/{slug} ---


@router.get("/")
def home():
    return RedirectResponse("/places", status_code=302)


@router.get("/places")
def list_places(request: Request, q: str = "", filter: str | None = None, conn=Depends(get_conn)):
    if filter not in repo.FILTERS:
        filter = None
    rows = repo.search(conn, q, filter)
    template = "places/_table.html" if "hx-request" in request.headers else "places/list.html"
    return render(request, template, rows=rows, q=q, filter=filter)


@router.get("/places/new")
def new_place(request: Request, conn=Depends(get_conn)):
    meta = {key: schema.DEFAULTS.get(key) for key in schema.KNOWN_KEYS}
    meta["visited"] = date.today().isoformat()
    return render(request, "places/new.html", mode="create", meta=meta, body="", form_open=False, **_lists(conn))


@router.post("/places/new/search")
def search_candidates(request: Request, q: str = Form(""), conn=Depends(get_conn)):
    try:
        q = query_from_maps_url(q) or q.strip()
        results = search_text(q, max_results=5)
    except PlacesError as e:
        return render(request, "places/_error.html", message=str(e))
    return render(request, "places/_candidates.html", candidates=_candidates(conn, results), action="pick")


@router.post("/places/new/pick")
def pick_candidate(request: Request, place_id: str = Form(...), conn=Depends(get_conn)):
    meta = {key: schema.DEFAULTS.get(key) for key in schema.KNOWN_KEYS}
    problems, maps_url, area_suggestion = [], None, None
    try:
        place = get_place(place_id, fields=CONTACT_FIELDS)
        meta.update(place_to_meta(place))
        area_suggestion = suggest_area(place.lat, place.lon)
        if area_suggestion:
            meta["area"] = area_suggestion
        maps_url = place.maps_url
    except PlacesError as e:
        problems = [str(e)]
    meta["visited"] = date.today().isoformat()
    return render(
        request, "places/_form.html", mode="create", meta=meta, body="", form_open=True,
        maps_url=maps_url, problems=problems, area_suggestion=area_suggestion, **_lists(conn),
    )


@router.post("/places")
async def create_place(request: Request, conn=Depends(get_conn)):
    form = await request.form()
    meta, body = _form_meta(form)
    street_in_slug = "street_in_slug" in form
    slug = ""
    if meta["name"]:
        street = meta["address"] if street_in_slug and isinstance(meta["address"], str) else None
        slug = repo.unique_slug(conn, slugify(meta["name"], street))
    row = repo.meta_to_row(meta, body, slug=slug)
    errors, warnings = _validate(conn, row)
    if errors:
        return render(
            request, "places/new.html", 422, mode="create", meta=meta, body=body, form_open=True,
            street_in_slug=street_in_slug, problems=errors, warnings=warnings, **_lists(conn),
        )
    repo.insert(conn, row)
    return RedirectResponse(f"/places/{slug}?flash=created", status_code=303)


@router.get("/places/{slug}")
def edit_place(request: Request, slug: str, flash: str | None = None, conn=Depends(get_conn)):
    row = _row_or_404(conn, slug)
    return _edit_page(request, conn, row, flash=FLASHES.get(flash))


@router.post("/places/{slug}")
async def save_place(request: Request, slug: str, conn=Depends(get_conn)):
    row = _row_or_404(conn, slug)
    meta, body = _form_meta(await request.form())
    # Google identity changes only through the explicit relink workflow.
    meta["place_id"] = row["place_id"]
    candidate = dict(row, **meta, body=body)
    errors, warnings = _validate(conn, candidate, old_slug=slug)
    if errors:
        return _edit_page(request, conn, row, meta=meta, body=body, status_code=422, problems=errors, warnings=warnings)
    row = repo.update(conn, slug, {**meta, "body": body})
    return _edit_page(request, conn, row, flash="Saved")


@router.post("/places/{slug}/delete")
def delete_place(request: Request, slug: str, conn=Depends(get_conn), media=Depends(get_media)):
    row = _row_or_404(conn, slug)
    try:
        repo.delete(conn, slug)
    except ValueError as e:
        return PlainTextResponse(str(e), status_code=409)
    # the freed slug can be handed out again by unique_slug, so leave no stale photo behind
    photos.delete_photo(media, slug, row["photo_key"])
    if "hx-request" in request.headers:
        return Response(status_code=200, headers={"HX-Redirect": "/places"})
    return RedirectResponse("/places", status_code=303)


@router.get("/places/{slug}/preview")
def preview_place(slug: str, conn=Depends(get_conn), settings=Depends(get_settings)):
    """The public page for this row, rendered with the site's own templates."""
    row = _row_or_404(conn, slug)
    meta, body = repo.row_to_meta(row)
    problems = schema.validate_place(meta, body, slug)
    if problems:
        return PlainTextResponse("Cannot preview yet:\n" + "\n".join(problems), status_code=422)
    env = Environment(loader=FileSystemLoader(str(REPO_ROOT / "html")))
    env.globals["SITE_URL"] = settings.site_url
    return HTMLResponse(render_place_page(env, enrich_place(row, today=date.today())))


@router.post("/places/{slug}/relink")
def relink_place(
    request: Request, slug: str, q: str = Form(""), place_id: str = Form(""), conn=Depends(get_conn)
):
    """q -> candidates partial; place_id -> take Google's location data (name stays) and redirect."""
    row = _row_or_404(conn, slug)
    if place_id:
        try:
            place = get_place(place_id, fields=CONTACT_FIELDS)
        except PlacesError as e:
            return _edit_page(request, conn, row, status_code=502, problems=[str(e)], warnings=[])
        fields = {
            "place_id": place.place_id, "city": place.city, "lat": place.lat, "lon": place.lon,
            "address": place.street_address,
        }
        if not row["phone"]:
            fields["phone"] = place.phone
        if not row["website"]:
            fields["website"] = place.website
        errors, warnings = _validate(conn, dict(row, **fields), old_slug=slug)
        if errors:
            return _edit_page(request, conn, row, status_code=422, problems=errors, warnings=warnings)
        repo.update(conn, slug, fields)
        return RedirectResponse(f"/places/{slug}?flash=relinked", status_code=303)
    if q.strip():
        try:
            q = query_from_maps_url(q) or q.strip()
            results = search_text(q, max_results=5)
        except PlacesError as e:
            return render(request, "places/_error.html", message=str(e))
        return render(
            request, "places/_candidates.html", candidates=_candidates(conn, results, exclude=slug),
            action="relink", slug=slug,
        )
    raise HTTPException(400, "q or place_id required")
