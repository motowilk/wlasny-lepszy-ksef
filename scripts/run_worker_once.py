"""
Cron-friendly worker: process all pending jobs once and exit.

Usage (cron entry via DirectAdmin):
    cd /home/fdxiqghvtx/domains/limene.pl/public_html/wlasny-lepszy-ksef && \
    /home/fdxiqghvtx/virtualenv/domains/limene.pl/public_html/wlasny-lepszy-ksef/3.11/bin/python scripts/run_worker_once.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.workers.scheduler import Scheduler


def main() -> None:
    scheduler = Scheduler()
    scheduler.process_all_jobs()

    # Allow cooldown phase to display in UI briefly, then transition to idle
    time.sleep(15)
    scheduler._write_heartbeat("IDLE", phase="idle", current_jobs=[], mark_tick=False)

    print("Worker tick completed.")


if __name__ == "__main__":
    main()
