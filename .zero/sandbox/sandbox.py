"""
sandbox/sandbox.py — Zero OS Agent Subprocess Sandbox

Runs an agent's run() function in an isolated child process instead of the
CEO's main process. Prevents a buggy or slow agent from crashing the backend,
enforces a hard timeout, and keeps agent side-effects contained.

Borrowed from Hermes Agent's subprocess isolation design.

Activation
----------
Set ``ZERO_SANDBOX_AGENTS=true`` in .env (default: false — opt-in).
When disabled, CEO falls back to the standard in-process dispatch.

Protocol
--------
Spawns ``sandbox/_worker.py`` as a child process. Data flows:
  stdin  → JSON {entry, user_input}
  stdout ← JSON agent result dict
  stderr ← debug/error text (logged, not raised unless non-zero exit)
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_WORKER = Path(__file__).parent / "_worker.py"
_DEFAULT_TIMEOUT = 90   # seconds — covers LLM calls which can take ~25s each


# ---------------------------------------------------------------------------
# Public
# ---------------------------------------------------------------------------

def is_enabled() -> bool:
    """
    Return True when ZERO_SANDBOX_AGENTS is set to a truthy value.

    Check this before calling run_agent_sandboxed() to keep the hot path
    cost-free when sandboxing is disabled (the common default).
    """
    return os.environ.get("ZERO_SANDBOX_AGENTS", "").lower() in ("1", "true", "yes")


def run_agent_sandboxed(
    entry: str,
    user_input: str,
    timeout: int = _DEFAULT_TIMEOUT,
) -> dict:
    """
    Run an agent's run() function in an isolated subprocess.

    The child process inherits the current environment (venv, .env vars, PATH)
    so all packages and API keys are available — isolation is about crash
    containment and timeout enforcement, not permission restriction.

    Args:
        entry:      Absolute path to the agent's run.py file.
        user_input: Natural language query to pass to agent.run().
        timeout:    Wall-clock seconds before the process is killed.

    Returns:
        Agent result dict (same shape as the in-process dispatch returns).

    Raises:
        RuntimeError: If the subprocess times out, crashes, or returns bad output.
    """
    if not _WORKER.exists():
        raise RuntimeError(f"Sandbox worker not found at {_WORKER}")

    payload = json.dumps({"entry": str(entry), "user_input": user_input})

    try:
        proc = subprocess.run(
            [sys.executable, str(_WORKER)],
            input=payload,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(Path(__file__).parent.parent),   # .zero root
            env=os.environ.copy(),
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"Agent sandbox timed out after {timeout}s "
            f"(entry={Path(entry).name!r})"
        )

    if proc.stderr.strip():
        logger.debug(f"[sandbox] worker stderr: {proc.stderr.strip()[:500]}")

    if proc.returncode != 0:
        raise RuntimeError(
            f"Agent sandbox exited {proc.returncode} "
            f"(entry={Path(entry).name!r}): {proc.stderr.strip()[:300]}"
        )

    stdout = proc.stdout.strip()
    if not stdout:
        raise RuntimeError(
            f"Agent sandbox returned no output (entry={Path(entry).name!r})"
        )

    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Agent sandbox output is not valid JSON: {exc} — got: {stdout[:200]}"
        )
