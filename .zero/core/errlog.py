"""
core/errlog.py — Zero OS structured exception log.

Every caught exception that matters gets appended to logs/error_log.jsonl as one
JSON line: {timestamp, agent, action, error, traceback, context}. This gives a
single machine-readable place to diagnose failures after the fact (VANTA's audit
reads outcome strings today; this gives it real tracebacks tomorrow).

Design rules:
    - NEVER raises. A logging failure must not break the caller.
    - Cheap: no LLM, no network — a single appended line.
"""

from __future__ import annotations

import json
import logging
import time
import traceback
from pathlib import Path

logger = logging.getLogger(__name__)

LOG_DIR = Path(__file__).parent.parent / "logs"
ERROR_LOG = LOG_DIR / "error_log.jsonl"

_MAX_TB_CHARS = 4_000
_MAX_CTX_CHARS = 300


def log_error(agent: str, action: str, exc: BaseException, context: str = "") -> None:
    """
    Append one exception record to logs/error_log.jsonl.

    Args:
        agent:   Which component failed (e.g. 'ceo', 'research', 'llm').
        action:  What it was doing (e.g. 'dispatch', 'synthesise', 'chat').
        exc:     The caught exception.
        context: Short free-text context (e.g. the user query) — truncated.
    """
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        record = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "agent": agent,
            "action": action,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": tb[-_MAX_TB_CHARS:],
            "context": (context or "")[:_MAX_CTX_CHARS],
        }
        with ERROR_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as log_exc:  # never propagate a logging failure
        logger.debug(f"[errlog] Failed to write error log: {log_exc}")
