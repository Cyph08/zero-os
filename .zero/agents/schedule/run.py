"""
agents/schedule/run.py — Zero OS Schedule Agent

Manages time and calendar tasks. Reads and writes a local schedule file,
helps plan days, sets reminders, and will integrate with Google Calendar
in Phase 2 integrations.

Risk level: write — informs Cyph before creating/modifying schedule entries.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.llm import chat

if TYPE_CHECKING:
    from core.bus import ContextBus

logger = logging.getLogger(__name__)

AGENT_NAME = "Chrono"
AGENT_VERSION = "0.1.1"
LOG_DIR = Path(__file__).parent.parent.parent / "logs"
SCHEDULE_FILE = Path(__file__).parent.parent.parent / "memory" / "schedule.json"

# Captured BEFORE the dataclass below: its `time: str` field shadows the `time`
# module inside the class body, so `field(default_factory=time.time)` resolved to
# `"".time` → AttributeError('str' object has no attribute 'time') at import.
# This was the recurring Chrono crash. Never reference `time.*` inside ScheduleEntry.
_NOW = time.time


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class ScheduleEntry:
    """A single calendar/task entry."""
    title: str
    date: str           # ISO format: YYYY-MM-DD
    time: str = ""      # HH:MM or empty for all-day
    notes: str = ""
    done: bool = False
    created_at: float = field(default_factory=_NOW)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "date": self.date,
            "time": self.time,
            "notes": self.notes,
            "done": self.done,
            "created_at": self.created_at,
        }


@dataclass
class ScheduleResult:
    """Structured output returned by this agent."""
    query: str
    response: str
    entries: list[ScheduleEntry] = field(default_factory=list)
    action_taken: str = ""   # "read" | "created" | "updated" | "none"
    model_used: str = ""
    duration_ms: int = 0
    cost_usd: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "response": self.response,
            "entries": [e.to_dict() for e in self.entries],
            "action_taken": self.action_taken,
            "model_used": self.model_used,
            "duration_ms": self.duration_ms,
            "cost_usd": self.cost_usd,
        }


# ---------------------------------------------------------------------------
# Schedule file I/O
# ---------------------------------------------------------------------------

def _load_schedule() -> list[dict[str, Any]]:
    """Load the schedule JSON file, returning empty list if not found."""
    SCHEDULE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not SCHEDULE_FILE.exists():
        return []
    try:
        return json.loads(SCHEDULE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.error(f"[chrono] Failed to load schedule file: {exc}")
        return []


def _save_schedule(entries: list[dict[str, Any]]) -> None:
    """Save the schedule to JSON."""
    try:
        SCHEDULE_FILE.write_text(
            json.dumps(entries, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError as exc:
        logger.error(f"[chrono] Failed to save schedule file: {exc}")


# ---------------------------------------------------------------------------
# LLM helpers
# ---------------------------------------------------------------------------

def _build_prompt(query: str, existing_entries: list[dict[str, Any]]) -> str:
    """Build the scheduling prompt."""
    from datetime import date
    today = date.today().isoformat()
    entries_text = json.dumps(existing_entries[-20:], indent=2) if existing_entries else "No entries yet."

    return f"""You are Zero's schedule agent. Today's date is {today}.

About Cyph (whose schedule this is): MSc AI student at the University of Manchester,
and works part-time at Chen's Happy House in Manchester — factor those shifts and
university commitments in when planning his time.

User request: {query}

Current schedule (up to 20 most recent entries):
{entries_text}

Your job:
1. Answer the user's scheduling question or help them plan.
2. If they want to ADD an entry, respond with a JSON block at the end in this format:
   ```json
   {{"action": "create", "title": "...", "date": "YYYY-MM-DD", "time": "HH:MM", "notes": "..."}}
   ```
3. If they're just asking about their schedule, respond with a clear readable summary.
4. If the request is ambiguous, ask one clarifying question.

Keep your response concise and practical. No markdown headers."""


def _parse_action(response_text: str) -> dict[str, Any] | None:
    """Extract a JSON action block from the LLM response if present."""
    import re
    match = re.search(r"```json\s*(\{.*?\})\s*```", response_text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _log_action(query: str, result: ScheduleResult) -> None:
    """Append structured log line."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / "schedule.log"
    entry = (
        f"timestamp={time.strftime('%Y-%m-%dT%H:%M:%S')} "
        f"agent={AGENT_NAME} "
        f"action={result.action_taken} "
        f"query={query!r} "
        f"model={result.model_used} "
        f"duration_ms={result.duration_ms} "
        f"cost_usd={result.cost_usd:.6f}\n"
    )
    try:
        with log_file.open("a", encoding="utf-8") as f:
            f.write(entry)
    except OSError as exc:
        logger.error(f"[chrono] Failed to write log: {exc}")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run(query: str, bus: "ContextBus | None" = None) -> ScheduleResult:
    """
    Execute a scheduling task.

    Args:
        query: Natural language scheduling request from the user.
        bus:   Optional shared ContextBus. If provided, publishes today's
               schedule entries so other agents (e.g. career) can factor
               in Cyph's availability.

    Returns:
        ScheduleResult with response and any new/updated entries.
    """
    start_ms = int(time.time() * 1000)
    logger.info(f"[chrono] Query: {query!r}")

    existing = _load_schedule()
    prompt = _build_prompt(query, existing)

    model_used = ""
    cost_usd = 0.0
    action_taken = "read"
    new_entries: list[ScheduleEntry] = []

    try:
        response = chat(prompt, tier="fast", max_tokens=512)
        reply = response.text
        cost_usd = response.cost_usd
        model_used = f"{response.provider.value}/{response.model}"

        # Check if LLM wants to create an entry
        action = _parse_action(reply)
        if action and action.get("action") == "create":
            entry = ScheduleEntry(
                title=action.get("title", "Untitled"),
                date=action.get("date", ""),
                time=action.get("time", ""),
                notes=action.get("notes", ""),
            )
            existing.append(entry.to_dict())
            _save_schedule(existing)
            new_entries.append(entry)
            action_taken = "created"
            logger.info(f"[chrono] Created entry: {entry.title} on {entry.date}")

    except Exception as exc:
        logger.error(f"[chrono] LLM error: {exc}")
        reply = f"Schedule agent encountered an error: {exc}"

    duration_ms = int(time.time() * 1000) - start_ms
    result = ScheduleResult(
        query=query,
        response=reply,
        entries=new_entries,
        action_taken=action_taken,
        model_used=model_used,
        duration_ms=duration_ms,
        cost_usd=cost_usd,
    )
    _log_action(query, result)

    # Phase 4: publish to shared bus so other agents know what's on the schedule
    if bus is not None:
        all_entries = _load_schedule()
        bus.publish("schedule", "response", reply)
        bus.publish("schedule", "all_entries", all_entries[-20:])  # recent 20
        if new_entries:
            bus.publish("schedule", "new_entries", [e.to_dict() for e in new_entries])
        logger.debug(f"[chrono] Published to bus: response + {len(all_entries)} entries")

    return result


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "What's on my schedule this week?"
    result = run(q)
    print(f"\nQuery: {result.query}")
    print(f"Response:\n{result.response}")
    print(f"\nAction: {result.action_taken} | Model: {result.model_used} | Cost: ${result.cost_usd:.6f}")
