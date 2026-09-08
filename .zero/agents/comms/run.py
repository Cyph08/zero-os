"""
agents/comms/run.py — Zero OS Communications Agent

Handles day-to-day professional messaging for Cyph — different from the
career agent which focuses on job applications. This handles:
  - Emails to university supervisors and professors
  - Cold outreach to researchers or industry contacts
  - Follow-up emails after meetings or applications
  - Thank you emails
  - Networking introductions

RISK LEVEL: HIGH — this agent NEVER sends anything automatically.
It always drafts first, shows a full preview, and waits for Cyph's
explicit "yes" before anything leaves. No exceptions.
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

AGENT_NAME = "Echo"
AGENT_VERSION = "0.1.0"
LOG_DIR = Path(__file__).parent.parent.parent / "logs"

# Context about Cyph for personalised drafts
CYPH_COMMS_CONTEXT = """
About the sender (Cyph / Deepen Khandelwal):
- MSc Artificial Intelligence student, University of Manchester
- Background: machine learning, neural networks, EEG/BCI systems, Python
- Projects: BCI motor imagery classification, Zero OS (multi-agent AI OS), F.R.I.D.A.Y voice assistant
- Interests: AI agents, AI safety, BCIs, entrepreneurship
- Target: AI/ML engineer or researcher after MSc
- Email: deepenkhandelwal10@gmail.com
- Tone preference: professional but not stiff — direct, clear, genuine
"""


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class CommsResult:
    """Structured output from the comms agent."""
    query: str
    email_type: str           # "supervisor", "cold", "followup", "thankyou", "intro", "general"
    draft_subject: str        # Suggested email subject line
    draft_body: str           # Full email body draft
    response: str             # Full LLM response including explanation
    requires_confirmation: bool = True   # Always True — never auto-send
    model_used: str = ""
    duration_ms: int = 0
    cost_usd: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialise to plain dict for MCP / CEO response."""
        return {
            "query": self.query,
            "email_type": self.email_type,
            "draft_subject": self.draft_subject,
            "draft_body": self.draft_body,
            "response": self.response,
            "requires_confirmation": self.requires_confirmation,
            "model_used": self.model_used,
            "duration_ms": self.duration_ms,
            "cost_usd": self.cost_usd,
        }


# ---------------------------------------------------------------------------
# Email type classifier
# ---------------------------------------------------------------------------

def _detect_email_type(query: str) -> str:
    """
    Classify what kind of email Cyph needs.

    Args:
        query: Raw user query.

    Returns:
        One of: "supervisor", "cold", "followup", "thankyou", "intro", "general"
    """
    q = query.lower()
    if any(w in q for w in ["supervisor", "professor", "dr ", "phd", "dissertation", "thesis", "research group"]):
        return "supervisor"
    if any(w in q for w in ["cold", "cold email", "never met", "don't know them", "reach out to"]):
        return "cold"
    if any(w in q for w in ["follow up", "follow-up", "haven't heard", "checking in", "chase"]):
        return "followup"
    if any(w in q for w in ["thank", "thank you", "thanks email", "grateful"]):
        return "thankyou"
    if any(w in q for w in ["introduce", "introduction", "meet", "networking", "connect"]):
        return "intro"
    return "general"


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _build_prompt(query: str, email_type: str, career_context: str = "") -> str:
    """
    Build the comms agent prompt.

    Args:
        query:          The messaging request.
        email_type:     Classified email type.
        career_context: Career context from bus if available.

    Returns:
        Formatted prompt string.
    """
    career_block = (
        f"\n\nCareer context (from career agent):\n{career_context}"
        if career_context else ""
    )

    type_guidance = {
        "supervisor": (
            "This is to a university supervisor or professor. Be professional but personable.\n"
            "Show genuine interest in their work. Be specific — don't be generic.\n"
            "Keep it concise — academics are busy. Under 200 words in the body."
        ),
        "cold": (
            "This is a cold email to someone Cyph hasn't met. First impressions matter.\n"
            "Lead with value — why should they care? Reference their specific work.\n"
            "One clear ask. Under 150 words. No attachments mentioned unless Cyph specified."
        ),
        "followup": (
            "This is a follow-up. Be brief and direct.\n"
            "Remind them of the context in one sentence. Restate the ask clearly.\n"
            "Under 100 words. Don't grovel."
        ),
        "thankyou": (
            "A genuine thank you email. Be specific about what you're grateful for.\n"
            "Add one line about what you're taking forward from the interaction.\n"
            "Under 100 words."
        ),
        "intro": (
            "A professional introduction. Lead with who Cyph is and why he's reaching out.\n"
            "Make a clear connection — shared interests, mutual contact, specific reason.\n"
            "Under 150 words."
        ),
        "general": (
            "Write the email Cyph needs. Be professional, clear, and direct.\n"
            "Match the tone to the context."
        ),
    }

    return f"""You are Zero's communications agent. You draft professional emails for Cyph.

{CYPH_COMMS_CONTEXT}
{career_block}

Request: {query}

Email type guidance:
{type_guidance.get(email_type, type_guidance["general"])}

Respond in this exact structure:

EXPLANATION: [1-2 sentences on your approach and tone choices]

SUBJECT: [email subject line]

--- EMAIL START ---
[Full email body — signed as Deepen / Cyph as appropriate]
--- EMAIL END ---

NOTES: [Optional — any alternatives or things Cyph might want to adjust]

⚠️ DRAFT ONLY — Zero will NOT send this without your explicit confirmation."""


# ---------------------------------------------------------------------------
# Draft parser
# ---------------------------------------------------------------------------

def _parse_draft(response_text: str) -> tuple[str, str]:
    """
    Extract subject line and email body from the LLM response.

    Args:
        response_text: Full LLM response.

    Returns:
        Tuple of (subject, body).
    """
    import re

    subject = ""
    subject_match = re.search(r"SUBJECT:\s*(.+)", response_text)
    if subject_match:
        subject = subject_match.group(1).strip()

    body = ""
    body_match = re.search(
        r"--- EMAIL START ---\s*(.*?)\s*--- EMAIL END ---",
        response_text, re.DOTALL
    )
    if body_match:
        body = body_match.group(1).strip()

    return subject, body


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _log_action(query: str, result: CommsResult) -> None:
    """
    Append structured log line to logs/comms.log.

    Args:
        query:  The comms request.
        result: The completed CommsResult.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / "comms.log"
    entry = (
        f"timestamp={time.strftime('%Y-%m-%dT%H:%M:%S')} "
        f"agent={AGENT_NAME} "
        f"action={result.email_type} "
        f"query={query!r} "
        f"has_draft={bool(result.draft_body)} "
        f"model={result.model_used} "
        f"duration_ms={result.duration_ms} "
        f"cost_usd={result.cost_usd:.6f}\n"
    )
    try:
        with log_file.open("a", encoding="utf-8") as f:
            f.write(entry)
    except OSError as exc:
        logger.error(f"[echo] Failed to write log: {exc}")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run(query: str, bus: "ContextBus | None" = None) -> CommsResult:
    """
    Draft a professional email or message for Cyph.

    NEVER auto-sends. Always returns a draft for review.

    Args:
        query: Natural language description of the email to draft.
        bus:   Optional shared ContextBus. Reads career context if present.
               Publishes the draft for other agents to reference.

    Returns:
        CommsResult with draft subject, body, and full response.
    """
    start_ms = int(time.time() * 1000)
    logger.info(f"[echo] Query: {query!r}")

    email_type = _detect_email_type(query)
    logger.info(f"[echo] Email type: {email_type}")

    # Read career context from bus if available
    career_context = ""
    if bus is not None:
        career_response = bus.get_from("career", "response")
        if career_response:
            career_context = career_response[:500]  # limit to avoid bloating prompt
            logger.info("[echo] Injecting career context from bus")

    prompt = _build_prompt(query, email_type, career_context)
    model_used = ""
    cost_usd = 0.0
    response_text = ""

    try:
        response = chat(
            prompt,
            tier="capable",     # email quality matters — use stronger model
            system="You are Zero's communications agent. Write professional, genuine emails.",
            max_tokens=1024,
        )
        response_text = response.text
        cost_usd = response.cost_usd
        model_used = f"{response.provider.value}/{response.model}"
    except Exception as exc:
        logger.error(f"[echo] LLM error: {exc}")
        response_text = f"Comms agent encountered an error: {exc}"

    subject, body = _parse_draft(response_text)

    duration_ms = int(time.time() * 1000) - start_ms
    result = CommsResult(
        query=query,
        email_type=email_type,
        draft_subject=subject,
        draft_body=body,
        response=response_text,
        requires_confirmation=True,  # ALWAYS
        model_used=model_used,
        duration_ms=duration_ms,
        cost_usd=cost_usd,
    )

    _log_action(query, result)

    # Publish draft to bus — career agent may want to reference it
    if bus is not None:
        bus.publish("comms", "draft_subject", subject)
        bus.publish("comms", "draft_body", body)
        bus.publish("comms", "email_type", email_type)
        logger.debug(f"[echo] Published draft to bus (type={email_type})")

    logger.info(f"[echo] Done in {duration_ms}ms — cost=${cost_usd:.6f}")
    return result


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "Write an email to my MSc supervisor asking to schedule a meeting to discuss my dissertation progress on BCI motor imagery classification"
    logging.basicConfig(level=logging.INFO)
    result = run(q)
    print(f"\n{'='*60}")
    print(f"COMMS — {result.email_type.upper()}")
    print(f"{'='*60}")
    print(result.response)
    print(f"\nModel: {result.model_used} | Time: {result.duration_ms}ms | Cost: ${result.cost_usd:.6f}")
