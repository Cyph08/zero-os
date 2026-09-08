"""
core/jobs.py — Zero OS Scheduled Job Functions

These are the actual async functions that APScheduler calls on a schedule.
Each job:
  1. Calls the relevant agent(s)
  2. Formats the output into a clean message
  3. Pushes it to alert_queue so the phone picks it up

Registered jobs:
  - morning_briefing    → daily at 08:00 UTC (news + calendar + health prompt)
  - world_news_digest   → daily at 18:00 UTC (end-of-day global news summary)
  - research_digest     → weekly on Sundays at 09:00 UTC (BCI + AI papers)

Call register_default_jobs() once on API startup to activate them.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from core.alerts import alert_queue
from core.scheduler import scheduler

logger = logging.getLogger(__name__)

ZERO_ROOT = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# Job: Morning Briefing
# ---------------------------------------------------------------------------

async def morning_briefing_job() -> None:
    """
    Daily morning briefing — runs at 08:00 UTC.

    Fetches:
      - Top world news stories
      - AI/tech headlines
      - Today's calendar events (if Google Calendar is connected)
      - Health prompt (did you log gym/sleep yesterday?)

    Pushes the digest to the phone alert queue.
    """
    logger.info("[jobs] Running morning briefing…")
    t0 = time.time()

    sections: list[str] = []

    # 1. World + AI news via news agent
    try:
        import asyncio
        from agents.news.run import run as news_run
        result = await asyncio.to_thread(news_run, "morning briefing")
        sections.append(result.summary)
    except Exception as exc:
        logger.warning(f"[jobs] News fetch failed in morning briefing: {exc}")
        sections.append("📰 News unavailable this morning.")

    # 2. Today's calendar events (best-effort — skip if not connected)
    try:
        import asyncio
        from integrations.google_calendar import list_events
        events = await asyncio.to_thread(list_events, max_results=5)
        if events:
            event_lines = []
            for e in events[:5]:
                start = e.get("start", {}).get("dateTime", e.get("start", {}).get("date", ""))
                title = e.get("summary", "Untitled event")
                # Format time compactly
                time_str = start[11:16] if len(start) > 10 else start
                event_lines.append(f"  • {time_str} — {title}")
            sections.append("📅 TODAY:\n" + "\n".join(event_lines))
        else:
            sections.append("📅 No calendar events today.")
    except Exception as exc:
        logger.debug(f"[jobs] Calendar fetch skipped: {exc}")

    # 3. Health nudge — remind Cyph to log health if yesterday has no entry
    try:
        import asyncio
        import json
        health_log = ZERO_ROOT / "memory" / "health_log.json"
        if health_log.exists():
            with health_log.open("r", encoding="utf-8") as f:
                log = json.load(f)
            today_str = time.strftime("%Y-%m-%d")
            yesterday_str = time.strftime(
                "%Y-%m-%d",
                time.gmtime(time.time() - 86400)
            )
            has_yesterday = any(
                e.get("date", "").startswith(yesterday_str) for e in log
            )
            if not has_yesterday:
                sections.append(
                    "💪 HEALTH: No log for yesterday — say 'log gym session' "
                    "or 'log sleep 7 hours' to track it."
                )
    except Exception as exc:
        logger.debug(f"[jobs] Health check skipped: {exc}")

    body = "\n\n".join(sections) if sections else "No data available."
    elapsed = int((time.time() - t0) * 1000)

    alert_queue.push(
        alert_type="briefing",
        title="☀️ Morning Briefing",
        body=body,
    )
    logger.info(f"[jobs] Morning briefing pushed to phone in {elapsed}ms")


# ---------------------------------------------------------------------------
# Job: World News Digest
# ---------------------------------------------------------------------------

async def world_news_digest_job() -> None:
    """
    End-of-day world news digest — runs at 18:00 UTC.

    Fetches the most important global stories from the past 24 hours
    and pushes them to the phone alert queue.
    """
    logger.info("[jobs] Running world news digest…")
    t0 = time.time()

    try:
        import asyncio
        from agents.news.run import run as news_run
        result = await asyncio.to_thread(news_run, "top world news today most important global stories")
        body = result.summary
    except Exception as exc:
        logger.error(f"[jobs] World news digest failed: {exc}")
        body = f"News digest failed: {exc}"

    elapsed = int((time.time() - t0) * 1000)
    alert_queue.push(
        alert_type="news",
        title="🌍 World News Digest",
        body=body,
    )
    logger.info(f"[jobs] World news digest pushed in {elapsed}ms")


# ---------------------------------------------------------------------------
# Job: Research Digest
# ---------------------------------------------------------------------------

async def research_digest_job() -> None:
    """
    Weekly BCI + AI research digest — runs Sundays at 09:00 UTC.

    Searches for new papers on BCI/motor imagery/EEG and recent AI
    research developments, formats as a digest, pushes to phone.
    """
    logger.info("[jobs] Running weekly research digest…")
    t0 = time.time()

    sections: list[str] = []

    # 1. BCI/EEG papers
    try:
        import asyncio
        from agents.news.run import run as news_run
        bci_result = await asyncio.to_thread(news_run, "new BCI EEG motor imagery research papers arxiv 2026")
        sections.append("🧠 BCI RESEARCH\n" + bci_result.summary)
    except Exception as exc:
        logger.warning(f"[jobs] BCI research fetch failed: {exc}")
        sections.append("🧠 BCI RESEARCH: Fetch failed this week.")

    # 2. AI/ML research highlights
    try:
        import asyncio
        from agents.news.run import run as news_run
        ai_result = await asyncio.to_thread(news_run, "AI machine learning research news this week 2026")
        sections.append("🤖 AI RESEARCH\n" + ai_result.summary)
    except Exception as exc:
        logger.warning(f"[jobs] AI research fetch failed: {exc}")
        sections.append("🤖 AI RESEARCH: Fetch failed this week.")

    body = "\n\n".join(sections)
    elapsed = int((time.time() - t0) * 1000)

    alert_queue.push(
        alert_type="research",
        title="📚 Weekly Research Digest",
        body=body,
    )
    logger.info(f"[jobs] Research digest pushed in {elapsed}ms")


# ---------------------------------------------------------------------------
# Job registration — called once on API startup
# ---------------------------------------------------------------------------

def register_default_jobs() -> None:
    """
    Register Zero's default scheduled jobs.

    Called from api/main.py lifespan after the scheduler is started.
    All times are UTC. Adjust hour/minute to match Cyph's timezone.

    Current schedule:
      - Morning briefing  → 08:00 UTC daily  (09:00 BST / adjust as needed)
      - World news digest → 18:00 UTC daily  (19:00 BST)
      - Research digest   → 09:00 UTC Sundays
    """
    logger.info("[jobs] Registering default scheduled jobs…")

    try:
        # Daily morning briefing at 08:00 UTC
        scheduler.add_cron_job(
            job_id="morning_briefing",
            func=morning_briefing_job,
            hour=8,
            minute=0,
            day_of_week="mon-sun",
        )

        # Daily world news digest at 18:00 UTC (end of day)
        scheduler.add_cron_job(
            job_id="world_news_digest",
            func=world_news_digest_job,
            hour=18,
            minute=0,
            day_of_week="mon-sun",
        )

        # Weekly research digest — Sundays at 09:00 UTC
        scheduler.add_cron_job(
            job_id="research_digest",
            func=research_digest_job,
            hour=9,
            minute=0,
            day_of_week="sun",
        )

        jobs = scheduler.list_jobs()
        logger.info(f"[jobs] {len(jobs)} jobs registered: {[j['id'] for j in jobs]}")

    except Exception as exc:
        logger.error(f"[jobs] Failed to register default jobs: {exc}")
        raise
