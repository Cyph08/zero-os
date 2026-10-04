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

import hashlib
import logging
import os
import re
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
COLLECTION_FEEDBACK     = "feedback"     # Cyph's 👍/👎 on past answers


# ---------------------------------------------------------------------------
# Knowledge ingestion helpers — Cyph's Obsidian vaults and PDFs
# ---------------------------------------------------------------------------

_KB_EXTENSIONS = (".md", ".pdf")
# Code projects carry virtualenvs full of third-party docs: K:\foresight's .venv
# alone contributed 33 files (Hugging Face model-card templates, licences,
# matplotlib icon PDFs) against 8 of Cyph's own notes.
_KB_SKIP_DIRS = {".obsidian", ".trash", ".git", "node_modules", "__pycache__",
                 ".venv", "venv", "site-packages", ".pytest_cache", ".mypy_cache",
                 ".ruff_cache", ".tox"}
# The embedder (all-MiniLM-L6-v2) reads ~256 tokens, about 1,000 characters.
# Storing whole notes meant everything past the first paragraph or two was
# invisible to semantic recall, so notes are split into chunks that fit.
_CHUNK_CHARS = 1000
_CHUNK_OVERLAP = 150


def knowledge_dirs() -> list[Path]:
    """
    Folders Zero learns from. ZERO_KNOWLEDGE_DIRS in .env, semicolon-separated.
    Removing a folder from the list removes its notes from memory on the next sync.
    """
    raw = os.getenv("ZERO_KNOWLEDGE_DIRS", "")
    dirs = [Path(d.strip()) for d in raw.split(";") if d.strip()]
    return dirs or [Path(__file__).parent.parent.parent / "Zero Memory"]


def _chunk(text: str, size: int = _CHUNK_CHARS, overlap: int = _CHUNK_OVERLAP) -> list[str]:
    """Split on paragraph boundaries into chunks of about `size` characters."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    cur = ""
    for para in paras:
        while len(para) > size:            # PDF text often has no paragraph breaks
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(para[:size])
            para = para[size - overlap:]
        if cur and len(cur) + len(para) + 2 > size:
            chunks.append(cur)
            cur = cur[-overlap:] + "\n\n" + para   # carry a little context forward
        else:
            cur = f"{cur}\n\n{para}" if cur else para
    if cur:
        chunks.append(cur)
    return chunks


def _read_doc(path: Path) -> str:
    """Text of a .md or .pdf file."""
    if path.suffix.lower() == ".pdf":
        from pypdf import PdfReader
        return "\n\n".join((page.extract_text() or "") for page in PdfReader(str(path)).pages)
    return path.read_text(encoding="utf-8", errors="ignore")


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
            for name in (COLLECTION_INTERACTIONS, COLLECTION_RESEARCH, COLLECTION_KNOWLEDGE,
                         COLLECTION_FEEDBACK):
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

    def sync_vault(self, dirs: "list[Path] | None" = None) -> int:
        """
        Pull Cyph's notes and PDFs INTO cold memory, chunked, so Zero can recall them.

        Reads every .md and .pdf under each folder in ZERO_KNOWLEDGE_DIRS
        (recursively, skipping .obsidian/.trash). A file is re-read only when its
        modified time changes. Notes deleted from disk — or whose folder is
        removed from the list — are removed from memory too, so taking something
        out of the vault takes it out of what Zero can see.

        Args:
            dirs: Folders to sync. Defaults to knowledge_dirs().

        Returns:
            Number of files stored or updated.
        """
        if not self._available:
            return 0
        col = self._collection(COLLECTION_KNOWLEDGE)
        roots = [Path(d) for d in dirs] if dirs else knowledge_dirs()
        missing = [r for r in roots if not r.exists()]
        for r in missing:
            logger.warning(f"[cold] Knowledge folder not found, skipping: {r}")

        seen: set[str] = set()
        synced = 0
        for root in (r for r in roots if r.exists()):
            for path in sorted(root.rglob("*")):
                if path.suffix.lower() not in _KB_EXTENSIONS or not path.is_file():
                    continue
                if _KB_SKIP_DIRS.intersection(path.parts):
                    continue
                key = hashlib.sha1(str(path.resolve()).lower().encode()).hexdigest()[:16]
                try:
                    mtime = int(path.stat().st_mtime)
                    old = col.get(where={"file_key": key}, include=["metadatas"])
                    old_ids = old.get("ids") or []
                    if old_ids and all((m or {}).get("mtime") == mtime
                                       for m in old.get("metadatas") or []):
                        seen.update(old_ids)          # unchanged since last sync
                        continue
                    chunks = _chunk(_read_doc(path))
                except Exception as exc:              # unreadable PDF, locked file...
                    logger.warning(f"[cold] Knowledge sync skipped {path.name}: {exc}")
                    continue
                if not chunks:      # empty note / image-only PDF; old chunks purge below
                    continue
                new_ids = [f"kb_{key}_{i}" for i in range(len(chunks))]
                # ponytail: one upsert per chunk — the first full sync took ~9 min on
                # CPU. Later syncs only touch changed files. Batch the upserts if a
                # bigger vault makes that first pass painful.
                for i, (doc_id, chunk) in enumerate(zip(new_ids, chunks)):
                    self.store(
                        collection=COLLECTION_KNOWLEDGE,
                        doc_id=doc_id,
                        text=f"{path.stem}: {chunk}",
                        metadata={"source": "vault", "type": "vault", "file_key": key,
                                  "title": path.stem[:100], "path": str(path),
                                  "chunk": i, "mtime": mtime},
                    )
                for stale in set(old_ids) - set(new_ids):   # the file got shorter
                    self.delete(COLLECTION_KNOWLEDGE, stale)
                seen.update(new_ids)
                synced += 1

        # Purge what's no longer on disk. A folder that is merely missing (drive
        # unplugged) keeps its notes — only real deletions and removed folders go.
        everything = col.get(where={"source": "vault"}, include=["metadatas"])
        for doc_id, meta in zip(everything.get("ids") or [], everything.get("metadatas") or []):
            if doc_id in seen:
                continue
            path = str((meta or {}).get("path", "")).lower()
            if any(path.startswith(str(m).lower()) for m in missing):
                continue
            self.delete(COLLECTION_KNOWLEDGE, doc_id)

        if synced:
            logger.info(f"[cold] Knowledge sync: {synced} file(s) stored/updated, "
                        f"{len(seen)} chunks from {len(roots) - len(missing)} folder(s)")
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
