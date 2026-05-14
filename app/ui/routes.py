import io
import uuid
from datetime import datetime, timezone
from decimal import InvalidOperation
from pathlib import Path

from fastapi import APIRouter, Cookie, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy import delete as sql_delete, func, select
from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
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
    Invoice,
    InvoiceParty,
    NotificationLog,
)
from app.schemas.invoice import (
    InvoiceCreateRequest,
    InvoiceLinePayload,
    InvoicePartyPayload,
    PartyPayload,
)
from app.services.invoice_service import InvoiceService

_TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
router = APIRouter(tags=["ui"])


class UIAuthRequired(Exception):
    """Raised when a UI route requires an authenticated session cookie."""


def get_current_ui_user(
    db: Session = Depends(get_db),
    session_token: str | None = Cookie(default=None, alias="session"),
) -> AppUser:
    if not session_token:
        raise UIAuthRequired()
    user_id = decode_ui_session_token(session_token, settings.secret_key)
    if user_id is None:
        raise UIAuthRequired()
    stmt = (
        select(AppUser)
        .where(AppUser.id == user_id)
        .options(joinedload(AppUser.roles).joinedload(AppUserRole.role))
    )
    user = db.execute(stmt).unique().scalar_one_or_none()
    if not user or not user.is_active or user.is_locked:
        raise UIAuthRequired()
    return user


def ui_require_roles(*role_codes: str):
    def dependency(current_user: AppUser = Depends(get_current_ui_user)) -> AppUser:
        current_roles = {item.role.role_code for item in current_user.roles}
        if not any(role in current_roles for role in role_codes):
            raise HTTPException(
                status_code=403,
                detail=f"Brak wymaganej roli. Wymagane: {', '.join(role_codes)}",
            )
        return current_user
    return dependency


@router.get("/")
def root_redirect() -> RedirectResponse:
    return RedirectResponse(url="/ui", status_code=302)


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
        resp = RedirectResponse(url="/ui/login/totp", status_code=303)
        resp.set_cookie("totp_pending", pending, httponly=True, samesite="lax", max_age=300)
        return resp

    user.last_login_at = datetime.now(tz=timezone.utc)
    db.commit()

    token = create_ui_session_token(user.id, settings.secret_key)
    resp = RedirectResponse(url="/ui", status_code=303)
    resp.set_cookie("session", token, httponly=True, samesite="lax")
    return resp


@router.get("/ui/login/totp")
def totp_form(
    request: Request,
    totp_pending: str | None = Cookie(default=None),
):
    if not totp_pending or decode_totp_pending_token(totp_pending, settings.secret_key) is None:
        return RedirectResponse(url="/ui/login", status_code=302)
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
        return RedirectResponse(url="/ui/login", status_code=302)

    user = db.get(AppUser, user_id)
    if not user or not user.is_active or user.is_locked:
        return RedirectResponse(url="/ui/login", status_code=302)

    if not pyotp.TOTP(user.totp_secret).verify(code.strip()):
        resp = templates.TemplateResponse(
            "totp.html",
            {"request": request, "error": "Nieprawidłowy kod. Spróbuj ponownie."},
            status_code=401,
        )
        return resp

    user.last_login_at = datetime.now(tz=timezone.utc)
    db.commit()

    session_token = create_ui_session_token(user.id, settings.secret_key)
    resp = RedirectResponse(url="/ui", status_code=303)
    resp.set_cookie("session", session_token, httponly=True, samesite="lax")
    resp.delete_cookie("totp_pending")
    return resp


@router.get("/ui/logout")
def logout():
    resp = RedirectResponse(url="/ui/login", status_code=302)
    resp.delete_cookie("session")
    return resp


@router.get("/ui")
def dashboard(
    request: Request,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_ui_user),
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
        "batches": db.scalar(select(func.count()).select_from(AccountingBatch)),
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
        },
    )


@router.get("/ui/invoices")
def invoices_list(
    request: Request,
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
        },
    )


@router.get("/ui/purchase-invoices")
def purchase_invoices_list(
    request: Request,
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
        },
    )


@router.get("/ui/invoices/new")
def invoice_new_form(
    request: Request,
    current_user: AppUser = Depends(ui_require_roles("admin", "agent", "reviewer")),
):
    return templates.TemplateResponse(
        "invoice_form.html",
        {
            "request": request,
            "current_user": current_user,
            "invoice": None,
            "mode": "create",
        },
    )


@router.post("/ui/invoices/new")
def invoice_create_submit(
    invoice_number: str = Form(...),
    issue_date: str = Form(...),
    seller_name: str = Form(...),
    buyer_name: str = Form(...),
    product_name: str = Form(...),
    quantity: str = Form(...),
    unit_price_net: str = Form(...),
    vat_rate: str = Form(default="23"),
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(ui_require_roles("admin", "agent", "reviewer")),
):
    from datetime import date
    from decimal import Decimal

    try:
        payload = InvoiceCreateRequest(
            direction_code="SALE",
            invoice_kind_code="STANDARD",
            invoice_number=invoice_number,
            issue_date=date.fromisoformat(issue_date),
            parties=[
                InvoicePartyPayload(
                    role_code="SELLER",
                    sequence_no=1,
                    party=PartyPayload(
                        name_full=seller_name,
                        country_code="PL",
                    ),
                ),
                InvoicePartyPayload(
                    role_code="BUYER",
                    sequence_no=1,
                    party=PartyPayload(
                        name_full=buyer_name,
                        country_code="PL",
                    ),
                ),
            ],
            lines=[
                InvoiceLinePayload(
                    line_no=1,
                    product_name=product_name,
                    quantity=Decimal(quantity),
                    unit_price_net=Decimal(unit_price_net),
                    vat_rate=Decimal(vat_rate),
                    vat_code=vat_rate,
                    unit_code="szt",
                )
            ],
        )
        invoice = InvoiceService.create_invoice(db, payload, actor_id=str(current_user.id))
    except (InvalidOperation, ValidationError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail="Nieprawidłowe dane formularza faktury.",
        ) from exc

    return RedirectResponse(url=f"/ui/invoices/{invoice.id}", status_code=303)


@router.get("/ui/invoices/{invoice_id}")
def invoice_detail(
    invoice_id: int,
    request: Request,
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
        raise HTTPException(status_code=404, detail="Faktura nie istnieje.")

    return templates.TemplateResponse(
        "invoice_detail.html",
        {
            "request": request,
            "current_user": current_user,
            "invoice": invoice,
        },
    )


@router.post("/ui/invoices/{invoice_id}/approve")
def invoice_approve(
    invoice_id: int,
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
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Nie udało się zaakceptować faktury.",
        ) from exc

    return RedirectResponse(url=f"/ui/invoices/{invoice_id}", status_code=303)


@router.get("/ui/accounting-batches")
def accounting_batches_list(
    request: Request,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_ui_user),
):
    items = list(
        db.execute(select(AccountingBatch).order_by(AccountingBatch.id.desc()))
        .scalars()
        .all()
    )

    return templates.TemplateResponse(
        "accounting_batches_list.html",
        {
            "request": request,
            "current_user": current_user,
            "items": items,
        },
    )


@router.get("/ui/accounting-batches/{batch_id}")
def accounting_batch_detail(
    batch_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_ui_user),
):
    batch = db.get(AccountingBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch nie istnieje.")

    items = list(
        db.execute(
            select(AccountingBatchInvoice).where(AccountingBatchInvoice.batch_id == batch_id)
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
        },
    )


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
        {"request": request, "current_user": current_user, "users": users},
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
        return RedirectResponse(url=f"/ui/users/{new_user.id}/totp-setup", status_code=303)
    return RedirectResponse(url="/ui/users", status_code=303)


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
        return RedirectResponse(url="/ui/users", status_code=302)

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
        raise HTTPException(status_code=404, detail="Użytkownik nie istnieje.")

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
        raise HTTPException(status_code=404, detail="Użytkownik nie istnieje.")

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
    return RedirectResponse(url="/ui/users", status_code=303)


@router.post("/ui/users/{user_id}/totp-reset")
def user_totp_reset(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(ui_require_roles("admin")),
):
    import pyotp

    user = db.get(AppUser, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Użytkownik nie istnieje.")

    user.totp_secret = pyotp.random_base32()
    db.commit()
    return RedirectResponse(url=f"/ui/users/{user_id}/totp-setup", status_code=303)


@router.post("/ui/users/{user_id}/totp-disable")
def user_totp_disable(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(ui_require_roles("admin")),
):
    user = db.get(AppUser, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Użytkownik nie istnieje.")

    user.totp_secret = None
    db.commit()
    return RedirectResponse(url=f"/ui/users/{user_id}/edit", status_code=303)


@router.post("/ui/users/{user_id}/delete")
def user_delete(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(ui_require_roles("admin")),
):
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Nie możesz usunąć własnego konta.")

    user = db.get(AppUser, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Użytkownik nie istnieje.")

    db.execute(sql_delete(AppUserRole).where(AppUserRole.user_id == user_id))
    db.delete(user)
    db.commit()
    return RedirectResponse(url="/ui/users", status_code=303)
