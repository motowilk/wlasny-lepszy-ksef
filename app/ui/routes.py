import io
import re
import secrets
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import quote as _url_quote

from fastapi import APIRouter, Cookie, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy import delete as sql_delete, func, select
from sqlalchemy.exc import IntegrityError as SAIntegrityError
from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.core.iban_lookup import resolve_iban
from app.core.security import (
    create_totp_pending_token,
    create_ui_session_token,
    decode_totp_pending_token,
    decode_ui_session_token,
    get_password_hash,
    normalize_username,
    verify_password,
)
from app.db.dependencies import get_db
from app.db.models import (
    AccountingBatch,
    AccountingBatchInvoice,
    AppRole,
    AppUser,
    AppUserRole,
    IntegrationJob,
    Invoice,
    InvoiceParty,
    NotificationLog,
    Party,
)
from app.adapters.notification.discord import DiscordNotificationAdapter
from app.core.job_registry import JOB_TYPE_LABELS
from app.core.status_registry import (
    get_status_label,
    get_status_pill_class,
)
from app.schemas.invoice import (
    InvoiceCreateRequest,
    InvoiceLinePayload,
    InvoicePartyPayload,
    InvoiceUpdateRequest,
    PartyPayload,
)
from app.services.invoice_service import InvoiceService
from app.services.validation_service import ValidationService

from urllib.parse import urlparse

_TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
_UI_SESSION_NONCE_KEY = "ui_session_nonce"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

# Derive root_path from BASE_URL so templates can prefix all URLs.
# Locally (BASE_URL=http://127.0.0.1:8000) this is ""; on the server it's "/wlasny-lepszy-ksef-test".
_root_path = urlparse(settings.base_url).path.rstrip("/")
templates.env.globals["root_path"] = _root_path


def _plnum(value) -> str:
    """Format a number for Polish locale display (comma as decimal separator)."""
    if value is None:
        return ""
    s = str(value)
    # Replace only the last dot (decimal separator), leave others intact
    if "." in s:
        s = s.replace(".", ",")
    return s


templates.env.filters["plnum"] = _plnum
templates.env.globals["status_label"] = get_status_label
templates.env.globals["status_pill_class"] = get_status_pill_class

router = APIRouter(tags=["ui"])


def _use_secure_cookies() -> bool:
    return settings.base_url.startswith("https://")


def _get_user_session_nonce(user: AppUser) -> str | None:
    metadata = user.metadata_json or {}
    session_nonce = metadata.get(_UI_SESSION_NONCE_KEY)
    return session_nonce if isinstance(session_nonce, str) and session_nonce else None


def _rotate_user_session_nonce(user: AppUser) -> str:
    metadata = dict(user.metadata_json or {})
    metadata[_UI_SESSION_NONCE_KEY] = secrets.token_urlsafe(24)
    user.metadata_json = metadata
    return metadata[_UI_SESSION_NONCE_KEY]


def _resolve_ui_user(db: Session, session_token: str | None) -> AppUser:
    if not session_token:
        raise UIAuthRequired()

    token_data = decode_ui_session_token(session_token, settings.secret_key)
    if token_data is None:
        raise UIAuthRequired()

    stmt = (
        select(AppUser)
        .where(AppUser.id == int(token_data["user_id"]))
        .options(joinedload(AppUser.roles).joinedload(AppUserRole.role))
    )
    user = db.execute(stmt).unique().scalar_one_or_none()
    if not user or not user.is_active or user.is_locked:
        raise UIAuthRequired()

    session_nonce = _get_user_session_nonce(user)
    if session_nonce != token_data["session_nonce"]:
        raise UIAuthRequired()

    return user


@router.get("/ui/api/worker-status")
def ui_worker_status(
    db: Session = Depends(get_db),
    session_token: str | None = Cookie(default=None, alias="session"),
):
    """Return live worker heartbeat data for the status widget.

    Uses cookie auth directly so the browser-side fetch gets JSON 401
    instead of an HTML login-page redirect.
    """
    import json as _json
    from fastapi.responses import JSONResponse
    from app.db.models.worker_heartbeat import WorkerHeartbeat

    try:
        _resolve_ui_user(db, session_token)
    except UIAuthRequired:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    STALE_SECONDS = settings.scheduler_stale_seconds

    now = datetime.now(tz=timezone.utc)
    heartbeats = (
        db.execute(select(WorkerHeartbeat).order_by(WorkerHeartbeat.worker_id))
        .scalars()
        .all()
    )

    new_count = (
        db.scalar(
            select(func.count())
            .select_from(IntegrationJob)
            .where(IntegrationJob.status == "NEW")
        )
        or 0
    )
    processing_count = (
        db.scalar(
            select(func.count())
            .select_from(IntegrationJob)
            .where(IntegrationJob.status == "PROCESSING")
        )
        or 0
    )

    # Find the scheduler heartbeat
    scheduler_hb = None
    for hb in heartbeats:
        if hb.worker_id == "scheduler":
            scheduler_hb = hb
            break

    is_running = False
    seconds_since_heartbeat = None
    seconds_since_last_tick = None
    hb_status = None
    hb_job_type = None
    hb_job_id = None
    if scheduler_hb:
        hb_time = scheduler_hb.last_heartbeat_at
        if hb_time.tzinfo is None:
            hb_time = hb_time.replace(tzinfo=timezone.utc)
        seconds_since_heartbeat = max(0, int((now - hb_time).total_seconds()))
        is_running = seconds_since_heartbeat < STALE_SECONDS
        hb_status = scheduler_hb.status
        hb_job_type = scheduler_hb.current_job_type
        hb_job_id = scheduler_hb.current_job_id

        # Compute seconds since the last completed tick
        if scheduler_hb.last_tick_at:
            tick_time = scheduler_hb.last_tick_at
            if tick_time.tzinfo is None:
                tick_time = tick_time.replace(tzinfo=timezone.utc)
            seconds_since_last_tick = max(0, int((now - tick_time).total_seconds()))

    # Determine phase from DB heartbeat + in-memory state (if same process)
    # Priority: DB heartbeat is the source of truth for running/not-running.
    if not is_running:
        phase = "idle"
        current_jobs = []
    elif hb_status == "ACTIVE":
        phase = "processing"
        # Read job list from DB
        current_jobs = _json.loads(scheduler_hb.current_jobs_json) if scheduler_hb.current_jobs_json else []
        if not current_jobs and hb_job_type:
            current_jobs = [{"job_id": hb_job_id, "job_type": hb_job_type, "status": "running"}]
    else:
        # Heartbeat is IDLE and fresh → read phase from DB
        db_phase = scheduler_hb.phase if scheduler_hb else None
        if db_phase == "cooldown":
            phase = "cooldown"
            current_jobs = _json.loads(scheduler_hb.current_jobs_json) if scheduler_hb.current_jobs_json else []
        else:
            phase = "idle"
            current_jobs = []

    return JSONResponse(
        {
            "running": is_running,
            "seconds_since_heartbeat": seconds_since_heartbeat,
            "seconds_since_last_tick": seconds_since_last_tick,
            "phase": phase,
            "current_jobs": current_jobs,
            "queue": {"new": new_count, "processing": processing_count},
            "scheduler_interval": settings.scheduler_interval,
            "job_type_labels": JOB_TYPE_LABELS,
        }
    )


class UIAuthRequired(Exception):
    """Raised when a UI route requires an authenticated session cookie."""


class UIForbidden(Exception):
    """Raised when a UI user lacks the required role."""
    def __init__(self, detail: str = "Brak uprawnień."):
        self.detail = detail


def get_current_ui_user(
    db: Session = Depends(get_db),
    session_token: str | None = Cookie(default=None, alias="session"),
) -> AppUser:
    return _resolve_ui_user(db, session_token)


def ui_require_roles(*role_codes: str):
    def dependency(current_user: AppUser = Depends(get_current_ui_user)) -> AppUser:
        current_roles = {item.role.role_code for item in current_user.roles}
        if not any(role in current_roles for role in role_codes):
            raise UIForbidden(f"Brak wymaganej roli. Wymagane: {', '.join(role_codes)}")
        return current_user
    return dependency


@router.get("/")
def root_redirect() -> RedirectResponse:
    return RedirectResponse(url=f"{_root_path}/ui", status_code=302)


@router.get("/ui/login")
def login_form(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@router.post("/ui/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    normalized = normalize_username(username)
    stmt = (
        select(AppUser)
        .where(AppUser.username == normalized)
        .options(joinedload(AppUser.roles).joinedload(AppUserRole.role))
    )
    user = db.execute(stmt).unique().scalar_one_or_none()

    if (
        not user
        or not user.is_active
        or user.is_locked
        or not verify_password(password, user.password_hash)
    ):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Nieprawidłowy login lub hasło."},
            status_code=401,
        )

    # If TOTP is configured, issue a short-lived pending token and redirect to
    # the TOTP verification step instead of creating the full session immediately.
    if user.totp_secret:
        pending = create_totp_pending_token(user.id, settings.secret_key)
        resp = RedirectResponse(url=f"{_root_path}/ui/login/totp", status_code=303)
        resp.set_cookie(
            "totp_pending",
            pending,
            httponly=True,
            samesite="lax",
            secure=_use_secure_cookies(),
            max_age=300,
        )
        return resp

    user.last_login_at = datetime.now(tz=timezone.utc)
    session_nonce = _rotate_user_session_nonce(user)
    db.commit()

    DiscordNotificationAdapter().send(
        f"Właśnie zalogował się {user.display_name} - {user.email} - {datetime.now(tz=timezone.utc)}"
    )

    token = create_ui_session_token(user.id, settings.secret_key, session_nonce)
    resp = RedirectResponse(url=f"{_root_path}/ui", status_code=303)
    resp.set_cookie(
        "session",
        token,
        httponly=True,
        samesite="lax",
        secure=_use_secure_cookies(),
        max_age=settings.ui_session_max_age,
    )
    return resp


@router.get("/ui/login/totp")
def totp_form(
    request: Request,
    totp_pending: str | None = Cookie(default=None),
):
    if not totp_pending or decode_totp_pending_token(totp_pending, settings.secret_key) is None:
        return RedirectResponse(url=f"{_root_path}/ui/login", status_code=302)
    return templates.TemplateResponse("totp.html", {"request": request})


@router.post("/ui/login/totp")
def totp_submit(
    request: Request,
    code: str = Form(...),
    totp_pending: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    import pyotp

    user_id = (
        decode_totp_pending_token(totp_pending, settings.secret_key) if totp_pending else None
    )
    if user_id is None:
        return RedirectResponse(url=f"{_root_path}/ui/login", status_code=302)

    user = db.get(AppUser, user_id)
    if not user or not user.is_active or user.is_locked:
        return RedirectResponse(url=f"{_root_path}/ui/login", status_code=302)

    if not pyotp.TOTP(user.totp_secret).verify(code.strip()):
        resp = templates.TemplateResponse(
            "totp.html",
            {"request": request, "error": "Nieprawidłowy kod. Spróbuj ponownie."},
            status_code=401,
        )
        return resp

    user.last_login_at = datetime.now(tz=timezone.utc)
    session_nonce = _rotate_user_session_nonce(user)
    db.commit()

    DiscordNotificationAdapter().send(
        f"Właśnie zalogował się {user.display_name} - {user.email} - {datetime.now(tz=timezone.utc)}"
    )

    session_token = create_ui_session_token(user.id, settings.secret_key, session_nonce)
    resp = RedirectResponse(url=f"{_root_path}/ui", status_code=303)
    resp.set_cookie(
        "session",
        session_token,
        httponly=True,
        samesite="lax",
        secure=_use_secure_cookies(),
        max_age=settings.ui_session_max_age,
    )
    resp.delete_cookie("totp_pending")
    return resp


@router.post("/ui/logout")
def logout(
    db: Session = Depends(get_db),
    session_token: str | None = Cookie(default=None, alias="session"),
):
    try:
        user = _resolve_ui_user(db, session_token)
    except UIAuthRequired:
        user = None

    if user is not None:
        _rotate_user_session_nonce(user)
        db.commit()

    resp = RedirectResponse(url=f"{_root_path}/ui/login", status_code=302)
    resp.delete_cookie("session", secure=_use_secure_cookies())
    return resp


@router.get("/ui")
def dashboard(
    request: Request,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_ui_user),
    error: str | None = None,
):
    stats = {
        "total_invoices": db.scalar(select(func.count()).select_from(Invoice)),
        "sale_invoices": db.scalar(
            select(func.count()).select_from(Invoice).where(Invoice.direction_code == "SALE")
        ),
        "purchase_invoices": db.scalar(
            select(func.count()).select_from(Invoice).where(Invoice.direction_code == "PURCHASE")
        ),
        "notifications": db.scalar(select(func.count()).select_from(NotificationLog)),
        "pakiety": db.scalar(select(func.count()).select_from(AccountingBatch)),
    }

    latest_invoices = list(
        db.execute(
            select(Invoice)
            .options(
                joinedload(Invoice.parties).joinedload(InvoiceParty.party),
            )
            .order_by(Invoice.id.desc())
            .limit(10)
        )
        .unique()
        .scalars()
        .all()
    )

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "current_user": current_user,
            "stats": stats,
            "latest_invoices": latest_invoices,
            "error": error,
        },
    )


@router.get("/ui/invoices")
def invoices_list(
    request: Request,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_ui_user),
    error: str | None = None,
):
    items = list(
        db.execute(
            select(Invoice)
            .options(
                joinedload(Invoice.lines),
                joinedload(Invoice.parties).joinedload(InvoiceParty.party),
            )
            .where(Invoice.direction_code == "SALE")
            .order_by(Invoice.id.desc())
        )
        .unique()
        .scalars()
        .all()
    )

    return templates.TemplateResponse(
        "invoices_list.html",
        {
            "request": request,
            "current_user": current_user,
            "items": items,
            "title": "Faktury sprzedażowe",
            "error": error,
        },
    )


@router.get("/ui/purchase-invoices")
def purchase_invoices_list(
    request: Request,
    fetch_result: int | None = None,
    fetch_error: str | None = None,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_ui_user),
):
    items = list(
        db.execute(
            select(Invoice)
            .options(
                joinedload(Invoice.lines),
                joinedload(Invoice.parties).joinedload(InvoiceParty.party),
            )
            .where(Invoice.direction_code == "PURCHASE")
            .order_by(Invoice.id.desc())
        )
        .unique()
        .scalars()
        .all()
    )

    return templates.TemplateResponse(
        "purchase_invoices_list.html",
        {
            "request": request,
            "current_user": current_user,
            "items": items,
            "fetch_result": fetch_result,
            "fetch_error": fetch_error,
        },
    )


@router.post("/ui/purchase-invoices/fetch-ksef")
def purchase_invoices_fetch_ksef(
    request: Request,
    date_from: str = Form(...),
    date_to: str = Form(...),
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_ui_user),
):
    from app.services.ksef_import_service import KsefImportService
    from urllib.parse import urlencode

    try:
        imported = KsefImportService.fetch_and_import_purchases(
            db=db,
            date_from=f"{date_from}T00:00:00",
            date_to=f"{date_to}T23:59:59",
            actor_id=str(current_user.id),
        )
        params = urlencode({"fetch_result": len(imported)})
    except Exception as exc:
        params = urlencode({"fetch_error": str(exc)})

    return RedirectResponse(
        url=f"/ui/purchase-invoices?{params}",
        status_code=303,
    )


@router.get("/ui/iban-lookup")
def iban_lookup(
    iban: str = "",
    current_user: AppUser = Depends(ui_require_roles("admin", "agent", "reviewer")),
):
    return resolve_iban(iban)


@router.get("/ui/invoices/new")
def invoice_new_form(
    request: Request,
    clone: int | None = None,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(ui_require_roles("admin", "agent", "reviewer")),
):
    all_parties = list(
        db.execute(select(Party).where(Party.is_active.is_(True)).order_by(Party.name_full))
        .scalars()
        .all()
    )

    today_str = str(date.today())
    prefill: dict = {
        "issue_date": today_str,
        "sale_date": today_str,
        "due_date": today_str,
    }
    if clone:
        src = (
            db.execute(
                select(Invoice)
                .options(
                    joinedload(Invoice.lines),
                    joinedload(Invoice.parties).joinedload(InvoiceParty.party),
                )
                .where(Invoice.id == clone)
            )
            .unique()
            .scalar_one_or_none()
        )
        if src:
            fa_meta = src.fa_metadata or {}
            prefill = {
                "invoice_number": "",
                "issue_date": str(src.issue_date),
                "issue_place": fa_meta.get("issue_place", ""),
                "sale_date": str(src.sale_date) if src.sale_date else "",
                "due_date": str(src.due_date) if src.due_date else "",
                "currency_code": src.currency_code,
                "exchange_rate": str(src.exchange_rate) if src.exchange_rate else "",
                "payment_method": src.payment_method or "",
                "payment_account": src.payment_account or "",
                "payment_swift": fa_meta.get("payment_swift", ""),
                "payment_bank_name": fa_meta.get("payment_bank_name", ""),
                "contract_date": fa_meta.get("contract_date", ""),
                "contract_number": fa_meta.get("contract_number", ""),
                "footer_note": fa_meta.get("footer_note", ""),
            }
            for ip in src.parties:
                party = ip.party
                if not party:
                    continue
                if ip.role_code == "SELLER":
                    prefill["seller_party_id"] = party.id
                elif ip.role_code == "BUYER":
                    prefill["buyer_party_id"] = party.id
            lines_data = []
            for line in sorted(src.lines, key=lambda l: l.line_no):
                lm = line.line_metadata or {}
                exr = lm.get("exchange_rate")
                lines_data.append({
                    "description": line.product_name,
                    "unit": line.unit_code or "",
                    "qty": str(line.quantity),
                    "price": str(line.unit_price_net),
                    "vat_code": line.vat_code or ("23" if line.vat_rate else "oo"),
                    "exchange_rate": str(exr) if exr else "",
                })
            prefill["lines"] = lines_data

    return templates.TemplateResponse(
        "invoice_form.html",
        {
            "request": request,
            "current_user": current_user,
            "mode": "create",
            "prefill": prefill,
            "parties": all_parties,
            "parties_json": [
                {"id": p.id, "bank_account": p.bank_account or ""}
                for p in all_parties
            ],
        },
    )


@router.post("/ui/invoices/new")
async def invoice_create_submit(
    request: Request,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(ui_require_roles("admin", "agent", "reviewer")),
):
    form = await request.form()

    def _s(key: str, default: str = "") -> str:
        return (form.get(key) or default).strip()

    invoice_number = _s("invoice_number")
    issue_date_str = _s("issue_date")
    issue_place = _s("issue_place")
    sale_date_str = _s("sale_date")
    due_date_str = _s("due_date")
    currency_code = _s("currency_code", "PLN") or "PLN"
    exchange_rate_str = _s("exchange_rate")
    payment_method = _s("payment_method") or None
    payment_account = _s("payment_account") or None
    payment_swift = _s("payment_swift")
    payment_bank_name = _s("payment_bank_name")

    seller_party_id_str = _s("seller_party_id")
    buyer_party_id_str = _s("buyer_party_id")

    contract_date_str = _s("contract_date")
    contract_number = _s("contract_number")
    footer_note = _s("footer_note")

    line_count = int(_s("line_count", "0") or "0")

    vat_rate_map: dict = {
        "23": Decimal("23"), "8": Decimal("8"), "5": Decimal("5"),
        "0": Decimal("0"), "oo": None, "np": None,
    }

    try:
        # Build lines
        lines = []
        for i in range(1, line_count + 1):
            desc = _s(f"line_description_{i}")
            if not desc:
                continue
            unit = _s(f"line_unit_{i}") or None
            qty = _s(f"line_qty_{i}", "1") or "1"
            price = _s(f"line_price_{i}", "0") or "0"
            vat_code = _s(f"line_vat_{i}", "23")
            exr = _s(f"line_exchange_rate_{i}") or None

            lm = {"exchange_rate": exr} if exr else None
            lines.append(
                InvoiceLinePayload(
                    line_no=i,
                    product_name=desc,
                    unit_code=unit,
                    quantity=Decimal(qty),
                    unit_price_net=Decimal(price),
                    vat_rate=vat_rate_map.get(vat_code, Decimal("23")),
                    vat_code=vat_code,
                    line_metadata=lm,
                )
            )

        # Resolve parties from DB
        if not seller_party_id_str or not buyer_party_id_str:
            raise ValueError("Wybierz sprzedawcę i nabywcę.")
        seller_db = db.get(Party, int(seller_party_id_str))
        buyer_db = db.get(Party, int(buyer_party_id_str))
        if not seller_db or not buyer_db:
            raise ValueError("Wybrany kontrahent nie istnieje w bazie.")

        def _party_payload(p: Party) -> PartyPayload:
            return PartyPayload(
                party_uuid=p.party_uuid,
                name_full=p.name_full,
                name_short=p.name_short,
                tax_id=p.tax_id,
                vat_eu_id=p.vat_eu_id,
                regon=p.regon,
                krs=p.krs,
                country_code=p.country_code,
                street=p.street,
                building_no=p.building_no,
                apartment_no=p.apartment_no,
                city=p.city,
                postal_code=p.postal_code,
                province=p.province,
                email=p.email,
                phone=p.phone,
                bank_account=p.bank_account,
                extra_data=p.extra_data,
            )

        seller_party = InvoicePartyPayload(
            role_code="SELLER", sequence_no=1, party=_party_payload(seller_db)
        )
        buyer_party = InvoicePartyPayload(
            role_code="BUYER", sequence_no=1, party=_party_payload(buyer_db)
        )

        # Build fa_metadata
        fa_meta: dict = {}
        if issue_place:
            fa_meta["issue_place"] = issue_place
        if payment_swift:
            fa_meta["payment_swift"] = payment_swift
        if payment_bank_name:
            fa_meta["payment_bank_name"] = payment_bank_name
        if contract_date_str:
            fa_meta["contract_date"] = contract_date_str
        if contract_number:
            fa_meta["contract_number"] = contract_number
        if footer_note:
            fa_meta["footer_note"] = footer_note

        payload = InvoiceCreateRequest(
            direction_code="SALE",
            invoice_kind_code="STANDARD",
            invoice_number=invoice_number,
            issue_date=date.fromisoformat(issue_date_str),
            sale_date=date.fromisoformat(sale_date_str) if sale_date_str else None,
            due_date=date.fromisoformat(due_date_str) if due_date_str else None,
            currency_code=currency_code,
            exchange_rate=Decimal(exchange_rate_str) if exchange_rate_str else None,
            payment_method=payment_method,
            payment_account=payment_account,
            fa_metadata=fa_meta or None,
            parties=[seller_party, buyer_party],
            lines=lines,
        )
        invoice = InvoiceService.create_invoice(db, payload, actor_id=str(current_user.id))
    except SAIntegrityError as exc:
        db.rollback()
        if "uq_invoice_invoice_number" in str(exc):
            error_msg = f"Faktura o numerze '{invoice_number}' już istnieje w bazie."
        else:
            error_msg = "Błąd zapisu faktury (naruszenie ograniczeń bazy danych)."
    except (InvalidOperation, ValidationError, ValueError) as exc:
        error_msg = str(exc) if str(exc) else "Nieprawidłowe dane formularza faktury."
    else:
        return RedirectResponse(url=f"{_root_path}/ui/invoices/{invoice.id}", status_code=303)

    # Re-render form with error and previously entered data
    all_parties = list(
        db.execute(select(Party).where(Party.is_active.is_(True)).order_by(Party.name_full))
        .scalars()
        .all()
    )
    prefill_lines = []
    for i in range(1, line_count + 1):
        desc = _s(f"line_description_{i}")
        if not desc:
            continue
        prefill_lines.append({
            "description": desc,
            "unit": _s(f"line_unit_{i}"),
            "qty": _s(f"line_qty_{i}", "1"),
            "price": _s(f"line_price_{i}", "0"),
            "vat_code": _s(f"line_vat_{i}", "23"),
        })
    prefill = {
        "invoice_number": invoice_number,
        "issue_date": issue_date_str,
        "issue_place": issue_place,
        "sale_date": sale_date_str,
        "due_date": due_date_str,
        "currency_code": currency_code,
        "exchange_rate": exchange_rate_str,
        "payment_method": payment_method or "",
        "payment_account": payment_account or "",
        "payment_swift": payment_swift,
        "payment_bank_name": payment_bank_name,
        "contract_date": contract_date_str,
        "contract_number": contract_number,
        "footer_note": footer_note,
        "seller_party_id": int(seller_party_id_str) if seller_party_id_str else None,
        "buyer_party_id": int(buyer_party_id_str) if buyer_party_id_str else None,
        "lines": prefill_lines,
    }
    return templates.TemplateResponse(
        "invoice_form.html",
        {
            "request": request,
            "current_user": current_user,
            "mode": "create",
            "prefill": prefill,
            "parties": all_parties,
            "parties_json": [
                {"id": p.id, "bank_account": p.bank_account or ""}
                for p in all_parties
            ],
            "error": error_msg,
        },
    )


@router.get("/ui/invoices/{invoice_id}/edit")
def invoice_edit_form(
    invoice_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(ui_require_roles("admin", "agent", "reviewer")),
):
    invoice = (
        db.execute(
            select(Invoice)
            .options(
                joinedload(Invoice.lines),
                joinedload(Invoice.parties).joinedload(InvoiceParty.party),
            )
            .where(Invoice.id == invoice_id)
        )
        .unique()
        .scalar_one_or_none()
    )
    if not invoice:
        return RedirectResponse(url=f"{_root_path}/ui/invoices?error={_url_quote('Faktura nie istnieje.')}", status_code=303)
    if invoice.approved_at is not None:
        return RedirectResponse(url=f"{_root_path}/ui/invoices/{invoice_id}", status_code=303)

    all_parties = list(
        db.execute(select(Party).where(Party.is_active.is_(True)).order_by(Party.name_full))
        .scalars()
        .all()
    )

    fa_meta = invoice.fa_metadata or {}
    prefill: dict = {
        "invoice_number": invoice.invoice_number,
        "issue_date": str(invoice.issue_date) if invoice.issue_date else "",
        "issue_place": fa_meta.get("issue_place", ""),
        "sale_date": str(invoice.sale_date) if invoice.sale_date else "",
        "due_date": str(invoice.due_date) if invoice.due_date else "",
        "currency_code": invoice.currency_code,
        "exchange_rate": str(invoice.exchange_rate) if invoice.exchange_rate else "",
        "payment_method": invoice.payment_method or "",
        "payment_account": invoice.payment_account or "",
        "payment_swift": fa_meta.get("payment_swift", ""),
        "payment_bank_name": fa_meta.get("payment_bank_name", ""),
        "contract_date": fa_meta.get("contract_date", ""),
        "contract_number": fa_meta.get("contract_number", ""),
        "footer_note": fa_meta.get("footer_note", ""),
    }
    for ip in invoice.parties:
        party = ip.party
        if not party:
            continue
        if ip.role_code == "SELLER":
            prefill["seller_party_id"] = party.id
        elif ip.role_code == "BUYER":
            prefill["buyer_party_id"] = party.id

    lines_data = []
    for line in sorted(invoice.lines, key=lambda l: l.line_no):
        lm = line.line_metadata or {}
        exr = lm.get("exchange_rate")
        lines_data.append({
            "description": line.product_name,
            "unit": line.unit_code or "",
            "qty": str(line.quantity),
            "price": str(line.unit_price_net),
            "vat_code": line.vat_code or ("23" if line.vat_rate else "oo"),
            "exchange_rate": str(exr) if exr else "",
        })
    prefill["lines"] = lines_data

    error_msg = request.query_params.get("error")

    return templates.TemplateResponse(
        "invoice_form.html",
        {
            "request": request,
            "current_user": current_user,
            "mode": "edit",
            "invoice_id": invoice_id,
            "prefill": prefill,
            "parties": all_parties,
            "parties_json": [
                {"id": p.id, "bank_account": p.bank_account or ""}
                for p in all_parties
            ],
            "error": error_msg,
        },
    )


@router.post("/ui/invoices/{invoice_id}/edit")
async def invoice_edit_submit(
    invoice_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(ui_require_roles("admin", "agent", "reviewer")),
):
    form = await request.form()

    def _s(key: str, default: str = "") -> str:
        return (form.get(key) or default).strip()

    invoice_number = _s("invoice_number")
    issue_date_str = _s("issue_date")
    issue_place = _s("issue_place")
    sale_date_str = _s("sale_date")
    due_date_str = _s("due_date")
    currency_code = _s("currency_code", "PLN") or "PLN"
    exchange_rate_str = _s("exchange_rate")
    payment_method = _s("payment_method") or None
    payment_account = _s("payment_account") or None
    payment_swift = _s("payment_swift")
    payment_bank_name = _s("payment_bank_name")

    seller_party_id_str = _s("seller_party_id")
    buyer_party_id_str = _s("buyer_party_id")

    contract_date_str = _s("contract_date")
    contract_number = _s("contract_number")
    footer_note = _s("footer_note")

    line_count = int(_s("line_count", "0") or "0")

    vat_rate_map: dict = {
        "23": Decimal("23"), "8": Decimal("8"), "5": Decimal("5"),
        "0": Decimal("0"), "oo": None, "np": None,
    }

    try:
        lines = []
        for i in range(1, line_count + 1):
            desc = _s(f"line_description_{i}")
            if not desc:
                continue
            unit = _s(f"line_unit_{i}") or None
            qty = _s(f"line_qty_{i}", "1") or "1"
            price = _s(f"line_price_{i}", "0") or "0"
            vat_code = _s(f"line_vat_{i}", "23")
            exr = _s(f"line_exchange_rate_{i}") or None

            lm = {"exchange_rate": exr} if exr else None
            lines.append(
                InvoiceLinePayload(
                    line_no=i,
                    product_name=desc,
                    unit_code=unit,
                    quantity=Decimal(qty),
                    unit_price_net=Decimal(price),
                    vat_rate=vat_rate_map.get(vat_code, Decimal("23")),
                    vat_code=vat_code,
                    line_metadata=lm,
                )
            )

        if not seller_party_id_str or not buyer_party_id_str:
            raise ValueError("Wybierz sprzedawcę i nabywcę.")
        seller_db = db.get(Party, int(seller_party_id_str))
        buyer_db = db.get(Party, int(buyer_party_id_str))
        if not seller_db or not buyer_db:
            raise ValueError("Wybrany kontrahent nie istnieje w bazie.")

        def _party_payload(p: Party) -> PartyPayload:
            return PartyPayload(
                party_uuid=p.party_uuid,
                name_full=p.name_full,
                name_short=p.name_short,
                tax_id=p.tax_id,
                vat_eu_id=p.vat_eu_id,
                regon=p.regon,
                krs=p.krs,
                country_code=p.country_code,
                street=p.street,
                building_no=p.building_no,
                apartment_no=p.apartment_no,
                city=p.city,
                postal_code=p.postal_code,
                province=p.province,
                email=p.email,
                phone=p.phone,
                bank_account=p.bank_account,
                extra_data=p.extra_data,
            )

        seller_party = InvoicePartyPayload(
            role_code="SELLER", sequence_no=1, party=_party_payload(seller_db)
        )
        buyer_party = InvoicePartyPayload(
            role_code="BUYER", sequence_no=1, party=_party_payload(buyer_db)
        )

        fa_meta: dict = {}
        if issue_place:
            fa_meta["issue_place"] = issue_place
        if payment_swift:
            fa_meta["payment_swift"] = payment_swift
        if payment_bank_name:
            fa_meta["payment_bank_name"] = payment_bank_name
        if contract_date_str:
            fa_meta["contract_date"] = contract_date_str
        if contract_number:
            fa_meta["contract_number"] = contract_number
        if footer_note:
            fa_meta["footer_note"] = footer_note

        payload = InvoiceUpdateRequest(
            invoice_number=invoice_number,
            issue_date=date.fromisoformat(issue_date_str),
            sale_date=date.fromisoformat(sale_date_str) if sale_date_str else None,
            due_date=date.fromisoformat(due_date_str) if due_date_str else None,
            currency_code=currency_code,
            exchange_rate=Decimal(exchange_rate_str) if exchange_rate_str else None,
            payment_method=payment_method,
            payment_account=payment_account,
            fa_metadata=fa_meta or None,
            parties=[seller_party, buyer_party],
            lines=lines,
        )
        InvoiceService.update_invoice(db, invoice_id, payload, actor_id=str(current_user.id))
    except SAIntegrityError as exc:
        db.rollback()
        if "uq_invoice_invoice_number" in str(exc):
            error_msg = f"Faktura o numerze '{invoice_number}' już istnieje w bazie."
        else:
            error_msg = "Błąd zapisu faktury (naruszenie ograniczeń bazy danych)."
    except (InvalidOperation, ValidationError, ValueError) as exc:
        error_msg = str(exc) if str(exc) else "Nieprawidłowe dane formularza faktury."
    else:
        return RedirectResponse(url=f"{_root_path}/ui/invoices/{invoice_id}", status_code=303)

    # Re-render form with error and previously entered data
    all_parties = list(
        db.execute(select(Party).where(Party.is_active.is_(True)).order_by(Party.name_full))
        .scalars()
        .all()
    )
    prefill_lines = []
    for i in range(1, line_count + 1):
        desc = _s(f"line_description_{i}")
        if not desc:
            continue
        prefill_lines.append({
            "description": desc,
            "unit": _s(f"line_unit_{i}"),
            "qty": _s(f"line_qty_{i}", "1"),
            "price": _s(f"line_price_{i}", "0"),
            "vat_code": _s(f"line_vat_{i}", "23"),
        })
    prefill = {
        "invoice_number": invoice_number,
        "issue_date": issue_date_str,
        "issue_place": issue_place,
        "sale_date": sale_date_str,
        "due_date": due_date_str,
        "currency_code": currency_code,
        "exchange_rate": exchange_rate_str,
        "payment_method": payment_method or "",
        "payment_account": payment_account or "",
        "payment_swift": payment_swift,
        "payment_bank_name": payment_bank_name,
        "contract_date": contract_date_str,
        "contract_number": contract_number,
        "footer_note": footer_note,
        "seller_party_id": int(seller_party_id_str) if seller_party_id_str else None,
        "buyer_party_id": int(buyer_party_id_str) if buyer_party_id_str else None,
        "lines": prefill_lines,
    }
    return templates.TemplateResponse(
        "invoice_form.html",
        {
            "request": request,
            "current_user": current_user,
            "mode": "edit",
            "invoice_id": invoice_id,
            "prefill": prefill,
            "parties": all_parties,
            "parties_json": [
                {"id": p.id, "bank_account": p.bank_account or ""}
                for p in all_parties
            ],
            "error": error_msg,
        },
    )


@router.get("/ui/invoices/{invoice_id}")
def invoice_detail(
    invoice_id: int,
    request: Request,
    action_success: str | None = None,
    action_error: str | None = None,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_ui_user),
):
    invoice = (
        db.execute(
            select(Invoice)
            .options(
                joinedload(Invoice.lines),
                joinedload(Invoice.parties).joinedload(InvoiceParty.party),
                joinedload(Invoice.events),
                joinedload(Invoice.payloads),
                joinedload(Invoice.vat_summaries),
            )
            .where(Invoice.id == invoice_id)
        )
        .unique()
        .scalar_one_or_none()
    )

    if not invoice:
        return RedirectResponse(url=f"{_root_path}/ui/invoices?error={_url_quote('Faktura nie istnieje.')}", status_code=303)

    # Fetch open batches for the "add to batch" choice dialog
    open_batches = []
    if invoice.accounting_qualified and not invoice.accounting_batch_id:
        from app.services.accounting_service import AccountingService
        open_batches = AccountingService.get_open_batches(db)

    return templates.TemplateResponse(
        "invoice_detail.html",
        {
            "request": request,
            "current_user": current_user,
            "invoice": invoice,
            "open_batches": open_batches,
            "action_success": action_success,
            "action_error": action_error,
        },
    )


@router.get("/ui/invoices/{invoice_id}/pdf")
def invoice_pdf(
    invoice_id: int,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_ui_user),
):
    from fastapi.responses import Response
    from app.services.pdf_service import generate_invoice_pdf

    invoice = (
        db.execute(
            select(Invoice)
            .options(
                joinedload(Invoice.lines),
                joinedload(Invoice.parties).joinedload(InvoiceParty.party),
                joinedload(Invoice.vat_summaries),
            )
            .where(Invoice.id == invoice_id)
        )
        .unique()
        .scalar_one_or_none()
    )

    if not invoice:
        return RedirectResponse(url=f"{_root_path}/ui/invoices?error={_url_quote('Faktura nie istnieje.')}", status_code=303)

    pdf_bytes = generate_invoice_pdf(invoice)
    filename = f"faktura_{invoice.invoice_number.replace('/', '_')}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/ui/invoices/{invoice_id}/qualify")
def invoice_qualify(
    invoice_id: int,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(ui_require_roles("admin", "reviewer", "owner")),
):
    from urllib.parse import urlencode
    from app.services.accounting_service import AccountingService

    try:
        AccountingService.qualify_purchase_invoice(
            db=db,
            invoice_id=invoice_id,
            user_id=current_user.id,
            accounting_qualified=True,
            accounting_notes=None,
        )
        params = urlencode({"action_success": "Faktura zakwalifikowana do wysłania do biura księgowego."})
    except ValueError as exc:
        params = urlencode({"action_error": str(exc)})

    return RedirectResponse(url=f"{_root_path}/ui/invoices/{invoice_id}?{params}", status_code=303)


@router.post("/ui/invoices/{invoice_id}/reject-accounting")
def invoice_reject_accounting(
    invoice_id: int,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(ui_require_roles("admin", "reviewer", "owner")),
):
    from urllib.parse import urlencode
    from app.services.accounting_service import AccountingService

    try:
        AccountingService.qualify_purchase_invoice(
            db=db,
            invoice_id=invoice_id,
            user_id=current_user.id,
            accounting_qualified=False,
            accounting_notes="Odrzucono z procesu kosztowego.",
        )
        params = urlencode({"action_success": "Faktura odrzucona — nie zostanie wysłana do biura księgowego."})
    except ValueError as exc:
        params = urlencode({"action_error": str(exc)})

    return RedirectResponse(url=f"{_root_path}/ui/invoices/{invoice_id}?{params}", status_code=303)


@router.post("/ui/invoices/{invoice_id}/undo-qualify")
def invoice_undo_qualify(
    invoice_id: int,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(ui_require_roles("admin", "reviewer", "owner")),
):
    from urllib.parse import urlencode
    from app.db.models import InvoiceEvent

    try:
        invoice = db.get(Invoice, invoice_id)
        if not invoice:
            raise ValueError("Faktura nie istnieje.")
        if invoice.accounting_batch_id:
            raise ValueError("Nie można cofnąć kwalifikacji — faktura jest już w pakiecie.")

        invoice.accounting_qualified = None
        invoice.accounting_marked_by = None
        invoice.accounting_marked_at = None
        invoice.accounting_notes = None
        invoice.erp_status = "KSEF_ACCEPTED"
        invoice.review_status = None
        invoice.accounting_status = "new"

        db.add(
            InvoiceEvent(
                invoice_id=invoice.id,
                event_type="PURCHASE_QUALIFICATION_REVERTED",
                event_status="SUCCESS",
                actor_type="USER",
                actor_id=str(current_user.id),
                message="Cofnięto kwalifikację faktury.",
            )
        )
        db.commit()
        params = urlencode({"action_success": "Kwalifikacja cofnięta."})
    except ValueError as exc:
        params = urlencode({"action_error": str(exc)})

    return RedirectResponse(url=f"{_root_path}/ui/invoices/{invoice_id}?{params}", status_code=303)


@router.post("/ui/invoices/{invoice_id}/dodaj-do-pakietu")
def invoice_add_to_batch(
    invoice_id: int,
    batch_id: str | None = Form(None),
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(ui_require_roles("admin", "owner")),
):
    from urllib.parse import urlencode
    from app.services.accounting_service import AccountingService

    resolved_batch_id = int(batch_id) if batch_id else None

    try:
        batch = AccountingService.add_single_invoice_to_batch(
            db=db,
            invoice_id=invoice_id,
            created_by=current_user.id,
            batch_id=resolved_batch_id,
        )
        params = urlencode({"action_success": f"Dodano do pakietu {batch.batch_code}."})
    except ValueError as exc:
        params = urlencode({"action_error": str(exc)})

    return RedirectResponse(url=f"{_root_path}/ui/invoices/{invoice_id}?{params}", status_code=303)


@router.post("/ui/invoices/{invoice_id}/powiadom")
def invoice_send_notification(
    invoice_id: int,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(ui_require_roles("admin", "owner")),
):
    from urllib.parse import urlencode
    from app.services.notification_service import NotificationService

    try:
        notification = NotificationService.create_invoice_notification(db, invoice_id)
        notification = NotificationService.send_notification(db, notification.id)
        if notification.status == "SENT":
            params = urlencode({"action_success": f"Wysłano powiadomienie na {notification.recipient}."})
        else:
            params = urlencode({"action_error": notification.error_message or "Wysyłka nie powiodła się."})
    except (ValueError, RuntimeError) as exc:
        params = urlencode({"action_error": str(exc)})

    return RedirectResponse(url=f"{_root_path}/ui/invoices/{invoice_id}?{params}", status_code=303)


@router.post("/ui/invoices/{invoice_id}/approve")
def invoice_approve(
    invoice_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(ui_require_roles("admin", "reviewer")),
):
    from app.schemas.invoice import InvoiceApproveRequest

    try:
        InvoiceService.approve_invoice(
            db=db,
            invoice_id=invoice_id,
            payload=InvoiceApproveRequest(approved_by_user_id=current_user.id),
            actor_id=str(current_user.id),
        )
    except (ValueError, RuntimeError) as exc:
        from urllib.parse import quote
        error_msg = quote(str(exc))
        return RedirectResponse(
            url=f"/ui/invoices/{invoice_id}/edit?error={error_msg}",
            status_code=303,
        )
    except Exception as exc:
        from urllib.parse import quote
        error_msg = quote(f"Wysyłka do KSeF nie powiodła się: {exc}")
        return RedirectResponse(
            url=f"/ui/invoices/{invoice_id}/edit?error={error_msg}",
            status_code=303,
        )

    from urllib.parse import urlencode
    params = urlencode({"action_success": "Faktura zaakceptowana i wysłana do KSeF."})
    return RedirectResponse(url=f"{_root_path}/ui/invoices/{invoice_id}?{params}", status_code=303)


@router.post("/ui/invoices/{invoice_id}/retry-ksef")
def invoice_retry_ksef(
    invoice_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(ui_require_roles("admin", "reviewer")),
):
    from urllib.parse import urlencode, quote

    try:
        InvoiceService.retry_ksef_send(
            db=db,
            invoice_id=invoice_id,
            actor_id=str(current_user.id),
        )
    except (ValueError, RuntimeError) as exc:
        params = urlencode({"action_error": str(exc)})
        return RedirectResponse(
            url=f"/ui/invoices/{invoice_id}?{params}",
            status_code=303,
        )
    except Exception as exc:
        params = urlencode({"action_error": f"Wysyłka do KSeF nie powiodła się: {exc}"})
        return RedirectResponse(
            url=f"/ui/invoices/{invoice_id}?{params}",
            status_code=303,
        )

    params = urlencode({"action_success": "Faktura wysłana do KSeF."})
    return RedirectResponse(url=f"{_root_path}/ui/invoices/{invoice_id}?{params}", status_code=303)


@router.post("/ui/invoices/{invoice_id}/validate-ksef")
def invoice_validate_ksef(
    invoice_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(ui_require_roles("admin", "agent", "reviewer")),
):
    """Generate FA(3) XML for the invoice and validate it against the KSeF XSD schema."""
    invoice = InvoiceService.get_invoice(db, invoice_id)

    # Business rules first
    biz_result = ValidationService.validate_invoice(invoice)

    # Then generate XML and run XSD validation
    xsd_errors: list[str] = []
    xml_preview: str | None = None
    if biz_result.valid:
        try:
            xml_content = InvoiceService._generate_fa3_xml(invoice)
            xml_preview = xml_content
            xsd_errors = ValidationService.validate_ksef_xml(xml_content)
        except Exception as exc:
            xsd_errors = [f"Błąd generowania XML: {exc}"]

    return templates.TemplateResponse(
        "invoice_detail.html",
        {
            "request": request,
            "current_user": current_user,
            "invoice": invoice,
            "validate_result": {
                "valid": biz_result.valid and len(xsd_errors) == 0,
                "biz_errors": biz_result.errors,
                "biz_warnings": biz_result.warnings,
                "xsd_errors": xsd_errors,
                "xml_preview": xml_preview,
            },
        },
    )


# ── Party (kontrahent) CRUD ────────────────────────────────────────────────────

@router.get("/ui/parties")
def parties_list(
    request: Request,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_ui_user),
    success: str | None = None,
    error: str | None = None,
):
    parties = list(
        db.execute(select(Party).order_by(Party.name_full)).scalars().all()
    )
    return templates.TemplateResponse(
        "parties_list.html",
        {"request": request, "current_user": current_user, "parties": parties, "success": success, "error": error},
    )


# ── NIP lookup via Biała Lista ──────────────────────────────────────────────
@router.get("/ui/parties/lookup-nip")
async def party_lookup_nip(
    nip: str,
    current_user: AppUser = Depends(ui_require_roles("admin", "agent")),
):
    import httpx
    from fastapi.responses import JSONResponse

    nip_clean = re.sub(r"\D", "", nip)
    if len(nip_clean) != 10:
        return JSONResponse({"error": "NIP musi mieć 10 cyfr."}, status_code=422)

    yesterday = (date.today() - timedelta(days=1)).isoformat()
    url = f"https://wl-api.mf.gov.pl/api/search/nip/{nip_clean}?date={yesterday}"

    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get(url)
    except httpx.TimeoutException:
        return JSONResponse({"error": "Timeout — serwer MF nie odpowiada."}, status_code=504)

    if resp.status_code != 200:
        return JSONResponse({"error": "Nie znaleziono podmiotu o podanym NIP."}, status_code=404)

    data = resp.json()
    subject = data.get("result", {}).get("subject")
    if not subject:
        return JSONResponse({"error": "Brak danych podmiotu w odpowiedzi."}, status_code=404)

    # Check VAT status first
    status_vat = subject.get("statusVat") or ""
    if status_vat != "Czynny":
        return JSONResponse({
            "error": f"Podmiot NIE jest czynnym podatnikiem VAT (status: {status_vat or 'brak'}).",
            "status_vat": status_vat,
        }, status_code=422)

    # Parse address
    address_raw = subject.get("workingAddress") or subject.get("residenceAddress") or ""
    street = ""
    building_no = ""
    apartment_no = ""
    postal_code = ""
    city = ""

    if address_raw and "," in address_raw:
        parts = address_raw.split(",", 1)
        street_part = parts[0].strip()
        postal_city = parts[1].strip()

        # Last token with a digit is the building number
        tokens = street_part.rsplit(" ", 1)
        if len(tokens) == 2 and re.search(r"\d", tokens[1]):
            street = tokens[0]
            number_raw = tokens[1]
            if "/" in number_raw:
                building_no, apartment_no = number_raw.split("/", 1)
            else:
                building_no = number_raw
        else:
            street = street_part

        pc_match = re.match(r"(\d{2}-\d{3})\s+(.*)", postal_city)
        if pc_match:
            postal_code = pc_match.group(1)
            city = pc_match.group(2)

    # Bank accounts
    account_numbers = subject.get("accountNumbers") or []

    return JSONResponse({
        "name_full": subject.get("name") or "",
        "regon": subject.get("regon") or "",
        "krs": subject.get("krs") or "",
        "street": street,
        "building_no": building_no,
        "apartment_no": apartment_no,
        "postal_code": postal_code,
        "city": city,
        "account_numbers": account_numbers,
        "status_vat": status_vat,
    })


# ── Bank account verification via Biała Lista ────────────────────────────────
@router.get("/ui/parties/verify-bank-account")
async def party_verify_bank_account(
    account: str,
    current_user: AppUser = Depends(ui_require_roles("admin", "agent")),
):
    import httpx
    from fastapi.responses import JSONResponse

    account_clean = re.sub(r"\D", "", account)
    if len(account_clean) != 26:
        return JSONResponse({"error": "Numer rachunku musi mieć 26 cyfr."}, status_code=422)

    yesterday = (date.today() - timedelta(days=1)).isoformat()
    url = f"https://wl-api.mf.gov.pl/api/search/bank-account/{account_clean}?date={yesterday}"

    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get(url)
    except httpx.TimeoutException:
        return JSONResponse({"error": "Timeout — serwer MF nie odpowiada."}, status_code=504)

    if resp.status_code != 200:
        return JSONResponse({"error": "Nie znaleziono rachunku w rejestrze."}, status_code=404)

    data = resp.json()
    subjects = data.get("result", {}).get("subjects") or []

    if not subjects:
        return JSONResponse({
            "verified": False,
            "message": "Rachunek NIE figuruje na Białej Liście.",
        })

    # Return info about who owns this account
    owners = []
    for s in subjects:
        owners.append({
            "name": s.get("name") or "",
            "nip": s.get("nip") or "",
            "status_vat": s.get("statusVat") or "",
        })

    return JSONResponse({
        "verified": True,
        "message": "Rachunek figuruje na Białej Liście.",
        "owners": owners,
    })


@router.get("/ui/parties/new")
def party_new_form(
    request: Request,
    current_user: AppUser = Depends(ui_require_roles("admin", "agent")),
):
    return templates.TemplateResponse(
        "party_form.html",
        {"request": request, "current_user": current_user, "mode": "create", "party": None, "prefill": {}, "error": None},
    )


@router.post("/ui/parties/new")
async def party_create_submit(
    request: Request,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(ui_require_roles("admin", "agent")),
):
    form = await request.form()

    def _s(key: str) -> str | None:
        v = form.get(key)
        return v.strip() if v and v.strip() else None

    name_full = _s("name_full")
    if not name_full:
        return templates.TemplateResponse(
            "party_form.html",
            {"request": request, "current_user": current_user, "mode": "create",
             "party": None, "prefill": dict(form), "error": "Pełna nazwa jest wymagana."},
            status_code=422,
        )

    party = Party(
        party_uuid=str(uuid.uuid4()),
        name_full=name_full,
        name_short=_s("name_short"),
        party_type=_s("party_type"),
        tax_id=_s("tax_id"),
        vat_eu_id=_s("vat_eu_id"),
        regon=_s("regon"),
        krs=_s("krs"),
        country_code=_s("country_code") or "PL",
        street=_s("street"),
        building_no=_s("building_no"),
        apartment_no=_s("apartment_no"),
        city=_s("city"),
        postal_code=_s("postal_code"),
        province=_s("province"),
        email=_s("email"),
        phone=_s("phone"),
        bank_account=_s("bank_account"),
        is_active=bool(form.get("is_active")),
    )
    db.add(party)
    db.commit()
    return RedirectResponse(url=f"{_root_path}/ui/parties/{party.id}/edit?success=1", status_code=303)


@router.get("/ui/parties/{party_id}/edit")
def party_edit_form(
    party_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(ui_require_roles("admin", "agent")),
    success: int | None = None,
):
    party = db.get(Party, party_id)
    if not party:
        return RedirectResponse(url=f"{_root_path}/ui/parties?error={_url_quote('Kontrahent nie istnieje.')}", status_code=303)
    return templates.TemplateResponse(
        "party_form.html",
        {
            "request": request,
            "current_user": current_user,
            "mode": "edit",
            "party": party,
            "prefill": {},
            "error": None,
            "saved": bool(success),
        },
    )


@router.post("/ui/parties/{party_id}/edit")
async def party_edit_submit(
    party_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(ui_require_roles("admin", "agent")),
):
    party = db.get(Party, party_id)
    if not party:
        return RedirectResponse(url=f"{_root_path}/ui/parties?error={_url_quote('Kontrahent nie istnieje.')}", status_code=303)

    form = await request.form()

    def _s(key: str) -> str | None:
        v = form.get(key)
        return v.strip() if v and v.strip() else None

    name_full = _s("name_full")
    if not name_full:
        return templates.TemplateResponse(
            "party_form.html",
            {"request": request, "current_user": current_user, "mode": "edit",
             "party": party, "prefill": {}, "error": "Pełna nazwa jest wymagana."},
            status_code=422,
        )

    party.name_full = name_full
    party.name_short = _s("name_short")
    party.party_type = _s("party_type")
    party.tax_id = _s("tax_id")
    party.vat_eu_id = _s("vat_eu_id")
    party.regon = _s("regon")
    party.krs = _s("krs")
    party.country_code = _s("country_code") or "PL"
    party.street = _s("street")
    party.building_no = _s("building_no")
    party.apartment_no = _s("apartment_no")
    party.city = _s("city")
    party.postal_code = _s("postal_code")
    party.province = _s("province")
    party.email = _s("email")
    party.phone = _s("phone")
    party.bank_account = _s("bank_account")
    party.is_active = bool(form.get("is_active"))

    db.commit()
    return RedirectResponse(url=f"{_root_path}/ui/parties/{party_id}/edit?success=1", status_code=303)


@router.post("/ui/parties/{party_id}/delete")
def party_delete(
    party_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(ui_require_roles("admin")),
):
    party = db.get(Party, party_id)
    if not party:
        return RedirectResponse(url=f"{_root_path}/ui/parties?error={_url_quote('Kontrahent nie istnieje.')}", status_code=303)

    used_on_invoice = db.execute(
        select(InvoiceParty.id).where(InvoiceParty.party_id == party_id).limit(1)
    ).first()

    if used_on_invoice:
        party.is_active = False
        db.commit()
        return RedirectResponse(
            url="/ui/parties?success=Kontrahent+zosta%C5%82+dezaktywowany+(wyst%C4%99puje+na+fakturach).",
            status_code=303,
        )
    else:
        db.delete(party)
        db.commit()
        return RedirectResponse(
            url="/ui/parties?success=Kontrahent+zosta%C5%82+trwale+usuni%C4%99ty.",
            status_code=303,
        )


@router.get("/ui/pakiety-ksiegowe")
def accounting_batches_list(
    request: Request,
    q: str = "",
    year: str = "",
    month: str = "",
    week: str = "",
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_ui_user),
    error: str | None = None,
):
    from sqlalchemy import or_

    stmt = select(AccountingBatch).order_by(AccountingBatch.id.desc())

    if year.strip():
        try:
            stmt = stmt.where(AccountingBatch.period_year == int(year))
        except ValueError:
            pass

    if month.strip():
        try:
            stmt = stmt.where(AccountingBatch.period_month == int(month))
        except ValueError:
            pass

    if week.strip():
        try:
            stmt = stmt.where(AccountingBatch.period_week == int(week))
        except ValueError:
            pass

    items = list(db.execute(stmt).scalars().all())

    # Text filter: match batch_code, batch_type, status OR invoice numbers inside batches
    if q.strip():
        q_lower = q.strip().lower()
        filtered = []
        for batch in items:
            if (
                q_lower in batch.batch_code.lower()
                or q_lower in batch.batch_type.lower()
                or q_lower in batch.status.lower()
            ):
                filtered.append(batch)
                continue
            # Check invoice numbers within the batch
            batch_invoices = db.execute(
                select(AccountingBatchInvoice)
                .where(AccountingBatchInvoice.batch_id == batch.id)
            ).scalars().all()
            for bi in batch_invoices:
                inv = db.get(Invoice, bi.invoice_id)
                if inv and inv.invoice_number and q_lower in inv.invoice_number.lower():
                    filtered.append(batch)
                    break
        items = filtered

    # Compute distinct values for filter dropdowns from all batches
    all_batches = list(db.execute(select(AccountingBatch)).scalars().all())
    available_years = sorted({b.period_year for b in all_batches})
    available_months = sorted({b.period_month for b in all_batches if b.period_month})
    available_weeks = sorted({b.period_week for b in all_batches if b.period_week})

    return templates.TemplateResponse(
        "accounting_batches_list.html",
        {
            "request": request,
            "current_user": current_user,
            "items": items,
            "q": q,
            "filter_year": year,
            "filter_month": month,
            "filter_week": week,
            "available_years": available_years,
            "available_months": available_months,
            "available_weeks": available_weeks,
            "error": error,
        },
    )


@router.get("/ui/pakiety-ksiegowe/{batch_id}")
def accounting_batch_detail(
    batch_id: int,
    request: Request,
    action_success: str | None = None,
    action_error: str | None = None,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_ui_user),
):
    batch = db.get(AccountingBatch, batch_id)
    if not batch:
        return RedirectResponse(url=f"{_root_path}/ui/pakiety-ksiegowe?error={_url_quote('Pakiet nie istnieje.')}", status_code=303)

    items = list(
        db.execute(
            select(AccountingBatchInvoice)
            .options(joinedload(AccountingBatchInvoice.invoice))
            .where(AccountingBatchInvoice.batch_id == batch_id)
        )
        .scalars()
        .all()
    )

    return templates.TemplateResponse(
        "accounting_batch_detail.html",
        {
            "request": request,
            "current_user": current_user,
            "batch": batch,
            "items": items,
            "action_success": action_success,
            "action_error": action_error,
        },
    )


@router.post("/ui/pakiety-ksiegowe/{batch_id}/remove-invoice/{invoice_id}")
def batch_remove_invoice(
    batch_id: int,
    invoice_id: int,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(ui_require_roles("admin", "owner")),
):
    from urllib.parse import urlencode
    from app.db.models import InvoiceEvent

    try:
        batch = db.get(AccountingBatch, batch_id)
        if not batch:
            raise ValueError("Pakiet nie istnieje.")

        link = db.execute(
            select(AccountingBatchInvoice).where(
                AccountingBatchInvoice.batch_id == batch_id,
                AccountingBatchInvoice.invoice_id == invoice_id,
            )
        ).scalar_one_or_none()
        if not link:
            raise ValueError("Faktura nie jest w tym pakiecie.")

        invoice = db.get(Invoice, invoice_id)
        db.delete(link)

        batch.item_count = max(0, batch.item_count - 1)

        if invoice:
            invoice.accounting_batch_id = None
            invoice.erp_status = "READY_FOR_ACCOUNTING"
            invoice.accounting_status = "qualified"
            db.add(
                InvoiceEvent(
                    invoice_id=invoice.id,
                    event_type="REMOVED_FROM_ACCOUNTING_BATCH",
                    event_status="SUCCESS",
                    actor_type="USER",
                    actor_id=str(current_user.id),
                    message=f"Usunięto z pakietu {batch.batch_code}.",
                )
            )

        # If batch is now empty, delete it entirely
        if batch.item_count <= 0:
            db.delete(batch)
            db.commit()
            from urllib.parse import urlencode
            params = urlencode({"batch_deleted": "1"})
            return RedirectResponse(url=f"{_root_path}/ui/pakiety-ksiegowe", status_code=303)

        db.commit()
        params = urlencode({"action_success": f"Usunięto fakturę #{invoice_id} z pakietu."})
    except ValueError as exc:
        params = urlencode({"action_error": str(exc)})

    return RedirectResponse(url=f"{_root_path}/ui/pakiety-ksiegowe/{batch_id}?{params}", status_code=303)


@router.post("/ui/pakiety-ksiegowe/{batch_id}/update-settings")
def batch_update_settings(
    batch_id: int,
    batch_type: str = Form(...),
    send_at: str = Form(""),
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(ui_require_roles("admin", "owner")),
):
    from urllib.parse import urlencode
    from app.services.accounting_service import AccountingService

    try:
        parsed_send_at = None
        if send_at.strip():
            parsed_send_at = datetime.fromisoformat(send_at).replace(tzinfo=timezone.utc)

        AccountingService.update_batch_settings(
            db=db,
            batch_id=batch_id,
            batch_type=batch_type,
            send_at=parsed_send_at,
        )
        params = urlencode({"action_success": "Ustawienia pakietu zostały zapisane."})
    except ValueError as exc:
        params = urlencode({"action_error": str(exc)})

    return RedirectResponse(url=f"{_root_path}/ui/pakiety-ksiegowe/{batch_id}?{params}", status_code=303)


@router.post("/ui/pakiety-ksiegowe/{batch_id}/powiadom")
def batch_send_test_notification(
    batch_id: int,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(ui_require_roles("admin", "owner")),
):
    from urllib.parse import urlencode
    from app.adapters.notification.email import EmailNotificationAdapter
    from app.core.config import settings
    from app.db.models import InvoicePayload

    batch = db.get(AccountingBatch, batch_id)
    if not batch:
        params = urlencode({"action_error": "Pakiet nie istnieje."})
        return RedirectResponse(url=f"{_root_path}/ui/pakiety-ksiegowe?{params}", status_code=303)

    # Build batch summary
    batch_invoices = db.execute(
        select(AccountingBatchInvoice)
        .where(AccountingBatchInvoice.batch_id == batch_id)
    ).scalars().all()

    lines = [
        f"Pakiet: {batch.batch_code}",
        f"Typ: {batch.batch_type}",
        f"Okres: {batch.period_year}-{batch.period_month:02d}",
        f"Status: {batch.status}",
        f"Liczba faktur: {batch.item_count}",
        f"Zaplanowana wysyłka: {batch.send_at.strftime('%Y-%m-%d %H:%M') if batch.send_at else '—'}",
        "",
        "Faktury:",
    ]

    attachments = []
    for bi in batch_invoices:
        inv = db.get(Invoice, bi.invoice_id)
        if inv:
            inv_url = f"{settings.base_url}/ui/invoices/{inv.id}"
            lines.append(
                f"  • {inv.invoice_number} | {inv.direction_code} | {inv.issue_date} | brutto {inv.gross_total}"
            )
            lines.append(f"    Link: {inv_url}")

            # Attach XML if available
            xml_payload = db.execute(
                select(InvoicePayload)
                .where(
                    InvoicePayload.invoice_id == inv.id,
                    InvoicePayload.payload_type_code.in_(["KSEF_XML", "KSEF_XML_RECEIVED"]),
                )
                .order_by(InvoicePayload.id.desc())
            ).scalars().first()
            if xml_payload:
                safe_number = inv.invoice_number.replace("/", "_")
                attachments.append((f"{safe_number}.xml", xml_payload.content, "xml"))

    body = "\n".join(lines)
    recipient = settings.default_notification_email

    try:
        EmailNotificationAdapter().send(
            recipient=recipient,
            subject=f"[TEST] Pakiet {batch.batch_code} — podsumowanie",
            body=body,
            attachments=attachments or None,
        )
        params = urlencode({"action_success": f"Wysłano powiadomienie testowe na {recipient}."})
    except Exception as exc:
        params = urlencode({"action_error": str(exc)})

    return RedirectResponse(url=f"{_root_path}/ui/pakiety-ksiegowe/{batch_id}?{params}", status_code=303)


@router.get("/ui/notifications")
def notifications_list(
    request: Request,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_ui_user),
):
    items = list(
        db.execute(select(NotificationLog).order_by(NotificationLog.id.desc()))
        .scalars()
        .all()
    )

    return templates.TemplateResponse(
        "notifications_list.html",
        {
            "request": request,
            "current_user": current_user,
            "items": items,
        },
    )


# ---------------------------------------------------------------------------
# Admin: user management
# ---------------------------------------------------------------------------

@router.get("/ui/users")
def users_list(
    request: Request,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(ui_require_roles("admin")),
    error: str | None = None,
):
    users = (
        db.execute(
            select(AppUser)
            .options(joinedload(AppUser.roles).joinedload(AppUserRole.role))
            .order_by(AppUser.username)
        )
        .unique()
        .scalars()
        .all()
    )
    return templates.TemplateResponse(
        "users_list.html",
        {"request": request, "current_user": current_user, "users": users, "error": error},
    )


@router.get("/ui/users/new")
def user_new_form(
    request: Request,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(ui_require_roles("admin")),
):
    all_roles = db.execute(select(AppRole).order_by(AppRole.role_code)).scalars().all()
    return templates.TemplateResponse(
        "user_form.html",
        {
            "request": request,
            "current_user": current_user,
            "user": None,
            "all_roles": all_roles,
            "user_role_codes": set(),
            "mode": "create",
        },
    )


@router.post("/ui/users/new")
def user_create_submit(
    request: Request,
    username: str = Form(...),
    display_name: str = Form(...),
    email: str = Form(default=""),
    password: str = Form(...),
    is_active: str = Form(default=""),
    is_locked: str = Form(default=""),
    role_codes: list[str] = Form(default=[]),
    enable_2fa: str = Form(default=""),
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(ui_require_roles("admin")),
):
    import pyotp

    all_roles = db.execute(select(AppRole).order_by(AppRole.role_code)).scalars().all()

    def _error(msg: str):
        return templates.TemplateResponse(
            "user_form.html",
            {
                "request": request,
                "current_user": current_user,
                "user": None,
                "all_roles": all_roles,
                "user_role_codes": set(role_codes),
                "mode": "create",
                "error": msg,
            },
            status_code=400,
        )

    normalized = normalize_username(username)
    if db.execute(select(AppUser).where(AppUser.username == normalized)).scalar_one_or_none():
        return _error("Użytkownik o tym loginie już istnieje.")

    if len(password) < 10:
        return _error("Hasło musi mieć co najmniej 10 znaków.")

    totp_secret = pyotp.random_base32() if enable_2fa == "1" else None
    new_user = AppUser(
        user_uuid=str(uuid.uuid4()),
        username=normalized,
        email=email.strip() or None,
        display_name=display_name.strip(),
        password_hash=get_password_hash(password),
        auth_provider="LOCAL",
        is_active=(is_active == "1"),
        is_locked=(is_locked == "1"),
        totp_secret=totp_secret,
    )
    db.add(new_user)
    db.flush()

    if role_codes:
        roles = db.execute(select(AppRole).where(AppRole.role_code.in_(role_codes))).scalars().all()
        for role in roles:
            db.add(AppUserRole(user_id=new_user.id, role_id=role.id))

    db.commit()

    if totp_secret:
        return RedirectResponse(url=f"{_root_path}/ui/users/{new_user.id}/totp-setup", status_code=303)
    return RedirectResponse(url=f"{_root_path}/ui/users", status_code=303)


@router.get("/ui/users/{user_id}/totp-setup")
def user_totp_setup(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(ui_require_roles("admin")),
):
    import pyotp
    import qrcode
    import qrcode.image.svg

    user = db.get(AppUser, user_id)
    if not user or not user.totp_secret:
        return RedirectResponse(url=f"{_root_path}/ui/users", status_code=302)

    uri = pyotp.totp.TOTP(user.totp_secret).provisioning_uri(
        name=user.username, issuer_name="KSeF ERP"
    )

    qr = qrcode.QRCode(box_size=6, border=4)
    qr.add_data(uri)
    qr.make(fit=True)
    img = qr.make_image(image_factory=qrcode.image.svg.SvgPathImage)
    buf = io.BytesIO()
    img.save(buf)
    svg = buf.getvalue().decode("utf-8")
    # Strip XML declaration so SVG can be embedded inline
    if "<?xml" in svg:
        svg = svg[svg.index("<svg"):]

    return templates.TemplateResponse(
        "user_totp.html",
        {
            "request": request,
            "current_user": current_user,
            "user": user,
            "qr_svg": svg,
            "totp_secret": user.totp_secret,
        },
    )


@router.get("/ui/users/{user_id}/edit")
def user_edit_form(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(ui_require_roles("admin")),
):
    user = (
        db.execute(
            select(AppUser)
            .where(AppUser.id == user_id)
            .options(joinedload(AppUser.roles).joinedload(AppUserRole.role))
        )
        .unique()
        .scalar_one_or_none()
    )
    if not user:
        return RedirectResponse(url=f"{_root_path}/ui/users?error={_url_quote('Użytkownik nie istnieje.')}", status_code=303)

    all_roles = db.execute(select(AppRole).order_by(AppRole.role_code)).scalars().all()
    user_role_codes = {item.role.role_code for item in user.roles}

    return templates.TemplateResponse(
        "user_form.html",
        {
            "request": request,
            "current_user": current_user,
            "user": user,
            "all_roles": all_roles,
            "user_role_codes": user_role_codes,
            "mode": "edit",
        },
    )


@router.post("/ui/users/{user_id}/edit")
def user_edit_submit(
    user_id: int,
    request: Request,
    display_name: str = Form(...),
    email: str = Form(default=""),
    password: str = Form(default=""),
    is_active: str = Form(default=""),
    is_locked: str = Form(default=""),
    role_codes: list[str] = Form(default=[]),
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(ui_require_roles("admin")),
):
    user = (
        db.execute(
            select(AppUser)
            .where(AppUser.id == user_id)
            .options(joinedload(AppUser.roles).joinedload(AppUserRole.role))
        )
        .unique()
        .scalar_one_or_none()
    )
    if not user:
        return RedirectResponse(url=f"{_root_path}/ui/users?error={_url_quote('Użytkownik nie istnieje.')}", status_code=303)

    all_roles = db.execute(select(AppRole).order_by(AppRole.role_code)).scalars().all()

    if password and len(password) < 10:
        return templates.TemplateResponse(
            "user_form.html",
            {
                "request": request,
                "current_user": current_user,
                "user": user,
                "all_roles": all_roles,
                "user_role_codes": set(role_codes),
                "mode": "edit",
                "error": "Hasło musi mieć co najmniej 10 znaków.",
            },
            status_code=400,
        )

    user.display_name = display_name.strip()
    user.email = email.strip() or None
    user.is_active = (is_active == "1")
    user.is_locked = (is_locked == "1")
    if password:
        user.password_hash = get_password_hash(password)

    db.execute(sql_delete(AppUserRole).where(AppUserRole.user_id == user_id))
    if role_codes:
        roles = db.execute(select(AppRole).where(AppRole.role_code.in_(role_codes))).scalars().all()
        for role in roles:
            db.add(AppUserRole(user_id=user.id, role_id=role.id))

    db.commit()
    return RedirectResponse(url=f"{_root_path}/ui/users", status_code=303)


@router.post("/ui/users/{user_id}/totp-reset")
def user_totp_reset(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(ui_require_roles("admin")),
):
    import pyotp

    user = db.get(AppUser, user_id)
    if not user:
        return RedirectResponse(url=f"{_root_path}/ui/users?error={_url_quote('Użytkownik nie istnieje.')}", status_code=303)

    user.totp_secret = pyotp.random_base32()
    db.commit()
    return RedirectResponse(url=f"{_root_path}/ui/users/{user_id}/totp-setup", status_code=303)


@router.post("/ui/users/{user_id}/totp-disable")
def user_totp_disable(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(ui_require_roles("admin")),
):
    user = db.get(AppUser, user_id)
    if not user:
        return RedirectResponse(url=f"{_root_path}/ui/users?error={_url_quote('Użytkownik nie istnieje.')}", status_code=303)

    user.totp_secret = None
    db.commit()
    return RedirectResponse(url=f"{_root_path}/ui/users/{user_id}/edit", status_code=303)


@router.post("/ui/users/{user_id}/delete")
def user_delete(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(ui_require_roles("admin")),
):
    if user_id == current_user.id:
        return RedirectResponse(url=f"{_root_path}/ui/users?error={_url_quote('Nie możesz usunąć własnego konta.')}", status_code=303)

    user = db.get(AppUser, user_id)
    if not user:
        return RedirectResponse(url=f"{_root_path}/ui/users?error={_url_quote('Użytkownik nie istnieje.')}", status_code=303)

    db.execute(sql_delete(AppUserRole).where(AppUserRole.user_id == user_id))
    db.delete(user)
    db.commit()
    return RedirectResponse(url=f"{_root_path}/ui/users", status_code=303)
