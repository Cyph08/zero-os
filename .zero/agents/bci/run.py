"""
agents/bci/run.py — Zero OS BCI/EEG Specialist Agent

Cyph's dedicated BCI research assistant. Deep specialist knowledge in:
  - EEG signal processing (filtering, artifact removal, epoching)
  - Motor imagery classification (CSP, LDA, deep learning approaches)
  - BCI paradigms: motor imagery, P300, SSVEP, neurofeedback
  - Latest literature and benchmark datasets (BCI Competition IV, BCIC)
  - Lumineth — Cyph's long-term BCI-driven AI consciousness project

This agent has built-in BCI domain knowledge and combines it with
live research from the bus or web search when needed.

Risk level: read — research and analysis only.
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

AGENT_NAME = "Synapse"
AGENT_VERSION = "0.1.0"
LOG_DIR = Path(__file__).parent.parent.parent / "logs"

# Deep BCI domain context baked into every prompt
BCI_DOMAIN_CONTEXT = """
Cyph's BCI research context:
- Project: EEG motor imagery classification (left hand / right hand / feet / tongue)
- Dataset: Likely BCI Competition IV Dataset 2a (4-class, 22 EEG channels, 250Hz)
- Pipeline: bandpass filter (8–30Hz) → epoching → CSP → LDA or CNN
- Tools: MNE-Python, PyTorch, scikit-learn, NumPy
- Key challenges: non-stationarity, subject variability, small datasets, artifact contamination
- Long-term vision: Lumineth — BCI-driven AI consciousness, mapping neural states to AI latent spaces

Key BCI concepts Cyph cares about:
- Event-Related Desynchronisation (ERD) / Synchronisation (ERS) in mu (8–12Hz) and beta (13–30Hz) bands
- Common Spatial Patterns (CSP) for feature extraction
- Transfer learning for cross-subject generalisation
- EEGNet, ShallowConvNet, DeepConvNet architectures
- MOABB benchmark for fair comparison
- P300 speller paradigm (for future Lumineth applications)
"""


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class BCIResult:
    """Structured output from the BCI agent."""
    query: str
    query_type: str        # "technique", "paper", "pipeline", "dataset", "lumineth", "general"
    summary: str
    technical_details: str = ""
    code_example: str = ""
    related_papers: list[str] = field(default_factory=list)
    model_used: str = ""
    duration_ms: int = 0
    cost_usd: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialise to plain dict for MCP / CEO response."""
        return {
            "query": self.query,
            "query_type": self.query_type,
            "summary": self.summary,
            "technical_details": self.technical_details,
            "code_example": self.code_example,
            "related_papers": self.related_papers,
            "model_used": self.model_used,
            "duration_ms": self.duration_ms,
            "cost_usd": self.cost_usd,
        }


# ---------------------------------------------------------------------------
# Query type classifier
# ---------------------------------------------------------------------------

def _detect_query_type(query: str) -> str:
    """
    Classify the BCI query type.

    Args:
        query: Raw user query.

    Returns:
        One of: "technique", "paper", "pipeline", "dataset", "lumineth", "general"
    """
    q = query.lower()
    if "lumineth" in q:
        return "lumineth"
    if any(w in q for w in ["paper", "study", "arxiv", "published", "research on", "what does"]):
        return "paper"
    if any(w in q for w in ["pipeline", "how do i", "implement", "code", "process", "classify"]):
        return "pipeline"
    if any(w in q for w in ["dataset", "data", "bci comp", "moabb", "benchmark", "subjects"]):
        return "dataset"
    if any(w in q for w in ["csp", "eegnet", "filter", "epoch", "erd", "ers", "artifact",
                              "bandpass", "ica", "p300", "ssvep", "mu rhythm"]):
        return "technique"
    return "general"


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _build_prompt(query: str, query_type: str, research_context: str = "") -> str:
    """
    Build the BCI agent prompt.

    Args:
        query:            The BCI question or topic.
        query_type:       Classified query type.
        research_context: Research findings from bus if available.

    Returns:
        Formatted prompt string.
    """
    research_block = (
        f"\n\nWeb research findings (use these as primary sources):\n{research_context}"
        if research_context else ""
    )

    base = f"""You are Zero's BCI specialist agent. You have deep expertise in EEG/BCI systems.

{BCI_DOMAIN_CONTEXT}
{research_block}

Query: {query}

"""

    instructions = {
        "technique": (
            "Explain this BCI technique deeply.\n"
            "- Mathematical formulation if relevant\n"
            "- How it fits into Cyph's motor imagery pipeline\n"
            "- Python/MNE/PyTorch code snippet showing how to use it\n"
            "- Common pitfalls and how to avoid them\n"
            "- What to try if it doesn't work well"
        ),
        "paper": (
            "Summarise this BCI paper for Cyph.\n"
            "**PROBLEM** — what gap does this address?\n"
            "**METHOD** — key technical contribution, be specific\n"
            "**RESULTS** — accuracy on which dataset? vs what baseline?\n"
            "**LIMITATIONS** — what doesn't transfer to Cyph's setup?\n"
            "**WHAT TO STEAL** — one or two ideas Cyph could directly apply"
        ),
        "pipeline": (
            "Explain how to implement this BCI pipeline step by step.\n"
            "Write working MNE + scikit-learn/PyTorch code.\n"
            "Use BCI Competition IV Dataset 2a as the reference dataset.\n"
            "Include: loading data, preprocessing, feature extraction, classification, evaluation."
        ),
        "dataset": (
            "Describe this BCI dataset and how to use it.\n"
            "Include: number of subjects, channels, sampling rate, paradigm, classes.\n"
            "How to load it with MNE-Python or MOABB.\n"
            "Known quirks, artefact issues, or preprocessing tips specific to this dataset."
        ),
        "lumineth": (
            "Help Cyph think about this aspect of Lumineth — his BCI-driven AI consciousness project.\n"
            "Lumineth's vision: map neural states (EEG) to AI latent spaces to create a continuous\n"
            "bridge between biological and artificial intelligence.\n\n"
            "Be ambitious but grounded. What's technically feasible now vs. in 5 years?\n"
            "What's the research pathway? What would a meaningful MVP look like?"
        ),
        "general": (
            "Answer this BCI question with deep technical accuracy.\n"
            "Ground your answer in Cyph's specific setup and research context.\n"
            "Suggest concrete next steps where relevant."
        ),
    }

    return base + instructions.get(query_type, instructions["general"])


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _log_action(query: str, result: BCIResult) -> None:
    """
    Append structured log line to logs/bci.log.

    Args:
        query:  The BCI query.
        result: The completed BCIResult.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / "bci.log"
    entry = (
        f"timestamp={time.strftime('%Y-%m-%dT%H:%M:%S')} "
        f"agent={AGENT_NAME} "
        f"action={result.query_type} "
        f"query={query!r} "
        f"model={result.model_used} "
        f"duration_ms={result.duration_ms} "
        f"cost_usd={result.cost_usd:.6f}\n"
    )
    try:
        with log_file.open("a", encoding="utf-8") as f:
            f.write(entry)
    except OSError as exc:
        logger.error(f"[synapse] Failed to write log: {exc}")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run(query: str, bus: "ContextBus | None" = None) -> BCIResult:
    """
    Execute a BCI research or technical task.

    Args:
        query: BCI question, technique, paper, or Lumineth topic.
        bus:   Optional shared ContextBus. Reads research summaries if present,
               publishes BCI findings for the study agent to use.

    Returns:
        BCIResult with summary, technical details, and optional code example.
    """
    start_ms = int(time.time() * 1000)
    logger.info(f"[synapse] Query: {query!r}")

    query_type = _detect_query_type(query)
    logger.info(f"[synapse] Type: {query_type}")

    # Read research context from bus if research ran first
    research_context = ""
    if bus is not None:
        research_summary = bus.get_from("research", "summary")
        if research_summary:
            research_context = research_summary
            logger.info("[synapse] Injecting research context from bus")

    prompt = _build_prompt(query, query_type, research_context)
    model_used = ""
    cost_usd = 0.0
    response_text = ""

    try:
        response = chat(
            prompt,
            tier="capable",
            system="You are Zero's BCI specialist. Be technically precise and deeply knowledgeable.",
            max_tokens=2000,
        )
        response_text = response.text
        cost_usd = response.cost_usd
        model_used = f"{response.provider.value}/{response.model}"
    except Exception as exc:
        logger.error(f"[synapse] LLM error: {exc}")
        response_text = f"BCI agent encountered an error: {exc}"

    duration_ms = int(time.time() * 1000) - start_ms
    result = BCIResult(
        query=query,
        query_type=query_type,
        summary=response_text,
        model_used=model_used,
        duration_ms=duration_ms,
        cost_usd=cost_usd,
    )

    _log_action(query, result)

    # Publish to bus for study agent and CEO synthesis
    if bus is not None:
        bus.publish("bci", "findings", response_text)
        bus.publish("bci", "query_type", query_type)
        logger.debug("[synapse] Published findings to bus")

    logger.info(f"[synapse] Done in {duration_ms}ms — cost=${cost_usd:.6f}")
    return result


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "Explain Common Spatial Patterns (CSP) and how to implement it for 4-class motor imagery with MNE-Python"
    logging.basicConfig(level=logging.INFO)
    result = run(q)
    print(f"\n{'='*60}")
    print(f"BCI — {result.query_type.upper()}")
    print(f"{'='*60}")
    print(result.summary)
    print(f"\nModel: {result.model_used} | Time: {result.duration_ms}ms | Cost: ${result.cost_usd:.6f}")
