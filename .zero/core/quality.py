"""
core/quality.py — Zero OS Self-Fixing Loop (Build → Grade → Fix)

A quality gate that runs AFTER an answer is produced but BEFORE it reaches Cyph.
The model grades its own draft against a rubric, and if it falls short, it
rewrites it using the critique — looping until it passes or hits a max number
of attempts.

Pattern: build (done elsewhere) → grade → fix → re-grade → ...

This directly targets the recurring problems Cyph flagged:
    - leaking markdown (** , bullets, headers)
    - sounding like a bot instead of a calm, human friend
    - vague / shallow answers that don't actually answer the question
    - meta-commentary ("As an AI...", "I will now...")

Design rules:
    - NEVER raise. Any failure returns the original draft untouched.
    - Off-switch: set env ZERO_SELF_FIX=0 to disable entirely.
    - Bounded: ZERO_SELF_FIX_MAX_ITERS (default 2) caps the rewrite attempts.
    - Cheap: grading uses the 'fast' tier; a fix only happens on a real FAIL.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path

from core.llm import chat

logger = logging.getLogger(__name__)

_QUALITY_LOG = Path(__file__).parent.parent / "logs" / "quality_log.jsonl"


def _log_quality(user_input: str, persona_name: str, info: dict) -> None:
    """
    Append one self-fix outcome to logs/quality_log.jsonl. Never raises.

    Args:
        user_input:   The query that produced the graded draft.
        persona_name: Active persona ('Zero' or 'V').
        info:         The grade_and_fix info dict (passed/iterations/changed/cost).
    """
    try:
        _QUALITY_LOG.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "persona": persona_name,
            "passed": info.get("passed"),
            "iterations": info.get("iterations"),
            "changed": info.get("changed"),
            "cost_usd": round(float(info.get("cost_usd", 0.0)), 6),
            "input": (user_input or "")[:200],
        }
        with _QUALITY_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.debug(f"[quality] quality-log write skipped: {exc}")


def _enabled() -> bool:
    """Self-fixing is on unless explicitly disabled via env."""
    return os.getenv("ZERO_SELF_FIX", "1").strip() not in ("0", "false", "False", "")


def _max_iters() -> int:
    """The ceiling on fix attempts — env-configurable (default 2)."""
    try:
        return max(1, int(os.getenv("ZERO_SELF_FIX_MAX_ITERS", "2")))
    except ValueError:
        return 2


# Words that signal a question wants real depth — these earn the full iteration
# ceiling. Everything else (small talk, quick commands) gets a single pass.
_DEPTH_SIGNALS = (
    "explain", "why", "how", "design", "compare", "analyse", "analyze",
    "thesis", "research", "derive", "prove", "trade-off", "tradeoff",
    "walk me through", "in detail", "deep", "difference between",
)


def assess_depth(user_input: str, complex_hint: bool = False) -> str:
    """
    Classify a request into one of three depth bands.

    This single call drives BOTH the model tier and the self-fix budget so they
    never drift apart:
        small — a simple task or small talk.
        mid   — already complex (multiple agents fired, or a high-risk action)
                but not a deep-knowledge question.
        deep  — a genuine high-knowledge question (depth keyword, or long ≥15w).

    Args:
        user_input:   What Cyph asked.
        complex_hint: Caller signal that the request is already non-trivial.

    Returns:
        'small', 'mid', or 'deep'.
    """
    text = (user_input or "").lower()
    if any(sig in text for sig in _DEPTH_SIGNALS) or len(text.split()) >= 15:
        return "deep"
    if complex_hint:
        return "mid"
    return "small"


def iters_for(level: str) -> int:
    """
    Map a depth level to a self-fix pass count, clamped to the env ceiling.

    deep → full ceiling (max polish), mid → up to 2, small → 1.

    Args:
        level: 'small', 'mid', or 'deep' from assess_depth().

    Returns:
        An iteration count in [1, _max_iters()].
    """
    ceiling = _max_iters()
    if level == "deep":
        return ceiling
    if level == "mid":
        return min(2, ceiling)
    return 1


def recommend_iters(user_input: str, complex_hint: bool = False) -> int:
    """Backward-compatible shortcut: depth assessment → iteration count."""
    return iters_for(assess_depth(user_input, complex_hint))


# Rubric the grader scores every draft against. Rules 1–6 are shared by both
# personas; rule 7 differs — Zero values tightness, V values warmth — so V's
# gentle, caring delivery isn't graded down as "padding" and stripped.
_RUBRIC_COMMON = (
    "1. NO markdown whatsoever — no asterisks, no bold, no bullet points, "
    "no numbered lists, no headers, no backticks, no stray dashes used as bullets.\n"
    "2. Sounds like a real, calm, warm human friend speaking out loud — NOT a bot, "
    "NOT a corporate assistant. Natural, uses contractions, easy to listen to.\n"
    "3. Actually answers what Cyph asked — specific, concrete and useful, "
    "not vague filler or a description of what an answer would contain.\n"
    "4. No meta-commentary — never says things like 'As an AI', 'I will now', "
    "'Here is', or narrates its own process. It just talks.\n"
    "5. Stays consistent with the conversation so far and doesn't contradict it.\n"
    "6. NO filler opener — must not begin with 'Great question', 'Of course', "
    "'Sure', 'Absolutely', 'Certainly', 'I'd be happy to', 'Good question', or any "
    "throat-clearing. It starts straight on the substance, mid-thought.\n"
)

# Zero's tail: tightness.
_RUBRIC_ZERO = _RUBRIC_COMMON + (
    "7. NO padding — no empty intro or outro, no restating the question back, "
    "no needless wind-up. As tight as the content allows; length earned by substance."
)

# V's tail: warmth is required and is NOT a defect. Still bans empty filler so the
# loop can't be gamed into rambling.
_RUBRIC_V = _RUBRIC_COMMON + (
    "7. Warmth is REQUIRED and is NOT padding — gentle framing, noticing how Cyph's "
    "doing, and an unhurried, caring tone are correct, not faults. What's still "
    "banned: empty filler, fake cheer, repeating yourself, and going cold or clipped. "
    "It should read like a caring friend, never a brief."
)


def _rubric_for(persona_name: str) -> str:
    """Pick the grading rubric for the active persona ('V' → warmth, else tight)."""
    return _RUBRIC_V if (persona_name or "").lower() == "v" else _RUBRIC_ZERO


def _grade(user_input: str, draft: str, persona_name: str) -> tuple[bool, str, float]:
    """
    Ask the model to grade a draft against the rubric.

    Returns:
        (passed, critique, cost_usd). On any error, (True, "", 0.0) so the
        caller keeps the original draft.
    """
    prompt = (
        f"You are a strict quality reviewer for {persona_name}, a spoken-voice AI.\n"
        f"Cyph asked: {user_input!r}\n\n"
        f"Draft reply to grade:\n\"\"\"\n{draft}\n\"\"\"\n\n"
        f"Grade the draft against this rubric:\n{_rubric_for(persona_name)}\n\n"
        f"If the draft satisfies every rule, reply with exactly: PASS\n"
        f"If it breaks any rule, reply with: FAIL followed by one short line per "
        f"problem describing exactly what to fix. Be concise."
    )
    try:
        resp = chat(prompt, tier="fast", system="You grade drafts. Be strict and brief.", max_tokens=256)
        text = (resp.text or "").strip()
        passed = text.upper().startswith("PASS") or "PASS" == text.upper()[:4]
        # Treat as pass only when it clearly says PASS and not FAIL
        if "FAIL" in text.upper():
            passed = False
        critique = "" if passed else re.sub(r"^FAIL[:\s]*", "", text, flags=re.IGNORECASE).strip()
        return passed, critique, resp.cost_usd
    except Exception as exc:
        logger.debug(f"[quality] grade skipped (error): {exc}")
        return True, "", 0.0


def _fix(user_input: str, draft: str, critique: str, system_style: str) -> tuple[str, float]:
    """
    Rewrite a draft using the grader's critique, keeping the persona voice.

    Returns:
        (fixed_text, cost_usd). On error, (draft, 0.0).
    """
    prompt = (
        f"Cyph asked: {user_input!r}\n\n"
        f"Your previous reply had problems:\n{critique}\n\n"
        f"Previous reply:\n\"\"\"\n{draft}\n\"\"\"\n\n"
        f"Rewrite it so every problem is fixed. Keep everything that was good. "
        f"Plain spoken words only — absolutely no markdown. Just say it naturally, "
        f"the way you would out loud. Return only the rewritten reply, nothing else."
    )
    try:
        resp = chat(prompt, tier="capable", system=system_style, max_tokens=1024)
        return (resp.text or draft).strip(), resp.cost_usd
    except Exception as exc:
        logger.debug(f"[quality] fix skipped (error): {exc}")
        return draft, 0.0


def grade_and_fix(
    user_input: str,
    draft: str,
    system_style: str,
    persona_name: str = "Zero",
    max_iters: int | None = None,
) -> tuple[str, dict]:
    """
    Run the build→grade→fix loop on a finished draft.

    Args:
        user_input:   What Cyph asked.
        draft:        The freshly produced reply.
        system_style: The active persona's system prompt (so fixes keep voice).
        persona_name: 'Zero' or 'V' — used to frame the grader.
        max_iters:    How many grade→fix passes to allow. When None, uses the
                      env ceiling (_max_iters()). Callers pass a value from
                      recommend_iters() so deep questions get more passes than
                      small tasks. Always clamped to [1, ceiling].

    Returns:
        (final_text, info) where info = {
            "passed": bool, "iterations": int, "cost_usd": float,
            "changed": bool, "enabled": bool
        }
        final_text is always safe to use — the original draft if anything fails.
    """
    info = {"passed": True, "iterations": 0, "cost_usd": 0.0, "changed": False, "enabled": _enabled()}

    if not draft or not draft.strip() or not _enabled():
        return draft, info

    current = draft
    total_cost = 0.0
    ceiling = _max_iters()
    max_iters = ceiling if max_iters is None else max(1, min(max_iters, ceiling))

    for attempt in range(max_iters):
        passed, critique, gcost = _grade(user_input, current, persona_name)
        total_cost += gcost
        if passed:
            info["passed"] = True
            break
        # Failed — try to fix
        fixed, fcost = _fix(user_input, current, critique, system_style)
        total_cost += fcost
        info["iterations"] = attempt + 1
        if fixed and fixed.strip() and fixed.strip() != current.strip():
            current = fixed
            info["changed"] = True
        else:
            # Fix didn't change anything useful — stop looping
            info["passed"] = False
            break
    else:
        # Exhausted attempts without a clean pass
        info["passed"] = False

    info["cost_usd"] = total_cost
    logger.info(
        f"[quality] self-fix done — passed={info['passed']} "
        f"iters={info['iterations']} changed={info['changed']} cost=${total_cost:.6f}"
    )
    _log_quality(user_input, persona_name, info)
    return current, info
