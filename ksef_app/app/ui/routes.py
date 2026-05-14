from pathlib import Path
from decimal import InvalidOperation

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.api.dependencies.auth import get_current_user, require_roles
from app.db.dependencies import get_db
from app.db.models import (
    AccountingBatch,
    AccountingBatchInvoice,
    AppUser,
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


@router.get("/")
def root_redirect() -> RedirectResponse:
    return RedirectResponse(url="/ui", status_code=302)


@router.get("/ui")
def dashboard(
    request: Request,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
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
    current_user: AppUser = Depends(get_current_user),
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
    current_user: AppUser = Depends(get_current_user),
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
    current_user: AppUser = Depends(require_roles("admin", "agent", "reviewer")),
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
    current_user: AppUser = Depends(require_roles("admin", "agent", "reviewer")),
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
    current_user: AppUser = Depends(get_current_user),
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
    current_user: AppUser = Depends(require_roles("admin", "reviewer")),
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
    current_user: AppUser = Depends(get_current_user),
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
    current_user: AppUser = Depends(get_current_user),
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
    current_user: AppUser = Depends(get_current_user),
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
