import logging
import os
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db.models import IntegrationJob
from app.db.session import SessionLocal
from app.services.ksef_service import KsefService
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)


class JobWorker:
    def __init__(self) -> None:
        self.worker_id = f"job_worker:{os.getpid()}"

    @staticmethod
    def _retry_delay(attempts: int) -> timedelta:
        delay_seconds = min(300, 5 * (2 ** max(attempts - 1, 0)))
        return timedelta(seconds=delay_seconds)

    @staticmethod
    def _release_job_lock(job: IntegrationJob) -> None:
        job.locked_by = None
        job.locked_at = None

    def run_forever(self, sleep_seconds: int = 5) -> None:
        logger.info("JobWorker started.")
        while True:
            processed = self.process_next_job()
            if not processed:
                time.sleep(sleep_seconds)

    def _claim_next_job(self, db):
        now = datetime.now(tz=timezone.utc)
        stmt = (
            select(IntegrationJob)
            .where(
                IntegrationJob.status == "NEW",
                IntegrationJob.scheduled_at <= now,
            )
            .order_by(IntegrationJob.priority.asc(), IntegrationJob.id.asc())
            .with_for_update(skip_locked=True)
            .limit(1)
        )

        with db.begin():
            job = db.execute(stmt).scalars().first()
            if not job:
                return None

            job.status = "PROCESSING"
            job.locked_by = self.worker_id
            job.locked_at = now
            job.started_at = job.started_at or now
            job.attempts = (job.attempts or 0) + 1

        db.refresh(job)
        return job

    def _fail_job(self, db, job: IntegrationJob, exc: Exception) -> None:
        job.status = "FAILED"
        job.last_error_message = str(exc)
        job.finished_at = datetime.now(tz=timezone.utc)
        self._release_job_lock(job)
        db.commit()

    def _reschedule_job(self, db, job: IntegrationJob, exc: Exception) -> None:
        job.status = "NEW"
        job.last_error_message = str(exc)
        job.scheduled_at = datetime.now(tz=timezone.utc) + self._retry_delay(job.attempts)
        job.finished_at = None
        self._release_job_lock(job)
        db.commit()

    def process_next_job(self) -> bool:
        db = SessionLocal()
        job = None
        try:
            job = self._claim_next_job(db)
            if not job:
                return False

            logger.info("Processing job id=%s type=%s", job.id, job.job_type)

            if job.job_type == "SEND_TO_KSEF":
                KsefService.process_send_to_ksef_job(db, job)

            elif job.job_type == "POLL_KSEF_STATUS":
                KsefService.process_poll_ksef_status_job(db, job)

            elif job.job_type == "SEND_BOOKED_NOTIFICATION":
                invoice_id = (job.request_payload or {}).get("invoice_id")
                if not invoice_id:
                    raise ValueError("Brak invoice_id w request_payload.")
                notification = NotificationService.create_invoice_notification(db, invoice_id)
                notification = NotificationService.send_notification(db, notification.id)
                if notification.status != "SENT":
                    raise RuntimeError(
                        notification.error_message or "Wysyłka powiadomienia zakończyła się błędem."
                    )
                job.status = "DONE"
                job.finished_at = datetime.now(tz=timezone.utc)
                self._release_job_lock(job)
                db.commit()

            elif job.job_type == "SEND_ACCOUNTING_BATCH":
                from app.services.accounting_service import AccountingService
                batch_id = int(job.related_entity_id or "0")
                AccountingService.send_accounting_batch_notification(db, batch_id)
                job.status = "DONE"
                job.finished_at = datetime.now(tz=timezone.utc)
                job.response_payload = {"status": "BATCH_NOTIFICATION_SENT", "batch_id": batch_id}
                self._release_job_lock(job)
                db.commit()

            else:
                raise ValueError(f"Nieobsługiwany job_type={job.job_type}")

            logger.info("Job id=%s finished successfully", job.id)
            return True

        except Exception as exc:
            logger.exception("Job processing failed: %s", exc)
            if job is not None:
                try:
                    # Roll back any failed/dirty transaction before attempting to
                    # persist the error state.  Without this, a DB-level error
                    # (e.g. constraint violation in flush) leaves the session in
                    # an invalid state and the subsequent commit in _fail_job /
                    # _reschedule_job raises InvalidRequestError, leaving the
                    # job permanently stuck in PROCESSING.
                    db.rollback()
                    if job.attempts >= job.max_attempts:
                        self._fail_job(db, job, exc)
                    else:
                        self._reschedule_job(db, job, exc)
                except Exception:
                    db.rollback()
            return False
        finally:
            db.close()


def main() -> None:
    worker = JobWorker()
    worker.run_forever()


if __name__ == "__main__":
    main()
