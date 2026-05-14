import logging
import time

from apscheduler.schedulers.background import BackgroundScheduler

from app.workers.job_worker import JobWorker

logger = logging.getLogger(__name__)


def run_scheduler() -> None:
    worker = JobWorker(name="scheduler")
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        worker.process_next_job,
        "interval",
        seconds=10,
        id="job_worker_tick",
        # Prevent concurrent invocations: if a job takes longer than the
        # interval, APScheduler would otherwise spawn a second call while the
        # first is still running, causing thread-unsafe access to the shared
        # _real_ksef_client singleton and potential duplicate processing.
        max_instances=1,
    )
    scheduler.start()

    logger.info("Scheduler started.")
    try:
        while True:
            time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        logger.info("Scheduler stopped.")


if __name__ == "__main__":
    run_scheduler()
