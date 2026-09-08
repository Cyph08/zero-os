"""
agents/study/run.py — Zero OS Study Agent

Cyph's MSc AI coursework assistant. Handles:
  - Explaining AI/ML concepts at the right depth (peer-level, not beginner)
  - Summarising research papers into key takeaways
  - Creating structured revision plans for exams
  - Building Q&A flashcard sets for a topic
  - Answering questions about lectures and assignments

Grounded in Cyph's MSc AI curriculum at University of Manchester.
Risk level: read — generates study material only, no side effects.
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

AGENT_NAME = "Sage"
AGENT_VERSION = "0.1.0"
LOG_DIR = Path(__file__).parent.parent.parent / "logs"

CYPH_ACADEMIC_CONTEXT = """
About Cyph's studies:
- MSc Artificial Intelligence, University of Manchester
- Core areas: machine learning, deep learning, neural networks, NLP, computer vision
- Research focus: EEG/BCI motor imagery classification, signal processing
- Background: strong Python, comfortable with PyTorch, knows the maths (linear algebra, probability, calculus)
- Treat Cyph as a peer engineer, not a student — skip basics, go deep on the interesting parts
"""


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class StudyResult:
    """Structured output from the study agent."""
    query: str
    study_type: str            # "explain" | "paper" | "revision" | "flashcards" | "qa"
    summary: str               # Full response
    flashcards: list[dict[str, str]] = field(default_factory=list)  # [{q, a}, ...]
    key_points: list[str] = field(default_factory=list)
    model_used: str = ""
    duration_ms: int = 0
    cost_usd: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialise to plain dict for MCP / CEO response."""
        return {
            "query": self.query,
            "study_type": self.study_type,
            "summary": self.summary,
            "flashcards": self.flashcards,
            "key_points": self.key_points,
            "model_used": self.model_used,
            "duration_ms": self.duration_ms,
            "cost_usd": self.cost_usd,
        }


# ---------------------------------------------------------------------------
# Type detector
# ---------------------------------------------------------------------------

def _detect_study_type(query: str) -> str:
    """
    Classify the study request type.

    Args:
        query: Raw user query.

    Returns:
        One of: "explain", "paper", "revision", "flashcards", "qa"
    """
    q = query.lower()
    if any(w in q for w in ["flashcard", "quiz", "test me", "q&a", "questions on"]):
        return "flashcards"
    if any(w in q for w in ["paper", "summarise", "summarize", "abstract", "arxiv", "read this"]):
        return "paper"
    if any(w in q for w in ["revision", "revision plan", "exam", "study plan", "prepare for"]):
        return "revision"
    if any(w in q for w in ["?", "what is", "how does", "explain", "teach me", "difference between"]):
        return "explain"
    return "qa"


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _build_prompt(query: str, study_type: str, research_context: str = "") -> str:
    """
    Build the study agent prompt.

    Args:
        query:            The study question or topic.
        study_type:       Classified study type.
        research_context: Optional research findings from the bus.

    Returns:
        Formatted prompt string.
    """
    research_block = (
        f"\n\nAdditional context from web research:\n{research_context}"
        if research_context else ""
    )

    base = f"""You are Zero's study agent — Cyph's MSc AI coursework assistant.

{CYPH_ACADEMIC_CONTEXT}
{research_block}

Query: {query}

"""
    instructions = {
        "explain": (
            "Explain this concept clearly and deeply.\n"
            "- Start with the core intuition in 2–3 sentences\n"
            "- Then go into the mathematical/technical details\n"
            "- Give a concrete example (code snippet in Python/PyTorch if relevant)\n"
            "- End with: why this matters, what it connects to, and common exam gotchas\n"
            "- Cyph knows the basics — skip definitions of things like 'gradient descent' unless specifically asked"
        ),
        "paper": (
            "Summarise this paper for Cyph.\n"
            "Structure:\n"
            "**PROBLEM** — what gap does this paper address?\n"
            "**METHOD** — the key technical contribution (be specific, include equations if central)\n"
            "**RESULTS** — what did they achieve? Key numbers.\n"
            "**LIMITATIONS** — what doesn't it solve?\n"
            "**RELEVANCE TO CYPH** — how does this connect to BCI, motor imagery, or Zero OS?"
        ),
        "revision": (
            "Create a structured revision plan.\n"
            "Include:\n"
            "1. Topic breakdown — what subtopics need covering and in what order\n"
            "2. Time estimate per subtopic\n"
            "3. Key things to understand deeply vs things to just know exist\n"
            "4. Likely exam question types\n"
            "5. Resources to use (specific, not generic 'read a textbook')"
        ),
        "flashcards": (
            "Generate 10 Q&A flashcards on this topic.\n"
            "Format each as:\n"
            "Q: [question that would appear on an exam or viva]\n"
            "A: [concise, precise answer — include the key formula or insight]\n\n"
            "Mix conceptual questions with mathematical ones. Make them challenging."
        ),
        "qa": (
            "Answer Cyph's question directly and accurately.\n"
            "Be specific. If there's maths, show it. If there's code, write it.\n"
            "Point out common misconceptions if relevant."
        ),
    }

    return base + instructions.get(study_type, instructions["qa"])


# ---------------------------------------------------------------------------
# Flashcard parser
# ---------------------------------------------------------------------------

def _parse_flashcards(text: str) -> list[dict[str, str]]:
    """
    Extract Q&A flashcard pairs from the LLM response.

    Args:
        text: Raw LLM response text.

    Returns:
        List of {"q": "...", "a": "..."} dicts.
    """
    import re
    cards = []
    pattern = re.compile(r"Q:\s*(.+?)\nA:\s*(.+?)(?=\nQ:|\Z)", re.DOTALL)
    for match in pattern.finditer(text):
        cards.append({
            "q": match.group(1).strip(),
            "a": match.group(2).strip(),
        })
    return cards


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _log_action(query: str, result: StudyResult) -> None:
    """
    Append structured log line to logs/study.log.

    Args:
        query:  The study query.
        result: The completed StudyResult.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / "study.log"
    entry = (
        f"timestamp={time.strftime('%Y-%m-%dT%H:%M:%S')} "
        f"agent={AGENT_NAME} "
        f"action={result.study_type} "
        f"query={query!r} "
        f"flashcards={len(result.flashcards)} "
        f"model={result.model_used} "
        f"duration_ms={result.duration_ms} "
        f"cost_usd={result.cost_usd:.6f}\n"
    )
    try:
        with log_file.open("a", encoding="utf-8") as f:
            f.write(entry)
    except OSError as exc:
        logger.error(f"[sage] Failed to write log: {exc}")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run(query: str, bus: "ContextBus | None" = None) -> StudyResult:
    """
    Execute a study task.

    Args:
        query: The study question, topic, or paper to process.
        bus:   Optional shared ContextBus. Reads research findings if present,
               publishes explanations and flashcards for other agents.

    Returns:
        StudyResult with full response and optional flashcards.
    """
    start_ms = int(time.time() * 1000)
    logger.info(f"[sage] Query: {query!r}")

    study_type = _detect_study_type(query)
    logger.info(f"[sage] Type: {study_type}")

    # Read research context from bus if available
    research_context = ""
    if bus is not None:
        research_summary = bus.get_from("research", "summary")
        if research_summary:
            research_context = research_summary
            logger.info("[sage] Injecting research context from bus")

    prompt = _build_prompt(query, study_type, research_context)
    model_used = ""
    cost_usd = 0.0
    response_text = ""

    try:
        response = chat(
            prompt,
            tier="capable",
            system="You are Zero's study agent. Be precise, technical, and deeply helpful.",
            max_tokens=2000,
        )
        response_text = response.text
        cost_usd = response.cost_usd
        model_used = f"{response.provider.value}/{response.model}"
    except Exception as exc:
        logger.error(f"[sage] LLM error: {exc}")
        response_text = f"Study agent encountered an error: {exc}"

    flashcards = _parse_flashcards(response_text) if study_type == "flashcards" else []

    duration_ms = int(time.time() * 1000) - start_ms
    result = StudyResult(
        query=query,
        study_type=study_type,
        summary=response_text,
        flashcards=flashcards,
        model_used=model_used,
        duration_ms=duration_ms,
        cost_usd=cost_usd,
    )

    _log_action(query, result)

    # Publish to bus
    if bus is not None:
        bus.publish("study", "explanation", response_text)
        if flashcards:
            bus.publish("study", "flashcards", flashcards)
        logger.debug(f"[sage] Published to bus: explanation + {len(flashcards)} flashcards")

    logger.info(f"[sage] Done in {duration_ms}ms — cost=${cost_usd:.6f}")
    return result


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "Explain the attention mechanism in transformers — I know the basics, go deep"
    logging.basicConfig(level=logging.INFO)
    result = run(q)
    print(f"\n{'='*60}")
    print(f"STUDY — {result.study_type.upper()}: {result.query}")
    print(f"{'='*60}")
    print(result.summary)
    if result.flashcards:
        print(f"\n--- {len(result.flashcards)} FLASHCARDS ---")
        for i, card in enumerate(result.flashcards, 1):
            print(f"\n[{i}] Q: {card['q']}\n    A: {card['a']}")
    print(f"\nModel: {result.model_used} | Time: {result.duration_ms}ms | Cost: ${result.cost_usd:.6f}")
