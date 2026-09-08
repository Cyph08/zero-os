"""
agents/news/run.py — Zero OS News Agent (v0.2.0)

Fetches and summarises:
  1. World news — top important global stories right now
  2. AI/tech news — relevant ML, AI agents, LLM developments
  3. BCI/EEG research — new papers, preprints, datasets

v0.2.0 fix (Vanta): replaced serial advanced-depth research-agent searches with
parallel basic-depth direct Tavily calls. All queries for a given news type now
run concurrently. Typical latency dropped from ~33s to ~3-5s.
"""

from __future__ import annotations

import concurrent.futures
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.llm import chat

if TYPE_CHECKING:
    from core.bus import ContextBus

logger = logging.getLogger(__name__)

AGENT_NAME = "Herald"
AGENT_VERSION = "0.2.0"
LOG_DIR = Path(__file__).parent.parent.parent / "logs"

WORLD_NEWS_QUERIES = [
    "top world news today breaking",
    "important global events today",
]

AI_NEWS_QUERIES = [
    "AI machine learning news today 2026",
    "large language model research news today",
]

BCI_RESEARCH_QUERIES = [
    "EEG BCI motor imagery research 2026 new paper",
    "brain computer interface arxiv preprint 2026",
]

_MAX_PARALLEL = 6


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class NewsResult:
    query: str
    news_type: str
    summary: str
    story_count: int = 0
    model_used: str = ""
    duration_ms: int = 0
    cost_usd: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "news_type": self.news_type,
            "summary": self.summary,
            "story_count": self.story_count,
            "model_used": self.model_used,
            "duration_ms": self.duration_ms,
            "cost_usd": self.cost_usd,
        }


# ---------------------------------------------------------------------------
# News type classifier
# ---------------------------------------------------------------------------

def _detect_news_type(query: str) -> str:
    q = query.lower()
    if any(w in q for w in ["briefing", "morning", "daily", "what's happening", "whats happening"]):
        return "briefing"
    if any(w in q for w in ["bci", "eeg", "motor imagery", "brain", "neuroscience", "paper", "arxiv", "research"]):
        return "bci"
    if any(w in q for w in ["ai", "ml", "llm", "machine learning", "deep learning", "model", "gpt", "claude"]):
        return "ai"
    if any(w in q for w in ["digest", "weekly", "summary"]):
        return "digest"
    return "world"


# ---------------------------------------------------------------------------
# Fast parallel search — basic depth, no raw content, all queries concurrent
# ---------------------------------------------------------------------------

def _search_news(tagged_queries: list[tuple[str, str]], max_results: int = 3) -> list[dict[str, str]]:
    """
    Run news searches in parallel with basic depth.

    Uses search_depth="basic" and include_raw_content=False — appropriate for
    news digests (snippets are sufficient) and ~5-10x faster than the advanced
    search used by the research agent.

    Args:
        tagged_queries: List of (tag, query_string) pairs. Tag is passed through
                        to results so callers can split world vs AI results.
        max_results:    Results per query.

    Returns:
        Flat list of result dicts with keys: tag, title, url, snippet.
    """
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        logger.warning("[herald] TAVILY_API_KEY not set — skipping search")
        return []

    def _one(tag_query: tuple[str, str]) -> list[dict[str, str]]:
        tag, query = tag_query
        try:
            from tavily import TavilyClient
            client = TavilyClient(api_key=api_key)
            resp = client.search(
                query=query,
                max_results=max_results,
                search_depth="basic",
                include_raw_content=False,
            )
            return [
                {
                    "tag": tag,
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "snippet": r.get("content", ""),
                }
                for r in resp.get("results", [])
            ]
        except Exception as exc:
            logger.warning(f"[herald] Search failed for {query!r}: {exc}")
            return []

    all_results: list[dict[str, str]] = []
    workers = min(_MAX_PARALLEL, len(tagged_queries) or 1)
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for hits in pool.map(_one, tagged_queries):
            all_results.extend(hits)
    return all_results


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def _build_world_news_prompt(query: str, results: list[dict]) -> str:
    items = "\n".join(
        f"- {r.get('title', 'Untitled')}: {r.get('snippet', '')}"
        for r in results[:10]
    )
    return (
        f"You are Zero, briefing Cyph (MSc AI student, entrepreneur) on today's world news.\n\n"
        f"Web search results:\n{items}\n\n"
        f"User asked: {query}\n\n"
        f"Write a concise news briefing covering the 3-5 MOST IMPORTANT global stories today. "
        f"For each story: one sentence headline + one sentence context. "
        f"Skip sports, celebrity gossip — focus on geopolitics, science, tech, economics, and anything "
        f"that could affect Cyph's world. Be direct, no filler words. "
        f"End with one line: 'AI/Tech highlight:' covering the most relevant AI or tech development."
    )


def _build_ai_news_prompt(query: str, results: list[dict]) -> str:
    items = "\n".join(
        f"- {r.get('title', 'Untitled')}: {r.get('snippet', '')}"
        for r in results[:10]
    )
    return (
        f"You are Zero, briefing Cyph (MSc AI student building a multi-agent OS) on AI/ML news.\n\n"
        f"Web search results:\n{items}\n\n"
        f"User asked: {query}\n\n"
        f"Summarise the 3-5 most important AI/ML developments. Focus on: new model releases, "
        f"research breakthroughs, agent frameworks, anything relevant to BCI/EEG, "
        f"and any news about Anthropic/Claude or tools Cyph uses. "
        f"One sentence per story. Be concise and specific."
    )


def _build_bci_research_prompt(query: str, results: list[dict]) -> str:
    items = "\n".join(
        f"- {r.get('title', 'Untitled')}: {r.get('snippet', '')}"
        for r in results[:10]
    )
    return (
        f"You are Zero's BCI research agent briefing Cyph (doing motor imagery EEG research for MSc).\n\n"
        f"Web search results:\n{items}\n\n"
        f"User asked: {query}\n\n"
        f"Summarise the most relevant BCI/EEG research updates. Focus on:\n"
        f"- Motor imagery classification improvements\n"
        f"- EEGNet, CSP, or new EEG architectures\n"
        f"- New datasets (especially BCI Competition IV Datasets)\n"
        f"- Any P300, SSVEP, or hybrid BCI breakthroughs\n"
        f"- Brain-computer interface clinical applications\n\n"
        f"For each: title + one sentence summary + why it matters for Cyph's research. "
        f"If nothing truly new, say so honestly."
    )


def _fetch_manchester_weather() -> str:
    """
    Fetch today's Manchester weather from open-meteo (free, no API key).

    Returns:
        One-line weather summary, or "" if unavailable (never blocks the briefing).
    """
    import httpx
    _WMO = {
        0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast",
        45: "fog", 48: "fog", 51: "light drizzle", 53: "drizzle", 55: "heavy drizzle",
        61: "light rain", 63: "rain", 65: "heavy rain", 71: "light snow", 73: "snow",
        75: "heavy snow", 80: "rain showers", 81: "rain showers", 82: "heavy showers",
        95: "thunderstorm", 96: "thunderstorm", 99: "thunderstorm",
    }
    try:
        resp = httpx.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": 53.4808, "longitude": -2.2426,   # Manchester, UK
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "timezone": "Europe/London", "forecast_days": 1,
            },
            timeout=6.0,
        )
        resp.raise_for_status()
        d = resp.json().get("daily", {})
        code = (d.get("weather_code") or [0])[0]
        tmax = (d.get("temperature_2m_max") or ["?"])[0]
        tmin = (d.get("temperature_2m_min") or ["?"])[0]
        rain = (d.get("precipitation_probability_max") or [0])[0]
        return (
            f"Manchester today: {_WMO.get(code, 'mixed')}, "
            f"{tmin} to {tmax} degrees, {rain}% chance of rain."
        )
    except Exception as exc:
        logger.warning(f"[herald] Weather fetch failed (skipping): {exc}")
        return ""


def _todays_schedule() -> str:
    """
    Read today's entries from Chrono's schedule file (memory/schedule.json).

    Returns:
        Newline-joined "HH:MM title" lines for today, or "" if none/unavailable.
    """
    import json as _json
    from datetime import date
    sched_file = Path(__file__).parent.parent.parent / "memory" / "schedule.json"
    try:
        if not sched_file.exists():
            return ""
        entries = _json.loads(sched_file.read_text(encoding="utf-8"))
        today = date.today().isoformat()
        todays = [e for e in entries if e.get("date") == today and not e.get("done")]
        if not todays:
            return ""
        todays.sort(key=lambda e: e.get("time") or "99:99")
        return "\n".join(
            f"- {e.get('time') or 'all day'}: {e.get('title', '')}" for e in todays[:8]
        )
    except Exception as exc:
        logger.warning(f"[herald] Schedule read failed (skipping): {exc}")
        return ""


def _build_morning_briefing_prompt(world_results: list[dict], ai_results: list[dict]) -> str:
    world_text = "\n".join(
        f"- {r.get('title', '')}: {r.get('snippet', '')}"
        for r in world_results[:8]
    )
    ai_text = "\n".join(
        f"- {r.get('title', '')}: {r.get('snippet', '')}"
        for r in ai_results[:5]
    )
    weather = _fetch_manchester_weather()
    schedule = _todays_schedule()
    weather_block = f"WEATHER:\n{weather}\n\n" if weather else ""
    schedule_block = f"CYPH'S SCHEDULE TODAY:\n{schedule}\n\n" if schedule else ""
    return (
        f"You are Zero giving Cyph (MSc AI student, entrepreneur) his morning briefing.\n\n"
        f"{weather_block}"
        f"{schedule_block}"
        f"WORLD NEWS SEARCH RESULTS:\n{world_text}\n\n"
        f"AI/TECH SEARCH RESULTS:\n{ai_text}\n\n"
        f"Write a morning briefing in this structure:\n\n"
        + ("WEATHER — one sentence: today's Manchester weather\n" if weather else "")
        + ("TODAY — up to 3 bullet points: Cyph's schedule items\n" if schedule else "")
        + f"WORLD — 3 bullet points: the most important global stories\n"
        f"AI AND TECH — 2 bullet points: most relevant AI/ML news\n"
        f"ZERO NOTE — one sentence: one thing worth Cyph's attention today\n\n"
        f"Be concise. Each bullet = 1-2 sentences max. No filler phrases like 'Good morning'. "
        f"No markdown — write plain text, spoken out loud."
    )


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _log_action(query: str, result: NewsResult) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / "news.log"
    entry = (
        f"timestamp={time.strftime('%Y-%m-%dT%H:%M:%S')} "
        f"agent={AGENT_NAME} "
        f"version={AGENT_VERSION} "
        f"news_type={result.news_type} "
        f"story_count={result.story_count} "
        f"query={query!r} "
        f"model={result.model_used} "
        f"duration_ms={result.duration_ms} "
        f"cost_usd={result.cost_usd:.6f}\n"
    )
    try:
        with log_file.open("a", encoding="utf-8") as f:
            f.write(entry)
    except OSError as exc:
        logger.error(f"[herald] Failed to write log: {exc}")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run(query: str = "morning briefing", bus: "ContextBus | None" = None) -> NewsResult:
    """
    Fetch and summarise news/research based on the query type.

    Args:
        query: What kind of news Cyph wants.
        bus:   Optional ContextBus — publishes summary for other agents.

    Returns:
        NewsResult with curated news digest.
    """
    start_ms = int(time.time() * 1000)
    logger.info(f"[herald] Query: {query!r}")

    news_type = _detect_news_type(query)
    logger.info(f"[herald] Type: {news_type}")

    summary = ""
    cost_usd = 0.0
    model_used = ""
    story_count = 0

    try:
        if news_type == "briefing":
            # All 4 queries run in parallel — world + AI simultaneously
            tagged = (
                [("world", q) for q in WORLD_NEWS_QUERIES] +
                [("ai", q) for q in AI_NEWS_QUERIES]
            )
            all_results = _search_news(tagged, max_results=3)
            world_results = [r for r in all_results if r["tag"] == "world"]
            ai_results = [r for r in all_results if r["tag"] == "ai"]
            prompt = _build_morning_briefing_prompt(world_results, ai_results)
            story_count = len(all_results)

        elif news_type == "bci":
            tagged = [("bci", q) for q in BCI_RESEARCH_QUERIES]
            results = _search_news(tagged, max_results=4)
            prompt = _build_bci_research_prompt(query, results)
            story_count = len(results)

        elif news_type == "ai":
            tagged = [("ai", q) for q in AI_NEWS_QUERIES]
            results = _search_news(tagged, max_results=5)
            prompt = _build_ai_news_prompt(query, results)
            story_count = len(results)

        elif news_type == "digest":
            # BCI + AI queries all in parallel
            tagged = (
                [("bci", q) for q in BCI_RESEARCH_QUERIES] +
                [("ai", q) for q in AI_NEWS_QUERIES]
            )
            all_results = _search_news(tagged, max_results=4)
            prompt = _build_bci_research_prompt(query, all_results)
            story_count = len(all_results)

        else:  # world
            tagged = [("world", q) for q in WORLD_NEWS_QUERIES]
            results = _search_news(tagged, max_results=5)
            prompt = _build_world_news_prompt(query, results)
            story_count = len(results)

        response = chat(
            prompt,
            tier="fast",
            system="You are Zero's news agent. Be concise, specific, and relevant. No markdown.",
            max_tokens=600,
        )
        summary = response.text
        cost_usd = response.cost_usd
        model_used = f"{response.provider.value}/{response.model}"

    except Exception as exc:
        logger.error(f"[herald] Failed: {exc}")
        summary = f"News fetch failed: {exc}. Please check your connection and try again."

    duration_ms = int(time.time() * 1000) - start_ms
    result = NewsResult(
        query=query,
        news_type=news_type,
        summary=summary,
        story_count=story_count,
        model_used=model_used,
        duration_ms=duration_ms,
        cost_usd=cost_usd,
    )

    _log_action(query, result)

    if bus is not None:
        bus.publish("news", "summary", summary)
        bus.publish("news", "news_type", news_type)
        bus.publish("news", "story_count", story_count)
        logger.debug(f"[herald] Published to bus: {story_count} stories ({news_type})")

    logger.info(f"[herald] Done in {duration_ms}ms — {story_count} sources — cost=${cost_usd:.6f}")
    return result


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    q = " ".join(sys.argv[1:]) or "morning briefing"
    result = run(q)
    print(f"\nNEWS — {result.news_type.upper()}")
    print(result.summary)
    print(f"\nSources: {result.story_count} | Model: {result.model_used} | "
          f"Time: {result.duration_ms}ms | Cost: ${result.cost_usd:.6f}")
