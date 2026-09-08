#!/usr/bin/env python3
"""
sandbox/_worker.py — Zero OS sandbox subprocess worker.

Spawned by sandbox.py to run an agent's run() function in an isolated process.
Reads a JSON payload from stdin, imports the agent, runs it, writes the JSON
result to stdout. Exit 0 = success; non-zero = failure (stderr has the reason).

This file is intentionally minimal and self-contained — it must not depend on
anything that isn't available in the subprocess's import path.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

# Ensure the .zero root is on the path (inherits venv, so packages are available;
# but the project root itself must be added explicitly for local imports like core/).
_ZERO_ROOT = Path(__file__).parent.parent
if str(_ZERO_ROOT) not in sys.path:
    sys.path.insert(0, str(_ZERO_ROOT))


def main() -> None:
    try:
        raw = sys.stdin.read()
        data = json.loads(raw)
    except (json.JSONDecodeError, EOFError) as exc:
        sys.stderr.write(f"[worker] Bad JSON input: {exc}\n")
        sys.exit(1)

    entry = data.get("entry", "").strip()
    user_input = data.get("user_input", "")

    if not entry:
        sys.stderr.write("[worker] Payload missing 'entry' field\n")
        sys.exit(1)

    if not Path(entry).exists():
        sys.stderr.write(f"[worker] Agent file not found: {entry!r}\n")
        sys.exit(1)

    try:
        spec = importlib.util.spec_from_file_location("agent", entry)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load module spec from {entry!r}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[attr-defined]

        if not hasattr(module, "run"):
            raise AttributeError(f"Agent at {entry!r} has no run() function")

        result = module.run(user_input)

        if hasattr(result, "to_dict"):
            result = result.to_dict()
        elif not isinstance(result, dict):
            result = {"output": str(result)}

        sys.stdout.write(json.dumps(result))
        sys.stdout.flush()
        sys.exit(0)

    except Exception as exc:
        sys.stderr.write(f"[worker] Agent execution error: {exc}\n")
        sys.exit(2)


if __name__ == "__main__":
    main()
