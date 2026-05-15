from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies.auth import require_roles
from app.db.dependencies import get_db
from app.db.models import AppUser, Invoice, InvoiceEvent, InvoicePayload
from app.schemas.invoice import (
    InvoiceApproveRequest,
    InvoiceCreateRequest,
    InvoiceListQuery,
    InvoiceRead,
    InvoiceUpdateRequest,
    InvoiceValidateResponse,
)
from app.services.invoice_service import InvoiceService

router = APIRouter(prefix="/api/invoices", tags=["invoices"])


@router.post("/draft", response_model=InvoiceRead)
def create_draft(
    payload: InvoiceCreateRequest,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(require_roles("admin", "agent", "reviewer")),
) -> InvoiceRead:
    invoice = InvoiceService.create_invoice(db, payload, actor_id=str(current_user.id))
    return InvoiceRead.model_validate(invoice, from_attributes=True)


@router.get("", response_model=list[InvoiceRead])
def list_invoices(
    direction_code: str | None = Query(default=None),
    ksef_status_code: str | None = Query(default=None),
    accounting_status: str | None = Query(default=None),
    erp_status: str | None = Query(default=None),
    review_status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: AppUser = Depends(
        require_roles("admin", "reviewer", "owner", "viewer", "agent")
    ),
) -> list[InvoiceRead]:
    query = InvoiceListQuery(
        direction_code=direction_code,
        ksef_status_code=ksef_status_code,
        accounting_status=accounting_status,
        erp_status=erp_status,
        review_status=review_status,
        limit=limit,
        offset=offset,
    )
    items = InvoiceService.list_invoices(db, query)
    return [InvoiceRead.model_validate(item, from_attributes=True) for item in items]


@router.get("/{invoice_id}", response_model=InvoiceRead)
def get_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    _: AppUser = Depends(
        require_roles("admin", "reviewer", "owner", "viewer", "agent")
    ),
) -> InvoiceRead:
    try:
        invoice = InvoiceService.get_invoice(db, invoice_id)
        return InvoiceRead.model_validate(invoice, from_attributes=True)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Faktura nie istnieje.") from exc


@router.put("/{invoice_id}", response_model=InvoiceRead)
def update_invoice(
    invoice_id: int,
    payload: InvoiceUpdateRequest,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(require_roles("admin", "reviewer")),
) -> InvoiceRead:
    try:
        invoice = InvoiceService.update_invoice(
            db, invoice_id, payload, actor_id=str(current_user.id)
        )
        return InvoiceRead.model_validate(invoice, from_attributes=True)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Nie udało się zaktualizować faktury.",
        ) from exc


@router.post("/{invoice_id}/recalculate", response_model=InvoiceRead)
def recalculate_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(require_roles("admin", "reviewer")),
) -> InvoiceRead:
    try:
        invoice = InvoiceService.update_invoice(
            db,
            invoice_id,
            InvoiceUpdateRequest(),
            actor_id=str(current_user.id),
        )
        return InvoiceRead.model_validate(invoice, from_attributes=True)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Nie udało się przeliczyć faktury.",
        ) from exc


@router.post("/{invoice_id}/validate", response_model=InvoiceValidateResponse)
def validate_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    _: AppUser = Depends(require_roles("admin", "reviewer", "agent")),
) -> InvoiceValidateResponse:
    try:
        return InvoiceService.validate_invoice(db, invoice_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Faktura nie istnieje.") from exc


@router.post("/{invoice_id}/approve", response_model=InvoiceRead)
def approve_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(require_roles("admin", "reviewer")),
) -> InvoiceRead:
    try:
        invoice = InvoiceService.approve_invoice(
            db,
            invoice_id,
            InvoiceApproveRequest(approved_by_user_id=current_user.id),
            actor_id=str(current_user.id),
        )
        return InvoiceRead.model_validate(invoice, from_attributes=True)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Nie udało się zaakceptować faktury.",
        ) from exc


@router.get("/{invoice_id}/events")
def get_invoice_events(
    invoice_id: int,
    db: Session = Depends(get_db),
    _: AppUser = Depends(require_roles("admin", "reviewer", "owner", "viewer")),
):
    if not db.get(Invoice, invoice_id):
        raise HTTPException(status_code=404, detail="Faktura nie istnieje.")
    items = (
        db.execute(
            select(InvoiceEvent)
            .where(InvoiceEvent.invoice_id == invoice_id)
            .order_by(InvoiceEvent.id.desc())
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": e.id,
            "event_type": e.event_type,
            "event_status": e.event_status,
            "event_time": e.event_time,
            "actor_type": e.actor_type,
            "actor_id": e.actor_id,
            "message": e.message,
            "details": e.details,
        }
        for e in items
    ]


@router.get("/{invoice_id}/payloads")
def get_invoice_payloads(
    invoice_id: int,
    db: Session = Depends(get_db),
    _: AppUser = Depends(require_roles("admin", "reviewer", "owner", "viewer")),
):
    if not db.get(Invoice, invoice_id):
        raise HTTPException(status_code=404, detail="Faktura nie istnieje.")
    items = (
        db.execute(
            select(InvoicePayload)
            .where(InvoicePayload.invoice_id == invoice_id)
            .order_by(InvoicePayload.id.desc())
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": p.id,
            "payload_type_code": p.payload_type_code,
            "content_format": p.content_format,
            "content_sha256": p.content_sha256,
            "api_endpoint": p.api_endpoint,
            "created_at": p.created_at,
        }
        for p in items
    ]
