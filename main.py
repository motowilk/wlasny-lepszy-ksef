from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.api.routes.accounting import router as accounting_router
from app.api.routes.agent import router as agent_router
from app.api.routes.auth import router as auth_router
from app.api.routes.invoices import router as invoices_router
from app.api.routes.notifications import router as notifications_router
from app.api.routes.purchase_invoices import router as purchase_invoices_router
from app.api.routes.users import router as users_router
from app.core.config import settings
from app.core.logging import configure_logging
from app.core.security import decode_ui_session_token, verify_csrf_token
from app.ui.routes import UIAuthRequired, UIForbidden, _SESSION_COOKIE_NAME, _UI_SESSION_NONCE_KEY, router as ui_router

configure_logging()

_STATIC_DIR = Path(__file__).resolve().parent / "app" / "static"

app = FastAPI(
    title=settings.app_name,
    debug=settings.app_debug,
    version="1.0.0",
)

# CORS: No CORSMiddleware is configured intentionally — this app uses HTTP
# Basic Auth over server-side rendered HTML and is not designed to be called
# from a browser JS client on a different origin.  If you expose the REST API
# (/api/*) to a front-end app on a different origin, add CORSMiddleware here
# and restrict allow_origins to your specific trusted domain(s).

# ── CSRF middleware for UI POST requests ──────────────────────────────────
_CSRF_EXEMPT_PATHS = {"/ui/login", "/ui/login/totp"}


class CSRFMiddleware(BaseHTTPMiddleware):
    """Validate CSRF token on all UI POST requests (except login flows)."""

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.method == "POST" and request.url.path.startswith("/ui"):
            # Strip root_path prefix for comparison
            from urllib.parse import urlparse as _up
            rp = _up(settings.base_url).path.rstrip("/")
            rel_path = request.url.path
            if rp and rel_path.startswith(rp):
                rel_path = rel_path[len(rp):]

            if rel_path not in _CSRF_EXEMPT_PATHS:
                # Read session cookie and extract nonce
                cookie_name = _SESSION_COOKIE_NAME
                session_token = request.cookies.get(cookie_name)
                if session_token:
                    token_data = decode_ui_session_token(session_token, settings.secret_key)
                    if token_data:
                        session_nonce = token_data.get("session_nonce", "")
                        # Read raw body and check for _csrf field
                        body = await request.body()
                        from urllib.parse import parse_qs
                        form_data = parse_qs(body.decode("utf-8", errors="replace"))
                        csrf_values = form_data.get("_csrf", [])
                        csrf_token = csrf_values[0] if csrf_values else None
                        if not verify_csrf_token(csrf_token, session_nonce, settings.secret_key):
                            return Response("CSRF token invalid.", status_code=403)

        return await call_next(request)


app.add_middleware(CSRFMiddleware)


# ── Security headers middleware ───────────────────────────────────────────
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add standard security headers to every response."""

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
        if settings.base_url.startswith("https://"):
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "frame-ancestors 'none'"
        )
        return response


app.add_middleware(SecurityHeadersMiddleware)

app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

app.include_router(auth_router)
app.include_router(users_router)
app.include_router(invoices_router)
app.include_router(purchase_invoices_router)
app.include_router(accounting_router)
app.include_router(notifications_router)
app.include_router(agent_router)
app.include_router(ui_router)


@app.exception_handler(UIAuthRequired)
async def ui_auth_required_handler(request: Request, exc: UIAuthRequired) -> RedirectResponse:
    from urllib.parse import urlparse as _urlparse
    _rp = _urlparse(settings.base_url).path.rstrip("/")
    return RedirectResponse(url=f"{_rp}/ui/login", status_code=302)


@app.exception_handler(UIForbidden)
async def ui_forbidden_handler(request: Request, exc: UIForbidden) -> RedirectResponse:
    from urllib.parse import quote, urlparse as _urlparse
    _rp = _urlparse(settings.base_url).path.rstrip("/")
    return RedirectResponse(url=f"{_rp}/ui?error={quote(exc.detail)}", status_code=303)


@app.get("/health", tags=["system"])
def health() -> JSONResponse:
    return JSONResponse({"status": "ok"})
