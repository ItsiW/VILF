"""Sync against Google: the per-place check panel on the edit page and the audit page."""

from datetime import date

from fastapi import APIRouter, Depends, Form, HTTPException, Request

from scripts import repo, runs
from scripts.audit import GROUPS, audit_rows
from scripts.cross_reference import check_place, unique_clashes
from scripts.places import PlacesError, get_place, search_text

from ..deps import current_user, get_conn, render

router = APIRouter(dependencies=[Depends(current_user)])

RECENT_RUNS = 20


def _row_or_404(conn, slug: str) -> dict:
    row = repo.get(conn, slug)
    if row is None:
        raise HTTPException(404, f"no place {slug!r}")
    return row


def _last_check(conn, slug: str) -> dict | None:
    """The newest 'check' run scoped to this slug, if any."""
    for run in runs.recent(conn, 500):
        if run["kind"] == "check" and run["scope"] == slug:
            return run
    return None


def _panel(request, conn, row, *, contact=False, result=None, error=None, outcome=None):
    mismatches = result.mismatches if result else []
    return render(
        request, "places/_sync.html", row=row, contact=contact, error=error, outcome=outcome,
        checked=result is not None,
        note=result.note if result else None, mismatches=mismatches, info=result.info if result else [],
        can_apply=bool(row["place_id"] and mismatches), last=_last_check(conn, row["slug"]),
    )


def audit_summary(report, mark_closed: bool) -> str:
    """The one-line summary the CLI logs (scripts/audit.py); kept byte-identical so runs read alike."""
    groups = report.groups
    names = lambda key: ", ".join(line.split(":")[0] for line in groups[key]) or "none"
    summary = (
        f"{report.audited} audited, {report.no_id} without place_id; "
        f"permanently closed: {names('Permanently closed')}"
        + (" (marked closed)" if mark_closed and report.closed_slugs else "")
        + f"; temporarily closed: {names('Temporarily closed')}"
    )
    if groups["Could not check"]:
        summary += f"; could not check: {names('Could not check')}"
    return summary


# --- per-place panel ---


@router.get("/places/{slug}/sync")
def sync_panel(request: Request, slug: str, conn=Depends(get_conn)):
    return _panel(request, conn, _row_or_404(conn, slug))


@router.post("/places/{slug}/sync")
def check_against_google(request: Request, slug: str, contact: str = Form("0"), conn=Depends(get_conn)):
    row = _row_or_404(conn, slug)
    contact_flag = contact == "1"
    meta, body = repo.row_to_meta(row)
    try:
        # get/search are passed here so a monkeypatched module attribute is honoured
        result = check_place(meta, body=body, slug=slug, contact=contact_flag, fix=False, get=get_place, search=search_text)
    except (PlacesError, ValueError) as e:
        return _panel(request, conn, row, contact=contact_flag, error=str(e))
    return _panel(request, conn, row, contact=contact_flag, result=result)


@router.post("/places/{slug}/sync/apply")
def apply_fixes(
    request: Request, slug: str, contact: str = Form("0"), conn=Depends(get_conn), user=Depends(current_user)
):
    row = _row_or_404(conn, slug)
    contact_flag = contact == "1"
    meta, body = repo.row_to_meta(row)
    try:
        result = check_place(meta, body=body, slug=slug, contact=contact_flag, fix=True, get=get_place, search=search_text)
    except (PlacesError, ValueError) as e:
        return _panel(request, conn, row, contact=contact_flag, error=str(e))
    fields = {k: v for k, v in result.meta.items() if v != meta[k]}
    if fields:
        clashes = unique_clashes(repo.validate_for_save(conn, {**row, **fields}), fields)
        if clashes:
            return _panel(
                request, conn, row, contact=contact_flag, result=result, outcome="not fixed: " + "; ".join(clashes)
            )
        row = repo.update(conn, slug, fields)
    summary = "fixed: " + ", ".join(result.changed) if result.changed else "nothing to fix"
    runs.append(conn, "check", summary, scope=slug, by_email=user)
    return _panel(request, conn, row, contact=contact_flag, result=result, outcome=summary)


# --- audit page ---


@router.get("/sync")
def sync_page(request: Request, conn=Depends(get_conn)):
    previous = runs.last(conn, "audit")
    last_audit = None
    if previous:
        day = previous.astimezone().date()
        last_audit = {"day": day.isoformat(), "ago": (date.today() - day).days}
    return render(request, "sync/index.html", last_audit=last_audit, recent=runs.recent(conn, RECENT_RUNS))


@router.post("/sync/audit")
def run_audit(request: Request, mark_closed: str = Form("0"), conn=Depends(get_conn), user=Depends(current_user)):
    mark = mark_closed == "1"
    rows = repo.all_rows(conn)
    report = audit_rows([(r["slug"], repo.row_to_meta(r)[0]) for r in rows], get=get_place, workers=8)
    marked = []
    if mark:
        for slug in report.closed_slugs:
            repo.update(conn, slug, {"closed": True})
        marked = list(report.closed_slugs)
    runs.append(conn, "audit", audit_summary(report, mark), scope="all", details=report.groups, by_email=user)
    return render(request, "sync/_audit.html", report=report, groups=GROUPS, marked=marked)
