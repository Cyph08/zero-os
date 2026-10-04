"""
skills/skill_store.py — Zero OS Skill Store

SQLite-backed persistent store for auto-generated reusable skills.
Each skill is a compact named procedure distilled from a successful
multi-agent task: who ran, what triggered it, and a synthesis hint for
next time. Keyword-scored matching (same approach as registry.find) keeps
lookups instant with no extra LLM call.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

_DB_PATH = Path(__file__).parent / "skills.db"
_WORD_RE = re.compile(r"[a-z0-9]+")
_MIN_OVERLAP = 2  # meaningful-token overlap required to count as a skill hit

# Matching used to compare raw tokens against the UNION of every trigger phrase.
# With ~5 phrases per skill that union runs to 30+ tokens, most of them filler,
# so almost any query shared two and hijacked routing — a calendar skill was
# catching "find the restart-zero.bat file on my laptop". Stripping filler and
# requiring the match to cover half the query's real words fixes that.
_STOPWORDS = frozenset("""
a an and are as at be been by can could do does doing for from get give got had has
have how i if in into is it its just like make me my of on or our out should so some
that the their them then there these they this to up us was we were what when where
which who why will with would you your s t re ve ll d m o n
""".split())


def _meaningful(text: str) -> set[str]:
    """Tokenise and drop filler words, so only content words can match."""
    return {t for t in _WORD_RE.findall(text.lower()) if t not in _STOPWORDS and len(t) > 1}


# ---------------------------------------------------------------------------
# Skill dataclass
# ---------------------------------------------------------------------------

@dataclass
class Skill:
    """A reusable procedure extracted from a successful multi-agent task."""
    id: str
    name: str
    description: str
    trigger_phrases: list[str]
    agent_sequence: list[str]
    synthesis_hint: str
    use_count: int = 0
    created_at: float = field(default_factory=time.time)
    last_used_at: float | None = None

    def trigger_tokens(self) -> set[str]:
        """Content words across every trigger phrase (filler removed)."""
        return _meaningful(" ".join(self.trigger_phrases))


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

class SkillStore:
    """
    SQLite-backed persistent store for auto-generated skills.

    Thread-safe. All public methods no-op gracefully if SQLite is unavailable.
    Skills are loaded from disk on every find() (fast for <200 rows).
    """

    def __init__(self, db_path: Path = _DB_PATH) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()
        self._available = False
        self._connect()

    def _connect(self) -> None:
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            conn.execute(
                "CREATE TABLE IF NOT EXISTS skills ("
                "  id TEXT PRIMARY KEY,"
                "  name TEXT NOT NULL,"
                "  description TEXT,"
                "  trigger_phrases TEXT,"
                "  agent_sequence TEXT,"
                "  synthesis_hint TEXT,"
                "  use_count INTEGER DEFAULT 0,"
                "  created_at REAL,"
                "  last_used_at REAL"
                ")"
            )
            conn.commit()
            self._conn = conn
            self._available = True
            logger.info(f"[skill_store] Ready at {self._db_path}")
        except Exception as exc:
            logger.warning(f"[skill_store] Unavailable: {exc}")

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def save(self, skill: Skill) -> None:
        """Insert or replace a skill."""
        if not self._available:
            return
        try:
            with self._lock:
                self._conn.execute(  # type: ignore[union-attr]
                    "INSERT OR REPLACE INTO skills VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        skill.id,
                        skill.name,
                        skill.description,
                        json.dumps(skill.trigger_phrases),
                        json.dumps(skill.agent_sequence),
                        skill.synthesis_hint,
                        skill.use_count,
                        skill.created_at,
                        skill.last_used_at,
                    ),
                )
                self._conn.commit()  # type: ignore[union-attr]
            logger.info(f"[skill_store] Saved {skill.name!r}")
        except Exception as exc:
            logger.error(f"[skill_store] save failed: {exc}")

    def increment_use(self, skill_id: str) -> None:
        """Bump use_count and set last_used_at."""
        if not self._available:
            return
        try:
            with self._lock:
                self._conn.execute(  # type: ignore[union-attr]
                    "UPDATE skills SET use_count=use_count+1, last_used_at=? WHERE id=?",
                    (time.time(), skill_id),
                )
                self._conn.commit()  # type: ignore[union-attr]
        except Exception as exc:
            logger.error(f"[skill_store] increment_use failed: {exc}")

    def delete(self, skill_id: str) -> None:
        """Remove a skill — used when Cyph 👎s an answer it routed."""
        if not self._available:
            return
        try:
            with self._lock:
                self._conn.execute("DELETE FROM skills WHERE id=?", (skill_id,))  # type: ignore[union-attr]
                self._conn.commit()  # type: ignore[union-attr]
            logger.info(f"[skill_store] Deleted {skill_id!r}")
        except Exception as exc:
            logger.error(f"[skill_store] delete failed: {exc}")

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def load_all(self) -> list[Skill]:
        """Load every skill from the DB."""
        if not self._available:
            return []
        try:
            with self._lock:
                rows = self._conn.execute(  # type: ignore[union-attr]
                    "SELECT id,name,description,trigger_phrases,agent_sequence,"
                    "synthesis_hint,use_count,created_at,last_used_at FROM skills"
                ).fetchall()
            return [_row_to_skill(r) for r in rows]
        except Exception as exc:
            logger.error(f"[skill_store] load_all failed: {exc}")
            return []

    def find(self, query: str, top_k: int = 1) -> list[Skill]:
        """
        Keyword-score skills against a query.

        Requires at least _MIN_OVERLAP shared tokens before a skill qualifies.
        Returns at most top_k best-matching skills, best first.

        Args:
            query:  Natural language query.
            top_k:  Maximum skills to return.

        Returns:
            Ranked list of matching Skill objects.
        """
        query_tokens = _meaningful(query)
        if not query_tokens:
            return []
        # The match must also COVER the query, not just brush it. A skill that
        # shares two words with a ten-word question is not the right plan for it;
        # without this a stored calendar skill swallowed unrelated requests and
        # the correct specialist agent never got a chance to match.
        needed = max(_MIN_OVERLAP, (len(query_tokens) + 1) // 2)
        scored: list[tuple[int, Skill]] = []
        for skill in self.load_all():
            overlap = len(query_tokens & skill.trigger_tokens())
            if overlap >= needed:
                scored.append((overlap, skill))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [s for _, s in scored[:top_k]]

    def count(self) -> int:
        """Total stored skills."""
        if not self._available:
            return 0
        try:
            with self._lock:
                return self._conn.execute(  # type: ignore[union-attr]
                    "SELECT count(*) FROM skills"
                ).fetchone()[0]
        except Exception:
            return 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_skill(row: tuple) -> Skill:
    return Skill(
        id=row[0],
        name=row[1],
        description=row[2] or "",
        trigger_phrases=json.loads(row[3] or "[]"),
        agent_sequence=json.loads(row[4] or "[]"),
        synthesis_hint=row[5] or "",
        use_count=row[6] or 0,
        created_at=row[7] or 0.0,
        last_used_at=row[8],
    )


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

skill_store = SkillStore()
