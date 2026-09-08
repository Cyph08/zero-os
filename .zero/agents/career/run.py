"""
agents/career/run.py — Zero OS Career Agent

Handles CV improvement, job research, cover letter drafting, and career planning.

Risk level: HIGH — any action that submits an application, sends an email,
or posts publicly MUST show a full preview and wait for Cyph's explicit "yes".
This agent NEVER auto-submits anything. It drafts and advises only.
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

AGENT_NAME = "Maven"
AGENT_VERSION = "0.1.0"
LOG_DIR = Path(__file__).parent.parent.parent / "logs"

# Cyph's profile — update this as career progresses
CYPH_PROFILE = """
Name: Cyph (Deepen Khandelwal)
Degree: MSc Artificial Intelligence, University of Manchester
Background: Machine learning, neural networks, EEG/BCI systems, Python, AI research
Projects: BCI/EEG motor imagery classification, F.R.I.D.A.Y voice assistant, Zero OS (multi-agent AI operating system)
Interests: BCIs, AI agents, AI safety, entrepreneurship, photography (Nikon D3400)
Target roles: AI/ML engineer, AI researcher, BCI researcher, AI product roles
"""


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class CareerResult:
    """Structured output from the career agent."""
    query: str
    response: str
    draft: str = ""            # Any drafted document (CV section, cover letter, etc.)
    action_type: str = "advice"  # "advice" | "draft" | "review" | "research"
    requires_confirmation: bool = True   # Always True for this agent
    model_used: str = ""
    duration_ms: int = 0
    cost_usd: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "response": self.response,
            "draft": self.draft,
            "action_type": self.action_type,
            "requires_confirmation": self.requires_confirmation,
            "model_used": self.model_used,
            "duration_ms": self.duration_ms,
            "cost_usd": self.cost_usd,
        }


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def _build_prompt(query: str, action_type: str) -> str:
    """Build the career agent prompt based on action type."""
    base = f"""You are Zero's career agent. You help with CV writing, job applications,
cover letters, interview prep, and career strategy.

About the person you're helping:
{CYPH_PROFILE}

User request: {query}

"""
    if action_type == "draft":
        base += """Draft the requested document. Be professional, specific, and tailored.
Structure your response as:
1. Brief explanation of your approach
2. The full draft clearly marked with --- DRAFT START --- and --- DRAFT END ---
3. One or two suggestions to improve it further

IMPORTANT: End with this exact line:
⚠️ This is a DRAFT only. Zero will NOT submit or send anything without your explicit confirmation."""

    elif action_type == "review":
        base += """Review the provided content and give specific, actionable feedback.
Be direct — identify what's strong and what needs improvement.
Suggest specific rewrites for weak sections."""

    elif action_type == "research":
        base += """Research this career topic and provide practical, specific advice.
Focus on actionable steps Cyph can take right now."""

    else:  # advice
        base += """Give clear, honest career advice. Be direct and practical.
Draw on Cyph's MSc AI background and BCI/agent projects as differentiators."""

    return base


def _detect_action_type(query: str) -> str:
    """Classify the query into an action type."""
    q = query.lower()
    if any(w in q for w in ["write", "draft", "create", "generate", "make me a", "cover letter"]):
        return "draft"
    if any(w in q for w in ["review", "check", "improve", "fix", "feedback on"]):
        return "review"
    if any(w in q for w in ["research", "find", "what companies", "job market", "salary"]):
        return "research"
    return "advice"


def _extract_draft(response_text: str) -> str:
    """Pull out the DRAFT block from the response if present."""
    start = response_text.find("--- DRAFT START ---")
    end = response_text.find("--- DRAFT END ---")
    if start != -1 and end != -1:
        return response_text[start + len("--- DRAFT START ---"):end].strip()
    return ""


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _log_action(query: str, result: CareerResult) -> None:
    """Append structured log line."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / "career.log"
    entry = (
        f"timestamp={time.strftime('%Y-%m-%dT%H:%M:%S')} "
        f"agent={AGENT_NAME} "
        f"action={result.action_type} "
        f"query={query!r} "
        f"model={result.model_used} "
        f"duration_ms={result.duration_ms} "
        f"cost_usd={result.cost_usd:.6f}\n"
    )
    try:
        with log_file.open("a", encoding="utf-8") as f:
            f.write(entry)
    except OSError as exc:
        logger.error(f"[maven] Failed to write log: {exc}")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run(query: str, bus: "ContextBus | None" = None) -> CareerResult:
    """
    Execute a career task.

    Args:
        query: Natural language career request from the user.
        bus:   Optional shared ContextBus. If provided, reads research
               summaries published by the research agent and injects them
               into the career prompt for richer, source-backed responses.
               Also publishes the response and any draft for other agents.

    Returns:
        CareerResult with response, optional draft, and confirmation flag.
    """
    start_ms = int(time.time() * 1000)
    logger.info(f"[maven] Query: {query!r}")

    action_type = _detect_action_type(query)
    # Drafts need the more capable model; advice can use fast
    tier = "capable" if action_type in ("draft", "review") else "fast"

    # Phase 4: if research ran first, inject its findings into the prompt
    research_context = ""
    if bus is not None:
        research_summary = bus.get_from("research", "summary")
        research_sources = bus.get_from("research", "sources")
        if research_summary:
            research_context = f"\n\nRecent research findings (use these to inform your response):\n{research_summary}"
            logger.info(f"[maven] Injecting research bus context into prompt")
        if research_sources:
            src_lines = "\n".join(
                f"  - {s.get('title', '')} — {s.get('url', '')}"
                for s in (research_sources or [])[:3]
            )
            research_context += f"\n\nSources:\n{src_lines}"

    prompt = _build_prompt(query, action_type) + research_context

    model_used = ""
    cost_usd = 0.0
    reply = ""
    draft = ""

    try:
        response = chat(prompt, tier=tier, max_tokens=2048)  # type: ignore[arg-type]
        reply = response.text
        cost_usd = response.cost_usd
        model_used = f"{response.provider.value}/{response.model}"
        draft = _extract_draft(reply)
        logger.info(f"[maven] Action: {action_type} | Model: {model_used}")
    except Exception as exc:
        logger.error(f"[maven] LLM error: {exc}")
        reply = f"Career agent encountered an error: {exc}"

    duration_ms = int(time.time() * 1000) - start_ms
    result = CareerResult(
        query=query,
        response=reply,
        draft=draft,
        action_type=action_type,
        requires_confirmation=True,  # Always — never auto-submit
        model_used=model_used,
        duration_ms=duration_ms,
        cost_usd=cost_usd,
    )
    _log_action(query, result)

    # Phase 4: publish to shared bus
    if bus is not None:
        bus.publish("career", "response", reply)
        bus.publish("career", "action_type", action_type)
        if draft:
            bus.publish("career", "draft", draft)
        logger.debug(f"[maven] Published to bus: response (action_type={action_type})")

    return result


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "What roles should I be targeting with an MSc in AI and BCI experience?"
    result = run(q)
    print(f"\nQuery: {result.query}")
    print(f"Action type: {result.action_type}")
    print(f"\nResponse:\n{result.response}")
    if result.draft:
        print(f"\n--- DRAFT ---\n{result.draft}")
    print(f"\nModel: {result.model_used} | Cost: ${result.cost_usd:.6f} | Time: {result.duration_ms}ms")
