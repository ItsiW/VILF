"""FastAPI dependencies shared by the admin routers: settings, DB connection, storage, user, render."""

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse

from scripts.config import Settings
from scripts.storage import Storage

IAP_EMAIL_HEADER = "x-goog-authenticated-user-email"
IAP_JWT_HEADER = "x-goog-iap-jwt-assertion"


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_conn(request: Request):
    """One transaction per request: committed when the route returns, rolled back when it raises."""
    with request.app.state.engine.begin() as conn:
        yield conn


def get_media(request: Request) -> Storage:
    return request.app.state.media


def get_site(request: Request) -> Storage:
    return request.app.state.site


def current_user(request: Request) -> str:
    """The signed-in email.

    Behind IAP both headers are present and the email must be the configured admin.
    Without IAP headers the dev user is used only when no admin email is configured.
    Anything else is 403.
    """
    settings = request.app.state.settings
    email_header = request.headers.get(IAP_EMAIL_HEADER)
    jwt = request.headers.get(IAP_JWT_HEADER)
    if jwt and email_header:
        email = email_header.split(":", 1)[-1]
        if settings.admin_email and email == settings.admin_email:
            request.state.user = email
            return email
        raise HTTPException(403, "not an admin")
    if not jwt and not email_header and settings.admin_email is None:
        request.state.user = settings.dev_user
        return settings.dev_user
    raise HTTPException(403, "sign in through IAP")


def render(request: Request, template: str, status_code: int = 200, **ctx) -> HTMLResponse:
    """Render app/templates/<template>; partial is true for HTMX requests."""
    context = {
        "request": request,
        "settings": request.app.state.settings,
        "user": getattr(request.state, "user", None),
        "partial": "hx-request" in request.headers,
        "flash": ctx.pop("flash", None),
        **ctx,
    }
    html = request.app.state.templates.get_template(template).render(context)
    return HTMLResponse(html, status_code=status_code)
