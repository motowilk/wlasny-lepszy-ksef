import logging
import time

from apscheduler.schedulers.background import BackgroundScheduler

from app.workers.job_worker import JobWorker

logger = logging.getLogger(__name__)


def run_scheduler() -> None:
    worker = JobWorker()
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        worker.process_next_job,
        "interval",
        seconds=10,
        id="job_worker_tick",
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
