"""
core/bus.py — Zero OS Agent-to-Agent Context Bus

Think of this like a shared whiteboard that exists for the duration of a single
request. Every agent can post its results onto the whiteboard, and any other
agent that runs after it can read those results. This lets agents collaborate:
e.g. the research agent finds relevant papers, and the career agent reads them
to tailor a cover letter — all in one request, without Cyph having to chain
commands manually.

Key design decisions:
  - Per-request: CEO creates a fresh ContextBus() at the start of every handle()
    call. After the response is sent, the bus is discarded. This keeps memory
    clean and prevents stale data leaking between requests.
  - Thread-safe: uses threading.Lock so multiple agents running in parallel
    (future feature) won't corrupt each other's writes.
  - LLM-ready: as_context_string() formats everything as clean text that can
    be dropped directly into a synthesis prompt.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data model — one published item
# ---------------------------------------------------------------------------

@dataclass
class BusMessage:
    """
    A single piece of data published by an agent onto the shared bus.

    Think of it like a sticky note: who wrote it, what label is on it,
    what the content is, and when it was posted.

    Attributes:
        agent:     Name of the agent that published this (e.g. "research").
        key:       Short label describing what this data is (e.g. "summary").
        value:     The actual data — can be a string, dict, list, anything.
        timestamp: Unix timestamp (seconds) when this was published.
    """
    agent: str
    key: str
    value: Any
    timestamp: float = field(default_factory=time.time)

    def __repr__(self) -> str:
        value_preview = str(self.value)[:80] + "..." if len(str(self.value)) > 80 else str(self.value)
        return f"BusMessage(agent={self.agent!r}, key={self.key!r}, value={value_preview!r})"


# ---------------------------------------------------------------------------
# ContextBus — the shared whiteboard
# ---------------------------------------------------------------------------

class ContextBus:
    """
    Per-request shared message board for agent-to-agent communication.

    Lifecycle:
        1. CEO creates ContextBus() at the start of handle()
        2. CEO passes the bus to _dispatch() → passed to agent run()
        3. Each agent calls bus.publish() to post its results
        4. Later agents call bus.get() to read what earlier agents posted
        5. CEO calls bus.as_context_string() in synthesis to give Claude
           the full picture of everything every agent found
        6. After handle() returns, the bus object is garbage collected

    Thread safety:
        All public methods are guarded by self._lock. This means multiple
        agents can safely publish at the same time (Phase 5 async future).
    """

    def __init__(self) -> None:
        """Initialise an empty bus for a new request."""
        self._messages: list[BusMessage] = []
        self._lock = threading.Lock()
        logger.debug("[bus] New ContextBus created")

    # ------------------------------------------------------------------
    # Writing to the bus
    # ------------------------------------------------------------------

    def publish(self, agent: str, key: str, value: Any) -> None:
        """
        Post a piece of data onto the shared bus.

        Called by agents after they finish their work, so other agents
        (and the CEO synthesiser) can see what was found.

        Args:
            agent: The agent's name (e.g. "research", "career").
            key:   What this data represents (e.g. "summary", "sources").
            value: The actual data to share.

        Example:
            bus.publish("research", "summary", "BCI motor imagery uses...")
            bus.publish("research", "sources", [{"title": "...", "url": "..."}])
        """
        with self._lock:
            msg = BusMessage(agent=agent, key=key, value=value)
            self._messages.append(msg)
            logger.debug(f"[bus] {agent} published key={key!r}")

    # ------------------------------------------------------------------
    # Reading from the bus
    # ------------------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        """
        Get the most recent value for a given key, from any agent.

        Useful when you just want the latest version of something — e.g.
        "give me the latest summary" without caring which agent wrote it.

        Args:
            key:     The label to look for (e.g. "summary").
            default: What to return if nothing was published under that key.

        Returns:
            The value from the most recent matching BusMessage, or default.
        """
        with self._lock:
            # Search in reverse to get most recent first
            for msg in reversed(self._messages):
                if msg.key == key:
                    return msg.value
        return default

    def get_from(self, agent: str, key: str, default: Any = None) -> Any:
        """
        Get the most recent value published by a specific agent under a key.

        More precise than get() — use this when you care which agent found it.

        Args:
            agent:   The agent name to filter by (e.g. "research").
            key:     The label to look for (e.g. "sources").
            default: What to return if not found.

        Returns:
            The matching value, or default.
        """
        with self._lock:
            for msg in reversed(self._messages):
                if msg.agent == agent and msg.key == key:
                    return msg.value
        return default

    def get_all_from(self, agent: str) -> list[BusMessage]:
        """
        Get every message published by a specific agent.

        Args:
            agent: The agent name to filter by.

        Returns:
            List of BusMessage objects, in order of publication.
        """
        with self._lock:
            return [m for m in self._messages if m.agent == agent]

    def messages(self) -> list[BusMessage]:
        """
        Return a copy of all messages on the bus, in publication order.

        Returns:
            List of all BusMessage objects.
        """
        with self._lock:
            return list(self._messages)

    def has(self, key: str) -> bool:
        """
        Check whether any agent has published data under a given key.

        Args:
            key: The label to check for.

        Returns:
            True if at least one message with this key exists.
        """
        with self._lock:
            return any(m.key == key for m in self._messages)

    # ------------------------------------------------------------------
    # LLM-ready formatting
    # ------------------------------------------------------------------

    def as_context_string(self) -> str:
        """
        Format all bus messages as a clean text block for LLM prompts.

        The CEO drops this into the synthesis prompt so Claude can see
        everything every agent found, not just a single agent's output.

        Returns:
            Multi-line string, or empty string if bus is empty.

        Example output:
            === Agent Bus Context ===
            [research / summary]
            BCI motor imagery uses EEG signals to classify left vs right hand...

            [research / sources]
            [{"title": "EEG Review", "url": "https://..."}, ...]

            [schedule / today_entries]
            [{"title": "Gym", "date": "2026-06-16", ...}]
        """
        with self._lock:
            if not self._messages:
                return ""
            lines = ["=== Agent Bus Context ==="]
            for msg in self._messages:
                lines.append(f"\n[{msg.agent} / {msg.key}]")
                if isinstance(msg.value, (dict, list)):
                    import json
                    try:
                        lines.append(json.dumps(msg.value, indent=2, ensure_ascii=False)[:1000])
                    except (TypeError, ValueError):
                        lines.append(str(msg.value)[:500])
                else:
                    lines.append(str(msg.value)[:500])
            return "\n".join(lines)

    def summary_line(self) -> str:
        """
        One-line summary of what's on the bus. Used in logs.

        Returns:
            String like "3 messages from [research, schedule]"
        """
        with self._lock:
            agents = sorted({m.agent for m in self._messages})
            return f"{len(self._messages)} messages from {agents}"

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """Wipe all messages. Mostly useful in tests."""
        with self._lock:
            self._messages.clear()
            logger.debug("[bus] ContextBus cleared")

    def __len__(self) -> int:
        with self._lock:
            return len(self._messages)

    def __repr__(self) -> str:
        return f"ContextBus({self.summary_line()})"


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json

    print("Testing ContextBus...")

    bus = ContextBus()
    print(f"Empty bus: {bus}")

    # Research agent publishes
    bus.publish("research", "summary", "BCI motor imagery uses EEG to classify limb movements.")
    bus.publish("research", "sources", [{"title": "EEG Review", "url": "https://example.com"}])

    # Schedule agent publishes
    bus.publish("schedule", "today_entries", [{"title": "Gym 9am", "date": "2026-06-16"}])

    print(f"After publishing: {bus}")
    print(f"\nget('summary'): {bus.get('summary')}")
    print(f"get_from('schedule', 'today_entries'): {bus.get_from('schedule', 'today_entries')}")
    print(f"has('sources'): {bus.has('sources')}")
    print(f"has('nonexistent'): {bus.has('nonexistent')}")

    print(f"\n{bus.as_context_string()}")
    print("\n✅ ContextBus working correctly")
