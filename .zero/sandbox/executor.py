"""
sandbox/executor.py — Zero OS Safe Code Executor

Runs user-provided Python or shell code in an isolated subprocess with a hard
timeout. Used by the Forge (code) agent when the user explicitly asks to run or
test generated code. Never called automatically — always requires an explicit
"run it" / "execute this" trigger in the query.

Design
------
- Each execution spawns a fresh child process so a crash or infinite loop cannot
  touch the Zero backend.
- Code is written to a temp file (not -c argument) so multi-line code, imports,
  and relative path references all work naturally.
- Stdout + stderr are captured and truncated to _MAX_OUTPUT chars per stream so
  a runaway print() loop can't flood memory.
- subprocess.run(timeout=...) enforces the wall-clock limit — the OS kills the
  child process hard if it exceeds it.
- Temp directory is cleaned up automatically (TemporaryDirectory context).
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

_MAX_OUTPUT = 4_000   # chars per stream before truncation
_MAX_CODE   = 16_000  # chars of code we'll execute (safety rail)


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

@dataclass
class ExecutionResult:
    """Output of one sandboxed code execution."""
    language: str
    success: bool
    stdout: str
    stderr: str
    returncode: int
    duration_ms: int
    timed_out: bool = False

    def as_text(self) -> str:
        """Compact human-readable summary for injecting into prompts."""
        status = "✓ Success" if self.success else ("✗ Timed out" if self.timed_out else f"✗ Exit {self.returncode}")
        parts = [f"[{self.language}] {status} in {self.duration_ms}ms"]
        if self.stdout:
            parts.append(f"--- stdout ---\n{self.stdout}")
        if self.stderr:
            parts.append(f"--- stderr ---\n{self.stderr}")
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# Public
# ---------------------------------------------------------------------------

def execute(
    code: str,
    language: str = "python",
    timeout: int = 10,
    working_dir: str | None = None,
) -> ExecutionResult:
    """
    Run code in a sandboxed subprocess with a hard timeout.

    Args:
        code:        Source code to execute.
        language:    "python", "shell", or "batch". Anything else returns an error.
        timeout:     Wall-clock seconds before the child process is killed (default 10).
        working_dir: CWD for the subprocess. Defaults to the user's home directory.

    Returns:
        ExecutionResult with stdout, stderr, returncode, and timing.
    """
    if not code.strip():
        return ExecutionResult(
            language=language, success=False,
            stdout="", stderr="No code provided.",
            returncode=-1, duration_ms=0,
        )
    if len(code) > _MAX_CODE:
        return ExecutionResult(
            language=language, success=False,
            stdout="", stderr=f"Code too long ({len(code)} chars). Max {_MAX_CODE}.",
            returncode=-1, duration_ms=0,
        )

    wdir = working_dir or str(Path.home())
    start = time.time()

    with tempfile.TemporaryDirectory(prefix="zero_exec_") as tmpdir:
        cmd = _build_command(language, code, tmpdir)
        if cmd is None:
            return ExecutionResult(
                language=language, success=False,
                stdout="", stderr=f"Unsupported language: {language!r}",
                returncode=-1, duration_ms=0,
            )

        timed_out = False
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=wdir,
            )
            stdout = proc.stdout[:_MAX_OUTPUT]
            stderr = proc.stderr[:_MAX_OUTPUT]
            returncode = proc.returncode
            success = returncode == 0
        except subprocess.TimeoutExpired:
            timed_out = True
            stdout = ""
            stderr = f"Timed out after {timeout}s — process killed."
            returncode = -1
            success = False

    duration_ms = int((time.time() - start) * 1000)
    return ExecutionResult(
        language=language,
        success=success,
        stdout=stdout,
        stderr=stderr,
        returncode=returncode,
        duration_ms=duration_ms,
        timed_out=timed_out,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_command(language: str, code: str, tmpdir: str) -> list[str] | None:
    """
    Write code to a temp file and return the command list to execute it.

    Args:
        language: Code language identifier.
        code:     Source code.
        tmpdir:   Temp directory to write the file into.

    Returns:
        Command list for subprocess.run, or None for unsupported languages.
    """
    lang = language.lower()
    if lang == "python":
        p = Path(tmpdir) / "code.py"
        p.write_text(code, encoding="utf-8")
        return [sys.executable, str(p)]

    if lang in ("shell", "bash", "sh"):
        p = Path(tmpdir) / "code.sh"
        p.write_text(code, encoding="utf-8")
        if sys.platform == "win32":
            return ["cmd.exe", "/c", "bash", str(p)]
        return ["bash", str(p)]

    if lang in ("batch", "bat", "cmd"):
        p = Path(tmpdir) / "code.bat"
        p.write_text(code, encoding="utf-8")
        return ["cmd.exe", "/c", str(p)]

    return None
