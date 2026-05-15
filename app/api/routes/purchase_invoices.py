from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.dependencies.auth import require_roles
from app.db.dependencies import get_db
from app.db.models import AppUser
from app.schemas.accounting import PurchaseQualificationRequest
from app.schemas.invoice import InvoiceListQuery, InvoiceRead
from app.services.accounting_service import AccountingService
from app.services.invoice_service import InvoiceService

router = APIRouter(prefix="/api/purchase-invoices", tags=["purchase-invoices"])


@router.get("", response_model=list[InvoiceRead])
def list_purchase_invoices(
    accounting_status: str | None = Query(default=None),
    review_status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: AppUser = Depends(require_roles("admin", "reviewer", "accountant", "viewer")),
) -> list[InvoiceRead]:
    query = InvoiceListQuery(
        direction_code="PURCHASE",
        accounting_status=accounting_status,
        review_status=review_status,
        limit=limit,
        offset=offset,
    )
    items = InvoiceService.list_invoices(db, query)
    return [InvoiceRead.model_validate(item, from_attributes=True) for item in items]


@router.get("/{invoice_id}", response_model=InvoiceRead)
def get_purchase_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    _: AppUser = Depends(require_roles("admin", "reviewer", "accountant", "viewer")),
) -> InvoiceRead:
    try:
        invoice = InvoiceService.get_invoice(db, invoice_id)
        if invoice.direction_code != "PURCHASE":
            raise HTTPException(status_code=400, detail="To nie jest faktura zakupowa.")
        return InvoiceRead.model_validate(invoice, from_attributes=True)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Faktura nie istnieje.") from exc


@router.post("/{invoice_id}/qualify", response_model=InvoiceRead)
def qualify_purchase_invoice(
    invoice_id: int,
    payload: PurchaseQualificationRequest,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(require_roles("admin", "reviewer", "accountant")),
) -> InvoiceRead:
    try:
        invoice = AccountingService.qualify_purchase_invoice(
            db=db,
            invoice_id=invoice_id,
            user_id=current_user.id,
            accounting_qualified=payload.accounting_qualified,
            accounting_notes=payload.accounting_notes,
        )
        return InvoiceRead.model_validate(invoice, from_attributes=True)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Nie udało się zakwalifikować faktury zakupowej.",
        ) from exc


@router.post("/{invoice_id}/reject-for-accounting", response_model=InvoiceRead)
def reject_purchase_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(require_roles("admin", "reviewer", "accountant")),
) -> InvoiceRead:
    try:
        invoice = AccountingService.qualify_purchase_invoice(
            db=db,
            invoice_id=invoice_id,
            user_id=current_user.id,
            accounting_qualified=False,
            accounting_notes="Odrzucono z procesu kosztowego.",
        )
        return InvoiceRead.model_validate(invoice, from_attributes=True)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Nie udało się odrzucić faktury z procesu kosztowego.",
        ) from exc


class FetchKsefPurchasesRequest(BaseModel):
    date_from: str  # ISO datetime, e.g. "2026-04-01T00:00:00"
    date_to: str  # ISO datetime, e.g. "2026-04-30T23:59:59"


class FetchKsefPurchasesResponse(BaseModel):
    imported_count: int
    imported_ids: list[int]


@router.post("/fetch-from-ksef", response_model=FetchKsefPurchasesResponse)
def fetch_purchases_from_ksef(
    payload: FetchKsefPurchasesRequest,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(require_roles("admin", "agent")),
) -> FetchKsefPurchasesResponse:
    """Fetch purchase invoices from KSeF API and import them."""
    from app.services.ksef_import_service import KsefImportService

    try:
        imported = KsefImportService.fetch_and_import_purchases(
            db=db,
            date_from=payload.date_from,
            date_to=payload.date_to,
            actor_id=str(current_user.id),
        )
        return FetchKsefPurchasesResponse(
            imported_count=len(imported),
            imported_ids=[inv.id for inv in imported],
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Błąd podczas pobierania faktur z KSeF: {exc}",
        ) from exc
