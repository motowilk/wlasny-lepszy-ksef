from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes.accounting import router as accounting_router
from app.api.routes.agent import router as agent_router
from app.api.routes.auth import router as auth_router
from app.api.routes.invoices import router as invoices_router
from app.api.routes.notifications import router as notifications_router
from app.api.routes.purchase_invoices import router as purchase_invoices_router
from app.api.routes.users import router as users_router
from app.core.config import settings
from app.core.logging import configure_logging
from app.ui.routes import router as ui_router

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
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

app.include_router(auth_router)
app.include_router(users_router)
app.include_router(invoices_router)
app.include_router(purchase_invoices_router)
app.include_router(accounting_router)
app.include_router(notifications_router)
app.include_router(agent_router)
app.include_router(ui_router)


@app.get("/health", tags=["system"])
def health() -> JSONResponse:
    return JSONResponse({"status": "ok"})
