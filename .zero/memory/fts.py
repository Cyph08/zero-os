"""
memory/fts.py — Zero OS FTS5 Keyword Memory Index

A SQLite FTS5 full-text index that sits alongside the ChromaDB vector store
(memory/cold.py). Vectors capture meaning; FTS5 captures exact terms — acronyms
(CSP, EEG), names (Lumineth), IDs (RTX 4050), file paths. Fusing the two (see
ColdMemory.hybrid_search) gives semantic + exact-term recall.

Borrowed from Nous Research's Hermes Agent, which pairs vector recall with FTS5.

Stdlib-only: sqlite3 ships with FTS5 in standard CPython builds. If FTS5 is not
compiled in, this module disables itself and every call no-ops, so memory recall
degrades gracefully to pure vector search.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Keep the keyword index next to the ChromaDB store.
_DB_PATH = Path(__file__).parent / "fts_index.db"

_WORD_RE = re.compile(r"[a-z0-9]+")


def _sanitise(query: str) -> str:
    """
    Reduce arbitrary text to a safe FTS5 MATCH expression.

    FTS5 MATCH has its own grammar (quotes, AND/OR/NOT/NEAR operators) that raw
    user text would break. We extract word tokens, quote each as a string literal
    so words like "and"/"or" can't be read as operators, and OR them together so
    any matching term contributes (bm25 then ranks by relevance).

    Args:
        query: Raw search text.

    Returns:
        An FTS5 MATCH string, or "" if the query has no usable tokens.
    """
    tokens = _WORD_RE.findall(query.lower())
    return " OR ".join(f'"{t}"' for t in tokens)


class FtsMemory:
    """SQLite FTS5 keyword index over stored memory documents."""

    def __init__(self, db_path: Path = _DB_PATH) -> None:
        """
        Args:
            db_path: SQLite file backing the FTS5 index.
        """
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None
        # One shared connection (check_same_thread=False) guarded by a lock, since
        # agents now run in parallel threads and may write memory concurrently.
        self._lock = threading.Lock()
        self._available = False
        self._connect()

    def _connect(self) -> None:
        """Open the DB and ensure the FTS5 table exists. Disables on any failure."""
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts "
                "USING fts5(doc_id UNINDEXED, collection UNINDEXED, text, ts UNINDEXED)"
            )
            conn.commit()
            self._conn = conn
            self._available = True
            logger.info(f"[fts] FTS5 keyword index ready at {self._db_path}")
        except Exception as exc:
            logger.warning(f"[fts] FTS5 unavailable ({exc}); keyword recall disabled")
            self._available = False

    @property
    def is_available(self) -> bool:
        """True if the FTS5 index is usable."""
        return self._available

    def index(self, doc_id: str, collection: str, text: str, ts: float | None = None) -> None:
        """
        Insert or replace a document in the keyword index.

        Args:
            doc_id:     Same ID used in the vector store (keeps the two aligned).
            collection: Which collection this doc belongs to.
            text:       Full text to index.
            ts:         Optional timestamp (defaults to now).
        """
        if not self._available or not text:
            return
        try:
            with self._lock:
                self._conn.execute("DELETE FROM memory_fts WHERE doc_id = ?", (doc_id,))
                self._conn.execute(
                    "INSERT INTO memory_fts (doc_id, collection, text, ts) VALUES (?, ?, ?, ?)",
                    (doc_id, collection, text, ts if ts is not None else time.time()),
                )
                self._conn.commit()
        except Exception as exc:
            logger.error(f"[fts] index({doc_id!r}) failed: {exc}")

    def delete(self, doc_id: str) -> None:
        """Remove a document from the keyword index by ID."""
        if not self._available:
            return
        try:
            with self._lock:
                self._conn.execute("DELETE FROM memory_fts WHERE doc_id = ?", (doc_id,))
                self._conn.commit()
        except Exception as exc:
            logger.error(f"[fts] delete({doc_id!r}) failed: {exc}")

    def search(
        self, query: str, collection: str | None = None, limit: int = 5
    ) -> list[dict[str, Any]]:
        """
        Keyword search ranked by bm25 (best first).

        Args:
            query:      Raw search text (sanitised internally).
            collection: Optional collection filter.
            limit:      Max results.

        Returns:
            List of dicts: {id, collection, text, score}. Empty if unavailable
            or the query has no usable tokens.
        """
        if not self._available:
            return []
        match = _sanitise(query)
        if not match:
            return []
        try:
            sql = (
                "SELECT doc_id, collection, text, bm25(memory_fts) AS score "
                "FROM memory_fts WHERE memory_fts MATCH ?"
            )
            params: list[Any] = [match]
            if collection:
                sql += " AND collection = ?"
                params.append(collection)
            sql += " ORDER BY score LIMIT ?"   # bm25: lower = better, so ASC
            params.append(limit)
            with self._lock:
                rows = self._conn.execute(sql, params).fetchall()
            return [
                {"id": r[0], "collection": r[1], "text": r[2], "score": r[3]}
                for r in rows
            ]
        except Exception as exc:
            logger.error(f"[fts] search({query!r}) failed: {exc}")
            return []

    def count(self) -> int:
        """Number of indexed documents (0 if unavailable)."""
        if not self._available:
            return 0
        try:
            with self._lock:
                return self._conn.execute("SELECT count(*) FROM memory_fts").fetchone()[0]
        except Exception:
            return 0

    def backfill_from(self, cold: Any) -> int:
        """
        One-time migration: index every doc from the ColdMemory collections.

        Only runs when the index is empty, so existing ChromaDB history becomes
        keyword-searchable on first launch. Takes the cold instance directly (not
        an import) to avoid a circular import between cold.py and fts.py.

        Args:
            cold: The ColdMemory instance whose collections to read.

        Returns:
            Number of documents indexed.
        """
        if not self._available or self.count() > 0:
            return 0
        indexed = 0
        try:
            collections = getattr(cold, "_collections", {}) or {}
            for name, col in collections.items():
                try:
                    data = col.get()   # pull all docs in this collection
                except Exception:
                    continue
                ids = data.get("ids", []) or []
                docs = data.get("documents", []) or []
                metas = data.get("metadatas", []) or []
                for i, doc_id in enumerate(ids):
                    text = docs[i] if i < len(docs) else ""
                    meta = metas[i] if i < len(metas) else {}
                    ts = (meta or {}).get("timestamp")
                    self.index(doc_id, name, text or "", ts)
                    indexed += 1
            if indexed:
                logger.info(f"[fts] backfilled {indexed} docs from the vector store")
        except Exception as exc:
            logger.error(f"[fts] backfill failed: {exc}")
        return indexed


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

fts_memory = FtsMemory()
