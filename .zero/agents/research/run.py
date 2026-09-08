"""
agents/research/run.py — Zero OS Research Agent (Iris)

Searches the web (and academic sources), grounds answers in Cyph's own notes,
and returns a structured research brief. Risk level: read — runs immediately.

v0.2.0 (depth upgrade):
  - Query decomposition: hard queries are split into 2-4 focused sub-queries.
  - Tiered depth: quick (1 search, fast model) vs deep (parallel sub-searches,
    capable model, more sources).
  - Academic mode: scholarly queries also hit arXiv + Semantic Scholar (any topic,
    not just BCI) — real papers with authors + year.
  - Personalization: pulls Cyph's own notes from cold memory and grounds the answer
    in them ("connect this to your Lumineth notes" now actually works).
  - Verified citations + structured `findings` for downstream agents / ATLAS.
"""

from __future__ import annotations

import concurrent.futures
import logging
import os
import time
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
from bs4 import BeautifulSoup
from tavily import TavilyClient

from core.llm import chat
from memory.warm import warm_memory
from memory.cold import cold_memory

if TYPE_CHECKING:
    from core.bus import ContextBus

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
AGENT_NAME = "Iris"
AGENT_VERSION = "0.2.0"
MAX_PAGE_CHARS = 4_000
REQUEST_TIMEOUT = 10
MAX_PARALLEL = 6
QUICK_RESULTS = 5           # web results for a quick query
DEEP_PER_QUERY = 4          # web results per sub-query in deep mode
DEEP_SOURCE_CAP = 10        # total sources kept after merge in deep mode
LOG_DIR = Path(__file__).parent.parent.parent / "logs"

_DEEP_SIGNALS = (
    "compar", "versus", " vs ", "deep", "in depth", "in-depth", "comprehensive",
    "research", "analyse", "analyze", "explain how", "why does", "trade-off",
    "tradeoff", "pros and cons", "state of the art", "survey", "review",
    "landscape", "full picture", "everything about", "break down", "deep dive",
)
_SCHOLARLY_SIGNALS = (
    "paper", "papers", "study", "studies", "arxiv", "preprint", "journal",
    "research on", "literature", "meta-analysis", "publication", "et al",
    "citation", "peer-review", "peer reviewed", "academic", "dataset",
    "benchmark", "state of the art", "sota", "thesis",
)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------
@dataclass
class Source:
    """A single search result with optional fetched content."""
    title: str
    url: str
    snippet: str
    content: str = ""


@dataclass
class ResearchBrief:
    """Structured output returned by this agent."""
    query: str
    summary: str
    sources: list[Source] = field(default_factory=list)
    findings: list[dict[str, str]] = field(default_factory=list)
    depth: str = "quick"
    is_academic: bool = False
    model_used: str = ""
    duration_ms: int = 0
    cost_usd: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialise to plain dict for MCP / CEO response."""
        return {
            "query": self.query,
            "summary": self.summary,
            "sources": [
                {"title": s.title, "url": s.url, "snippet": s.snippet}
                for s in self.sources
            ],
            "findings": self.findings,
            "depth": self.depth,
            "is_academic": self.is_academic,
            "model_used": self.model_used,
            "duration_ms": self.duration_ms,
            "cost_usd": self.cost_usd,
        }


# ---------------------------------------------------------------------------
# Query planning
# ---------------------------------------------------------------------------

def _assess_depth(query: str) -> str:
    """
    Classify a query as 'quick' (single fact) or 'deep' (needs decomposition).

    Args:
        query: Raw user query.

    Returns:
        "quick" | "deep".
    """
    q = query.lower()
    if any(s in q for s in _DEEP_SIGNALS):
        return "deep"
    if len(q.split()) >= 14:
        return "deep"
    return "quick"


def _is_scholarly(query: str) -> bool:
    """Return True if the query is about academic papers/research (any topic)."""
    q = query.lower()
    return any(s in q for s in _SCHOLARLY_SIGNALS)


def _decompose(query: str) -> list[str]:
    """
    Split a complex query into 2-4 focused web-search sub-queries.

    Args:
        query: The research question.

    Returns:
        List of sub-query strings (falls back to [query] on any failure).
    """
    prompt = (
        "Break this research question into 2 to 4 focused web-search sub-queries that "
        "together cover it thoroughly. Reply with ONLY the sub-queries, one per line, "
        "no numbering, no commentary.\n\n"
        f"Question: {query}"
    )
    try:
        resp = chat(prompt, tier="fast", max_tokens=200)
        subs = [ln.strip("-•* \t") for ln in resp.text.splitlines() if ln.strip()]
        subs = [s for s in subs if len(s) > 3][:4]
        return subs or [query]
    except Exception as exc:
        logger.warning(f"[iris] Decompose failed, using single query: {exc}")
        return [query]


# ---------------------------------------------------------------------------
# Search backends
# ---------------------------------------------------------------------------

def _tavily_one(query: str, max_results: int) -> list[Source]:
    """
    Run a single Tavily search. Error-safe — returns [] on failure.

    Args:
        query: Search string.
        max_results: Results to request.

    Returns:
        List of Source objects.
    """
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        logger.warning("[iris] TAVILY_API_KEY not set — skipping web search")
        return []
    for attempt in (1, 2):  # one retry on transient failure
        try:
            client = TavilyClient(api_key=api_key)
            resp = client.search(
                query=query,
                max_results=max_results,
                search_depth="advanced",
                include_raw_content=True,
            )
            return [
                Source(
                    title=r.get("title", ""),
                    url=r.get("url", ""),
                    snippet=r.get("content", ""),
                    content=(r.get("raw_content") or "")[:MAX_PAGE_CHARS],
                )
                for r in resp.get("results", [])
            ]
        except Exception as exc:
            logger.warning(f"[iris] Tavily attempt {attempt} failed for {query!r}: {exc}")
    return []


def _search_web_parallel(queries: list[str], per_query: int) -> list[Source]:
    """
    Run several web searches concurrently and merge the results.

    Args:
        queries: Sub-queries to search.
        per_query: Results per sub-query.

    Returns:
        Flat list of Source objects (not yet deduped).
    """
    results: list[Source] = []
    workers = min(MAX_PARALLEL, max(1, len(queries)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for hits in pool.map(lambda q: _tavily_one(q, per_query), queries):
            results.extend(hits)
    return results


def _search_arxiv(query: str, max_results: int = 4) -> list[Source]:
    """
    Search arXiv for papers on any topic (no API key needed).

    Args:
        query: Topic to search.
        max_results: Max papers.

    Returns:
        List of Source objects tagged [arXiv].
    """
    out: list[Source] = []
    try:
        q = urllib.parse.quote(query)
        url = (
            f"https://export.arxiv.org/api/query?search_query=all:{q}"
            f"&start=0&max_results={max_results}&sortBy=relevance"
        )
        resp = httpx.get(url, timeout=8.0, follow_redirects=True,
                         headers={"User-Agent": "ZeroOS/0.2 research"})
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for entry in soup.find_all("entry")[:max_results]:
            title_el = entry.find("title")
            summary_el = entry.find("summary")
            id_el = entry.find("id")
            pub_el = entry.find("published")
            title = title_el.get_text(strip=True) if title_el else ""
            summary = summary_el.get_text(" ", strip=True) if summary_el else ""
            link = id_el.get_text(strip=True) if id_el else ""
            authors = ", ".join(a.get_text(strip=True) for a in entry.find_all("name")[:4])
            pub = pub_el.get_text(strip=True)[:10] if pub_el else ""
            out.append(Source(
                title=f"[arXiv] {title}",
                url=link,
                snippet=f"{authors} ({pub}). {summary[:400]}",
                content=summary[:MAX_PAGE_CHARS],
            ))
    except Exception as exc:
        logger.warning(f"[iris] arXiv search failed: {exc}")
    return out


def _search_semantic_scholar(query: str, max_results: int = 4) -> list[Source]:
    """
    Search Semantic Scholar for papers on any topic (free, no key, rate-limited).

    Args:
        query: Topic to search.
        max_results: Max papers.

    Returns:
        List of Source objects tagged [Paper].
    """
    out: list[Source] = []
    resp = None
    for attempt in (1, 2):  # free tier is rate-limited; one backoff retry
        try:
            resp = httpx.get(
                "https://api.semanticscholar.org/graph/v1/paper/search",
                params={"query": query, "limit": max_results, "fields": "title,abstract,year,authors,url"},
                timeout=REQUEST_TIMEOUT,
                follow_redirects=True,
                headers={"User-Agent": "ZeroOS/0.2 research"},
            )
            if resp.status_code == 429 and attempt == 1:
                time.sleep(1.5)
                continue
            resp.raise_for_status()
            break
        except Exception as exc:
            logger.warning(f"[iris] Semantic Scholar search failed: {exc}")
            return out
    try:
        for p in (resp.json().get("data", []) if resp is not None else [])[:max_results]:
            authors = ", ".join(a.get("name", "") for a in (p.get("authors") or [])[:4])
            year = p.get("year", "")
            abstract = p.get("abstract") or ""
            out.append(Source(
                title=f"[Paper] {p.get('title', '')}",
                url=p.get("url", ""),
                snippet=f"{authors} ({year}). {abstract[:400]}",
                content=abstract[:MAX_PAGE_CHARS],
            ))
    except Exception as exc:
        logger.warning(f"[iris] Semantic Scholar search failed: {exc}")
    return out


def _dedup(sources: list[Source]) -> list[Source]:
    """Drop duplicate sources by URL (falls back to title)."""
    seen: set[str] = set()
    out: list[Source] = []
    for s in sources:
        key = (s.url or s.title).strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(s)
    return out


# ---------------------------------------------------------------------------
# Personalization — ground answers in Cyph's own notes
# ---------------------------------------------------------------------------

def _personal_context(query: str) -> str:
    """
    Pull Cyph's most relevant stored notes/research from cold memory.

    Args:
        query: Current query.

    Returns:
        A short text block of his prior notes, or "" if none/unavailable.
    """
    try:
        hits = cold_memory.search_all(query, n_results=3)
    except Exception as exc:
        logger.warning(f"[iris] Personal context lookup failed: {exc}")
        return ""
    lines: list[str] = []
    for h in hits[:4]:
        txt = h.get("text") or h.get("document") or h.get("content") or ""
        if txt:
            lines.append("- " + " ".join(txt.split())[:220])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

def _build_prompt(query: str, sources: list[Source], personal: str, deep: bool) -> str:
    """
    Build the synthesis prompt from numbered sources + Cyph's own notes.

    Args:
        query:    Original query.
        sources:  Merged, deduped sources.
        personal: Cyph's prior notes (may be empty).
        deep:     Whether this is a deep query (allows a longer answer).

    Returns:
        Formatted prompt string.
    """
    source_blocks = ""
    for i, src in enumerate(sources, 1):
        body = src.content or src.snippet
        source_blocks += f"\n[{i}] {src.title}\nURL: {src.url}\n{body}\n"

    personal_block = (
        f"\nCyph's own notes / prior research (connect your answer to these when relevant):\n{personal}\n"
        if personal else ""
    )
    length = "3-6 short paragraphs" if deep else "2-4 short paragraphs"

    return f"""You are Zero's research agent (Iris). Answer Cyph's query using the sources below.
{personal_block}
Query: {query}

Sources:
{source_blocks}

CRITICAL RULES:
- Think it through and give the real answer with actual detail — not a summary that you found something.
- Cite sources inline as [1], [2] using the numbers above. Only cite numbers that exist.
- If Cyph's own notes are relevant, tie the findings back to them explicitly.
- Write flowing prose like you're explaining it to a smart friend. ZERO markdown — no asterisks, bullets, headers, or backticks.
- If the sources are weak or conflict, say so briefly and give your best grounded view.
- {length}. Write exactly as you'd say it out loud."""


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _log_action(query: str, brief: ResearchBrief) -> None:
    """Append a structured log line to logs/research.log."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / "research.log"
    entry = (
        f"timestamp={time.strftime('%Y-%m-%dT%H:%M:%S')} "
        f"agent={AGENT_NAME} "
        f"version={AGENT_VERSION} "
        f"action=research "
        f"depth={brief.depth} "
        f"academic={brief.is_academic} "
        f"query={query!r} "
        f"sources={len(brief.sources)} "
        f"model={brief.model_used} "
        f"duration_ms={brief.duration_ms} "
        f"cost_usd={brief.cost_usd:.6f}\n"
    )
    try:
        with log_file.open("a", encoding="utf-8") as f:
            f.write(entry)
    except OSError as exc:
        logger.error(f"[iris] Failed to write log: {exc}")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run(query: str, fetch_pages: bool = True, bus: "ContextBus | None" = None) -> ResearchBrief:
    """
    Execute a research task end-to-end.

    Args:
        query:       The user's research question or topic.
        fetch_pages: Retained for interface compatibility (Tavily returns raw content).
        bus:         Optional shared ContextBus. Publishes summary/sources/findings.

    Returns:
        ResearchBrief with summary, sources, structured findings, and metadata.
    """
    start_ms = int(time.time() * 1000)
    logger.info(f"[iris] Starting research for: {query!r}")

    # 0. Warm cache — avoid re-searching identical queries
    cached = warm_memory.get_cached_research(query)
    if cached:
        logger.info(f"[iris] Cache hit for: {query!r}")
        return ResearchBrief(
            query=cached.get("query", query),
            summary=f"[Cached] {cached.get('summary', '')}",
            sources=[
                Source(title=s.get("title", ""), url=s.get("url", ""), snippet=s.get("snippet", ""))
                for s in cached.get("sources", [])
            ],
            findings=cached.get("findings", []),
            depth=cached.get("depth", "quick"),
            is_academic=cached.get("is_academic", False),
            model_used=cached.get("model_used", "cache"),
            duration_ms=int(time.time() * 1000) - start_ms,
            cost_usd=0.0,
        )

    depth = _assess_depth(query)
    academic = _is_scholarly(query)
    deep = depth == "deep"
    logger.info(f"[iris] depth={depth} academic={academic}")

    # 1. Plan queries
    queries = _decompose(query) if deep else [query]
    logger.info(f"[iris] {len(queries)} sub-query(ies): {queries}")

    # 2. Search — web sub-queries + (optionally) academic APIs, ALL concurrently so a
    #    slow/blocked source (arXiv/S2 can be flaky) never delays the web results.
    per = DEEP_PER_QUERY if deep else QUICK_RESULTS
    tasks: list = [(lambda q=q: _tavily_one(q, per)) for q in queries]
    if academic:
        tasks.append(lambda: _search_arxiv(query))
        tasks.append(lambda: _search_semantic_scholar(query))
    sources = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(MAX_PARALLEL + 2, len(tasks) or 1)) as pool:
        for fut in [pool.submit(t) for t in tasks]:
            try:
                sources.extend(fut.result())
            except Exception as exc:
                logger.warning(f"[iris] search task failed: {exc}")
    sources = _dedup(sources)
    if deep:
        sources = sources[:DEEP_SOURCE_CAP]

    if not sources:
        return ResearchBrief(
            query=query,
            summary="No search results found. Please try a different query or check the connection.",
            depth=depth,
            is_academic=academic,
            duration_ms=int(time.time() * 1000) - start_ms,
        )

    # 3. Personalize + synthesise
    personal = _personal_context(query)
    prompt = _build_prompt(query, sources, personal, deep)

    model_used = ""
    cost_usd = 0.0
    try:
        response = chat(prompt, tier="capable" if deep else "fast", max_tokens=1500 if deep else 1024)
        summary = response.text
        cost_usd = response.cost_usd
        model_used = f"{response.provider.value}/{response.model}"
        logger.info(f"[iris] Synthesised with {model_used} ({len(summary)} chars)")
    except Exception as exc:
        logger.error(f"[iris] LLM synthesis error: {exc}")
        summary = f"Research completed but synthesis failed: {exc}"

    # 4. Structured findings for downstream agents / ATLAS
    findings = [
        {"title": s.title, "url": s.url, "snippet": (s.snippet or "")[:200]}
        for s in sources
    ]

    duration_ms = int(time.time() * 1000) - start_ms
    brief = ResearchBrief(
        query=query,
        summary=summary,
        sources=sources,
        findings=findings,
        depth=depth,
        is_academic=academic,
        model_used=model_used,
        duration_ms=duration_ms,
        cost_usd=cost_usd,
    )

    _log_action(query, brief)

    # 5. Caches + long-term memory
    try:
        warm_memory.cache_research(query, brief.to_dict())
    except Exception as exc:
        logger.warning(f"[iris] Warm cache save failed: {exc}")
    try:
        if brief.summary and not brief.summary.startswith("No search results"):
            cold_memory.store_research(query=query, summary=brief.summary, sources_count=len(brief.sources))
    except Exception as exc:
        logger.warning(f"[iris] Cold memory save failed: {exc}")

    # 6. Publish to the shared bus so other agents (Forge, ATLAS) can use it
    if bus is not None:
        bus.publish("research", "summary", brief.summary)
        bus.publish("research", "sources", [{"title": s.title, "url": s.url} for s in brief.sources])
        bus.publish("research", "findings", brief.findings)
        bus.publish("research", "query", query)
        logger.debug(f"[iris] Published to bus: summary + {len(brief.sources)} sources + findings")

    logger.info(f"[iris] Done in {duration_ms}ms — {len(sources)} sources, cost=${cost_usd:.6f}")
    return brief


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "compare transformer and mamba architectures for long sequences"
    logging.basicConfig(level=logging.INFO)
    result = run(q)
    print(f"\n{'='*60}")
    print(f"Query: {result.query}  [depth={result.depth} academic={result.is_academic}]")
    print(f"{'='*60}")
    print(result.summary)
    print(f"\nSources ({len(result.sources)}):")
    for i, s in enumerate(result.sources, 1):
        print(f"  [{i}] {s.title} — {s.url}")
    print(f"\nModel: {result.model_used} | Time: {result.duration_ms}ms | Cost: ${result.cost_usd:.6f}")
