"""
core/registry.py — Zero OS Plugin Registry

Auto-discovers agents by scanning the /agents/ directory for manifest.json files.
Builds a keyword index for fast agent lookup.
Watches /agents/ at runtime — drop a new agent folder in and it's live immediately.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from threading import Thread
from typing import Any

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

logger = logging.getLogger(__name__)

AGENTS_DIR = Path(__file__).parent.parent / "agents"
MANIFEST_FILENAME = "manifest.json"


# ---------------------------------------------------------------------------
# Text matching helpers (used by AgentRegistry.find)
# ---------------------------------------------------------------------------

_WORD_RE = re.compile(r"[a-z0-9]+")

# Longest-first so 'ing' is tried before 's'. Light, not linguistically perfect —
# just enough to fold plurals/gerunds (research/researching/researches → research).
_SUFFIXES = ("ing", "edly", "ed", "es", "s", "er", "ly")


def _stem(word: str) -> str:
    """Strip a common suffix so simple inflections collapse to one form.

    'headlines'→'headline', 'ideas'→'idea', 'researching'→'research'. Only fires
    when the remaining stem is long enough to stay meaningful, so short words are
    left untouched (avoids 'is'→'i' type damage).
    """
    for suf in _SUFFIXES:
        if word.endswith(suf) and len(word) - len(suf) >= 3:
            return word[: -len(suf)]
    return word


def _tokenize(text: str) -> list[str]:
    """Lowercase word/number tokens, punctuation stripped ('research.'→'research')."""
    return _WORD_RE.findall(text.lower())


class AgentManifest:
    """Parsed representation of an agent's manifest.json."""

    def __init__(self, data: dict[str, Any], path: Path) -> None:
        """
        Args:
            data: Parsed JSON dict from manifest.json.
            path: Absolute path to the manifest file.
        """
        self.name: str = data["name"]
        self.description: str = data["description"]
        self.trigger_keywords: list[str] = [kw.lower() for kw in data.get("trigger_keywords", [])]
        self.capabilities: list[str] = data.get("capabilities", [])
        self.risk_level: str = data.get("risk_level", "read")
        self.collaborates_with: list[str] = data.get("collaborates_with", [])
        self.model_preference: str = data.get("model_preference", "claude-haiku")
        self.entry_point: str = data["entry_point"]
        self.version: str = data.get("version", "0.1.0")
        self.manifest_path: Path = path
        self.agent_dir: Path = path.parent

    def to_dict(self) -> dict[str, Any]:
        """Serialise back to a plain dict (useful for MCP tool registration)."""
        return {
            "name": self.name,
            "description": self.description,
            "trigger_keywords": self.trigger_keywords,
            "capabilities": self.capabilities,
            "risk_level": self.risk_level,
            "collaborates_with": self.collaborates_with,
            "model_preference": self.model_preference,
            "entry_point": self.entry_point,
            "version": self.version,
        }

    def __repr__(self) -> str:
        return f"<AgentManifest name={self.name!r} risk={self.risk_level!r}>"


class _ManifestChangeHandler(FileSystemEventHandler):
    """Watchdog event handler that triggers registry refresh on manifest changes."""

    def __init__(self, registry: "AgentRegistry") -> None:
        super().__init__()
        self._registry = registry

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory and Path(event.src_path).name == MANIFEST_FILENAME:
            logger.info(f"[registry] New manifest detected: {event.src_path}")
            self._registry.reload()

    def on_modified(self, event: FileSystemEvent) -> None:
        if not event.is_directory and Path(event.src_path).name == MANIFEST_FILENAME:
            logger.info(f"[registry] Manifest changed: {event.src_path}")
            self._registry.reload()

    def on_deleted(self, event: FileSystemEvent) -> None:
        if not event.is_directory and Path(event.src_path).name == MANIFEST_FILENAME:
            logger.info(f"[registry] Manifest removed: {event.src_path}")
            self._registry.reload()


class AgentRegistry:
    """
    Scans /agents/ for manifest.json files and maintains a live keyword index.

    Usage:
        registry = AgentRegistry()
        registry.start_watcher()           # background thread, hot-reload on changes
        matches = registry.find("research paper about LLMs")
        agent = registry.get("research")
    """

    def __init__(self, agents_dir: Path = AGENTS_DIR) -> None:
        """
        Args:
            agents_dir: Root directory to scan for agent subdirectories.
        """
        self._agents_dir = agents_dir
        self._agents: dict[str, AgentManifest] = {}          # name → manifest
        self._keyword_index: dict[str, list[str]] = {}        # keyword → [agent names]
        self._observer: Observer | None = None

        self.reload()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def reload(self) -> None:
        """Re-scan the agents directory and rebuild the keyword index."""
        new_agents: dict[str, AgentManifest] = {}

        if not self._agents_dir.exists():
            logger.warning(f"[registry] Agents directory does not exist: {self._agents_dir}")
            self._agents = new_agents
            self._rebuild_index()
            return

        for manifest_path in self._agents_dir.rglob(MANIFEST_FILENAME):
            try:
                with manifest_path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                manifest = AgentManifest(data, manifest_path)
                new_agents[manifest.name] = manifest
                logger.info(f"[registry] Loaded agent: {manifest.name} (v{manifest.version})")
            except (json.JSONDecodeError, KeyError) as exc:
                logger.error(f"[registry] Failed to parse {manifest_path}: {exc}")

        self._agents = new_agents
        self._rebuild_index()
        logger.info(f"[registry] Registry loaded — {len(self._agents)} agents active")

    def get(self, name: str) -> AgentManifest | None:
        """
        Retrieve a manifest by exact agent name.

        Args:
            name: Agent name as defined in manifest.json.

        Returns:
            AgentManifest or None if not found.
        """
        return self._agents.get(name)

    def find(self, query: str, top_k: int = 3) -> list[AgentManifest]:
        """
        Find the most relevant agents for a natural language query.
        Scores agents by keyword overlap — lightweight, no model call needed.

        Matching handles three things the naive split() approach missed:
          - punctuation — 'do some research.' still matches the 'research' keyword.
          - multi-word keywords — 'motor imagery', 'world news', 'look up' etc.
            now actually fire (they could never match a single-token set before).
          - light stemming — 'researching'/'headlines' fold to their root.

        Multi-word phrase hits score highest (most specific intent), exact single
        words next, stemmed matches slightly below.

        Args:
            query: The user's raw command or question.
            top_k: Maximum number of agents to return.

        Returns:
            List of AgentManifest sorted by relevance score (highest first).
        """
        text = query.lower()
        tokens = _tokenize(text)
        token_set = set(tokens)
        stem_set = {_stem(t) for t in tokens}
        scores: dict[str, float] = {}

        for keyword, agent_names in self._keyword_index.items():
            weight = 0.0
            if " " in keyword:
                # Multi-word keyword: phrase substring, or all its words present.
                kw_words = keyword.split()
                if keyword in text or all(w in token_set for w in kw_words):
                    weight = 2.0
            elif keyword in token_set:
                weight = 1.0
            elif _stem(keyword) in stem_set:
                weight = 0.8
            if weight:
                for name in agent_names:
                    scores[name] = scores.get(name, 0.0) + weight

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return [self._agents[name] for name, _ in ranked[:top_k] if name in self._agents]

    def all_agents(self) -> list[AgentManifest]:
        """Return all registered agents."""
        return list(self._agents.values())

    def all_names(self) -> list[str]:
        """Return all registered agent names."""
        return list(self._agents.keys())

    def start_watcher(self) -> None:
        """
        Start a background watchdog observer to hot-reload agents on file changes.
        Call once at application startup. Safe to call multiple times (idempotent).
        """
        if self._observer is not None and self._observer.is_alive():
            return

        handler = _ManifestChangeHandler(self)
        self._observer = Observer()
        self._observer.schedule(handler, str(self._agents_dir), recursive=True)
        thread = Thread(target=self._observer.start, daemon=True, name="zero-registry-watcher")
        thread.start()
        logger.info(f"[registry] File watcher started on: {self._agents_dir}")

    def stop_watcher(self) -> None:
        """Stop the background file watcher gracefully."""
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None
            logger.info("[registry] File watcher stopped")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _rebuild_index(self) -> None:
        """Rebuild the keyword → [agent names] lookup table."""
        index: dict[str, list[str]] = {}
        for manifest in self._agents.values():
            for keyword in manifest.trigger_keywords:
                index.setdefault(keyword, []).append(manifest.name)
        self._keyword_index = index
        logger.debug(f"[registry] Keyword index rebuilt — {len(index)} keywords")


# Singleton instance — import this in ceo.py and mcp_server.py
registry = AgentRegistry()
