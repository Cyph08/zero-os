"""
agents/health/run.py — Zero OS Health Agent

Cyph's daily wellness tracker. Tracks gym workouts, hydration, sleep,
and mood in a local JSON log. Can:
  - Log a workout / sleep / water intake from natural language
  - Review past entries and compute streaks
  - Spot patterns ("you've skipped gym 4 days in a row")
  - Give brief, honest health nudges

Risk level: write — saves entries to memory/health_log.json.
Uses claude-haiku since logging tasks are simple (fast + cheap).
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.llm import chat

if TYPE_CHECKING:
    from core.bus import ContextBus

logger = logging.getLogger(__name__)

AGENT_NAME = "Pulse"
AGENT_VERSION = "0.1.0"
LOG_DIR = Path(__file__).parent.parent.parent / "logs"
HEALTH_LOG_FILE = Path(__file__).parent.parent.parent / "memory" / "health_log.json"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class HealthResult:
    """Structured output from the health agent."""
    query: str
    action_type: str       # "log" | "review" | "streak" | "advice"
    response: str
    entry_logged: dict[str, Any] = field(default_factory=dict)
    streak_days: int = 0
    model_used: str = ""
    duration_ms: int = 0
    cost_usd: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialise to plain dict for MCP / CEO response."""
        return {
            "query": self.query,
            "action_type": self.action_type,
            "response": self.response,
            "entry_logged": self.entry_logged,
            "streak_days": self.streak_days,
            "model_used": self.model_used,
            "duration_ms": self.duration_ms,
            "cost_usd": self.cost_usd,
        }


# ---------------------------------------------------------------------------
# Health log I/O
# ---------------------------------------------------------------------------

def _load_log() -> list[dict[str, Any]]:
    """
    Load the health log JSON file.

    Returns:
        List of log entry dicts, most recent last.
    """
    HEALTH_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not HEALTH_LOG_FILE.exists():
        return []
    try:
        return json.loads(HEALTH_LOG_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.error(f"[pulse] Failed to load health log: {exc}")
        return []


def _save_log(entries: list[dict[str, Any]]) -> None:
    """
    Save the health log to JSON.

    Args:
        entries: Full list of log entries to write.
    """
    try:
        HEALTH_LOG_FILE.write_text(
            json.dumps(entries, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError as exc:
        logger.error(f"[pulse] Failed to save health log: {exc}")


def _compute_gym_streak(entries: list[dict[str, Any]]) -> int:
    """
    Count consecutive days with at least one gym entry ending today.

    Args:
        entries: All health log entries.

    Returns:
        Number of consecutive gym days. 0 if no gym today.
    """
    gym_dates = {
        e["date"] for e in entries
        if e.get("type") in ("workout", "gym")
    }
    streak = 0
    check = date.today()
    while check.isoformat() in gym_dates:
        streak += 1
        check = date(check.year, check.month, check.day - 1) if check.day > 1 else date(check.year, check.month - 1, 1)
        # Simplified: just count back until gap
        from datetime import timedelta
        check = date.today() - timedelta(days=streak)
    return streak


# ---------------------------------------------------------------------------
# Action detector
# ---------------------------------------------------------------------------

def _detect_action(query: str) -> str:
    """
    Classify the health request type.

    Args:
        query: Raw user query.

    Returns:
        One of: "log", "review", "streak", "advice"
    """
    q = query.lower()
    if any(w in q for w in ["streak", "how many days", "how long", "consecutive"]):
        return "streak"
    if any(w in q for w in ["review", "how am i doing", "summary", "this week", "this month", "check"]):
        return "review"
    if any(w in q for w in ["log", "did", "went", "completed", "slept", "drank", "ate",
                              "gym", "workout", "run", "had", "feeling", "mood"]):
        return "log"
    return "advice"


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _build_prompt(query: str, action_type: str, log_excerpt: list[dict[str, Any]]) -> str:
    """
    Build the health agent prompt.

    Args:
        query:        The health request.
        action_type:  Classified action type.
        log_excerpt:  Recent log entries for context.

    Returns:
        Formatted prompt string.
    """
    today = date.today().isoformat()
    recent_log = json.dumps(log_excerpt[-14:], indent=2) if log_excerpt else "No entries yet."

    instructions = {
        "log": (
            f"Today is {today}. The user wants to log a health entry.\n"
            "Extract what they logged and respond with a JSON block:\n"
            "```json\n"
            '{{"action": "log", "type": "workout|sleep|water|mood|other", '
            '"details": "...", "value": null, "notes": "..."}}\n'
            "```\n"
            "Then give a brief (1 sentence) encouraging acknowledgement."
        ),
        "review": (
            f"Today is {today}. Review Cyph's health log for the past 2 weeks.\n"
            "Summarise: gym frequency, sleep patterns, anything concerning.\n"
            "Be direct — if something looks bad, say so. Keep it under 150 words."
        ),
        "streak": (
            f"Today is {today}. Tell Cyph his current gym streak based on the log.\n"
            "Be brief and motivating."
        ),
        "advice": (
            "Give Cyph one specific, actionable health tip based on his log and query.\n"
            "No generic advice. One thing, clearly stated."
        ),
    }

    return (
        f"You are Zero's health agent — Cyph's wellness tracker.\n\n"
        f"About Cyph: MSc AI student at the University of Manchester who also works "
        f"part-time shifts at Chen's Happy House — long study days plus standing work, "
        f"so factor recovery, sleep and meal timing around that reality.\n\n"
        f"Recent health log (last 14 entries):\n{recent_log}\n\n"
        f"User said: {query}\n\n"
        + instructions.get(action_type, instructions["advice"])
    )


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _log_action_to_file(query: str, result: HealthResult) -> None:
    """
    Append structured log line to logs/health.log.

    Args:
        query:  The health query.
        result: The completed HealthResult.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / "health.log"
    entry = (
        f"timestamp={time.strftime('%Y-%m-%dT%H:%M:%S')} "
        f"agent={AGENT_NAME} "
        f"action={result.action_type} "
        f"query={query!r} "
        f"logged={bool(result.entry_logged)} "
        f"model={result.model_used} "
        f"duration_ms={result.duration_ms} "
        f"cost_usd={result.cost_usd:.6f}\n"
    )
    try:
        with log_file.open("a", encoding="utf-8") as f:
            f.write(entry)
    except OSError as exc:
        logger.error(f"[pulse] Failed to write action log: {exc}")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run(query: str, bus: "ContextBus | None" = None) -> HealthResult:
    """
    Execute a health tracking task.

    Args:
        query: Natural language health log entry or review request.
        bus:   Optional shared ContextBus. Publishes health summary
               so schedule agent can factor in rest days.

    Returns:
        HealthResult with response and any logged entry.
    """
    start_ms = int(time.time() * 1000)
    logger.info(f"[pulse] Query: {query!r}")

    action_type = _detect_action(query)
    existing_log = _load_log()
    prompt = _build_prompt(query, action_type, existing_log)

    model_used = ""
    cost_usd = 0.0
    response_text = ""
    logged_entry: dict[str, Any] = {}

    try:
        response = chat(
            prompt,
            tier="fast",    # health logging is simple — use haiku
            system="You are Zero's health agent. Be brief, direct, and honest.",
            max_tokens=512,
        )
        response_text = response.text
        cost_usd = response.cost_usd
        model_used = f"{response.provider.value}/{response.model}"

        # If logging, extract the JSON action and save
        if action_type == "log":
            import re
            match = re.search(r"```json\s*(\{.*?\})\s*```", response_text, re.DOTALL)
            if match:
                try:
                    action_data = json.loads(match.group(1))
                    if action_data.get("action") == "log":
                        logged_entry = {
                            "date": date.today().isoformat(),
                            "time": datetime.now().strftime("%H:%M"),
                            "type": action_data.get("type", "other"),
                            "details": action_data.get("details", query),
                            "value": action_data.get("value"),
                            "notes": action_data.get("notes", ""),
                        }
                        existing_log.append(logged_entry)
                        _save_log(existing_log)
                        logger.info(f"[pulse] Logged: {logged_entry['type']} on {logged_entry['date']}")
                except (json.JSONDecodeError, KeyError) as exc:
                    logger.warning(f"[pulse] Could not parse log entry: {exc}")

    except Exception as exc:
        logger.error(f"[pulse] LLM error: {exc}")
        response_text = f"Health agent encountered an error: {exc}"

    streak = _compute_gym_streak(existing_log)
    duration_ms = int(time.time() * 1000) - start_ms

    result = HealthResult(
        query=query,
        action_type=action_type,
        response=response_text,
        entry_logged=logged_entry,
        streak_days=streak,
        model_used=model_used,
        duration_ms=duration_ms,
        cost_usd=cost_usd,
    )

    _log_action_to_file(query, result)

    # Publish health context to bus
    if bus is not None:
        bus.publish("health", "summary", response_text)
        if logged_entry:
            bus.publish("health", "last_entry", logged_entry)
        bus.publish("health", "gym_streak", streak)
        logger.debug(f"[pulse] Published to bus: summary + streak={streak}")

    logger.info(f"[pulse] Done in {duration_ms}ms — cost=${cost_usd:.6f}")
    return result


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "Logged gym — did upper body, 1 hour, felt strong"
    logging.basicConfig(level=logging.INFO)
    result = run(q)
    print(f"\nQuery: {result.query}")
    print(f"Action: {result.action_type} | Streak: {result.streak_days} days")
    print(f"\nResponse:\n{result.response}")
    if result.entry_logged:
        print(f"\nLogged: {result.entry_logged}")
    print(f"\nModel: {result.model_used} | Time: {result.duration_ms}ms | Cost: ${result.cost_usd:.6f}")
