import json
import logging
import time
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import delete, select

from app.core.config import settings
from app.db.models import IntegrationJob, WorkerHeartbeat
from app.db.session import SessionLocal
from app.services.ksef_service import KsefService
from app.services.notification_service import NotificationService
from app.adapters.notification.discord import DiscordNotificationAdapter

logger = logging.getLogger(__name__)

# ─── Shared state for the worker-status API ────────────────────────────────
# Updated by the scheduler tick; read by /ui/api/worker-status.
scheduler_state: dict = {
    "running": False,
    "last_tick_at": None,
    "last_job_finished_at": None,
    "current_jobs": [],       # list of {"job_id", "job_type", "status": "pending"|"running"|"done"|"failed"}
    "phase": "idle",          # "idle" | "processing" | "cooldown"
}


class Scheduler:
    WORKER_ID = "scheduler"

    def __init__(self) -> None:
        self._scheduler: BackgroundScheduler | None = None

    # ─── Retry helpers ──────────────────────────────────────────────────
    @staticmethod
    def _retry_delay(attempts: int) -> timedelta:
        delay_seconds = min(300, 5 * (2 ** max(attempts - 1, 0)))
        return timedelta(seconds=delay_seconds)

    @staticmethod
    def _release_job_lock(job: IntegrationJob) -> None:
        job.locked_by = None
        job.locked_at = None

    # ─── Discord webhook ────────────────────────────────────────────────
    def _notify_discord(self, summary: str) -> None:
        discord = DiscordNotificationAdapter()
        if not discord.enabled:
            return
        discord.send(summary)

    _JOB_TYPE_LABELS = {
        "SEND_TO_KSEF": "Wysyłanie do KSeF",
        "POLL_KSEF_STATUS": "Sprawdzanie statusu KSeF",
        "SEND_BOOKED_NOTIFICATION": "Wysyłanie powiadomienia",
        "SEND_ACCOUNTING_BATCH": "Batch księgowy",
        "FETCH_KSEF_PURCHASES": "Pobieranie faktur zakupowych",
        "POLL_GITHUB_PROJECT": "Sprawdzanie tablicy GitHub",
    }

    _STATUS_LABELS = {
        "done": "wykonano",
        "skipped": "pominięto",
        "failed": "błąd",
        "running": "w trakcie",
        "pending": "oczekuje",
    }

    def _run_synthetic_job(self, job_type: str) -> None:
        """Execute synthetic jobs that don't have a DB record."""
        if job_type == "POLL_GITHUB_PROJECT":
            from app.services.github_monitor_service import GitHubMonitorService
            GitHubMonitorService.check_board_changes()
        elif job_type == "SEND_DISCORD_NOTIFICATION":
            lines = ["**Podsumowanie cyklu schedulera:**"]
            for entry in scheduler_state.get("current_jobs", []):
                jt = entry.get("job_type", "?")
                st = entry.get("status", "?")
                jid = entry.get("job_id")
                if jt == "SEND_DISCORD_NOTIFICATION":
                    continue
                label = self._JOB_TYPE_LABELS.get(jt, jt)
                status_label = self._STATUS_LABELS.get(st, st)
                id_part = f" (id={jid})" if jid else ""
                lines.append(f"\u2022 {label}{id_part} \u2014 {status_label}")
            self._notify_discord("\n".join(lines))
        else:
            raise ValueError(f"Unknown synthetic job: {job_type}")

    # ─── Heartbeat ──────────────────────────────────────────────────────
    def _write_heartbeat(
        self,
        status: str,
        job_type: str | None = None,
        job_id: int | None = None,
        phase: str | None = None,
        current_jobs: list | None = None,
        mark_tick: bool = False,
    ) -> None:
        db = SessionLocal()
        try:
            now = datetime.now(tz=timezone.utc)
            jobs_json = json.dumps(current_jobs) if current_jobs is not None else None
            heartbeat = db.execute(
                select(WorkerHeartbeat).where(WorkerHeartbeat.worker_id == self.WORKER_ID)
            ).scalars().first()
            if heartbeat:
                heartbeat.last_heartbeat_at = now
                heartbeat.status = status
                heartbeat.current_job_type = job_type
                heartbeat.current_job_id = job_id
                if phase is not None:
                    heartbeat.phase = phase
                if jobs_json is not None:
                    heartbeat.current_jobs_json = jobs_json
                if mark_tick:
                    heartbeat.last_tick_at = now
            else:
                db.execute(
                    delete(WorkerHeartbeat).where(
                        WorkerHeartbeat.worker_id.like(self.WORKER_ID + ":%")
                    )
                )
                db.add(
                    WorkerHeartbeat(
                        worker_id=self.WORKER_ID,
                        last_heartbeat_at=now,
                        status=status,
                        current_job_type=job_type,
                        current_job_id=job_id,
                        phase=phase or "idle",
                        current_jobs_json=jobs_json,
                        last_tick_at=now if mark_tick else None,
                    )
                )
            db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.error("Heartbeat write failed: %s", exc)
            db.rollback()
        finally:
            db.close()

    # ─── Claim all eligible jobs ────────────────────────────────────────
    def _claim_all_jobs(self, db) -> list[IntegrationJob]:
        now = datetime.now(tz=timezone.utc)
        stmt = (
            select(IntegrationJob)
            .where(
                IntegrationJob.status == "NEW",
                IntegrationJob.scheduled_at <= now,
            )
            .order_by(IntegrationJob.priority.asc(), IntegrationJob.id.asc())
            .with_for_update(skip_locked=True)
        )

        with db.begin():
            jobs = db.execute(stmt).scalars().all()
            for job in jobs:
                job.status = "PROCESSING"
                job.locked_by = self.WORKER_ID
                job.locked_at = now
                job.started_at = job.started_at or now
                job.attempts = (job.attempts or 0) + 1

        for job in jobs:
            db.refresh(job)
        return list(jobs)

    # ─── Execute a single job ───────────────────────────────────────────
    def _execute_job(self, db, job: IntegrationJob) -> None:
        """Run job logic. On success, marks DONE. On failure, raises."""
        if job.job_type == "SEND_TO_KSEF":
            KsefService.process_send_to_ksef_job(db, job)

        elif job.job_type == "POLL_KSEF_STATUS":
            KsefService.process_poll_ksef_status_job(db, job)
            # POLL may re-queue itself (status set to NEW inside service)
            if job.status == "NEW":
                self._release_job_lock(job)
                db.commit()
                return

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

        elif job.job_type == "SEND_ACCOUNTING_BATCH":
            from app.services.accounting_service import AccountingService
            batch_id = int(job.related_entity_id or "0")

            # Check if the batch send_at time has been reached
            from app.db.models import AccountingBatch
            batch = db.get(AccountingBatch, batch_id)
            if batch and batch.send_at and datetime.now(tz=timezone.utc) < batch.send_at:
                # Not yet time to send — reschedule
                job.status = "NEW"
                job.scheduled_at = batch.send_at
                self._release_job_lock(job)
                db.commit()
                return

            AccountingService.send_accounting_batch_notification(db, batch_id)
            job.response_payload = {"status": "BATCH_NOTIFICATION_SENT", "batch_id": batch_id}

        elif job.job_type == "FETCH_KSEF_PURCHASES":
            from app.services.ksef_import_service import KsefImportService
            req = job.request_payload or {}
            date_from = req.get("date_from", "")
            date_to = req.get("date_to", "")
            if not date_from or not date_to:
                raise ValueError("FETCH_KSEF_PURCHASES wymaga date_from i date_to w request_payload.")
            imported = KsefImportService.fetch_and_import_purchases(
                db=db,
                date_from=date_from,
                date_to=date_to,
                actor_id=self.WORKER_ID,
            )
            job.response_payload = {
                "status": "PURCHASES_FETCHED",
                "imported_count": len(imported),
                "imported_ids": [inv.id for inv in imported],
            }


        else:
            raise ValueError(f"Nieobsługiwany job_type={job.job_type}")

        # Unified lifecycle management for successful jobs
        job.status = "DONE"
        job.finished_at = datetime.now(tz=timezone.utc)
        self._release_job_lock(job)
        db.commit()

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

    # All known job types — shown in toast on every tick
    JOB_TYPES = [
        "SEND_TO_KSEF",
        "POLL_KSEF_STATUS",
        "SEND_BOOKED_NOTIFICATION",
        "SEND_ACCOUNTING_BATCH",
        "FETCH_KSEF_PURCHASES",
        "POLL_GITHUB_PROJECT",
        "SEND_DISCORD_NOTIFICATION",
    ]

    # ─── Main tick: process ALL pending jobs ────────────────────────────
    def process_all_jobs(self) -> None:
        global scheduler_state

        db = SessionLocal()
        try:
            jobs = self._claim_all_jobs(db)

            # Build task list: one entry per known job type
            # Jobs that have pending work get real entries; others are "skipped"
            job_by_type: dict[str, list[IntegrationJob]] = {}
            for job in jobs:
                job_by_type.setdefault(job.job_type, []).append(job)

            task_list = []
            for jt in self.JOB_TYPES:
                if jt in job_by_type:
                    for j in job_by_type[jt]:
                        task_list.append({"job_id": j.id, "job_type": jt, "status": "pending", "_job": j})
                elif jt in ("SEND_DISCORD_NOTIFICATION", "POLL_GITHUB_PROJECT"):
                    # Always run — synthetic job, no DB record needed
                    task_list.append({"job_id": None, "job_type": jt, "status": "pending", "_job": "synthetic"})
                else:
                    task_list.append({"job_id": None, "job_type": jt, "status": "skipped", "_job": None})

            scheduler_state["phase"] = "processing"
            scheduler_state["current_jobs"] = [
                {"job_id": t["job_id"], "job_type": t["job_type"], "status": "pending"}
                for t in task_list
            ]
            self._write_heartbeat(
                "ACTIVE",
                phase="processing",
                current_jobs=scheduler_state["current_jobs"],
            )

            for idx, task in enumerate(task_list):
                job = task["_job"]

                # Mark as running (even if it will be skipped — show it briefly)
                scheduler_state["current_jobs"][idx]["status"] = "running"
                self._write_heartbeat(
                    "ACTIVE", task["job_type"], task["job_id"],
                    phase="processing",
                    current_jobs=scheduler_state["current_jobs"],
                )

                # Pause so frontend can see the "running" state
                time.sleep(2)

                if job is None:
                    # No work for this job type — mark skipped
                    scheduler_state["current_jobs"][idx]["status"] = "skipped"
                    self._write_heartbeat(
                        "ACTIVE", task["job_type"], task["job_id"],
                        phase="processing",
                        current_jobs=scheduler_state["current_jobs"],
                    )
                    continue

                # Synthetic job (e.g. SEND_DISCORD_NOTIFICATION) — no DB record
                if job == "synthetic":
                    try:
                        self._run_synthetic_job(task["job_type"])
                        scheduler_state["current_jobs"][idx]["status"] = "done"
                    except Exception as exc:
                        logger.exception("Synthetic job %s failed: %s", task["job_type"], exc)
                        scheduler_state["current_jobs"][idx]["status"] = "failed"
                    self._write_heartbeat(
                        "ACTIVE", task["job_type"], task["job_id"],
                        phase="processing",
                        current_jobs=scheduler_state["current_jobs"],
                    )
                    continue

                # POLL_KSEF_STATUS jobs are handled as a batch below
                if task["job_type"] == "POLL_KSEF_STATUS":
                    continue

                logger.info("Processing job id=%s type=%s", job.id, job.job_type)

                try:
                    self._execute_job(db, job)
                    scheduler_state["current_jobs"][idx]["status"] = "done"
                    self._write_heartbeat(
                        "ACTIVE", job.job_type, job.id,
                        phase="processing",
                        current_jobs=scheduler_state["current_jobs"],
                    )
                    logger.info("Job id=%s finished successfully", job.id)
                except Exception as exc:
                    logger.exception("Job id=%s failed: %s", job.id, exc)
                    scheduler_state["current_jobs"][idx]["status"] = "failed"
                    self._write_heartbeat(
                        "ACTIVE", job.job_type, job.id,
                        phase="processing",
                        current_jobs=scheduler_state["current_jobs"],
                    )
                    try:
                        db.rollback()
                        if job.attempts >= job.max_attempts:
                            self._fail_job(db, job, exc)
                        else:
                            self._reschedule_job(db, job, exc)
                    except Exception:
                        db.rollback()

            # Process POLL_KSEF_STATUS jobs as a batch via the service
            poll_indices = [
                i for i, t in enumerate(task_list)
                if t["job_type"] == "POLL_KSEF_STATUS" and t["_job"] is not None
            ]
            if poll_indices:
                poll_jobs = [task_list[i]["_job"] for i in poll_indices]
                batch_result = KsefService.process_poll_ksef_status_batch(db, poll_jobs)
                for i, res in zip(poll_indices, batch_result["results"]):
                    job = task_list[i]["_job"]
                    if res["result"] == "accepted":
                        job.status = "DONE"
                        job.finished_at = datetime.now(tz=timezone.utc)
                        self._release_job_lock(job)
                        scheduler_state["current_jobs"][i]["status"] = "done"
                    elif res["result"] == "pending":
                        self._release_job_lock(job)
                        scheduler_state["current_jobs"][i]["status"] = "done"
                    elif res["result"] == "rejected":
                        job.status = "FAILED"
                        job.last_error_message = res.get("error", "")
                        job.finished_at = datetime.now(tz=timezone.utc)
                        self._release_job_lock(job)
                        scheduler_state["current_jobs"][i]["status"] = "failed"
                    db.commit()

            # All jobs processed — enter cooldown (15s) to show results
            now = datetime.now(tz=timezone.utc)
            scheduler_state["phase"] = "cooldown"
            scheduler_state["last_job_finished_at"] = now.isoformat()
            scheduler_state["last_tick_at"] = now.isoformat()
            self._write_heartbeat(
                "IDLE",
                phase="cooldown",
                current_jobs=scheduler_state["current_jobs"],
                mark_tick=True,
            )

        finally:
            db.close()

    # ─── Scheduler lifecycle ────────────────────────────────────────────
    def _heartbeat_tick(self) -> None:
        """Lightweight periodic heartbeat so the toast stays green between job ticks.
        Also transitions cooldown → idle after 15s."""
        global scheduler_state
        if scheduler_state.get("phase") == "cooldown":
            last_finished = scheduler_state.get("last_job_finished_at")
            if last_finished:
                finished_dt = datetime.fromisoformat(last_finished)
                if finished_dt.tzinfo is None:
                    finished_dt = finished_dt.replace(tzinfo=timezone.utc)
                if (datetime.now(tz=timezone.utc) - finished_dt).total_seconds() >= 15:
                    scheduler_state["phase"] = "idle"
                    scheduler_state["current_jobs"] = []
                    self._write_heartbeat("IDLE", phase="idle", current_jobs=[])
                    return
        self._write_heartbeat("IDLE")

    def start(self) -> None:
        global scheduler_state
        scheduler_state["running"] = True

        self._scheduler = BackgroundScheduler()
        self._scheduler.add_job(
            self.process_all_jobs,
            "interval",
            seconds=settings.scheduler_interval,
            id="scheduler_tick",
            max_instances=1,
            next_run_time=datetime.now(tz=timezone.utc),  # fire immediately on start
        )
        # Heartbeat every 5s keeps the toast green between job-processing ticks
        self._scheduler.add_job(
            self._heartbeat_tick,
            "interval",
            seconds=5,
            id="heartbeat_tick",
        )
        self._scheduler.start()

        logger.info("Scheduler started (interval: %ss).", settings.scheduler_interval)

        # Write initial heartbeat
        self._write_heartbeat("IDLE")
        scheduler_state["last_tick_at"] = datetime.now(tz=timezone.utc).isoformat()

    def stop(self) -> None:
        global scheduler_state
        scheduler_state["running"] = False
        if self._scheduler:
            self._scheduler.shutdown()
        logger.info("Scheduler stopped.")


def run_scheduler() -> None:
    scheduler = Scheduler()
    scheduler.start()
    try:
        while True:
            time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        scheduler.stop()


if __name__ == "__main__":
    run_scheduler()
