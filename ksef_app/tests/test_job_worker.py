from datetime import datetime, timezone
from types import SimpleNamespace

from app.workers.job_worker import JobWorker
import app.workers.job_worker as job_worker_module


class FakeSession:
    def __init__(self) -> None:
        self.commit_calls = 0
        self.rollback_calls = 0
        self.closed = False

    def commit(self) -> None:
        self.commit_calls += 1

    def rollback(self) -> None:
        self.rollback_calls += 1

    def close(self) -> None:
        self.closed = True


class FakeNotificationService:
    @staticmethod
    def create_invoice_notification(db, invoice_id: int):
        return SimpleNamespace(id=invoice_id, status="NEW", error_message=None)

    @staticmethod
    def send_notification(db, notification_id: int):
        return SimpleNamespace(id=notification_id, status="FAILED", error_message="smtp offline")


def test_process_next_job_reschedules_failed_notification(monkeypatch) -> None:
    fake_db = FakeSession()
    job = SimpleNamespace(
        id=10,
        job_type="SEND_BOOKED_NOTIFICATION",
        request_payload={"invoice_id": 99},
        status="PROCESSING",
        attempts=1,
        max_attempts=3,
        locked_by="job_worker:test",
        locked_at=datetime.now(tz=timezone.utc),
        finished_at=None,
        scheduled_at=datetime.now(tz=timezone.utc),
        last_error_message=None,
        response_payload=None,
    )

    monkeypatch.setattr(job_worker_module, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(job_worker_module, "NotificationService", FakeNotificationService)

    worker = JobWorker()
    monkeypatch.setattr(worker, "_claim_next_job", lambda db: job)

    processed = worker.process_next_job()

    assert processed is False
    assert job.status == "NEW"
    assert job.last_error_message == "smtp offline"
    assert job.locked_by is None
    assert job.locked_at is None
    assert job.scheduled_at > datetime.now(tz=timezone.utc)
    assert fake_db.commit_calls == 1
    assert fake_db.closed is True
