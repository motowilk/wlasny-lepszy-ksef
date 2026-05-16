from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WorkerHeartbeat(Base):
    """Tracks the liveness and current activity of each worker process.

    Each running worker (scheduler) upserts a row keyed on
    *worker_id*.  The row is updated on every heartbeat tick so the UI
    can detect workers that have gone silent.
    """

    __tablename__ = "worker_heartbeat"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    worker_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    last_heartbeat_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    # ACTIVE while processing a job, IDLE otherwise
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    current_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("integration_job.id", ondelete="SET NULL"),
        nullable=True,
    )
    current_job_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Scheduler phase: idle | processing | cooldown
    phase: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # JSON array of current job statuses for the toast UI
    current_jobs_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Timestamp of the last completed scheduler tick (process_all_jobs)
    last_tick_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
