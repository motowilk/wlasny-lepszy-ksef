"""Service for importing invoices fetched from KSeF into the local database."""

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.notification.discord import DiscordNotificationAdapter
from app.db.models import Invoice, InvoiceEvent, InvoicePayload
from app.services.invoice_service import InvoiceService
from app.services.ksef_xml_parser import parse_fa3_xml

logger = logging.getLogger(__name__)


class KsefImportService:
    @staticmethod
    def import_invoice_xml(
        db: Session,
        xml_content: str,
        ksef_number: str | None = None,
        direction_code: str = "PURCHASE",
        actor_id: str | None = None,
    ) -> Invoice | None:
        """
        Parse an FA(3) XML and create a PURCHASE invoice in the database.

        Skips if an invoice with the same ksef_number already exists.

        Returns the created Invoice or None if skipped.
        """
        # Deduplicate by ksef_number
        if ksef_number:
            existing = db.execute(
                select(Invoice).where(Invoice.ksef_number == ksef_number)
            ).scalar_one_or_none()
            if existing:
                logger.info(
                    "Invoice with ksef_number=%s already exists (id=%s), skipping.",
                    ksef_number,
                    existing.id,
                )
                return None

        # Also deduplicate by invoice_number from XML
        payload = parse_fa3_xml(xml_content, direction_code=direction_code)

        if payload.invoice_number:
            existing_by_number = db.execute(
                select(Invoice).where(Invoice.invoice_number == payload.invoice_number)
            ).scalar_one_or_none()
            if existing_by_number:
                logger.info(
                    "Invoice with invoice_number=%s already exists (id=%s), skipping.",
                    payload.invoice_number,
                    existing_by_number.id,
                )
                return None

        # Create the invoice
        invoice = InvoiceService.create_invoice(db, payload, actor_id=actor_id)

        # Set KSeF-specific fields
        if ksef_number:
            invoice.ksef_number = ksef_number
        invoice.ksef_status_code = "ACCEPTED"
        invoice.erp_status = "KSEF_ACCEPTED"
        invoice.receive_date = datetime.now(tz=timezone.utc).date()

        # Save the raw XML as a payload
        import hashlib as _hashlib

        db.add(
            InvoicePayload(
                invoice_id=invoice.id,
                payload_type_code="KSEF_XML_RECEIVED",
                content_format="XML",
                content=xml_content,
                content_sha256=_hashlib.sha256(xml_content.encode()).hexdigest(),
            )
        )

        # Event
        db.add(
            InvoiceEvent(
                invoice_id=invoice.id,
                event_type="KSEF_INVOICE_IMPORTED",
                event_status="SUCCESS",
                actor_type="WORKER",
                actor_id=actor_id,
                message=f"Zaimportowano fakturę z KSeF: {ksef_number or payload.invoice_number}",
            )
        )

        db.commit()
        db.refresh(invoice)

        seller_name = ""
        for ip in invoice.parties:
            if ip.role_code == "SELLER":
                seller_name = ip.party.name_full if ip.party else ""
                break
        DiscordNotificationAdapter().send(
            f"Pobrano fakturę zakupową {invoice.invoice_number} od {seller_name} na kwotę {invoice.gross_total}"
        )

        logger.info(
            "Imported invoice id=%s ksef_number=%s invoice_number=%s",
            invoice.id,
            ksef_number,
            invoice.invoice_number,
        )
        return invoice

    @staticmethod
    def fetch_and_import_purchases(
        db: Session,
        date_from: str,
        date_to: str,
        actor_id: str | None = None,
    ) -> list[Invoice]:
        """
        Fetch purchase invoices from KSeF API and import them.

        Args:
            db: Database session.
            date_from: ISO datetime string for range start.
            date_to: ISO datetime string for range end.
            actor_id: Optional user/system actor ID.

        Returns:
            List of newly imported Invoice objects.
        """
        from app.services.ksef_service import _get_real_ksef_client
        from app.core.config import get_settings

        settings = get_settings()

        if settings.ksef_mode == "mock":
            from app.adapters.ksef.mock_client import MockKsefClient
            client = MockKsefClient()
        else:
            client = _get_real_ksef_client()

        fetched = client.fetch_invoices(
            date_from=date_from,
            date_to=date_to,
            subject_type="subject2",  # buyer = me → purchase invoices
        )

        imported: list[Invoice] = []
        for item in fetched:
            try:
                invoice = KsefImportService.import_invoice_xml(
                    db=db,
                    xml_content=item["xml_content"],
                    ksef_number=item.get("ksef_number"),
                    direction_code="PURCHASE",
                    actor_id=actor_id,
                )
                if invoice:
                    imported.append(invoice)
            except Exception as exc:
                logger.error(
                    "Failed to import invoice ksef_number=%s: %s",
                    item.get("ksef_number"),
                    exc,
                )

        logger.info("Fetched %d invoices from KSeF, imported %d new.", len(fetched), len(imported))
        return imported
