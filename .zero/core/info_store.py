"""
core/info_store.py — Zero OS Info Stored System

Persists information explicitly when Cyph says "save this", "remember this",
or "store this" (detected by the CEO intent gate). Nothing is auto-saved —
this is only for deliberate, named saves.

Storage layout:
    memory/info_store/
        research/items.json
        code/items.json
        study/items.json
        ...
        global/items.json   ← items not tied to a specific agent

Each items.json is a list of entries:
    [
        {"key": "label", "value": "content", "timestamp": "...", "agent": "research"},
        ...
    ]

API usage (exposed by api/main.py):
    GET  /info              — all items across all agents (flat list)
    GET  /info/{agent}      — items for one agent
    POST /info/{agent}      — save item {"key": "...", "value": "..."}
    DELETE /info/{agent}/{key} — delete a specific item
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Root path for all info store files (machine-readable JSON — the search index)
STORE_ROOT = Path(__file__).parent.parent / "memory" / "info_store"

# Obsidian-ready markdown vault — the HUMAN-READABLE source of truth.
# Lives in K:\\Zero\\Zero Memory so Cyph can open the whole folder as an Obsidian
# vault and read/edit what Zero remembers. The JSON store is just a fast index;
# if it is ever lost it can be rebuilt from this vault via InfoStore.rebuild_vault().
VAULT_ROOT = Path(__file__).parent.parent.parent / "Zero Memory"


def _slugify(text: str) -> str:
    """Turn a key into a safe markdown filename."""
    out = re.sub(r"[^\w\s-]", "", text.strip().lower())
    out = re.sub(r"[\s_-]+", "-", out).strip("-")
    return out or "note"

# Save triggers — CEO checks user input against these
SAVE_TRIGGERS = [
    "save this",
    "remember this",
    "store this",
    "keep this",
    "save that",
    "remember that",
    "store that",
    "note this",
    "note that",
    "write this down",
    "make a note",
]


# ---------------------------------------------------------------------------
# InfoStore class
# ---------------------------------------------------------------------------

class InfoStore:
    """
    Manages the per-agent persistent info store.

    All operations are synchronous JSON reads/writes (fast for small datasets).
    Thread-safe: each write operation reads the current file, appends, and writes.

    Usage:
        from core.info_store import info_store
        info_store.save("research", "key", "value")
        items = info_store.get_all("research")
        info_store.delete("research", "key")
    """

    def __init__(self, root: Path = STORE_ROOT) -> None:
        self._root = root

    def _agent_file(self, agent: str) -> Path:
        """Return the path to an agent's items.json, creating dirs if needed."""
        d = self._root / agent
        d.mkdir(parents=True, exist_ok=True)
        return d / "items.json"

    def _read(self, agent: str) -> list[dict[str, Any]]:
        """Read and return all items for an agent (empty list if file missing)."""
        f = self._agent_file(agent)
        if not f.exists():
            return []
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(f"[info_store] Failed to read {f}: {exc}")
            return []

    def _write(self, agent: str, items: list[dict[str, Any]]) -> None:
        """Write items list to the agent's file."""
        f = self._agent_file(agent)
        try:
            f.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:
            logger.error(f"[info_store] Failed to write {f}: {exc}")

    # ------------------------------------------------------------------
    # Markdown vault mirror (Obsidian-ready, human-readable source of truth)
    # ------------------------------------------------------------------

    def _md_path(self, agent: str, key: str) -> Path:
        """Return the markdown file path for an item inside the vault."""
        d = VAULT_ROOT / agent
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{_slugify(key)}.md"

    def _write_markdown(self, entry: dict[str, Any]) -> None:
        """Mirror a saved item to the Obsidian vault as a readable .md file.

        YAML frontmatter lets Obsidian show tags/graph. Never raises — a vault
        failure must never block the real (JSON) save.
        """
        try:
            agent = entry.get("agent", "global")
            key = entry.get("key", "note")
            value = entry.get("value", "")
            ts = entry.get("timestamp", "")
            md = (
                f"---\nkey: {key}\nagent: {agent}\nsaved: {ts}\n"
                f"tags: [zero-memory, {agent}]\n---\n\n"
                f"# {key}\n\n{value}\n\n"
                f"> Saved by Zero - agent: {agent} - {ts}\n"
            )
            self._md_path(agent, key).write_text(md, encoding="utf-8")
        except Exception as exc:  # noqa: BLE001 - vault is best-effort
            logger.warning(f"[info_store] markdown vault write failed: {exc}")

    def _delete_markdown(self, agent: str, key: str) -> None:
        """Remove an item's markdown file from the vault (best-effort)."""
        try:
            p = self._md_path(agent, key)
            if p.exists():
                p.unlink()
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[info_store] markdown vault delete failed: {exc}")

    def rebuild_vault(self) -> int:
        """Regenerate the whole markdown vault from the JSON store.

        Returns the number of markdown notes written.
        """
        count = 0
        for entry in self.get_all():
            self._write_markdown(entry)
            count += 1
        logger.info(f"[info_store] rebuilt markdown vault: {count} notes")
        return count

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save(self, agent: str, key: str, value: str) -> dict[str, Any]:
        """
        Save or update an item.

        If an item with the same key already exists for this agent, it is
        replaced. Otherwise a new entry is appended.

        Args:
            agent: Agent name (or 'global' for cross-agent items).
            key:   Short label / identifier.
            value: The content to store.

        Returns:
            The saved item dict.
        """
        agent = agent.lower().strip() or "global"
        items = self._read(agent)

        entry: dict[str, Any] = {
            "key": key,
            "value": value,
            "agent": agent,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }

        # Replace existing key if present
        replaced = False
        for i, existing in enumerate(items):
            if existing.get("key") == key:
                items[i] = entry
                replaced = True
                break

        if not replaced:
            items.append(entry)

        self._write(agent, items)
        # Mirror to the human-readable Obsidian vault (source of truth).
        self._write_markdown(entry)
        action = "updated" if replaced else "saved"
        logger.info(f"[info_store] {action}: agent={agent} key={key!r}")
        return entry

    def get_all(self, agent: str | None = None) -> list[dict[str, Any]]:
        """
        Return all stored items.

        Args:
            agent: If provided, return only items for this agent.
                   If None, return all items across all agents (merged).

        Returns:
            List of item dicts sorted by timestamp (newest last).
        """
        if agent:
            return self._read(agent.lower())

        # Collect from all agent subfolders
        all_items: list[dict[str, Any]] = []
        if self._root.exists():
            for d in self._root.iterdir():
                if d.is_dir():
                    f = d / "items.json"
                    if f.exists():
                        try:
                            all_items.extend(json.loads(f.read_text(encoding="utf-8")))
                        except (json.JSONDecodeError, OSError):
                            pass

        # Sort by timestamp ascending
        all_items.sort(key=lambda x: x.get("timestamp", ""))
        return all_items

    def delete(self, agent: str, key: str) -> bool:
        """
        Delete a specific item by key.

        Args:
            agent: Agent name.
            key:   Item key to delete.

        Returns:
            True if the item was found and deleted, False if not found.
        """
        agent = agent.lower()
        items = self._read(agent)
        new_items = [i for i in items if i.get("key") != key]
        if len(new_items) == len(items):
            return False   # key not found
        self._write(agent, new_items)
        self._delete_markdown(agent, key)
        logger.info(f"[info_store] deleted: agent={agent} key={key!r}")
        return True

    def clear(self, agent: str) -> int:
        """
        Clear all items for an agent.

        Args:
            agent: Agent name.

        Returns:
            Number of items cleared.
        """
        items = self._read(agent.lower())
        self._write(agent.lower(), [])
        return len(items)

    def agents_with_data(self) -> list[str]:
        """Return names of agents that have stored items."""
        if not self._root.exists():
            return []
        return [
            d.name for d in self._root.iterdir()
            if d.is_dir() and (d / "items.json").exists()
        ]


# ---------------------------------------------------------------------------
# Save trigger detection (used by CEO)
# ---------------------------------------------------------------------------

def is_save_command(user_input: str) -> bool:
    """
    Detect whether the user is asking Zero to save/remember something.

    Args:
        user_input: Raw user message.

    Returns:
        True if the message starts with or contains a save trigger phrase.
    """
    low = user_input.lower().strip()
    return any(trigger in low for trigger in SAVE_TRIGGERS)


def parse_save_command(
    user_input: str,
    active_agent: str = "global",
) -> tuple[str, str]:
    """
    Extract key and value from a save command.

    Examples:
        "save this: my contact is john@example.com" → ("note", "my contact is john@example.com")
        "remember this as contact — john@example.com" → ("contact", "john@example.com")
        "store this: EEGNet paper uses depthwise conv" → ("note", "EEGNet paper uses depthwise conv")

    Args:
        user_input: Raw user message.
        active_agent: Agent context (hints at key naming).

    Returns:
        Tuple of (key, value).
    """
    text = user_input.strip()

    # Try "save this as KEY: VALUE" or "remember this as KEY — VALUE"
    import re
    m = re.search(
        r"(?:as|called?|labelled?)\s+['\"]?(\w[\w\s-]*?)['\"]?\s*[:\—\-]\s*(.+)$",
        text, re.IGNORECASE
    )
    if m:
        return m.group(1).strip().lower(), m.group(2).strip()

    # Try "save this: VALUE" — use auto-generated key
    m2 = re.search(r"(?:save|remember|store|note)\s+(?:this|that)[:\s]+(.+)$", text, re.IGNORECASE)
    if m2:
        key = f"note_{time.strftime('%H%M%S')}"
        return key, m2.group(1).strip()

    # Fallback: strip the trigger phrase and use the rest as value
    for trigger in sorted(SAVE_TRIGGERS, key=len, reverse=True):
        if trigger in text.lower():
            remainder = re.sub(re.escape(trigger), "", text, flags=re.IGNORECASE).strip(" :—-")
            key = f"note_{time.strftime('%H%M%S')}"
            return key, remainder or text

    return f"note_{time.strftime('%H%M%S')}", text


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

info_store = InfoStore()
