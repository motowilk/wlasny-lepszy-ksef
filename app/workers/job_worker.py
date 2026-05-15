"""Deprecated: job_worker has been replaced by the scheduler.

Use `python -m app.workers.scheduler` to run the background job processor.
The Scheduler class in scheduler.py now handles all job processing in batch mode.
"""

# Keep a minimal shim for backwards compatibility with tests that import JobWorker.
# This re-exports the Scheduler so old references don't break on import.
from app.workers.scheduler import Scheduler as JobWorker  # noqa: F401


def main() -> None:
    from app.workers.scheduler import run_scheduler
    run_scheduler()


if __name__ == "__main__":
    main()

