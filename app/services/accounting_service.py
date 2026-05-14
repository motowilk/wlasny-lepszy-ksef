import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    AccountingBatch,
    AccountingBatchInvoice,
    IntegrationJob,
    Invoice,
    InvoiceEvent,
)

ALLOWED_ACCOUNTING_STATUSES = {"new", "verified", "posted", "booked", "cancelled"}


class AccountingService:
    @staticmethod
    def update_accounting_status(
        db: Session,
        invoice_id: int,
        accounting_status: str,
        user_id: int,
        accounting_notes: str | None = None,
        accounting_qualified: bool | None = None,
    ) -> Invoice:
        if accounting_status not in ALLOWED_ACCOUNTING_STATUSES:
            raise ValueError(f"Nieprawidłowy accounting_status={accounting_status}.")

        invoice = db.get(Invoice, invoice_id)
        if not invoice:
            raise ValueError(f"Invoice id={invoice_id} nie istnieje.")

        invoice.accounting_status = accounting_status
        invoice.accounting_marked_by = user_id
        invoice.accounting_marked_at = datetime.now(tz=timezone.utc)

        if accounting_notes is not None:
            invoice.accounting_notes = accounting_notes
        if accounting_qualified is not None:
            invoice.accounting_qualified = accounting_qualified

        if accounting_status == "booked":
            invoice.erp_status = "COMPLETED"

        db.add(
            InvoiceEvent(
                invoice_id=invoice.id,
                event_type="ACCOUNTING_STATUS_CHANGED",
                event_status="SUCCESS",
                actor_type="USER",
                actor_id=str(user_id),
                message=f"Zmieniono accounting_status na {accounting_status}.",
                details={
                    "accounting_status": accounting_status,
                    "accounting_qualified": accounting_qualified,
                },
            )
        )

        if accounting_status == "booked":
            db.add(
                IntegrationJob(
                    job_uuid=str(uuid.uuid4()),
                    tenant_id=invoice.tenant_id,
                    invoice_id=invoice.id,
                    related_entity_type="NOTIFICATION",
                    related_entity_id=str(invoice.id),
                    job_type="SEND_BOOKED_NOTIFICATION",
                    status="NEW",
                    priority=200,
                    attempts=0,
                    max_attempts=5,
                    request_payload={"invoice_id": invoice.id, "status": "booked"},
                )
            )
            db.add(
                InvoiceEvent(
                    invoice_id=invoice.id,
                    event_type="BOOKED_CLICK_RECORDED",
                    event_status="SUCCESS",
                    actor_type="USER",
                    actor_id=str(user_id),
                    message='Zarejestrowano kliknięcie "Zaksięgowano".',
                )
            )

        db.commit()
        db.refresh(invoice)
        return invoice

    @staticmethod
    def qualify_purchase_invoice(
        db: Session,
        invoice_id: int,
        user_id: int,
        accounting_qualified: bool,
        accounting_notes: str | None = None,
    ) -> Invoice:
        invoice = db.get(Invoice, invoice_id)
        if not invoice:
            raise ValueError(f"Invoice id={invoice_id} nie istnieje.")

        if invoice.direction_code != "PURCHASE":
            raise ValueError("Tylko faktury zakupowe mogą być kwalifikowane w tym procesie.")

        invoice.accounting_qualified = accounting_qualified
        invoice.accounting_marked_by = user_id
        invoice.accounting_marked_at = datetime.now(tz=timezone.utc)
        invoice.accounting_notes = accounting_notes
        invoice.erp_status = "READY_FOR_ACCOUNTING" if accounting_qualified else "BLOCKED"
        invoice.review_status = "APPROVED" if accounting_qualified else "REJECTED"

        db.add(
            InvoiceEvent(
                invoice_id=invoice.id,
                event_type="PURCHASE_QUALIFICATION_UPDATED",
                event_status="SUCCESS",
                actor_type="USER",
                actor_id=str(user_id),
                message="Zmieniono kwalifikację faktury zakupowej.",
                details={
                    "accounting_qualified": accounting_qualified,
                    "accounting_notes": accounting_notes,
                },
            )
        )

        db.commit()
        db.refresh(invoice)
        return invoice

    @staticmethod
    def generate_monthly_purchase_batch(
        db: Session,
        period_year: int,
        period_month: int,
        created_by: int | None = None,
        criteria_json: dict | None = None,
    ) -> AccountingBatch:
        try:
            batch = AccountingBatch(
                batch_uuid=str(uuid.uuid4()),
                batch_code=(
                    f"PURCHASE-{period_year}-{period_month:02d}-"
                    f"{uuid.uuid4().hex[:8].upper()}"
                ),
                batch_type="PURCHASE_MONTHLY",
                status="GENERATED",
                period_year=period_year,
                period_month=period_month,
                criteria_json=criteria_json,
                created_by=created_by,
                item_count=0,
            )
            db.add(batch)
            db.flush()

            stmt = (
                select(Invoice)
                .where(
                    Invoice.direction_code == "PURCHASE",
                    Invoice.accounting_qualified.is_(True),
                    Invoice.accounting_batch_id.is_(None),
                )
                .with_for_update()
            )
            invoices = list(db.execute(stmt).scalars().all())

            for invoice in invoices:
                db.add(
                    AccountingBatchInvoice(
                        batch_id=batch.id,
                        invoice_id=invoice.id,
                        inclusion_status="SELECTED",
                        inclusion_reason="Zakwalifikowana do batcha miesięcznego.",
                    )
                )
                invoice.accounting_batch_id = batch.batch_code
                invoice.erp_status = "ACCOUNTING_BATCHED"
                batch.item_count += 1

                db.add(
                    InvoiceEvent(
                        invoice_id=invoice.id,
                        event_type="ADDED_TO_ACCOUNTING_BATCH",
                        event_status="SUCCESS",
                        actor_type="SYSTEM",
                        actor_id="accounting_service",
                        message="Dodano do batcha księgowego.",
                        details={"batch_code": batch.batch_code},
                    )
                )

            db.add(
                IntegrationJob(
                    job_uuid=str(uuid.uuid4()),
                    related_entity_type="ACCOUNTING_BATCH",
                    related_entity_id=str(batch.id),
                    job_type="SEND_ACCOUNTING_BATCH",
                    status="NEW",
                    priority=300,
                    attempts=0,
                    max_attempts=5,
                    request_payload={"batch_id": batch.id},
                )
            )

            db.commit()
            db.refresh(batch)
            return batch
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def send_accounting_batch_notification(db: Session, batch_id: int) -> None:
        """Mark the accounting batch as SENT and log the event."""
        import logging as _logging
        batch = db.get(AccountingBatch, batch_id)
        if not batch:
            _logging.getLogger(__name__).warning(
                "SEND_ACCOUNTING_BATCH: batch id=%s not found.", batch_id
            )
            return

        batch.status = "SENT"
        batch.sent_at = datetime.now(tz=timezone.utc)
        db.commit()

        _logging.getLogger(__name__).info(
            "Accounting batch id=%s code=%s (%d invoices) marked as SENT.",
            batch.id,
            batch.batch_code,
            batch.item_count,
        )
