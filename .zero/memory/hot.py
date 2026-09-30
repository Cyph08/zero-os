"""
memory/hot.py — Zero OS Session RAM Context

Recent messages, agent outputs and intent history — Zero's short-term
working memory.

Mirrored to hot_session.jsonl so it SURVIVES A RESTART. Zero autostarts on
login, so without this every reboot wiped the conversation and Telegram
follow-ups ("add levels to it") landed with no idea what "it" was.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_STORE = Path(__file__).parent / "hot_session.jsonl"


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
        self._load()

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
        self._append_to_disk(entry)
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

    def _append_to_disk(self, entry: MemoryEntry) -> None:
        """Mirror one entry to the session file. Never raises — memory is best-effort."""
        try:
            with _STORE.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
        except OSError as exc:
            logger.warning(f"[hot] Could not persist entry: {exc}")

    def _load(self) -> None:
        """
        Restore the tail of the last session from disk, then rewrite the file with
        only what was kept so it can't grow without bound.
        """
        if not _STORE.exists():
            return
        kept: list[MemoryEntry] = []
        try:
            for line in _STORE.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue      # a half-written line from a hard kill
                kept.append(MemoryEntry(
                    role=d.get("role", "user"),
                    content=d.get("content", ""),
                    agent=d.get("agent", ""),
                    timestamp=d.get("timestamp", 0.0),
                    metadata=d.get("metadata") or {},
                ))
        except OSError as exc:
            logger.warning(f"[hot] Could not read session file: {exc}")
            return
        self._entries = kept[-self._max_entries:]
        if len(kept) > self._max_entries:
            try:
                _STORE.write_text(
                    "".join(json.dumps(e.to_dict(), ensure_ascii=False) + "\n"
                            for e in self._entries),
                    encoding="utf-8",
                )
            except OSError:
                pass          # growth is cosmetic; recall already works
        logger.info(f"[hot] Restored {len(self._entries)} entries from previous session")

    def clear(self) -> None:
        """Wipe all entries, on disk too. Called on session reset."""
        self._entries.clear()
        self._session_start = time.time()
        try:
            _STORE.unlink(missing_ok=True)
        except OSError:
            pass

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


# ---------------------------------------------------------------------------
# Self-check: python -m memory.hot
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        _STORE = Path(tmp) / "session.jsonl"          # type: ignore[assignment]

        a = HotMemory(max_entries=4)
        a.add_user("make me a snake game")
        a.add_zero("Built it, saved to Zero Tech.")
        assert len(a) == 2

        # The whole point: a NEW instance (i.e. after a restart) still has the turns.
        b = HotMemory(max_entries=4)
        assert len(b) == 2, f"lost history across restart: {len(b)}"
        assert "snake" in b.as_context_string()

        # Bounded: the tail is kept and the file is trimmed to it.
        for i in range(6):
            b.add_user(f"turn {i}")
        c = HotMemory(max_entries=4)
        assert len(c) == 4, len(c)
        assert "turn 5" in c.as_context_string()
        assert "snake" not in c.as_context_string()

        # A half-written line from a hard kill must not break the load.
        with _STORE.open("a", encoding="utf-8") as f:
            f.write('{"role": "user", "cont')
        assert len(HotMemory(max_entries=4)) == 4

        c.clear()
        assert not _STORE.exists()

    print("hot memory self-check passed — history survives a restart")
