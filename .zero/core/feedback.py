"""
core/feedback.py — Cyph's 👍/👎 on Zero's answers, and what Zero does with them.

This is how Zero improves over time without retraining a model. Its brain is a
hosted API (DeepSeek / Kimi) whose weights can't be trained, so the learning
lives around the model instead:

- Every rating is kept: logs/feedback.jsonl (a preference dataset — exactly
  what fine-tuning the local model would need later) and cold memory.
- Similar future questions see the rated answer in their prompt: "Cyph liked
  this — match it" or "Cyph disliked this — don't repeat it". See
  ceo._load_memory_context().
- 👍 on a multi-agent answer teaches Zero that route (a "skill"), so similar
  questions skip the routing step. Skills are ONLY learned this way now —
  learning from every answer meant learning from failures.
- 👎 deletes the learned skill that routed the answer, so a bad route can't
  keep hijacking requests (the bug where Zero denied having laptop access).

Ratings are keyed by the interaction id cold memory already assigns, so a
button on a days-old message still works after any number of restarts.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_LOG = Path(__file__).parent.parent / "logs" / "feedback.jsonl"


def record(memory_id: str, rating: int) -> str:
    """
    Apply a 👍 (+1) or 👎 (-1) to a past answer.

    Args:
        memory_id: The interaction's cold-memory id (TaskContext.memory_id).
        rating:    +1 or -1. Rating again overwrites — the latest tap wins.

    Returns:
        A short line to show Cyph.
    """
    from memory.cold import COLLECTION_FEEDBACK, COLLECTION_INTERACTIONS, cold_memory

    try:
        got = cold_memory._collection(COLLECTION_INTERACTIONS).get(
            ids=[memory_id], include=["documents", "metadatas"])
    except Exception as exc:
        logger.error(f"[feedback] lookup failed for {memory_id}: {exc}")
        return "Couldn't save that rating."
    if not got.get("ids"):
        return "I can't find that answer any more."

    meta = (got["metadatas"] or [{}])[0] or {}
    doc = (got["documents"] or [""])[0] or ""
    query = meta.get("user_input") or doc.partition("\nZero: ")[0].removeprefix("User: ")
    answer = doc.partition("\nZero: ")[2]
    agents = [a for a in (meta.get("agents") or "").split(",") if a]

    try:
        with _LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": time.time(), "memory_id": memory_id, "rating": rating,
                "query": query, "answer": answer, "agents": agents,
            }, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.warning(f"[feedback] log write failed: {exc}")

    # Embed the QUESTION so similar future questions find it; carry the answer
    # in metadata for the prompt.
    cold_memory.store(
        collection=COLLECTION_FEEDBACK,
        doc_id=f"fb_{memory_id}",
        text=query,
        metadata={"rating": rating, "answer": answer[:1500],
                  "agents": ",".join(agents), "type": "feedback"},
    )

    note = _forget_skill(query, agents) if rating < 0 else _learn_skill(query, answer, agents)
    logger.info(f"[feedback] {'+1' if rating > 0 else '-1'} on {memory_id} "
                f"[{','.join(agents) or 'direct'}] {query[:60]!r}{note and ' — ' + note}")
    head = "👍 Noted — I'll answer like that again." if rating > 0 else "👎 Noted — I won't repeat that."
    return f"{head} {note}" if note else head


def _learn_skill(query: str, answer: str, agents: list[str]) -> str:
    """
    👍 on a multi-agent answer teaches Zero that route, so similar questions skip
    the routing step next time. This is the only place skills are created: they
    used to be learned from every answer, including failed ones.
    """
    try:
        from types import SimpleNamespace
        from skills.skill_generator import maybe_generate
        skill = maybe_generate(SimpleNamespace(
            user_input=query, final_response=answer,
            selected_agents=[SimpleNamespace(name=a) for a in agents],
        ))
        if skill is not None:
            return f"Learned the route '{skill.name}'."
    except Exception as exc:
        logger.warning(f"[feedback] skill learning failed: {exc}")
    return ""


def _forget_skill(query: str, agents: list[str]) -> str:
    """
    Delete the learned skill behind a 👎'd answer, if one routed it.

    The skill store is deterministic: the skill find() returns for this query now
    is the one that routed it — or the one just learned FROM it. Only deleted when
    its agent sequence matches what actually ran, so an unrelated skill is safe.
    """
    try:
        from skills.skill_store import skill_store
        hits = skill_store.find(query, top_k=1)
        if hits and hits[0].agent_sequence == agents:
            skill_store.delete(hits[0].id)
            return f"Dropped the learned route '{hits[0].name}'."
    except Exception as exc:
        logger.warning(f"[feedback] skill cleanup failed: {exc}")
    return ""
