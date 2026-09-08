"""
skills/skill_generator.py — Zero OS Skill Auto-Generator

After a qualifying multi-agent task completes, distil the successful
interaction into a reusable Skill — a compact named procedure whose
agent_sequence and synthesis_hint can be recalled without replanning.

Borrowed from Hermes Agent's skill auto-generation design. Zero's version
uses a single fast-tier LLM call (Haiku, cheap) to extract the skill JSON.
It only fires on multi-agent tasks, never on direct responses or errors.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from typing import TYPE_CHECKING

from core.llm import chat
from skills.skill_store import Skill, skill_store

if TYPE_CHECKING:
    from core.ceo import TaskContext

logger = logging.getLogger(__name__)

_MIN_AGENTS = 2          # multi-agent threshold to qualify for distillation
_MIN_RESPONSE_LEN = 80   # skip trivial/error responses
_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


# ---------------------------------------------------------------------------
# Public
# ---------------------------------------------------------------------------

def maybe_generate(ctx: "TaskContext") -> Skill | None:
    """
    Attempt to distil a completed task into a reusable skill.

    Qualification rules (all must pass):
    - At least _MIN_AGENTS department agents were used
    - Final response is substantial and doesn't start with an error marker
    - No duplicate skill already covers the same agent sequence + query

    On pass: calls the LLM (fast tier, one cheap call) to extract the skill
    JSON, stores it, and returns the Skill. On any failure or disqualification:
    returns None silently.

    Args:
        ctx: Completed TaskContext from CEO.handle().

    Returns:
        The saved Skill, or None.
    """
    if not _qualifies(ctx):
        return None

    agents_used = [a.name for a in ctx.selected_agents]

    # --- Deduplicate: skip if an existing skill already covers this agent set ---
    existing = skill_store.find(ctx.user_input, top_k=1)
    if existing and existing[0].agent_sequence == agents_used:
        logger.debug(
            f"[skill_gen] Skipping — existing skill {existing[0].name!r} "
            f"covers same agent sequence {agents_used}"
        )
        return None

    # --- LLM extraction (single fast call) ---
    prompt = (
        f"A user asked: {ctx.user_input!r}\n"
        f"Agents used (in order): {', '.join(agents_used)}\n"
        f"Result preview: {ctx.final_response[:300]!r}\n\n"
        "Distil this into a reusable skill. Reply with ONLY valid JSON, "
        "no markdown, no explanation:\n"
        "{\n"
        '  "name": "short_snake_case_name",\n'
        '  "description": "one sentence — what class of task this handles",\n'
        '  "trigger_phrases": ["3 to 5 example queries that should activate this skill"],\n'
        '  "synthesis_hint": "one sentence tip for synthesizing this type of response"\n'
        "}"
    )

    try:
        resp = chat(prompt, tier="fast", max_tokens=256)
        raw = resp.text.strip()

        m = _JSON_RE.search(raw)
        if not m:
            logger.warning("[skill_gen] LLM returned no parseable JSON")
            return None

        data = json.loads(m.group(0))

        skill = Skill(
            id=f"skill_{uuid.uuid4().hex[:8]}",
            name=_safe_name(data.get("name", "unnamed_skill")),
            description=data.get("description", ""),
            trigger_phrases=_coerce_list(data.get("trigger_phrases", [])),
            agent_sequence=agents_used,
            synthesis_hint=str(data.get("synthesis_hint", ""))[:200],
            created_at=time.time(),
        )

        if not skill.trigger_phrases:
            logger.warning("[skill_gen] Skill has no trigger phrases — discarding")
            return None

        skill_store.save(skill)
        logger.info(
            f"[skill_gen] Generated skill {skill.name!r} "
            f"(agents={agents_used}, triggers={len(skill.trigger_phrases)})"
        )
        return skill

    except (json.JSONDecodeError, KeyError) as exc:
        logger.warning(f"[skill_gen] Skill extraction failed: {exc}")
        return None
    except Exception as exc:
        logger.error(f"[skill_gen] Unexpected error: {exc}")
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _qualifies(ctx: "TaskContext") -> bool:
    """Return True if this interaction is worth distilling."""
    if len(ctx.selected_agents) < _MIN_AGENTS:
        return False
    if not ctx.final_response:
        return False
    if len(ctx.final_response) < _MIN_RESPONSE_LEN:
        return False
    # Rough error check — don't distil failed responses
    first_40 = ctx.final_response[:40].lower()
    if "error" in first_40 or "failed" in first_40:
        return False
    return True


def _safe_name(raw: str) -> str:
    """Sanitise the skill name to a safe snake_case slug."""
    slug = re.sub(r"[^a-z0-9_]", "_", raw.lower().strip())
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug[:60] or "unnamed_skill"


def _coerce_list(val: object) -> list[str]:
    """Ensure trigger_phrases is a plain list of strings."""
    if isinstance(val, list):
        return [str(v) for v in val if v]
    if isinstance(val, str):
        return [val]
    return []
