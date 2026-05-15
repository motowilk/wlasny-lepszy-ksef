from datetime import datetime, timezone
from types import SimpleNamespace

from app.workers.scheduler import Scheduler
import app.workers.scheduler as scheduler_module


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


def test_process_all_jobs_reschedules_failed_notification(monkeypatch) -> None:
    fake_db = FakeSession()
    job = SimpleNamespace(
        id=10,
        job_type="SEND_BOOKED_NOTIFICATION",
        request_payload={"invoice_id": 99},
        status="PROCESSING",
        attempts=1,
        max_attempts=3,
        locked_by="scheduler",
        locked_at=datetime.now(tz=timezone.utc),
        finished_at=None,
        scheduled_at=datetime.now(tz=timezone.utc),
        last_error_message=None,
        response_payload=None,
    )

    monkeypatch.setattr(scheduler_module, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(scheduler_module, "NotificationService", FakeNotificationService)

    scheduler = Scheduler()
    monkeypatch.setattr(scheduler, "_claim_all_jobs", lambda db: [job])
    monkeypatch.setattr(scheduler, "_write_heartbeat", lambda *a, **kw: None)

    scheduler.process_all_jobs()

    assert job.status == "NEW"
    assert job.last_error_message == "smtp offline"
    assert job.locked_by is None
    assert job.locked_at is None
    assert job.scheduled_at > datetime.now(tz=timezone.utc)
    assert fake_db.commit_calls >= 1
    assert fake_db.closed is True
