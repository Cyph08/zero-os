"""
memory/warm.py — Zero OS Redis Warm Cache

Redis-backed cache for recent weeks of context. Stores summaries,
agent outputs, and user preferences with TTL-based expiry.

Falls back gracefully to an in-memory dict if Redis isn't running —
so Zero keeps working even without Redis installed.

Think of this as Zero's medium-term memory — what happened in the
last few days or weeks, surviving restarts.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# Default TTLs
TTL_SHORT = 60 * 60          # 1 hour
TTL_MEDIUM = 60 * 60 * 24   # 1 day
TTL_LONG = 60 * 60 * 24 * 7 # 1 week (default)


# ---------------------------------------------------------------------------
# Fallback in-memory store (used when Redis is unavailable)
# ---------------------------------------------------------------------------

class _InMemoryFallback:
    """Mimics the Redis interface Zero uses, stored in process RAM."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[Any, float | None]] = {}  # key → (value, expiry)

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        expiry = time.time() + ex if ex else None
        self._store[key] = (value, expiry)

    def get(self, key: str) -> str | None:
        item = self._store.get(key)
        if item is None:
            return None
        value, expiry = item
        if expiry and time.time() > expiry:
            del self._store[key]
            return None
        return value

    def delete(self, key: str) -> None:
        self._store.pop(key, None)

    def keys(self, pattern: str = "*") -> list[str]:
        now = time.time()
        # Expire stale keys
        stale = [k for k, (_, exp) in self._store.items() if exp and now > exp]
        for k in stale:
            del self._store[k]
        if pattern == "*":
            return list(self._store.keys())
        prefix = pattern.rstrip("*")
        return [k for k in self._store if k.startswith(prefix)]

    def ping(self) -> bool:
        return True

    def flushdb(self) -> None:
        self._store.clear()


# ---------------------------------------------------------------------------
# Warm memory store
# ---------------------------------------------------------------------------

class WarmMemory:
    """
    Redis-backed warm cache with in-memory fallback.

    Keys are namespaced: zero:{category}:{identifier}
    Values are JSON-serialised dicts.

    Categories:
      - interaction  — recent Q&A pairs
      - research     — cached research briefs
      - preference   — user preferences and settings
      - agent        — agent outputs worth keeping
    """

    def __init__(self, redis_url: str = "redis://localhost:6379/0") -> None:
        """
        Args:
            redis_url: Redis connection URL. Falls back to in-memory if unavailable.
        """
        self._redis_url = redis_url
        self._client: Any = None
        self._using_fallback = False
        self._connect()

    def _connect(self) -> None:
        """Attempt Redis connection; fall back to in-memory if it fails."""
        try:
            import redis
            client = redis.from_url(self._redis_url, decode_responses=True)
            client.ping()
            self._client = client
            self._using_fallback = False
            logger.info(f"[warm] Redis connected at {self._redis_url}")
        except Exception as exc:
            logger.warning(
                f"[warm] Redis unavailable ({exc}). "
                "Using in-memory fallback — data won't survive restarts."
            )
            self._client = _InMemoryFallback()
            self._using_fallback = True

    @property
    def is_redis(self) -> bool:
        """True if backed by real Redis."""
        return not self._using_fallback

    # ------------------------------------------------------------------
    # Low-level key/value
    # ------------------------------------------------------------------

    def _key(self, category: str, identifier: str) -> str:
        return f"zero:{category}:{identifier}"

    def set(
        self,
        category: str,
        identifier: str,
        data: dict[str, Any],
        ttl: int = TTL_LONG,
    ) -> None:
        """
        Store a JSON-serialisable dict.

        Args:
            category: Namespace (e.g. "research", "interaction").
            identifier: Unique key within the category.
            data: Data to store.
            ttl: Time-to-live in seconds.
        """
        key = self._key(category, identifier)
        try:
            self._client.set(key, json.dumps(data), ex=ttl)
        except Exception as exc:
            logger.error(f"[warm] set({key}) failed: {exc}")

    def get(self, category: str, identifier: str) -> dict[str, Any] | None:
        """
        Retrieve a stored dict.

        Args:
            category: Namespace.
            identifier: Key within the category.

        Returns:
            Dict if found and not expired, else None.
        """
        key = self._key(category, identifier)
        try:
            raw = self._client.get(key)
            if raw is None:
                return None
            return json.loads(raw)
        except Exception as exc:
            logger.error(f"[warm] get({key}) failed: {exc}")
            return None

    def delete(self, category: str, identifier: str) -> None:
        """Delete a specific entry."""
        key = self._key(category, identifier)
        try:
            self._client.delete(key)
        except Exception as exc:
            logger.error(f"[warm] delete({key}) failed: {exc}")

    def list_keys(self, category: str) -> list[str]:
        """
        List all identifiers in a category.

        Args:
            category: Namespace to list.

        Returns:
            List of identifier strings (without the namespace prefix).
        """
        prefix = f"zero:{category}:"
        try:
            raw_keys = self._client.keys(f"{prefix}*")
            return [k[len(prefix):] for k in raw_keys]
        except Exception as exc:
            logger.error(f"[warm] list_keys({category}) failed: {exc}")
            return []

    # ------------------------------------------------------------------
    # High-level helpers
    # ------------------------------------------------------------------

    def cache_interaction(self, user_input: str, zero_response: str, metadata: dict[str, Any] | None = None) -> None:
        """
        Cache a user↔Astra interaction for recent context.

        Args:
            user_input: What the user said.
            zero_response: What Zero replied.
            metadata: Optional extra data (agents used, cost, etc.)
        """
        identifier = str(int(time.time() * 1000))
        self.set("interaction", identifier, {
            "user": user_input,
            "zero": zero_response,
            "timestamp": time.time(),
            "metadata": metadata or {},
        }, ttl=TTL_LONG)

    def get_recent_interactions(self, n: int = 10) -> list[dict[str, Any]]:
        """
        Return the n most recent cached interactions, newest first.

        Args:
            n: Max interactions to return.

        Returns:
            List of interaction dicts.
        """
        keys = sorted(self.list_keys("interaction"), reverse=True)[:n]
        results = []
        for k in keys:
            entry = self.get("interaction", k)
            if entry:
                results.append(entry)
        return results

    def cache_research(self, query: str, brief: dict[str, Any]) -> None:
        """
        Cache a research brief to avoid re-searching the same topic.

        Args:
            query: The original search query (used as key).
            brief: ResearchBrief.to_dict() output.
        """
        # Normalise key: lowercase, spaces→underscores, max 100 chars
        identifier = query.lower().replace(" ", "_")[:100]
        self.set("research", identifier, brief, ttl=TTL_MEDIUM)
        logger.debug(f"[warm] Cached research brief for: {query!r}")

    def get_cached_research(self, query: str) -> dict[str, Any] | None:
        """
        Check if a research brief is cached.

        Args:
            query: The search query to look up.

        Returns:
            Cached brief dict or None.
        """
        identifier = query.lower().replace(" ", "_")[:100]
        return self.get("research", identifier)

    def set_preference(self, key: str, value: Any) -> None:
        """
        Persist a user preference.

        Args:
            key: Preference name (e.g. "voice", "tts_backend").
            value: JSON-serialisable value.
        """
        self.set("preference", key, {"value": value, "updated": time.time()}, ttl=60 * 60 * 24 * 365)

    def get_preference(self, key: str, default: Any = None) -> Any:
        """
        Retrieve a user preference.

        Args:
            key: Preference name.
            default: Value to return if not found.

        Returns:
            Stored value or default.
        """
        entry = self.get("preference", key)
        if entry is None:
            return default
        return entry.get("value", default)

    def stats(self) -> dict[str, Any]:
        """Return cache stats for debugging."""
        categories = ["interaction", "research", "preference", "agent"]
        return {
            "backend": "redis" if self.is_redis else "in-memory-fallback",
            "redis_url": self._redis_url,
            "counts": {cat: len(self.list_keys(cat)) for cat in categories},
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

warm_memory = WarmMemory()
