from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies.auth import require_roles
from app.db.dependencies import get_db
from app.db.models import AccountingBatch, AppUser
from app.schemas.accounting import (
    AccountingBatchGenerateRequest,
    AccountingBatchRead,
    AccountingStatusUpdateRequest,
    PurchaseQualificationRequest,
)
from app.schemas.invoice import InvoiceRead
from app.services.accounting_service import AccountingService

router = APIRouter(prefix="/api", tags=["accounting"])


@router.post("/invoices/{invoice_id}/accounting-status", response_model=InvoiceRead)
def update_accounting_status(
    invoice_id: int,
    payload: AccountingStatusUpdateRequest,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(require_roles("admin", "accountant")),
) -> InvoiceRead:
    try:
        invoice = AccountingService.update_accounting_status(
            db=db,
            invoice_id=invoice_id,
            accounting_status=payload.accounting_status,
            user_id=current_user.id,
            accounting_notes=payload.accounting_notes,
            accounting_qualified=payload.accounting_qualified,
        )
        return InvoiceRead.model_validate(invoice, from_attributes=True)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Nie udało się zaktualizować statusu księgowego.",
        ) from exc


@router.post("/accounting-batches/generate", response_model=AccountingBatchRead)
def generate_accounting_batch(
    payload: AccountingBatchGenerateRequest,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(require_roles("admin", "accountant")),
) -> AccountingBatchRead:
    batch = AccountingService.generate_monthly_purchase_batch(
        db=db,
        period_year=payload.period_year,
        period_month=payload.period_month,
        created_by=current_user.id,
        criteria_json=payload.criteria_json,
    )
    return AccountingBatchRead.model_validate(batch, from_attributes=True)


@router.get("/accounting-batches", response_model=list[AccountingBatchRead])
def list_accounting_batches(
    db: Session = Depends(get_db),
    _: AppUser = Depends(require_roles("admin", "accountant", "viewer")),
) -> list[AccountingBatchRead]:
    items = (
        db.execute(select(AccountingBatch).order_by(AccountingBatch.id.desc()))
        .scalars()
        .all()
    )
    return [AccountingBatchRead.model_validate(item, from_attributes=True) for item in items]


@router.get("/accounting-batches/{batch_id}", response_model=AccountingBatchRead)
def get_accounting_batch(
    batch_id: int,
    db: Session = Depends(get_db),
    _: AppUser = Depends(require_roles("admin", "accountant", "viewer")),
) -> AccountingBatchRead:
    batch = db.get(AccountingBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch nie istnieje.")
    return AccountingBatchRead.model_validate(batch, from_attributes=True)


@router.post("/invoices/{invoice_id}/qualify", response_model=InvoiceRead)
def qualify_invoice_for_accounting(
    invoice_id: int,
    payload: PurchaseQualificationRequest,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(require_roles("admin", "agent", "accountant")),
) -> InvoiceRead:
    """Qualify any invoice (PURCHASE or SALE with KSEF ACCEPTED) for accounting batch."""
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
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/invoices/{invoice_id}/add-to-batch", response_model=AccountingBatchRead)
def add_invoice_to_batch(
    invoice_id: int,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(require_roles("admin", "agent", "accountant")),
) -> AccountingBatchRead:
    """Add a qualified invoice to the monthly accounting batch for its issue_date period."""
    from app.db.models import Invoice as InvoiceModel

    invoice = db.get(InvoiceModel, invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Faktura nie istnieje.")
    if not invoice.accounting_qualified:
        raise HTTPException(
            status_code=400,
            detail="Faktura nie jest zakwalifikowana do procesu księgowego.",
        )
    if invoice.accounting_batch_id:
        raise HTTPException(
            status_code=400,
            detail=f"Faktura jest już w batchu: {invoice.accounting_batch_id}",
        )

    batch = AccountingService.generate_monthly_purchase_batch(
        db=db,
        period_year=invoice.issue_date.year,
        period_month=invoice.issue_date.month,
        created_by=current_user.id,
    )
    return AccountingBatchRead.model_validate(batch, from_attributes=True)
