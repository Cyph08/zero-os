"""
memory/hot.py — Zero OS Session RAM Context

In-memory store for the current session only. Holds recent messages,
agent outputs, and intent history. Cleared on every restart.

Think of this as Zero's short-term working memory — what happened
in the last few minutes of this conversation.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class MemoryEntry:
    """A single item stored in hot memory."""
    role: str                    # "user" | "zero" | "agent"
    content: str                 # The actual text
    agent: str = ""              # Which agent produced this (if role=="agent")
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to plain dict."""
        return {
            "role": self.role,
            "content": self.content,
            "agent": self.agent,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# Hot memory store
# ---------------------------------------------------------------------------

class HotMemory:
    """
    In-memory session context. Thread-safe for single-process use.

    Keeps the last `max_entries` interactions so the CEO agent has
    recent context when planning responses.
    """

    def __init__(self, max_entries: int = 50) -> None:
        """
        Args:
            max_entries: Maximum number of entries to keep. Oldest are dropped.
        """
        self._entries: list[MemoryEntry] = []
        self._max_entries = max_entries
        self._session_start = time.time()

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def add(
        self,
        role: str,
        content: str,
        agent: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> MemoryEntry:
        """
        Add an entry to hot memory.

        Args:
            role: "user", "zero", or "agent"
            content: The text content to store.
            agent: Agent name if role is "agent".
            metadata: Optional extra data (cost, duration, etc.)

        Returns:
            The created MemoryEntry.
        """
        entry = MemoryEntry(
            role=role,
            content=content,
            agent=agent,
            metadata=metadata or {},
        )
        self._entries.append(entry)
        # Drop oldest if over limit
        if len(self._entries) > self._max_entries:
            self._entries = self._entries[-self._max_entries:]
        return entry

    def add_user(self, content: str) -> MemoryEntry:
        """Shortcut: add a user message."""
        return self.add(role="user", content=content)

    def add_zero(self, content: str, metadata: dict[str, Any] | None = None) -> MemoryEntry:
        """Shortcut: add Zero's response."""
        return self.add(role="zero", content=content, metadata=metadata or {})

    def add_agent(self, agent: str, content: str, metadata: dict[str, Any] | None = None) -> MemoryEntry:
        """Shortcut: add an agent's output."""
        return self.add(role="agent", content=content, agent=agent, metadata=metadata or {})

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def recent(self, n: int = 10) -> list[MemoryEntry]:
        """
        Return the n most recent entries.

        Args:
            n: Number of entries to return.

        Returns:
            List of entries, oldest first.
        """
        return self._entries[-n:]

    def as_context_string(self, n: int = 10) -> str:
        """
        Format recent memory as a conversation string for LLM prompts.

        Args:
            n: Number of recent entries to include.

        Returns:
            Formatted string ready to inject into a prompt.
        """
        lines = []
        for e in self.recent(n):
            label = e.role.upper()
            if e.agent:
                label = f"AGENT({e.agent})"
            lines.append(f"[{label}]: {e.content}")
        return "\n".join(lines)

    def search(self, query: str, n: int = 5) -> list[MemoryEntry]:
        """
        Simple keyword search over hot memory (no embeddings — that's cold memory).

        Args:
            query: Search string.
            n: Max results.

        Returns:
            Matching entries, most recent first.
        """
        q = query.lower()
        matches = [
            e for e in reversed(self._entries)
            if q in e.content.lower()
        ]
        return matches[:n]

    # ------------------------------------------------------------------
    # Housekeeping
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """Wipe all entries. Called on session reset."""
        self._entries.clear()
        self._session_start = time.time()

    def stats(self) -> dict[str, Any]:
        """Return session stats for logging."""
        uptime = time.time() - self._session_start
        return {
            "entries": len(self._entries),
            "max_entries": self._max_entries,
            "session_uptime_s": round(uptime, 1),
            "roles": {
                role: sum(1 for e in self._entries if e.role == role)
                for role in ("user", "zero", "agent")
            },
        }

    def __len__(self) -> int:
        return len(self._entries)

    def __repr__(self) -> str:
        return f"HotMemory(entries={len(self._entries)}, max={self._max_entries})"


# ---------------------------------------------------------------------------
# Singleton — import this everywhere
# ---------------------------------------------------------------------------

hot_memory = HotMemory(max_entries=50)
