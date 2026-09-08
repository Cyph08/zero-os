"""
agents/brainstorm/run.py — Zero OS Brainstorm Agent

Cyph's personal product manager and idea structurer. Takes any vague concept —
"I want to add X to Astra", "what should I build next", "how do I approach Y" —
and outputs a fully structured breakdown: problem, features, architecture, MVP
steps, risks, and immediate next actions.

Reads from the bus if research already ran, grounding ideas in real data.
Risk level: read — generates ideas only, never creates files or sends anything.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.llm import chat

if TYPE_CHECKING:
    from core.bus import ContextBus

logger = logging.getLogger(__name__)

AGENT_NAME = "Spark"
AGENT_VERSION = "0.1.0"
LOG_DIR = Path(__file__).parent.parent.parent / "logs"

# Cyph's context — what he's building and working on
CYPH_CONTEXT = """
About Cyph:
- MSc Artificial Intelligence, University of Manchester
- Building Zero OS: a multi-agent AI operating system (this system)
- BCI/EEG research: motor imagery classification using EEG signals
- Long-term vision: Lumineth — a BCI-driven AI consciousness project
- F.R.I.D.A.Y: a voice assistant already built with Claude API
- Interests: AI agents, AI safety, BCIs, entrepreneurship, photography
- Target: AI/ML engineer or AI researcher after MSc
"""


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class BrainstormResult:
    """Structured output from the brainstorm agent."""
    topic: str
    problem_statement: str
    summary: str                          # Full structured output from LLM
    key_features: list[str] = field(default_factory=list)
    mvp_steps: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    model_used: str = ""
    duration_ms: int = 0
    cost_usd: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialise to plain dict for MCP / CEO response."""
        return {
            "topic": self.topic,
            "problem_statement": self.problem_statement,
            "summary": self.summary,
            "key_features": self.key_features,
            "mvp_steps": self.mvp_steps,
            "risks": self.risks,
            "next_actions": self.next_actions,
            "model_used": self.model_used,
            "duration_ms": self.duration_ms,
            "cost_usd": self.cost_usd,
        }


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _build_prompt(topic: str, research_context: str = "") -> str:
    """
    Build the brainstorm prompt.

    Args:
        topic:            The idea or topic to brainstorm.
        research_context: Optional research findings from the bus.

    Returns:
        Formatted prompt string.
    """
    research_block = f"\n\nResearch context (use this to ground your ideas):\n{research_context}" if research_context else ""

    return f"""You are Zero's brainstorm agent — Cyph's personal product manager and idea structurer.

{CYPH_CONTEXT}
{research_block}

Topic to brainstorm: {topic}

Produce a structured breakdown in this exact format:

**PROBLEM / OPPORTUNITY**
One clear sentence defining what problem this solves or opportunity it captures.

**KEY FEATURES** (5–8 bullet points)
The core capabilities this needs. Be specific and technical.

**ARCHITECTURE / APPROACH**
2–3 sentences on how to build it — tech stack choices, data flow, key design decisions.

**MVP STEPS** (numbered, in order)
The minimum viable version — what's the fastest path to something working?

**RISKS & UNKNOWNS**
3–5 honest risks or open questions Cyph should think about.

**IMMEDIATE NEXT ACTIONS** (numbered)
What Cyph should do in the next 48 hours to move this forward.

Be direct, technical, and specific to Cyph's actual stack (Python, FastAPI, LangGraph, ChromaDB, PyTorch).
No generic advice. No fluff."""


# ---------------------------------------------------------------------------
# Parser — extract structured sections from LLM output
# ---------------------------------------------------------------------------

def _parse_sections(text: str) -> dict[str, list[str]]:
    """
    Extract bullet/numbered lists from the LLM response.

    Args:
        text: Raw LLM response text.

    Returns:
        Dict with keys: features, mvp_steps, risks, next_actions.
    """
    import re

    def extract_section(header: str) -> list[str]:
        pattern = rf"\*\*{re.escape(header)}\*\*.*?\n(.*?)(?=\n\*\*|\Z)"
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if not match:
            return []
        block = match.group(1).strip()
        lines = [
            re.sub(r"^[\-\*\d\.\s]+", "", line).strip()
            for line in block.splitlines()
            if line.strip() and not line.strip().startswith("**")
        ]
        return [l for l in lines if l]

    return {
        "features":     extract_section("KEY FEATURES"),
        "mvp_steps":    extract_section("MVP STEPS"),
        "risks":        extract_section("RISKS & UNKNOWNS"),
        "next_actions": extract_section("IMMEDIATE NEXT ACTIONS"),
    }


def _extract_problem(text: str) -> str:
    """Pull the PROBLEM / OPPORTUNITY section from LLM output."""
    import re
    match = re.search(
        r"\*\*PROBLEM / OPPORTUNITY\*\*.*?\n(.+?)(?=\n\*\*|\Z)",
        text, re.DOTALL
    )
    if match:
        return match.group(1).strip().splitlines()[0].strip()
    return ""


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _log_action(topic: str, result: BrainstormResult) -> None:
    """
    Append structured log line to logs/brainstorm.log.

    Args:
        topic:  The brainstorm topic.
        result: The completed BrainstormResult.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / "brainstorm.log"
    entry = (
        f"timestamp={time.strftime('%Y-%m-%dT%H:%M:%S')} "
        f"agent={AGENT_NAME} "
        f"action=brainstorm "
        f"topic={topic!r} "
        f"features={len(result.key_features)} "
        f"model={result.model_used} "
        f"duration_ms={result.duration_ms} "
        f"cost_usd={result.cost_usd:.6f}\n"
    )
    try:
        with log_file.open("a", encoding="utf-8") as f:
            f.write(entry)
    except OSError as exc:
        logger.error(f"[spark] Failed to write log: {exc}")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run(query: str, bus: "ContextBus | None" = None) -> BrainstormResult:
    """
    Execute a brainstorm session on a topic or idea.

    Args:
        query: The idea, concept, or question to brainstorm.
        bus:   Optional shared ContextBus. Reads research summaries if present,
               publishes structured output for other agents (e.g. code agent).

    Returns:
        BrainstormResult with structured breakdown.
    """
    start_ms = int(time.time() * 1000)
    logger.info(f"[spark] Topic: {query!r}")

    # Read research context from bus if research ran first
    research_context = ""
    if bus is not None:
        research_summary = bus.get_from("research", "summary")
        if research_summary:
            research_context = research_summary
            logger.info("[spark] Injecting research context from bus")

    prompt = _build_prompt(query, research_context)
    model_used = ""
    cost_usd = 0.0
    summary = ""

    try:
        response = chat(
            prompt,
            tier="capable",      # brainstorming benefits from the stronger model
            system="You are Zero's brainstorm agent. Be direct, technical, and specific.",
            max_tokens=1500,
        )
        summary = response.text
        cost_usd = response.cost_usd
        model_used = f"{response.provider.value}/{response.model}"
        logger.info(f"[spark] Response generated — {len(summary)} chars")
    except Exception as exc:
        logger.error(f"[spark] LLM error: {exc}")
        summary = f"Brainstorm agent encountered an error: {exc}"

    # Parse structured sections from the response
    sections = _parse_sections(summary)
    problem = _extract_problem(summary)

    duration_ms = int(time.time() * 1000) - start_ms
    result = BrainstormResult(
        topic=query,
        problem_statement=problem,
        summary=summary,
        key_features=sections["features"],
        mvp_steps=sections["mvp_steps"],
        risks=sections["risks"],
        next_actions=sections["next_actions"],
        model_used=model_used,
        duration_ms=duration_ms,
        cost_usd=cost_usd,
    )

    _log_action(query, result)

    # Publish to bus so code agent can pick up the structure
    if bus is not None:
        bus.publish("brainstorm", "summary", summary)
        bus.publish("brainstorm", "mvp_steps", sections["mvp_steps"])
        bus.publish("brainstorm", "next_actions", sections["next_actions"])
        logger.debug(f"[spark] Published to bus: summary + {len(sections['mvp_steps'])} MVP steps")

    logger.info(f"[spark] Done in {duration_ms}ms — cost=${cost_usd:.6f}")
    return result


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "Add a proactive alert system to Zero OS that pushes daily briefings to my phone"
    logging.basicConfig(level=logging.INFO)
    result = run(q)
    print(f"\n{'='*60}")
    print(f"BRAINSTORM: {result.topic}")
    print(f"{'='*60}")
    print(result.summary)
    print(f"\nModel: {result.model_used} | Time: {result.duration_ms}ms | Cost: ${result.cost_usd:.6f}")
