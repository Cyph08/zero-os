"""
memory/cold.py — Zero OS ChromaDB Long-Term Vector Store

Permanent semantic memory. Stores embeddings of past interactions,
research briefs, agent outputs, and any knowledge Zero should remember
forever. Uses cosine similarity search to retrieve relevant past context.

Think of this as Zero's long-term memory — things from months ago
that are still relevant to today's questions.

ChromaDB runs locally, no cloud needed.
Embeddings are generated using sentence-transformers (all-MiniLM-L6-v2)
which runs entirely on CPU — no GPU needed for memory.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from memory.fts import fts_memory

logger = logging.getLogger(__name__)

# Persist DB here so memory survives restarts
_DB_PATH = Path(__file__).parent.parent / "memory" / "chroma_db"

# Collections (like tables in a relational DB)
COLLECTION_INTERACTIONS = "interactions"
COLLECTION_RESEARCH     = "research"
COLLECTION_KNOWLEDGE    = "knowledge"


# ---------------------------------------------------------------------------
# Cold memory store
# ---------------------------------------------------------------------------

class ColdMemory:
    """
    ChromaDB-backed long-term semantic memory.

    Stores text as vector embeddings. When you search, it finds
    semantically similar entries — not just keyword matches.

    Example: storing "BCI motor imagery EEG classification paper"
    will match a search for "brain computer interface neural patterns"
    because the embeddings capture meaning, not just words.
    """

    def __init__(self, db_path: Path = _DB_PATH) -> None:
        """
        Args:
            db_path: Directory where ChromaDB persists data.
        """
        self._db_path = db_path
        self._client: Any = None
        self._collections: dict[str, Any] = {}
        self._available = False
        self._connect()

    def _connect(self) -> None:
        """Initialise ChromaDB client. Logs warning if unavailable."""
        try:
            import chromadb
            self._db_path.mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(path=str(self._db_path))
            # Pre-load collections
            for name in (COLLECTION_INTERACTIONS, COLLECTION_RESEARCH, COLLECTION_KNOWLEDGE):
                self._collections[name] = self._client.get_or_create_collection(
                    name=name,
                    metadata={"hnsw:space": "cosine"},   # cosine similarity
                )
            self._available = True
            logger.info(f"[cold] ChromaDB connected at {self._db_path}")
            # Seed the keyword index from existing history on first run (no-op if
            # already populated). Keeps vector + keyword recall in sync.
            fts_memory.backfill_from(self)
        except ImportError:
            logger.warning("[cold] chromadb not installed. Run: uv pip install chromadb")
        except Exception as exc:
            logger.warning(f"[cold] ChromaDB unavailable: {exc}")

    @property
    def is_available(self) -> bool:
        """True if ChromaDB connected successfully."""
        return self._available

    def _collection(self, name: str) -> Any:
        """Get a collection by name, raising clearly if unavailable."""
        if not self._available:
            raise RuntimeError(
                "ChromaDB is not available. "
                "Install with: uv pip install chromadb"
            )
        return self._collections[name]

    # ------------------------------------------------------------------
    # Store
    # ------------------------------------------------------------------

    def store(
        self,
        collection: str,
        doc_id: str,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        Store a text document as a vector embedding.

        ChromaDB generates the embedding automatically using its default
        embedding function (sentence-transformers all-MiniLM-L6-v2).

        Args:
            collection: Which collection to store in (use constants above).
            doc_id: Unique ID for this document. If it already exists, it's updated.
            text: The text to embed and store.
            metadata: Optional dict of filterable metadata (must be str/int/float/bool values).
        """
        if not self._available:
            logger.warning("[cold] store() skipped — ChromaDB unavailable")
            return
        try:
            col = self._collection(collection)
            meta = {"timestamp": time.time(), **(metadata or {})}
            # upsert = insert or update
            col.upsert(
                ids=[doc_id],
                documents=[text],
                metadatas=[meta],
            )
            # Mirror into the FTS5 keyword index so exact terms are recallable too.
            fts_memory.index(doc_id, collection, text, meta["timestamp"])
            logger.debug(f"[cold] Stored doc {doc_id!r} in {collection!r}")
        except Exception as exc:
            logger.error(f"[cold] store({collection}, {doc_id}) failed: {exc}")

    def store_interaction(self, user_input: str, zero_response: str, agents_used: list[str] | None = None) -> str:
        """
        Store a user↔Astra exchange in long-term memory.

        Args:
            user_input: What the user said.
            zero_response: What Zero replied.
            agents_used: Which agents handled this interaction.

        Returns:
            The doc_id used (timestamp-based).
        """
        doc_id = f"interaction_{int(time.time() * 1000)}"
        text = f"User: {user_input}\nZero: {zero_response}"
        self.store(
            collection=COLLECTION_INTERACTIONS,
            doc_id=doc_id,
            text=text,
            metadata={
                "user_input": user_input[:500],
                "agents": ",".join(agents_used or []),
                "type": "interaction",
            },
        )
        return doc_id

    def store_research(self, query: str, summary: str, sources_count: int = 0) -> str:
        """
        Store a research brief summary in long-term memory.

        Args:
            query: Original search query.
            summary: The research summary text.
            sources_count: How many sources were used.

        Returns:
            The doc_id used.
        """
        doc_id = f"research_{int(time.time() * 1000)}"
        self.store(
            collection=COLLECTION_RESEARCH,
            doc_id=doc_id,
            text=f"Query: {query}\n\n{summary}",
            metadata={
                "query": query[:300],
                "sources_count": sources_count,
                "type": "research",
            },
        )
        return doc_id

    def store_knowledge(self, topic: str, content: str, source: str = "user") -> str:
        """
        Store a piece of knowledge Zero should remember permanently.

        Args:
            topic: Short topic label (e.g. "Cyph's MSc project").
            content: The knowledge to store.
            source: Where this came from ("user", "research", "agent").

        Returns:
            The doc_id used.
        """
        doc_id = f"knowledge_{topic.lower().replace(' ', '_')}_{int(time.time())}"
        self.store(
            collection=COLLECTION_KNOWLEDGE,
            doc_id=doc_id,
            text=f"{topic}: {content}",
            metadata={"topic": topic[:100], "source": source, "type": "knowledge"},
        )
        return doc_id

    def sync_vault(self, vault_dir: "Path | None" = None, max_chars: int = 4000) -> int:
        """
        Pull the Obsidian vault (K:\\Zero\\Zero Memory) INTO cold memory.

        The vault was previously write-only: info_store mirrors saves out to .md
        files, but notes Cyph edits or adds by hand in Obsidian were invisible to
        recall. This scans every vault .md, and (re)stores any file that is new or
        changed since its last sync, keyed by filename so re-syncs update in place.

        Args:
            vault_dir: Vault folder. Defaults to <repo-parent>/Zero Memory.
            max_chars: Per-note cap fed to the embedder.

        Returns:
            Number of notes stored/updated (0 if vault missing or ChromaDB down).
        """
        from pathlib import Path as _P
        vault = _P(vault_dir) if vault_dir else _P(__file__).parent.parent.parent / "Zero Memory"
        if not vault.exists() or self._client is None:
            return 0
        synced = 0
        for md in sorted(vault.glob("*.md")):
            try:
                mtime = int(md.stat().st_mtime)
                doc_id = f"vault_{md.stem.lower().replace(' ', '_')}"
                # Skip unchanged files: stored metadata carries the mtime.
                try:
                    existing = self._collections[COLLECTION_KNOWLEDGE].get(ids=[doc_id])
                    metas = existing.get("metadatas") or []
                    if metas and metas[0] and metas[0].get("mtime") == mtime:
                        continue
                except Exception:
                    pass  # not present yet — store below
                text = md.read_text(encoding="utf-8", errors="ignore")[:max_chars]
                if not text.strip():
                    continue
                self.store(
                    collection=COLLECTION_KNOWLEDGE,
                    doc_id=doc_id,
                    text=f"{md.stem}: {text}",
                    metadata={"topic": md.stem[:100], "source": "vault", "type": "vault", "mtime": mtime},
                )
                synced += 1
            except (OSError, UnicodeDecodeError) as exc:
                logger.warning(f"[cold] Vault sync skipped {md.name}: {exc}")
        if synced:
            logger.info(f"[cold] Vault sync: {synced} note(s) stored/updated from {vault}")
        return synced

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(
        self,
        collection: str,
        query: str,
        n_results: int = 5,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Semantic search: find documents most similar to the query.

        Args:
            collection: Which collection to search.
            query: The search query (embedded and compared to stored docs).
            n_results: Max results to return.
            where: Optional metadata filter, e.g. {"type": "research"}.

        Returns:
            List of dicts with keys: id, text, metadata, distance.
        """
        if not self._available:
            return []
        try:
            col = self._collection(collection)
            kwargs: dict[str, Any] = {
                "query_texts": [query],
                "n_results": min(n_results, col.count() or 1),
            }
            if where:
                kwargs["where"] = where
            results = col.query(**kwargs)
            output = []
            ids = results.get("ids", [[]])[0]
            docs = results.get("documents", [[]])[0]
            metas = results.get("metadatas", [[]])[0]
            distances = results.get("distances", [[]])[0]
            for doc_id, text, meta, dist in zip(ids, docs, metas, distances):
                output.append({
                    "id": doc_id,
                    "text": text,
                    "metadata": meta,
                    "distance": round(dist, 4),   # 0 = identical, 1 = unrelated
                })
            return output
        except Exception as exc:
            logger.error(f"[cold] search({collection}, {query!r}) failed: {exc}")
            return []

    def search_all(self, query: str, n_results: int = 3) -> list[dict[str, Any]]:
        """
        Search across all collections and return combined results.

        Args:
            query: Semantic search query.
            n_results: Results per collection.

        Returns:
            Combined list sorted by distance (most relevant first).
        """
        results = []
        for col_name in (COLLECTION_INTERACTIONS, COLLECTION_RESEARCH, COLLECTION_KNOWLEDGE):
            hits = self.search(col_name, query, n_results=n_results)
            for hit in hits:
                hit["collection"] = col_name
            results.extend(hits)
        results.sort(key=lambda x: x["distance"])
        return results

    def hybrid_search(
        self, collection: str, query: str, n_results: int = 4
    ) -> list[dict[str, Any]]:
        """
        Fuse semantic (vector) and keyword (FTS5) recall for the best of both.

        Vector search captures meaning; FTS5 captures exact terms (acronyms,
        names, IDs) that embeddings often miss. The two score scales aren't
        comparable, so we merge by Reciprocal Rank Fusion: each result scores
        sum(1 / (k + rank)) across the lists it appears in, then we take the top
        few. Degrades to pure vector search if FTS5 is unavailable.

        Args:
            collection: Which collection to search.
            query:      The search text.
            n_results:  How many fused results to return.

        Returns:
            List of dicts (id, text, metadata/collection, sources) best-first,
            where 'sources' notes which index(es) hit — 'vector', 'keyword', or both.
        """
        # Pull a slightly wider net from each side, then fuse and trim.
        fetch = max(n_results * 2, 6)
        vector_hits = self.search(collection, query, n_results=fetch)
        keyword_hits = fts_memory.search(query, collection=collection, limit=fetch)

        if not keyword_hits:
            return vector_hits[:n_results]   # FTS unavailable / no match → vector only

        k = 60   # RRF dampening constant (standard default)
        fused: dict[str, dict[str, Any]] = {}

        def _add(doc_id: str, rank: int, payload: dict[str, Any], source: str) -> None:
            entry = fused.get(doc_id)
            if entry is None:
                entry = {**payload, "id": doc_id, "rrf": 0.0, "sources": []}
                fused[doc_id] = entry
            entry["rrf"] += 1.0 / (k + rank)
            if source not in entry["sources"]:
                entry["sources"].append(source)

        for rank, hit in enumerate(vector_hits):
            _add(hit["id"], rank, hit, "vector")
        for rank, hit in enumerate(keyword_hits):
            _add(hit["id"], rank, {"text": hit["text"], "collection": hit["collection"]}, "keyword")

        ranked = sorted(fused.values(), key=lambda x: x["rrf"], reverse=True)
        return ranked[:n_results]

    # ------------------------------------------------------------------
    # Housekeeping
    # ------------------------------------------------------------------

    def delete(self, collection: str, doc_id: str) -> None:
        """
        Delete a document by ID.

        Args:
            collection: Collection name.
            doc_id: Document ID to delete.
        """
        if not self._available:
            return
        try:
            self._collection(collection).delete(ids=[doc_id])
            fts_memory.delete(doc_id)
        except Exception as exc:
            logger.error(f"[cold] delete({collection}, {doc_id}) failed: {exc}")

    def stats(self) -> dict[str, Any]:
        """Return collection counts for debugging."""
        if not self._available:
            return {"available": False}
        counts = {}
        for name, col in self._collections.items():
            try:
                counts[name] = col.count()
            except Exception:
                counts[name] = -1
        return {"available": True, "db_path": str(self._db_path), "counts": counts}


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

cold_memory = ColdMemory()
