"""
core/scheduler.py — Zero OS Proactive Scheduler

Wraps APScheduler's AsyncIOScheduler with a clean API.
Jobs persist across restarts via SQLite job store.

Design:
  - AsyncIOScheduler runs inside the FastAPI event loop — no extra threads
  - Jobs are stored in ZERO_ROOT/scheduler.db (SQLite via SQLAlchemy)
  - Each job is a plain async function that calls agents and pushes to the alert queue
  - Jobs can be: cron (time-based), interval (every N minutes), or date (one-shot)

Usage:
    from core.scheduler import scheduler
    scheduler.start()
    scheduler.add_cron_job("morning_briefing", morning_briefing_job, hour=8, minute=0)
    scheduler.list_jobs()
    scheduler.remove_job("morning_briefing")
    scheduler.stop()

Dependencies:
    pip install apscheduler sqlalchemy
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)

ZERO_ROOT = Path(__file__).parent.parent
DB_PATH = ZERO_ROOT / "scheduler.db"


# ---------------------------------------------------------------------------
# Scheduler wrapper
# ---------------------------------------------------------------------------

class AstraScheduler:
    """
    Thin wrapper around APScheduler's AsyncIOScheduler.

    Provides a clean, Astra-flavoured API for registering and managing
    proactive background jobs.
    """

    def __init__(self) -> None:
        """Initialise the scheduler (does not start it yet)."""
        self._scheduler = None  # lazy-init on start()
        self._started = False

    def _get_scheduler(self):
        """
        Lazily initialise the APScheduler instance with SQLite persistence.

        Returns:
            AsyncIOScheduler instance.
        """
        if self._scheduler is not None:
            return self._scheduler

        try:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler
            from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
        except ImportError:
            raise RuntimeError(
                "APScheduler not installed. Run: pip install apscheduler sqlalchemy"
            )

        jobstore = SQLAlchemyJobStore(url=f"sqlite:///{DB_PATH}")
        self._scheduler = AsyncIOScheduler(
            jobstores={"default": jobstore},
            job_defaults={
                "coalesce": True,       # merge missed runs into one
                "max_instances": 1,     # never run two copies of the same job
                "misfire_grace_time": 60,  # allow up to 60s of startup delay
            },
            timezone="UTC",
        )
        logger.info(f"[scheduler] Initialised with SQLite store at {DB_PATH}")
        return self._scheduler

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """
        Start the scheduler. Must be called after the asyncio event loop is running.
        Idempotent — safe to call multiple times.
        """
        if self._started:
            return
        try:
            sched = self._get_scheduler()
            sched.start()
            self._started = True
            logger.info(f"[scheduler] Started — {len(sched.get_jobs())} jobs loaded from store")
        except Exception as exc:
            logger.error(f"[scheduler] Failed to start: {exc}")
            raise

    def stop(self) -> None:
        """Stop the scheduler gracefully, waiting for running jobs to finish."""
        if not self._started or self._scheduler is None:
            return
        self._scheduler.shutdown(wait=True)
        self._started = False
        logger.info("[scheduler] Stopped")

    @property
    def running(self) -> bool:
        """True if the scheduler is currently running."""
        return self._started and self._scheduler is not None

    # ------------------------------------------------------------------
    # Job registration
    # ------------------------------------------------------------------

    def add_cron_job(
        self,
        job_id: str,
        func: Callable[..., Coroutine],
        *,
        hour: int = 8,
        minute: int = 0,
        day_of_week: str = "mon-sun",
        replace_existing: bool = True,
        kwargs: dict[str, Any] | None = None,
    ) -> None:
        """
        Add a cron-triggered job (runs at a fixed time each day/week).

        Args:
            job_id:           Unique identifier for this job (used to remove/pause it).
            func:             Async function to call.
            hour:             Hour (0-23, UTC) to run at.
            minute:           Minute (0-59) to run at.
            day_of_week:      Days to run on (e.g. "mon-fri", "mon-sun", "mon").
            replace_existing: If True, replaces any existing job with this ID.
            kwargs:           Extra kwargs to pass to func.
        """
        sched = self._get_scheduler()
        sched.add_job(
            func,
            trigger="cron",
            id=job_id,
            hour=hour,
            minute=minute,
            day_of_week=day_of_week,
            replace_existing=replace_existing,
            kwargs=kwargs or {},
        )
        logger.info(f"[scheduler] Cron job added: {job_id} at {hour:02d}:{minute:02d} ({day_of_week})")

    def add_interval_job(
        self,
        job_id: str,
        func: Callable[..., Coroutine],
        *,
        hours: int = 0,
        minutes: int = 0,
        seconds: int = 0,
        replace_existing: bool = True,
        kwargs: dict[str, Any] | None = None,
    ) -> None:
        """
        Add an interval-triggered job (repeats every N hours/minutes/seconds).

        Args:
            job_id:           Unique identifier.
            func:             Async function to call.
            hours:            Interval hours component.
            minutes:          Interval minutes component.
            seconds:          Interval seconds component.
            replace_existing: If True, replaces any existing job with this ID.
            kwargs:           Extra kwargs to pass to func.
        """
        sched = self._get_scheduler()
        sched.add_job(
            func,
            trigger="interval",
            id=job_id,
            hours=hours,
            minutes=minutes,
            seconds=seconds,
            replace_existing=replace_existing,
            kwargs=kwargs or {},
        )
        logger.info(
            f"[scheduler] Interval job added: {job_id} every "
            f"{hours}h {minutes}m {seconds}s"
        )

    def add_date_job(
        self,
        job_id: str,
        func: Callable[..., Coroutine],
        *,
        run_date: str,
        kwargs: dict[str, Any] | None = None,
    ) -> None:
        """
        Add a one-shot job that runs once at a specific datetime.

        Args:
            job_id:    Unique identifier.
            func:      Async function to call.
            run_date:  ISO datetime string, e.g. "2026-06-17 09:00:00"
            kwargs:    Extra kwargs to pass to func.
        """
        sched = self._get_scheduler()
        sched.add_job(
            func,
            trigger="date",
            id=job_id,
            run_date=run_date,
            replace_existing=True,
            kwargs=kwargs or {},
        )
        logger.info(f"[scheduler] Date job added: {job_id} at {run_date}")

    # ------------------------------------------------------------------
    # Job management
    # ------------------------------------------------------------------

    def remove_job(self, job_id: str) -> bool:
        """
        Remove a job by ID.

        Args:
            job_id: The job's unique identifier.

        Returns:
            True if removed, False if job not found.
        """
        sched = self._get_scheduler()
        try:
            sched.remove_job(job_id)
            logger.info(f"[scheduler] Job removed: {job_id}")
            return True
        except Exception:
            logger.warning(f"[scheduler] Job not found: {job_id}")
            return False

    def pause_job(self, job_id: str) -> bool:
        """
        Pause a job without removing it.

        Args:
            job_id: The job's unique identifier.

        Returns:
            True if paused successfully.
        """
        sched = self._get_scheduler()
        try:
            sched.pause_job(job_id)
            logger.info(f"[scheduler] Job paused: {job_id}")
            return True
        except Exception as exc:
            logger.warning(f"[scheduler] Could not pause {job_id}: {exc}")
            return False

    def resume_job(self, job_id: str) -> bool:
        """
        Resume a paused job.

        Args:
            job_id: The job's unique identifier.

        Returns:
            True if resumed successfully.
        """
        sched = self._get_scheduler()
        try:
            sched.resume_job(job_id)
            logger.info(f"[scheduler] Job resumed: {job_id}")
            return True
        except Exception as exc:
            logger.warning(f"[scheduler] Could not resume {job_id}: {exc}")
            return False

    def list_jobs(self) -> list[dict[str, Any]]:
        """
        Return all registered jobs as a list of dicts.

        Returns:
            List of job info dicts with id, name, trigger, next_run_time, status.
        """
        sched = self._get_scheduler()
        jobs = []
        for job in sched.get_jobs():
            next_run = job.next_run_time
            jobs.append({
                "id": job.id,
                "name": job.name or job.id,
                "trigger": str(job.trigger),
                "next_run_time": next_run.isoformat() if next_run else None,
                "pending": job.pending,
            })
        return jobs

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        """
        Get info about a specific job.

        Args:
            job_id: The job's unique identifier.

        Returns:
            Job info dict, or None if not found.
        """
        sched = self._get_scheduler()
        job = sched.get_job(job_id)
        if job is None:
            return None
        next_run = job.next_run_time
        return {
            "id": job.id,
            "name": job.name or job.id,
            "trigger": str(job.trigger),
            "next_run_time": next_run.isoformat() if next_run else None,
            "pending": job.pending,
        }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

scheduler = AstraScheduler()
