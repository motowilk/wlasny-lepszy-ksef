import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.notification.email import EmailNotificationAdapter
from app.core.config import settings
from app.db.models import Invoice, InvoiceEvent, InvoicePayload, NotificationLog


class NotificationService:
    @staticmethod
    def create_invoice_notification(
        db: Session,
        invoice_id: int,
        recipient: str | None = None,
    ) -> NotificationLog:
        invoice = db.get(Invoice, invoice_id)
        if not invoice:
            raise ValueError(f"Invoice id={invoice_id} nie istnieje.")

        xml_payload = NotificationService._get_latest_xml_payload(db, invoice_id)
        ui_link = f"{settings.base_url}/ui/invoices/{invoice_id}"

        # Store only a reference to the XML payload, not its full content, to
        # avoid bloating the notification_log table with large XML blobs.
        payload = {
            "invoice_number": invoice.invoice_number,
            "ksef_number": invoice.ksef_number,
            "ui_link": ui_link,
            "xml_payload_id": xml_payload.id if xml_payload else None,
        }

        notification = NotificationLog(
            notification_uuid=str(uuid.uuid4()),
            invoice_id=invoice_id,
            channel="EMAIL",
            recipient=recipient or settings.default_notification_email,
            subject=(
                f"Faktura {invoice.invoice_number} — "
                f"numer KSeF {invoice.ksef_number or '-'}"
            ),
            payload=payload,
            status="NEW",
        )
        db.add(notification)

        invoice.notification_status = "PENDING"
        invoice.notification_channel = "EMAIL"

        db.add(
            InvoiceEvent(
                invoice_id=invoice_id,
                event_type="NOTIFICATION_CREATED",
                event_status="SUCCESS",
                actor_type="SYSTEM",
                actor_id="notification_service",
                message="Utworzono notyfikację mailową.",
                details={"recipient": notification.recipient},
            )
        )

        db.commit()
        db.refresh(notification)
        return notification

    @staticmethod
    def send_notification(db: Session, notification_id: int) -> NotificationLog:
        notification = db.get(NotificationLog, notification_id)
        if not notification:
            raise ValueError(f"Notification id={notification_id} nie istnieje.")

        invoice = db.get(Invoice, notification.invoice_id) if notification.invoice_id else None

        try:
            payload = notification.payload or {}
            body = (
                f"Numer faktury: {payload.get('invoice_number', '-')}\n"
                f"Numer KSeF: {payload.get('ksef_number', '-')}\n"
                f"Link do UI: {payload.get('ui_link', '-')}\n"
            )
            EmailNotificationAdapter().send(
                recipient=notification.recipient,
                subject=notification.subject or "Powiadomienie KSeF ERP",
                body=body,
            )
            notification.status = "SENT"
            notification.sent_at = datetime.now(tz=timezone.utc)

            if invoice:
                invoice.notification_status = "SENT"
                invoice.last_notification_at = datetime.now(tz=timezone.utc)
                db.add(
                    InvoiceEvent(
                        invoice_id=invoice.id,
                        event_type="NOTIFICATION_SENT",
                        event_status="SUCCESS",
                        actor_type="SYSTEM",
                        actor_id="notification_service",
                        message="Wysłano mail z powiadomieniem.",
                        details={"recipient": notification.recipient},
                    )
                )
        except Exception as exc:
            notification.status = "FAILED"
            notification.error_message = str(exc)
            if invoice:
                invoice.notification_status = "FAILED"
                db.add(
                    InvoiceEvent(
                        invoice_id=invoice.id,
                        event_type="NOTIFICATION_FAILED",
                        event_status="ERROR",
                        actor_type="SYSTEM",
                        actor_id="notification_service",
                        message="Błąd wysyłki maila.",
                        details={"error": str(exc), "recipient": notification.recipient},
                    )
                )

        db.commit()
        db.refresh(notification)
        return notification

    @staticmethod
    def _get_latest_xml_payload(db: Session, invoice_id: int) -> InvoicePayload | None:
        stmt = (
            select(InvoicePayload)
            .where(
                InvoicePayload.invoice_id == invoice_id,
                InvoicePayload.payload_type_code == "KSEF_XML",
            )
            .order_by(InvoicePayload.id.desc())
        )
        return db.execute(stmt).scalars().first()

