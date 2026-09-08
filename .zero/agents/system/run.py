"""
agents/system/run.py — Zero OS Laptop Access Agent (Helm)

Gives Zero real hands on Cyph's machine: find, read, open, write, move, copy,
delete and run. An LLM turns the spoken request into one JSON action, then plain
stdlib (pathlib / shutil / subprocess / os.startfile) performs it.

Safety model — reversible by default, so no confirmation round-trip is needed:
    - Deletes go to `.zero/trash/<timestamp>_<name>`, never os.remove.
    - Overwrites back the original up to `<name>.bak` first.
    - Windows/Program Files and the venv are protected — refused outright.
    - `run` executes through sandbox.executor (hard timeout + captured output),
      and obviously destructive shell commands are refused unless the SAME
      message carries an explicit confirm phrase.

Risk level: high (it can run commands) — but every file action is undoable.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.llm import chat

if TYPE_CHECKING:
    from core.bus import ContextBus

logger = logging.getLogger(__name__)

AGENT_NAME = "Helm"
AGENT_VERSION = "0.1.0"

ZERO_ROOT = Path(__file__).parent.parent.parent
LOG_DIR = ZERO_ROOT / "logs"
TRASH_DIR = ZERO_ROOT / "trash"

# Never touch these, whatever the LLM decides.
_PROTECTED = (
    Path("C:/Windows"),
    Path("C:/Program Files"),
    Path("C:/Program Files (x86)"),
    Path("C:/ProgramData"),
    ZERO_ROOT.parent / ".venv",
)

# Directories that are never worth walking during a search.
_SKIP_DIRS = {
    "node_modules", ".git", "__pycache__", ".venv", "venv", "AppData",
    "Library", "PackageCache", "site-packages", "$RECYCLE.BIN",
    "System Volume Information", ".next", "dist", "build", ".cache",
}

# Shell commands that can't be undone — refused without an explicit confirm.
_DANGEROUS_CMD = re.compile(
    r"\b(format|del\s+/[fs]|rmdir\s+/s|rd\s+/s|rm\s+-rf|shutdown|diskpart|"
    r"reg\s+delete|takeown|cipher\s+/w|mkfs)\b",
    re.IGNORECASE,
)
_CONFIRM_SIGNALS = ("yes run", "confirm run", "i confirm", "do it anyway", "yes i'm sure", "yes im sure")

_MAX_READ_CHARS = 6_000
_MAX_FIND_HITS = 25
_MAX_WALK_DIRS = 20_000   # ponytail: bounded os.walk, swap for Everything/es.exe if too slow


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

@dataclass
class SystemResult:
    """Structured output of one laptop action."""
    query: str
    response: str
    op: str = ""
    paths: list[str] = field(default_factory=list)
    succeeded: bool = True
    undo_hint: str = ""
    model_used: str = ""
    duration_ms: int = 0
    cost_usd: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "response": self.response,
            "op": self.op,
            "paths": self.paths,
            "succeeded": self.succeeded,
            "undo_hint": self.undo_hint,
            "model_used": self.model_used,
            "duration_ms": self.duration_ms,
            "cost_usd": self.cost_usd,
        }


# ---------------------------------------------------------------------------
# Path safety + lookup
# ---------------------------------------------------------------------------

def _is_protected(p: Path) -> bool:
    """
    True if the path sits inside a protected system location.

    Args:
        p: Path to check.

    Returns:
        True when the path must not be modified.
    """
    try:
        rp = p.resolve()
    except OSError:
        return True
    return any(rp == prot or prot in rp.parents for prot in _PROTECTED)


def _search_roots(query: str) -> list[Path]:
    """
    Pick which folders to walk for a filename search.

    Args:
        query: The user's request (a drive letter in it widens the search).

    Returns:
        Existing root directories, most likely first.
    """
    drive = re.search(r"\b([A-Za-z]):[\\/]", query)
    if drive:
        root = Path(f"{drive.group(1).upper()}:/")
        if root.exists():
            return [root]
    home = Path.home()
    roots = [home / n for n in ("Desktop", "Documents", "Downloads", "Pictures", "Videos")]
    roots += [ZERO_ROOT.parent, home]
    return [r for r in roots if r.exists()]


def _find(pattern: str, query: str = "", limit: int = _MAX_FIND_HITS) -> list[Path]:
    """
    Find files whose name contains `pattern` (case-insensitive).

    Args:
        pattern: Substring or *glob* fragment of the filename.
        query:   Original request, used to widen the search roots.
        limit:   Stop after this many hits.

    Returns:
        Matching paths, best-effort ordered by search root priority.
    """
    needle = pattern.lower().strip("*")
    hits: list[Path] = []
    seen: set[str] = set()
    walked = 0
    for root in _search_roots(query):
        for dirpath, dirnames, filenames in os.walk(root, topdown=True):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")]
            walked += 1
            if walked > _MAX_WALK_DIRS:
                logger.warning("[helm] search truncated at %d dirs", _MAX_WALK_DIRS)
                return hits
            for fn in filenames:
                if needle in fn.lower():
                    p = Path(dirpath) / fn
                    key = str(p).lower()
                    if key not in seen:
                        seen.add(key)
                        hits.append(p)
                        if len(hits) >= limit:
                            return hits
    return hits


def _resolve(raw: str, query: str) -> Path | None:
    """
    Turn whatever the LLM produced into a real existing path.

    Falls back to a filename search when the literal path doesn't exist, so
    "open my dissertation notes" works without Cyph knowing the folder.

    Args:
        raw:   Path or bare filename from the parsed action.
        query: Original request (widens the search).

    Returns:
        An existing Path, or None if nothing matched.
    """
    if not raw:
        return None
    p = Path(os.path.expandvars(raw)).expanduser()
    if p.exists():
        return p
    hits = _find(p.name, query, limit=1)
    return hits[0] if hits else None


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------

def _to_trash(p: Path) -> Path:
    """
    Move a file or folder into the recoverable trash bin.

    Args:
        p: Path to remove.

    Returns:
        Where it now lives inside `.zero/trash`.
    """
    TRASH_DIR.mkdir(parents=True, exist_ok=True)
    dest = TRASH_DIR / f"{int(time.time())}_{p.name}"
    shutil.move(str(p), str(dest))
    return dest


def _op_write(path: Path, content: str, append: bool) -> tuple[str, str]:
    """
    Create, overwrite (with backup) or append to a text file.

    Args:
        path:    Destination file.
        content: Text to write.
        append:  True to append instead of replacing.

    Returns:
        (human summary, undo hint).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    undo = ""
    if path.exists() and not append:
        backup = path.with_suffix(path.suffix + ".bak")
        shutil.copy2(path, backup)
        undo = f"Original backed up to {backup}"
    mode = "a" if append else "w"
    with path.open(mode, encoding="utf-8") as f:
        f.write(content)
    verb = "Appended to" if append else "Wrote"
    return f"{verb} {path} ({len(content)} chars).", undo


def _op_run(command: str, query: str, cwd: str | None) -> tuple[str, bool]:
    """
    Execute a shell command via the sandbox executor.

    Args:
        command: The command line to run.
        query:   Original request — checked for a confirm phrase.
        cwd:     Working directory, defaults to the user's home.

    Returns:
        (output text, succeeded).
    """
    if _DANGEROUS_CMD.search(command):
        low = query.lower()
        if not any(sig in low for sig in _CONFIRM_SIGNALS):
            return (
                f"That command is destructive and I won't run it on a guess:\n  {command}\n"
                f"If you really want it, say: yes run: {command}",
                False,
            )
    from sandbox.executor import execute
    result = execute(command, language="batch", timeout=60, working_dir=cwd)
    return result.as_text(), result.success


# ---------------------------------------------------------------------------
# LLM action parsing
# ---------------------------------------------------------------------------

_PARSE_PROMPT = """You control Cyph's Windows laptop. Turn his request into ONE JSON action.

Request: {query}

Reply with ONLY a JSON object, no prose, no code fence. Shape:
{{"op": "...", "path": "...", "dest": "...", "content": "...", "command": "...", "pattern": "..."}}

Ops:
  find    - locate files. Use "pattern" = the distinctive part of the filename.
  list    - list what's in a folder. "path" = the folder.
  read    - show a file's contents. "path" = the file.
  open    - open a file or app in its default program. "path" = file or app name.
  write   - create/replace a text file. "path" + "content".
  append  - add to the end of a text file. "path" + "content".
  move    - move or rename. "path" + "dest".
  copy    - duplicate. "path" + "dest".
  delete  - remove (goes to a recoverable trash). "path".
  run     - run a shell command. "command".

Only include the keys that op needs. Use full Windows paths when Cyph gave one;
otherwise put the bare filename in "path" and it will be searched for.
Cyph's home is {home}. Zero OS lives at {zero}."""


def _parse_action(query: str) -> tuple[dict[str, Any], str, float]:
    """
    Ask the fast model which single action the request means.

    Args:
        query: The user's request.

    Returns:
        (action dict, model label, cost in USD). Empty dict when unparseable.
    """
    prompt = _PARSE_PROMPT.format(query=query, home=Path.home(), zero=ZERO_ROOT)
    resp = chat(
        prompt,
        tier="fast",
        system="You convert requests into strict JSON actions. Output JSON only.",
        max_tokens=700,
    )
    text = (resp.text or "").strip()
    model = f"{resp.provider.value}/{resp.model}"
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return {}, model, resp.cost_usd
    try:
        return json.loads(match.group(0)), model, resp.cost_usd
    except json.JSONDecodeError as exc:
        logger.warning(f"[helm] Could not parse action JSON: {exc}")
        return {}, model, resp.cost_usd


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _log_action(result: SystemResult) -> None:
    """Append one structured line to logs/system.log."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    entry = (
        f"timestamp={time.strftime('%Y-%m-%dT%H:%M:%S')} "
        f"agent={AGENT_NAME} op={result.op} ok={result.succeeded} "
        f"paths={result.paths[:3]} query={result.query!r} "
        f"model={result.model_used} duration_ms={result.duration_ms} "
        f"cost_usd={result.cost_usd:.6f}\n"
    )
    try:
        with (LOG_DIR / "system.log").open("a", encoding="utf-8") as f:
            f.write(entry)
    except OSError as exc:
        logger.error(f"[helm] Failed to write log: {exc}")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run(query: str, bus: "ContextBus | None" = None) -> SystemResult:
    """
    Perform one laptop action described in natural language.

    Args:
        query: What Cyph wants done ("open my CV", "delete the old snake file").
        bus:   Optional shared ContextBus — the result is published for other agents.

    Returns:
        SystemResult with a spoken-ready summary and the paths touched.
    """
    start_ms = int(time.time() * 1000)
    logger.info(f"[helm] Query: {query!r}")

    action, model, cost = _parse_action(query)
    op = str(action.get("op", "")).lower().strip()
    paths: list[str] = []
    undo = ""
    ok = True

    try:
        if not op:
            response = "I couldn't work out what to do on the laptop from that. Try naming the file or folder."
            ok = False

        elif op == "find":
            pattern = action.get("pattern") or action.get("path") or ""
            hits = _find(str(pattern), query)
            paths = [str(h) for h in hits]
            response = (
                "Found nothing matching that."
                if not hits
                else f"Found {len(hits)}:\n" + "\n".join(f"  {h}" for h in hits)
            )

        elif op == "list":
            target = _resolve(str(action.get("path", "")), query) or Path.home()
            if not target.is_dir():
                target = target.parent
            items = sorted(target.iterdir())[:60]
            paths = [str(target)]
            response = f"{target} contains {len(items)} items:\n" + "\n".join(
                f"  {'[dir] ' if i.is_dir() else ''}{i.name}" for i in items
            )

        elif op == "read":
            target = _resolve(str(action.get("path", "")), query)
            if target is None or not target.is_file():
                response, ok = f"I couldn't find {action.get('path')!r} on the laptop.", False
            else:
                text = target.read_text(encoding="utf-8", errors="replace")
                paths = [str(target)]
                clipped = " (truncated)" if len(text) > _MAX_READ_CHARS else ""
                response = f"{target}{clipped}:\n\n{text[:_MAX_READ_CHARS]}"

        elif op == "open":
            raw = str(action.get("path", ""))
            target = _resolve(raw, query)
            if target is not None:
                os.startfile(str(target))          # noqa: S606 — Windows native open
                paths = [str(target)]
                response = f"Opened {target}."
            else:
                os.startfile(raw)                  # app name, e.g. "notepad"
                response = f"Opened {raw}."

        elif op in ("write", "append"):
            raw = str(action.get("path", ""))
            target = _resolve(raw, query) or Path(os.path.expandvars(raw)).expanduser()
            if _is_protected(target):
                response, ok = f"{target} is in a protected system folder — refusing.", False
            else:
                response, undo = _op_write(target, str(action.get("content", "")), op == "append")
                paths = [str(target)]

        elif op in ("move", "copy"):
            src = _resolve(str(action.get("path", "")), query)
            dest_raw = str(action.get("dest", ""))
            if src is None:
                response, ok = f"I couldn't find {action.get('path')!r}.", False
            elif not dest_raw:
                response, ok = "No destination given.", False
            else:
                dest = Path(os.path.expandvars(dest_raw)).expanduser()
                if dest.is_dir():
                    dest = dest / src.name
                if _is_protected(src) or _is_protected(dest):
                    response, ok = "That touches a protected system folder — refusing.", False
                else:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    if op == "move":
                        shutil.move(str(src), str(dest))
                        undo = f"Move it back with: move {dest} {src}"
                    else:
                        (shutil.copytree if src.is_dir() else shutil.copy2)(str(src), str(dest))
                    paths = [str(src), str(dest)]
                    response = f"{'Moved' if op == 'move' else 'Copied'} {src} to {dest}."

        elif op == "delete":
            target = _resolve(str(action.get("path", "")), query)
            if target is None:
                response, ok = f"I couldn't find {action.get('path')!r}.", False
            elif _is_protected(target):
                response, ok = f"{target} is in a protected system folder — refusing.", False
            else:
                dest = _to_trash(target)
                paths = [str(target)]
                undo = f"Recover it from {dest}"
                response = f"Deleted {target}. It's recoverable in the trash folder."

        elif op == "run":
            command = str(action.get("command", "")).strip()
            if not command:
                response, ok = "No command to run.", False
            else:
                response, ok = _op_run(command, query, action.get("cwd"))

        else:
            response, ok = f"I don't know how to do {op!r} on the laptop yet.", False

    except (OSError, shutil.Error) as exc:
        logger.error(f"[helm] {op} failed: {exc}")
        response, ok = f"That failed: {exc}", False

    result = SystemResult(
        query=query, response=response, op=op, paths=paths, succeeded=ok,
        undo_hint=undo, model_used=model,
        duration_ms=int(time.time() * 1000) - start_ms, cost_usd=cost,
    )
    _log_action(result)

    if bus is not None:
        bus.publish("system", "response", response)
        bus.publish("system", "paths", paths)

    return result


# ---------------------------------------------------------------------------
# Self-check — no LLM, no network. Run: python agents/system/run.py
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)

        # write → read
        msg, undo = _op_write(tmp / "note.txt", "hello cyph", append=False)
        assert (tmp / "note.txt").read_text(encoding="utf-8") == "hello cyph", msg
        assert not undo, "first write should not create a backup"

        # overwrite backs the original up
        _op_write(tmp / "note.txt", "replaced", append=False)
        assert (tmp / "note.txt.bak").read_text(encoding="utf-8") == "hello cyph"
        assert (tmp / "note.txt").read_text(encoding="utf-8") == "replaced"

        # append
        _op_write(tmp / "note.txt", "!", append=True)
        assert (tmp / "note.txt").read_text(encoding="utf-8") == "replaced!"

        # delete is recoverable
        gone = _to_trash(tmp / "note.txt")
        assert not (tmp / "note.txt").exists() and gone.exists()
        gone.unlink()

        # protected paths are refused, normal ones are not
        assert _is_protected(Path("C:/Windows/System32/drivers/etc/hosts"))
        assert not _is_protected(tmp / "anything.txt")

        # destructive commands need an explicit confirm in the same message
        out, ok = _op_run("del /f C:\\stuff", "delete that folder", None)
        assert not ok and "destructive" in out

    print("Helm self-check passed.")
