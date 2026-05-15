import uuid
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import IntegrationJob, Invoice, InvoiceEvent, InvoicePayload

if TYPE_CHECKING:
    from app.adapters.ksef.real_client import RealKsefClient

# Module-level singleton so the authenticated session and cached token are
# reused across all jobs instead of re-authenticating on every call.
_real_ksef_client: "RealKsefClient | None" = None


def _release_job_lock(job: IntegrationJob) -> None:
    job.locked_by = None
    job.locked_at = None


def _poll_retry_delay(attempts: int) -> timedelta:
    delay_seconds = min(300, 15 * (2 ** max(attempts - 1, 0)))
    return timedelta(seconds=delay_seconds)


def _get_real_ksef_client() -> "RealKsefClient":
    global _real_ksef_client
    if _real_ksef_client is None:
        from app.adapters.ksef.real_client import RealKsefClient
        _real_ksef_client = RealKsefClient()
    return _real_ksef_client


class KsefService:
    @staticmethod
    def process_send_to_ksef_job(db: Session, job: IntegrationJob) -> IntegrationJob:
        if not job.invoice_id:
            raise ValueError("Job nie ma invoice_id.")

        invoice = db.get(Invoice, job.invoice_id)
        if not invoice:
            raise ValueError(f"Invoice id={job.invoice_id} nie istnieje.")

        xml_payload = KsefService._get_latest_xml_payload(db, invoice.id)
        if not xml_payload:
            raise ValueError("Brak payloadu XML dla faktury.")

        invoice.ksef_status_code = "SENT"
        invoice.erp_status = "SENT_TO_KSEF"
        invoice.ksef_submission_timestamp = datetime.now(tz=timezone.utc)

        db.add(
            InvoiceEvent(
                invoice_id=invoice.id,
                event_type="KSEF_SEND_STARTED",
                event_status="SUCCESS",
                actor_type="WORKER",
                actor_id="scheduler",
                message="Rozpoczęto wysyłkę do KSeF.",
                details={"job_id": job.id},
            )
        )
        db.flush()

        settings = get_settings()
        if settings.ksef_mode == "live":
            return KsefService._process_real_send(db, job, invoice, xml_payload)
        return KsefService._process_mock_send(db, job, invoice, xml_payload)

    @staticmethod
    def _process_mock_send(
        db: Session,
        job: IntegrationJob,
        invoice: Invoice,
        xml_payload: InvoicePayload,
    ) -> IntegrationJob:
        ksef_number = KsefService._generate_mock_ksef_number(invoice.id)

        invoice.ksef_number = ksef_number
        invoice.ksef_reference_number = f"REF-{invoice.id}-{uuid.uuid4().hex[:8].upper()}"
        invoice.ksef_status_code = "ACCEPTED"
        invoice.erp_status = "KSEF_ACCEPTED"
        invoice.ksef_acceptance_timestamp = datetime.now(tz=timezone.utc)

        db.add(
            InvoicePayload(
                invoice_id=invoice.id,
                payload_type_code="KSEF_RESPONSE",
                content_format="JSON",
                content=(
                    '{"status":"ACCEPTED",'
                    f'"ksef_number":"{ksef_number}",'
                    f'"reference":"{invoice.ksef_reference_number}"'
                    "}"
                ),
                api_endpoint="/mock/ksef/status",
                transport_metadata={"mode": "mock", "result": "accepted"},
            )
        )

        db.add(
            InvoiceEvent(
                invoice_id=invoice.id,
                event_type="KSEF_ACCEPTED",
                event_status="SUCCESS",
                actor_type="WORKER",
                actor_id="scheduler",
                message="Mock KSeF zaakceptował dokument.",
                details={"ksef_number": ksef_number},
            )
        )

        job.response_payload = {
            "status": "ACCEPTED",
            "ksef_number": ksef_number,
            "invoice_id": invoice.id,
        }
        return job

    @staticmethod
    def _process_real_send(
        db: Session,
        job: IntegrationJob,
        invoice: Invoice,
        xml_payload: InvoicePayload,
    ) -> IntegrationJob:
        client = _get_real_ksef_client()
        result = client.send_invoice(invoice.id, xml_payload.content)

        invoice.ksef_reference_number = result["invoice_ref"]
        invoice.ksef_session_reference = result["session_ref"]

        db.add(
            InvoiceEvent(
                invoice_id=invoice.id,
                event_type="KSEF_SENT",
                event_status="SUCCESS",
                actor_type="WORKER",
                actor_id="scheduler",
                message="Faktura wysłana do KSeF — oczekiwanie na akceptację.",
                details={
                    "invoice_ref": result["invoice_ref"],
                    "session_ref": result["session_ref"],
                },
            )
        )

        poll_job = IntegrationJob(
            job_uuid=str(uuid.uuid4()),
            invoice_id=invoice.id,
            job_type="POLL_KSEF_STATUS",
            status="NEW",
            priority=90,
            request_payload={
                "invoice_ref": result["invoice_ref"],
                "session_ref": result["session_ref"],
            },
        )
        db.add(poll_job)

        job.response_payload = {
            "status": "SENT",
            "invoice_ref": result["invoice_ref"],
            "session_ref": result["session_ref"],
        }
        return job

    @staticmethod
    def process_poll_ksef_status_job(db: Session, job: IntegrationJob) -> IntegrationJob:
        """
        Poll KSeF for the acceptance status of a previously submitted invoice.
        If still processing, re-queues the job (sets status back to NEW).
        """
        if not job.invoice_id:
            raise ValueError("POLL_KSEF_STATUS job nie ma invoice_id.")

        invoice = db.get(Invoice, job.invoice_id)
        if not invoice:
            raise ValueError(f"Invoice id={job.invoice_id} nie istnieje.")

        payload = job.request_payload or {}
        session_ref = payload.get("session_ref")
        invoice_ref = payload.get("invoice_ref")

        if not session_ref or not invoice_ref:
            raise ValueError("Brak session_ref lub invoice_ref w request_payload.")

        if job.attempts >= job.max_attempts:
            raise ValueError("Przekroczono max_attempts dla POLL_KSEF_STATUS.")

        settings = get_settings()
        if settings.ksef_mode == "live":
            client = _get_real_ksef_client()
        else:
            from app.adapters.ksef.mock_client import MockKsefClient
            client = MockKsefClient()

        status = client.get_invoice_status(session_ref, invoice_ref)

        ksef_number = status.get("ksefNumber")
        status_code = (status.get("status") or {}).get("code", 0)

        if ksef_number:
            invoice.ksef_number = ksef_number
            invoice.ksef_status_code = "ACCEPTED"
            invoice.erp_status = "KSEF_ACCEPTED"
            invoice.ksef_acceptance_timestamp = datetime.now(tz=timezone.utc)

            db.add(
                InvoiceEvent(
                    invoice_id=invoice.id,
                    event_type="KSEF_ACCEPTED",
                    event_status="SUCCESS",
                    actor_type="WORKER",
                    actor_id="scheduler",
                    message="KSeF zaakceptował dokument.",
                    details={"ksef_number": ksef_number},
                )
            )

            job.response_payload = {"ksefNumber": ksef_number}

        elif status_code >= 400:
            error_desc = (status.get("status") or {}).get("description", "KSeF rejected.")

            db.add(
                InvoiceEvent(
                    invoice_id=invoice.id,
                    event_type="KSEF_REJECTED",
                    event_status="ERROR",
                    actor_type="WORKER",
                    actor_id="scheduler",
                    message=f"KSeF odrzucił dokument: {error_desc}",
                    details={"status": status},
                )
            )

            invoice.ksef_status_code = "REJECTED"
            invoice.erp_status = "KSEF_REJECTED"
            raise RuntimeError(error_desc)

        else:
            # Still processing — signal the caller to re-queue
            job.response_payload = {"poll_status": "PENDING"}
            job.status = "NEW"
            job.scheduled_at = datetime.now(tz=timezone.utc) + _poll_retry_delay(job.attempts)

        return job

    @staticmethod
    def _generate_mock_ksef_number(invoice_id: int) -> str:
        timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d%H%M%S")
        return f"KSEF-MOCK-{timestamp}-{invoice_id:06d}"

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
