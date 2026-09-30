"""
core/intent.py — Zero OS Intent Classifier + Risk Gate

Classifies incoming commands into risk levels and enforces confirmation
before any high-risk action executes.

Risk levels:
    read  — reads data only, runs immediately
    write — creates/modifies files, informs user then proceeds
    high  — sends emails, submits forms, posts publicly, spends money
             ALWAYS shows full preview and waits for explicit confirmation
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

LOG_DIR = Path(__file__).parent.parent / "logs"


# ---------------------------------------------------------------------------
# Risk level enum
# ---------------------------------------------------------------------------

class RiskLevel(str, Enum):
    READ  = "read"
    WRITE = "write"
    HIGH  = "high"


# ---------------------------------------------------------------------------
# Keyword-based risk signals
# ---------------------------------------------------------------------------

_READ_SIGNALS: list[str] = [
    "what", "who", "when", "where", "why", "how", "search", "find",
    "show", "list", "summarise", "summarize", "tell me", "explain",
    "look up", "research", "read", "check", "get", "fetch", "display",
    "calculate", "convert",
]

_WRITE_SIGNALS: list[str] = [
    "create", "write", "save", "make", "generate", "build", "add",
    "update", "edit", "modify", "change", "rename", "move", "copy",
    "schedule", "note", "draft", "organise", "organize", "delete file",
    "remove file",
]

_HIGH_SIGNALS: list[str] = [
    # Email / messaging actions
    "send", "send email", "send message", "reply all", "forward", "dm",
    "tweet", "post to", "publish",
    # Applications / forms
    "submit", "apply", "apply for", "register", "sign up", "unsubscribe",
    # Financial
    "buy", "purchase", "pay", "transfer", "order", "book",
    # Code / deployment
    "deploy", "push", "merge", "release",
    # Account / data destruction
    "delete account", "wipe", "nuke", "drop database",
    # Social / public
    "upload to", "share publicly",
]

# When a command is phrased as one of these, it's asking ABOUT an action, not
# requesting it — "how do I delete my account" is information, not a deletion.
# These downgrade an otherwise-HIGH match so questions don't trip the gate.
_INFO_QUESTION_PREFIXES: tuple[str, ...] = (
    "how do i", "how do you", "how to", "how can i", "how would i", "how should i",
    "can i", "could i", "should i", "do i need to", "what happens if",
    "what happens when", "what if i", "is it possible", "is it safe to",
    "what's the best way to", "what is the best way to", "what's the difference",
    "explain how", "tell me how", "what does it mean to",
)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class IntentResult:
    """Output from the intent classifier."""
    raw_input: str
    risk_level: RiskLevel
    confidence: float                   # 0.0–1.0 — keyword match strength
    matched_signals: list[str]          # which keywords triggered this level
    requires_confirmation: bool
    confirmation_prompt: str = ""       # shown to user if requires_confirmation

    def is_safe_to_proceed(self) -> bool:
        """
        True if this action can proceed without explicit user confirmation.

        Returns:
            bool: True for read/write, False for high risk.
        """
        return self.risk_level != RiskLevel.HIGH


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------

class IntentClassifier:
    """
    Keyword-based intent classifier with pluggable escalation callbacks.

    Designed to be fast (no model call for classification) and extensible
    (swap in a local 7B model later by overriding classify()).
    """

    def __init__(self) -> None:
        self._confirmation_handler: Callable[[IntentResult], bool] | None = None

    def set_confirmation_handler(
        self, handler: Callable[[IntentResult], bool]
    ) -> None:
        """
        Register a callback that will be called for HIGH risk actions.
        The callback receives the IntentResult and must return True (confirmed)
        or False (cancelled).

        Args:
            handler: Callable that returns True to allow, False to cancel.
        """
        self._confirmation_handler = handler

    def classify(self, user_input: str) -> IntentResult:
        """
        Classify the risk level of a user command using keyword matching.

        HIGH overrides WRITE overrides READ.

        Args:
            user_input: Raw user command string.

        Returns:
            IntentResult with risk level and metadata.
        """
        text = user_input.lower()
        tokens = set(re.findall(r"\b\w+\b", text))

        # Check signals from most-to-least restrictive
        high_matches   = _match_signals(text, tokens, _HIGH_SIGNALS)
        write_matches  = _match_signals(text, tokens, _WRITE_SIGNALS)
        read_matches   = _match_signals(text, tokens, _READ_SIGNALS)

        # An informational question ("how do I send an email?") names a high-risk
        # verb but isn't asking to perform it — don't trip the confirmation gate.
        if high_matches and _is_informational_question(text):
            logger.info(f"[intent] HIGH signals downgraded — informational question: {user_input!r}")
            high_matches = []

        if high_matches:
            risk = RiskLevel.HIGH
            matched = high_matches
            confidence = min(1.0, len(high_matches) / 2)
        elif write_matches:
            risk = RiskLevel.WRITE
            matched = write_matches
            confidence = min(1.0, len(write_matches) / 3)
        else:
            risk = RiskLevel.READ
            matched = read_matches
            confidence = min(1.0, len(read_matches) / 3) if read_matches else 0.5

        requires_conf = (risk == RiskLevel.HIGH)
        conf_prompt = (
            f"⚠️  HIGH-RISK ACTION DETECTED\n"
            f"Command: {user_input}\n"
            f"Matched signals: {', '.join(high_matches)}\n\n"
            f"Type 'yes' to confirm, anything else to cancel."
        ) if requires_conf else ""

        result = IntentResult(
            raw_input=user_input,
            risk_level=risk,
            confidence=confidence,
            matched_signals=matched,
            requires_confirmation=requires_conf,
            confirmation_prompt=conf_prompt,
        )

        _log_classification(result)
        return result

    def gate(self, user_input: str) -> tuple[IntentResult, bool]:
        """
        Classify and enforce the risk gate.

        For HIGH risk: invokes the confirmation handler (or blocks if none set).
        For READ/WRITE: always returns allowed=True.

        Args:
            user_input: Raw user command string.

        Returns:
            Tuple of (IntentResult, allowed: bool).
        """
        result = self.classify(user_input)

        if result.risk_level == RiskLevel.WRITE:
            logger.info(
                f"[intent] WRITE action — informing before proceed: {user_input!r}"
            )
            return result, True

        if result.risk_level == RiskLevel.HIGH:
            if self._confirmation_handler is None:
                logger.warning(
                    "[intent] HIGH risk action with no confirmation handler — blocking"
                )
                return result, False

            allowed = self._confirmation_handler(result)
            if allowed:
                logger.info(f"[intent] HIGH risk confirmed by user: {user_input!r}")
            else:
                logger.info(f"[intent] HIGH risk cancelled by user: {user_input!r}")
            return result, allowed

        # READ — always allowed
        return result, True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_informational_question(text: str) -> bool:
    """
    True if the command is asking *about* an action rather than requesting it.

    Args:
        text: Lowercased user input.

    Returns:
        True when the text opens with an informational question framing.
    """
    stripped = text.strip()
    return any(stripped.startswith(prefix) for prefix in _INFO_QUESTION_PREFIXES)


def _match_signals(text: str, tokens: set[str], signals: list[str]) -> list[str]:
    """
    Find which signals appear in the text (supports multi-word phrases).

    Args:
        text: Lowercased full input string.
        tokens: Set of individual word tokens.
        signals: List of keyword strings to check (single or multi-word).

    Returns:
        List of matched signal strings.
    """
    matched: list[str] = []
    for signal in signals:
        if " " in signal:
            if signal in text:
                matched.append(signal)
        else:
            if signal in tokens:
                matched.append(signal)
    return matched


def _log_classification(result: IntentResult) -> None:
    """
    Append classification result to logs/intent.log.

    Args:
        result: The IntentResult to log.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / "intent.log"
    entry = (
        f"timestamp={time.strftime('%Y-%m-%dT%H:%M:%S')} "
        f"agent=intent "
        f"risk={result.risk_level.value} "
        f"confidence={result.confidence:.2f} "
        f"signals={result.matched_signals} "
        f"requires_confirmation={result.requires_confirmation} "
        f"input={result.raw_input!r}\n"
    )
    try:
        with log_file.open("a", encoding="utf-8") as f:
            f.write(entry)
    except OSError as exc:
        logger.error(f"[intent] Failed to write log: {exc}")


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

classifier = IntentClassifier()


# ---------------------------------------------------------------------------
# Build follow-up detection
# ---------------------------------------------------------------------------

# A request for a whole new artifact says "a/an/another/new <thing>" — "make me a
# snake game". A follow-up names features instead — "create levels with three lives",
# "make it faster", "end the game at 30 points" ("the", not "a"). That article is the
# cheapest reliable signal between the two.
_FRESH_ARTIFACT_RE = re.compile(
    r"\b(?:a|an|another|new)\s+(?:\w+\s+){0,2}"
    r"(?:game|app|application|website|web\s?site|web\s?app|webpage|web\s?page|"
    r"site|page|tool|dashboard|calculator|clone|simulator)\b"
)
_FRESH_PHRASES = ("from scratch", "start over", "start again", "forget that")


def is_build_followup(history: str, query: str) -> bool:
    """
    True when a build happened earlier in this conversation and this request
    modifies it rather than asking for something new.

    Lives here because BOTH the CEO (to route the request to Forge at all) and
    Forge (to edit the real file instead of generating a new one) have to agree.
    They each used to guess from their own keyword list on the current sentence
    alone, so "create levels with three lives each" produced a second, unrelated
    game and "make it faster" reached no agent at all — while the answer was
    sitting in the conversation the whole time.

    Args:
        history: Recent conversation text (hot memory, via the context bus).
        query:   The current request.

    Returns:
        True to treat this as an edit of the last build.
    """
    if not history:
        return False
    if "Zero Tech" not in history and "saved it to" not in history:
        return False
    q = query.lower()
    if "agent" in q:                       # "improve the research agent" is Vanta's job
        return False
    if any(m in q for m in _FRESH_PHRASES) or _FRESH_ARTIFACT_RE.search(q):
        return False
    return True


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    test_commands = [
        "What is the latest research on BCI motor imagery?",
        "Create a new file called notes.txt",
        "Send an email to my supervisor about the project update",
        "Search for Python tutorials on YouTube",
        "Apply for the ML engineer job at DeepMind",
        "Buy a coffee using my saved card",
    ]

    for cmd in test_commands:
        result = classifier.classify(cmd)
        print(
            f"[{result.risk_level.value.upper():5}] "
            f"conf={result.confidence:.2f} "
            f"signals={result.matched_signals} "
            f"→ {cmd!r}"
        )
