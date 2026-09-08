"""
agents/linkedin/run.py — Zero LinkedIn Agent

Capabilities:
  - View your own profile summary
  - Search jobs by keyword + location
  - Look up a person's public profile
  - Draft a connection request note
  - Draft a cold outreach message
  - Search people by keyword (recruiters, researchers, etc.)

Uses the unofficial linkedin-api library (cookie-based auth).
Install: uv pip install linkedin-api

risk_level: HIGH — any action that sends a message or connection request
requires explicit confirmation from Cyph before executing.

Auth: Set LINKEDIN_EMAIL + LINKEDIN_PASSWORD in .env
      LinkedIn may prompt a CAPTCHA on first login — handle manually once,
      then it caches the session cookies.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.bus import ContextBus

logger = logging.getLogger(__name__)

ZERO_ROOT = Path(__file__).parent.parent.parent


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class LinkedInResult:
    """Structured output from the LinkedIn agent."""

    query: str
    action: str                        # profile / job_search / person_search / draft_connection / draft_message
    summary: str                       # human-readable output
    data: dict[str, Any] = field(default_factory=dict)   # raw structured data
    draft: str = ""                    # drafted message/note (risk=high, never auto-sent)
    model_used: str = "n/a"
    duration_ms: int = 0
    cost_usd: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialise to plain dict for MCP / CEO response."""
        return {
            "query": self.query,
            "action": self.action,
            "summary": self.summary,
            "data": self.data,
            "draft": self.draft,
            "model_used": self.model_used,
            "duration_ms": self.duration_ms,
            "cost_usd": self.cost_usd,
        }


# ---------------------------------------------------------------------------
# LinkedIn client (lazy init — only imports if linkedin-api is installed)
# ---------------------------------------------------------------------------

_client = None

def _get_client():
    """
    Lazy-init the LinkedIn API client using credentials from .env.

    Returns:
        Authenticated Linkedin client or None if credentials/package missing.
    """
    global _client
    if _client is not None:
        return _client

    email = os.getenv("LINKEDIN_EMAIL", "")
    password = os.getenv("LINKEDIN_PASSWORD", "")

    if not email or not password:
        logger.warning("[nexus] LINKEDIN_EMAIL / LINKEDIN_PASSWORD not set in .env")
        return None

    try:
        from linkedin_api import Linkedin
        _client = Linkedin(email, password)
        logger.info("[nexus] Authenticated with LinkedIn")
        return _client
    except ImportError:
        logger.error("[nexus] linkedin-api not installed. Run: uv pip install linkedin-api")
        return None
    except Exception as exc:
        logger.error(f"[nexus] Auth failed: {exc}")
        return None


# ---------------------------------------------------------------------------
# Action helpers
# ---------------------------------------------------------------------------

def _detect_action(query: str) -> str:
    """
    Classify the query into an action type.

    Args:
        query: Raw user input.

    Returns:
        One of: profile / job_search / person_search / draft_connection / draft_message
    """
    q = query.lower()
    if any(x in q for x in ["message", "reach out", "outreach", "cold message"]):
        return "draft_message"
    if any(x in q for x in ["connect", "connection request", "add "]):
        return "draft_connection"
    if any(x in q for x in ["job", "role", "hiring", "vacancy", "opening", "position"]):
        return "job_search"
    if any(x in q for x in ["my profile", "my linkedin", "my page"]):
        return "profile"
    return "person_search"


def _view_profile(client: Any) -> dict[str, Any]:
    """
    Fetch Cyph's own LinkedIn profile summary.

    Args:
        client: Authenticated Linkedin client.

    Returns:
        Dict with name, headline, summary, experience, education.
    """
    try:
        me = client.get_profile()
        return {
            "name": f"{me.get('firstName', '')} {me.get('lastName', '')}".strip(),
            "headline": me.get("headline", ""),
            "summary": me.get("summary", ""),
            "location": me.get("geoLocationName", ""),
            "experience": [
                {
                    "company": e.get("companyName", ""),
                    "title": e.get("title", ""),
                    "duration": e.get("timePeriod", {}),
                }
                for e in me.get("experience", [])[:5]
            ],
            "education": [
                {
                    "school": e.get("schoolName", ""),
                    "degree": e.get("degreeName", ""),
                    "field": e.get("fieldOfStudy", ""),
                }
                for e in me.get("education", [])[:3]
            ],
        }
    except Exception as exc:
        logger.error(f"[nexus] Profile fetch failed: {exc}")
        return {}


def _search_jobs(client: Any, query: str) -> list[dict[str, Any]]:
    """
    Search LinkedIn jobs.

    Args:
        client: Authenticated Linkedin client.
        query: Job search query string.

    Returns:
        List of job dicts (title, company, location, url).
    """
    try:
        # Extract keywords and location from query
        keywords = query
        location = "United Kingdom"  # default to UK for Cyph
        if " in " in query.lower():
            parts = query.lower().split(" in ", 1)
            keywords = parts[0].strip()
            location = parts[1].strip()

        results = client.search_jobs(
            keywords=keywords,
            location_name=location,
            limit=10,
        )
        jobs = []
        for j in results:
            entity = j.get("entityUrn", "")
            job_id = entity.split(":")[-1] if entity else ""
            jobs.append({
                "title": j.get("title", ""),
                "company": j.get("companyName", ""),
                "location": j.get("formattedLocation", ""),
                "listed_at": j.get("listedAt", ""),
                "url": f"https://www.linkedin.com/jobs/view/{job_id}" if job_id else "",
            })
        return jobs
    except Exception as exc:
        logger.error(f"[nexus] Job search failed: {exc}")
        return []


def _search_people(client: Any, query: str) -> list[dict[str, Any]]:
    """
    Search LinkedIn people.

    Args:
        client: Authenticated Linkedin client.
        query: People search query.

    Returns:
        List of person dicts (name, headline, location, profile_url).
    """
    try:
        results = client.search_people(
            keywords=query,
            limit=10,
        )
        people = []
        for p in results:
            public_id = p.get("publicIdentifier", "")
            people.append({
                "name": f"{p.get('firstName', '')} {p.get('lastName', '')}".strip(),
                "headline": p.get("headline", ""),
                "location": p.get("subline", {}).get("text", ""),
                "profile_url": f"https://www.linkedin.com/in/{public_id}" if public_id else "",
                "public_id": public_id,
            })
        return people
    except Exception as exc:
        logger.error(f"[nexus] People search failed: {exc}")
        return []


# ---------------------------------------------------------------------------
# LLM drafting
# ---------------------------------------------------------------------------

def _draft_with_llm(
    action: str,
    query: str,
    context: str,
    bus_context: str = "",
) -> tuple[str, float]:
    """
    Use the LLM to draft a connection request or cold message.

    Args:
        action: "draft_connection" or "draft_message".
        query: Original user query.
        context: Relevant profile / job context.
        bus_context: Shared bus data from other agents.

    Returns:
        Tuple of (draft_text, cost_usd).
    """
    try:
        from core.llm import chat

        if action == "draft_connection":
            system = (
                "You are Zero, writing a LinkedIn connection request note for Cyph — "
                "an MSc AI student at the University of Manchester building an AI OS called Zero. "
                "Write a short, genuine, non-generic note (max 300 chars — LinkedIn limit). "
                "No cringe. No 'I'd love to connect'. Be specific to the person/context."
            )
        else:
            system = (
                "You are Zero, drafting a cold LinkedIn message for Cyph — "
                "MSc AI student at Manchester, building Zero OS (multi-agent AI), "
                "working on BCI/EEG research (Lumineth project). "
                "Write a short, punchy cold outreach message. "
                "Professional but human. Under 150 words. Specific to the recipient."
            )

        prompt = f"Query: {query}\n\nContext about the recipient/job:\n{context}"
        if bus_context:
            prompt += f"\n\nAdditional context from Zero:\n{bus_context}"

        response = chat(prompt, tier="capable", system=system, max_tokens=512)
        return response.text.strip(), response.cost_usd
    except Exception as exc:
        logger.error(f"[nexus] LLM draft failed: {exc}")
        return f"[Draft failed: {exc}]", 0.0


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run(
    query: str = "view my linkedin profile",
    bus: "ContextBus | None" = None,
) -> LinkedInResult:
    """
    Run the LinkedIn agent.

    Args:
        query: User request — job search, profile view, draft message, etc.
        bus: Optional shared context bus.

    Returns:
        LinkedInResult with summary, data, and any drafted text.
    """
    t0 = time.time()
    logger.info(f"[nexus] Query: {query!r}")

    action = _detect_action(query)
    bus_context = bus.as_context_string() if bus else ""

    # Try to get LinkedIn client
    client = _get_client()
    no_client_msg = (
        "LinkedIn not connected. Add LINKEDIN_EMAIL and LINKEDIN_PASSWORD to .env, "
        "then run: uv pip install linkedin-api"
    )

    summary = ""
    data: dict[str, Any] = {}
    draft = ""
    cost = 0.0

    # ── Profile view ─────────────────────────────────────────────────────────
    if action == "profile":
        if client is None:
            summary = no_client_msg
        else:
            data = _view_profile(client)
            if data:
                exp_lines = "\n".join(
                    f"  • {e['title']} at {e['company']}"
                    for e in data.get("experience", [])
                )
                edu_lines = "\n".join(
                    f"  • {e['degree']} in {e['field']} — {e['school']}"
                    for e in data.get("education", [])
                )
                summary = (
                    f"**{data.get('name')}** — {data.get('headline')}\n"
                    f"Location: {data.get('location')}\n\n"
                    f"Experience:\n{exp_lines}\n\n"
                    f"Education:\n{edu_lines}"
                )
            else:
                summary = "Could not fetch profile."

    # ── Job search ────────────────────────────────────────────────────────────
    elif action == "job_search":
        if client is None:
            summary = no_client_msg
        else:
            jobs = _search_jobs(client, query)
            data = {"jobs": jobs}
            if jobs:
                lines = [f"Found {len(jobs)} jobs:\n"]
                for i, j in enumerate(jobs, 1):
                    lines.append(
                        f"{i}. **{j['title']}** at {j['company']} — {j['location']}\n"
                        f"   {j['url']}"
                    )
                summary = "\n".join(lines)
            else:
                summary = "No jobs found for that query."

    # ── Person search ─────────────────────────────────────────────────────────
    elif action == "person_search":
        if client is None:
            summary = no_client_msg
        else:
            people = _search_people(client, query)
            data = {"people": people}
            if people:
                lines = [f"Found {len(people)} people:\n"]
                for i, p in enumerate(people, 1):
                    lines.append(
                        f"{i}. **{p['name']}** — {p['headline']}\n"
                        f"   {p['profile_url']}"
                    )
                summary = "\n".join(lines)
            else:
                summary = "No people found for that query."

    # ── Draft connection request ───────────────────────────────────────────────
    elif action == "draft_connection":
        # Draft even without client — just needs LLM
        context = query  # user provides context in query
        if client:
            # Try to find the person and enrich context
            people = _search_people(client, query)
            if people:
                p = people[0]
                context = (
                    f"Person: {p['name']}\nHeadline: {p['headline']}\n"
                    f"Location: {p['location']}\nURL: {p['profile_url']}"
                )
                data = {"target": p}

        draft, cost = _draft_with_llm(action, query, context, bus_context)
        summary = (
            f"Connection request drafted (NOT sent — requires your approval):\n\n"
            f'"{draft}"\n\n'
            f"⚠️ Zero will never send this without your explicit 'yes'."
        )

    # ── Draft cold message ────────────────────────────────────────────────────
    elif action == "draft_message":
        context = query
        if client:
            people = _search_people(client, query)
            if people:
                p = people[0]
                context = (
                    f"Person: {p['name']}\nHeadline: {p['headline']}\n"
                    f"Location: {p['location']}"
                )
                data = {"target": p}

        draft, cost = _draft_with_llm(action, query, context, bus_context)
        summary = (
            f"LinkedIn message drafted (NOT sent — requires your approval):\n\n"
            f"{draft}\n\n"
            f"⚠️ Zero will never send this without your explicit 'yes'."
        )

    # Publish to bus
    if bus:
        bus.publish("linkedin", "summary", summary)
        bus.publish("linkedin", "action", action)
        if draft:
            bus.publish("linkedin", "draft", draft)

    duration_ms = int((time.time() - t0) * 1000)
    logger.info(f"[nexus] Done ({action}) in {duration_ms}ms")

    return LinkedInResult(
        query=query,
        action=action,
        summary=summary,
        data=data,
        draft=draft,
        model_used="deepseek/sonnet",
        duration_ms=duration_ms,
        cost_usd=cost,
    )


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv
    load_dotenv(ZERO_ROOT / ".env")

    query = " ".join(sys.argv[1:]) or "view my linkedin profile"
    result = run(query)
    print(result.summary)
    if result.draft:
        print(f"\nDraft:\n{result.draft}")
