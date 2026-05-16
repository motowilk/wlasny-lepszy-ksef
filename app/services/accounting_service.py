import uuid
from datetime import date, timedelta
from datetime import datetime, timezone

from sqlalchemy import extract, or_, select
from sqlalchemy.orm import Session

from app.core.status_registry import ALLOWED_ACCOUNTING_STATUSES
from app.db.models import (
    AccountingBatch,
    AccountingBatchInvoice,
    IntegrationJob,
    Invoice,
    InvoiceEvent,
)

ALLOWED_BATCH_TYPES = ("MONTHLY", "WEEKLY")


def _purchase_batch_period_start(period_year: int, period_month: int) -> date:
    return date(period_year, period_month, 1)


def _default_send_at(batch_type: str, reference_date: date | None = None) -> datetime:
    """Compute default send_at based on batch type.

    MONTHLY: first day of next month 00:00 UTC
    WEEKLY: Monday of next week 00:00 UTC
    """
    ref = reference_date or date.today()
    if batch_type == "WEEKLY":
        days_until_monday = (7 - ref.weekday()) % 7 or 7
        target = ref + timedelta(days=days_until_monday)
    else:
        # MONTHLY: first day of next month
        if ref.month == 12:
            target = date(ref.year + 1, 1, 1)
        else:
            target = date(ref.year, ref.month + 1, 1)
    return datetime(target.year, target.month, target.day, 0, 0, 0, tzinfo=timezone.utc)


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

        if accounting_status == "sent_to_office":
            invoice.erp_status = "SENT_TO_OFFICE"

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

        # Allow PURCHASE invoices or SALE invoices that are KSEF_ACCEPTED
        if invoice.direction_code == "SALE" and invoice.ksef_status_code != "ACCEPTED":
            raise ValueError("Faktury sprzedażowe mogą być kwalifikowane tylko po akceptacji w KSeF.")
        if invoice.direction_code not in ("PURCHASE", "SALE"):
            raise ValueError("Nieobsługiwany kierunek faktury.")

        invoice.accounting_qualified = accounting_qualified
        invoice.accounting_marked_by = user_id
        invoice.accounting_marked_at = datetime.now(tz=timezone.utc)
        invoice.accounting_notes = accounting_notes
        invoice.erp_status = "READY_FOR_ACCOUNTING" if accounting_qualified else "BLOCKED"
        invoice.review_status = "APPROVED" if accounting_qualified else "REJECTED"
        invoice.accounting_status = "qualified" if accounting_qualified else "rejected"

        db.add(
            InvoiceEvent(
                invoice_id=invoice.id,
                event_type="PURCHASE_QUALIFICATION_UPDATED",
                event_status="SUCCESS",
                actor_type="USER",
                actor_id=str(user_id),
                message="Zmieniono kwalifikację faktury do wysyłki do biura księgowego.",
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
            _purchase_batch_period_start(period_year, period_month)

            # Reuse existing open batch for this period if one exists (never reuse SENT)
            existing_batch = db.execute(
                select(AccountingBatch).where(
                    AccountingBatch.batch_type == "MONTHLY",
                    AccountingBatch.period_year == period_year,
                    AccountingBatch.period_month == period_month,
                    AccountingBatch.status == "GENERATED",
                )
            ).scalar_one_or_none()

            if existing_batch:
                batch = existing_batch
            else:
                batch = AccountingBatch(
                    batch_uuid=str(uuid.uuid4()),
                    batch_code=(
                        f"BATCH-{period_year}-{period_month:02d}-"
                        f"{uuid.uuid4().hex[:8].upper()}"
                    ),
                    batch_type="MONTHLY",
                    status="GENERATED",
                    period_year=period_year,
                    period_month=period_month,
                    criteria_json=criteria_json,
                    created_by=created_by,
                    item_count=0,
                    send_at=_default_send_at("MONTHLY", date(period_year, period_month, 1)),
                )
                db.add(batch)
                db.flush()

            stmt = (
                select(Invoice)
                .where(
                    or_(
                        Invoice.direction_code == "PURCHASE",
                        Invoice.direction_code == "SALE",
                    ),
                    Invoice.accounting_qualified.is_(True),
                    Invoice.accounting_batch_id.is_(None),
                    extract("year", Invoice.issue_date) == period_year,
                    extract("month", Invoice.issue_date) == period_month,
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
                        inclusion_reason="Zakwalifikowana do pakietu miesięcznego.",
                    )
                )
                invoice.accounting_batch_id = batch.batch_code
                invoice.erp_status = "ACCOUNTING_BATCHED"
                invoice.accounting_status = "batched"
                batch.item_count += 1

                db.add(
                    InvoiceEvent(
                        invoice_id=invoice.id,
                        event_type="ADDED_TO_ACCOUNTING_BATCH",
                        event_status="SUCCESS",
                        actor_type="SYSTEM",
                        actor_id="accounting_service",
                        message="Dodano do pakietu wysyłkowego do biura księgowego.",
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
    def add_single_invoice_to_batch(
        db: Session,
        invoice_id: int,
        created_by: int | None = None,
    ) -> AccountingBatch:
        """Add a single qualified invoice to the monthly batch for its period."""
        invoice = db.get(Invoice, invoice_id)
        if not invoice:
            raise ValueError(f"Invoice id={invoice_id} nie istnieje.")
        if not invoice.accounting_qualified:
            raise ValueError("Faktura nie jest zakwalifikowana do wysyłki do biura księgowego.")
        if invoice.accounting_batch_id:
            raise ValueError(f"Faktura jest już w pakiecie: {invoice.accounting_batch_id}")

        period_year = invoice.issue_date.year
        period_month = invoice.issue_date.month

        # Reuse existing batch or create new one (never reuse SENT)
        existing_batch = db.execute(
            select(AccountingBatch).where(
                AccountingBatch.batch_type == "MONTHLY",
                AccountingBatch.period_year == period_year,
                AccountingBatch.period_month == period_month,
                AccountingBatch.status == "GENERATED",
            )
        ).scalar_one_or_none()

        if existing_batch:
            batch = existing_batch
        else:
            batch = AccountingBatch(
                batch_uuid=str(uuid.uuid4()),
                batch_code=(
                    f"BATCH-{period_year}-{period_month:02d}-"
                    f"{uuid.uuid4().hex[:8].upper()}"
                ),
                batch_type="MONTHLY",
                status="GENERATED",
                period_year=period_year,
                period_month=period_month,
                created_by=created_by,
                item_count=0,
                send_at=_default_send_at("MONTHLY", date(period_year, period_month, 1)),
            )
            db.add(batch)
            db.flush()

        db.add(
            AccountingBatchInvoice(
                batch_id=batch.id,
                invoice_id=invoice.id,
                inclusion_status="SELECTED",
                inclusion_reason="Dodano ręcznie do pakietu.",
            )
        )
        invoice.accounting_batch_id = batch.batch_code
        invoice.erp_status = "ACCOUNTING_BATCHED"
        invoice.accounting_status = "batched"
        batch.item_count += 1

        db.add(
            InvoiceEvent(
                invoice_id=invoice.id,
                event_type="ADDED_TO_ACCOUNTING_BATCH",
                event_status="SUCCESS",
                actor_type="USER",
                actor_id=str(created_by) if created_by else "system",
                message=f"Dodano do pakietu {batch.batch_code}.",
                details={"batch_code": batch.batch_code},
            )
        )

        db.commit()
        db.refresh(batch)
        return batch

    @staticmethod
    def send_accounting_batch_notification(db: Session, batch_id: int) -> None:
        """Mark the accounting batch as SENT to accounting office and update invoice statuses."""
        import logging as _logging
        batch = db.get(AccountingBatch, batch_id)
        if not batch:
            _logging.getLogger(__name__).warning(
                "SEND_ACCOUNTING_BATCH: batch id=%s not found.", batch_id
            )
            return

        batch.status = "SENT"
        batch.sent_at = datetime.now(tz=timezone.utc)

        # Update all invoices in batch to sent_to_office status
        batch_invoices = db.execute(
            select(AccountingBatchInvoice).where(
                AccountingBatchInvoice.batch_id == batch_id
            )
        ).scalars().all()
        for bi in batch_invoices:
            invoice = db.get(Invoice, bi.invoice_id)
            if invoice:
                invoice.accounting_status = "sent_to_office"
                invoice.erp_status = "SENT_TO_OFFICE"

        db.commit()

        _logging.getLogger(__name__).info(
            "Accounting batch id=%s code=%s (%d invoices) sent to accounting office.",
            batch.id,
            batch.batch_code,
            batch.item_count,
        )

    @staticmethod
    def update_batch_settings(
        db: Session,
        batch_id: int,
        batch_type: str | None = None,
        send_at: datetime | None = None,
    ) -> AccountingBatch:
        """Update batch_type and/or send_at on a GENERATED batch."""
        batch = db.get(AccountingBatch, batch_id)
        if not batch:
            raise ValueError(f"Pakiet id={batch_id} nie istnieje.")
        if batch.status != "GENERATED":
            raise ValueError("Nie można edytować pakietu, który został już wysłany.")

        if batch_type is not None:
            if batch_type not in ALLOWED_BATCH_TYPES:
                raise ValueError(f"Nieprawidłowy typ pakietu: {batch_type}. Dozwolone: {ALLOWED_BATCH_TYPES}")
            batch.batch_type = batch_type
            # Update period fields based on type
            if batch_type == "WEEKLY":
                batch.period_week = date.today().isocalendar()[1]
                batch.period_month = 0
            else:
                batch.period_week = None
                if batch.period_month == 0:
                    batch.period_month = date.today().month
            # Recalculate default send_at if send_at not explicitly provided
            if send_at is None:
                batch.send_at = _default_send_at(batch_type)

        if send_at is not None:
            batch.send_at = send_at

        db.commit()
        db.refresh(batch)
        return batch
