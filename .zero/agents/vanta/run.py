"""
agents/vanta/run.py — Zero OS System Evolution Agent

Maintains a live Agent Intelligence Map (AIM) built from every agent's
manifest.json + log file + ceo_actions.jsonl. Four modes:

  implement — reads agent code + health data, generates improved run.py,
              backs up original, writes the fix, logs changelog entry.
              Triggered by "improve / fix / optimize / speed up <agent>".
  diagnose  — targeted brief for one named agent (analysis only, no write).
              Triggered by "why / what's wrong / diagnose / analyze <agent>".
  audit     — rule-based health table across all agents (no LLM cost).
  changelog — append a confirmed change entry to an agent's CHANGELOG.md.

implement is the default action when an agent is named — Vanta acts, not advises.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.llm import chat

if TYPE_CHECKING:
    from core.bus import ContextBus

logger = logging.getLogger(__name__)

AGENT_NAME = "Vanta"
AGENT_VERSION = "0.1.0"
ROOT_DIR = Path(__file__).parent.parent.parent
LOG_DIR = ROOT_DIR / "logs"
AGENTS_DIR = ROOT_DIR / "agents"
CEO_ACTIONS_LOG = LOG_DIR / "ceo_actions.jsonl"

MAX_LOG_LINES = 200
MAX_ACTIONS_LINES = 500
_KV_RE = re.compile(r"(\w+)=('[^']*'|\"[^\"]*\"|\S+)")
_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)

_AUDIT_SIGNALS = (
    "system audit", "audit the system", "audit all agents",
    "system health", "health check", "full audit",
)
_CONFIRM_SIGNALS = (
    "log this change", "log that change", "log the change",
    "record this change", "record that change",
    "update the changelog", "update changelog",
    "write to changelog", "add to changelog",
    "changelog for", "confirm this change",
)

# Signals that mean "actually fix it" vs "just analyse it"
_IMPLEMENT_SIGNALS = (
    "improve", "fix", "optimize", "optimise", "speed up", "make faster",
    "upgrade", "enhance", "rewrite", "update",
)
_DIAGNOSE_ONLY_SIGNALS = (
    "why", "what's wrong", "whats wrong", "analyse", "analyze",
    "diagnose", "explain", "what is wrong", "tell me about",
)

_SLOW_THRESHOLD_MS = 8_000
_MAX_CODE_CHARS = 24_000  # safety cap on code sent to LLM


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class AgentHealth:
    name: str
    display_name: str
    version: str
    risk_level: str
    use_count: int = 0
    avg_duration_ms: float = 0.0
    last_used_at: str = ""
    recent_errors: int = 0
    notes: list[str] = field(default_factory=list)

    def summary_line(self) -> str:
        if self.recent_errors:
            status = f"{self.recent_errors} recent error(s)"
        elif self.use_count == 0:
            status = "unused"
        elif self.notes:
            status = "; ".join(self.notes)
        else:
            status = "healthy"
        uses = f"{self.use_count} logged call(s)"
        avg = f"avg {self.avg_duration_ms:.0f}ms" if self.avg_duration_ms else "no timing data"
        return f"{self.display_name} ({self.name} v{self.version}) — {status} — {uses}, {avg}"


@dataclass
class ImprovementBrief:
    agent_name: str
    agent_version: str
    whats_wrong: str
    proposed_change: str
    acceptance_criteria: list[str]
    risk: str
    effort: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "agent_version": self.agent_version,
            "whats_wrong": self.whats_wrong,
            "proposed_change": self.proposed_change,
            "acceptance_criteria": self.acceptance_criteria,
            "risk": self.risk,
            "effort": self.effort,
        }

    def as_text(self) -> str:
        criteria = "\n".join(f"  - {c}" for c in self.acceptance_criteria) or "  - (none specified)"
        return (
            f"{self.agent_name} v{self.agent_version}\n\n"
            f"What's wrong: {self.whats_wrong}\n\n"
            f"Proposed change: {self.proposed_change}\n\n"
            f"Acceptance criteria:\n{criteria}\n\n"
            f"Risk: {self.risk}\n"
            f"Effort: {self.effort}"
        )


@dataclass
class VantaResult:
    mode: str
    text: str
    data: dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "text": self.text,
            "data": self.data,
            "duration_ms": self.duration_ms,
        }


# ---------------------------------------------------------------------------
# AIM loader
# ---------------------------------------------------------------------------

def _tail_lines(path: Path, max_lines: int) -> list[str]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            return f.readlines()[-max_lines:]
    except OSError:
        return []


def _parse_kv_line(line: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for m in _KV_RE.finditer(line):
        key, val = m.group(1), m.group(2)
        if len(val) >= 2 and val[0] in ("'", '"') and val[-1] == val[0]:
            val = val[1:-1]
        result[key] = val
    return result


def _load_manifests() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not AGENTS_DIR.exists():
        return out
    for path in sorted(AGENTS_DIR.glob("*/manifest.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            data["_dir"] = path.parent
            out.append(data)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(f"[vanta] Could not parse {path}: {exc}")
    return out


def _load_agent_health(manifests: list[dict[str, Any]]) -> dict[str, AgentHealth]:
    error_counts: dict[str, int] = {}
    for raw in _tail_lines(CEO_ACTIONS_LOG, MAX_ACTIONS_LINES):
        raw = raw.strip()
        if not raw:
            continue
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            continue
        outcome = str(entry.get("outcome", "")).lower()
        if "error" in outcome or "failed" in outcome or "cancelled" in outcome:
            for agent_name in entry.get("agents_used", []):
                error_counts[agent_name] = error_counts.get(agent_name, 0) + 1

    health: dict[str, AgentHealth] = {}
    for manifest in manifests:
        name = manifest.get("name", "")
        if not name:
            continue
        display = manifest.get("display_name", name.title())
        version = manifest.get("version", "0.1.0")
        risk_level = manifest.get("risk_level", "read")

        log_path = LOG_DIR / f"{name}.log"
        lines = _tail_lines(log_path, MAX_LOG_LINES)

        durations: list[float] = []
        last_ts = ""
        for line in lines:
            kv = _parse_kv_line(line)
            if "duration_ms" in kv:
                try:
                    durations.append(float(kv["duration_ms"]))
                except ValueError:
                    pass
            if "timestamp" in kv:
                last_ts = kv["timestamp"]

        use_count = len(lines)
        avg_duration = sum(durations) / len(durations) if durations else 0.0

        notes: list[str] = []
        if use_count == 0:
            notes.append("no log activity recorded yet")
        if avg_duration > _SLOW_THRESHOLD_MS:
            notes.append(f"slow — avg {avg_duration:.0f}ms per call")

        health[name] = AgentHealth(
            name=name,
            display_name=display,
            version=version,
            risk_level=risk_level,
            use_count=use_count,
            avg_duration_ms=avg_duration,
            last_used_at=last_ts,
            recent_errors=error_counts.get(name, 0),
            notes=notes,
        )
    return health


# ---------------------------------------------------------------------------
# Mode: audit
# ---------------------------------------------------------------------------

def _run_audit(health: dict[str, AgentHealth]) -> VantaResult:
    def _severity(h: AgentHealth) -> tuple[int, int]:
        if h.recent_errors:
            return (0, -h.recent_errors)
        if any("slow" in n for n in h.notes):
            return (1, 0)
        if h.use_count == 0:
            return (2, 0)
        return (3, 0)

    rows = sorted(health.values(), key=_severity)

    lines = [f"System audit — {len(rows)} agents registered\n"]
    for h in rows:
        lines.append(h.summary_line())

    top = rows[0] if rows else None
    if top and top.recent_errors:
        top_finding = f"Top finding: {top.display_name} has {top.recent_errors} recent error(s) in ceo_actions.jsonl — investigate first."
    elif top and top.notes:
        top_finding = f"Top finding: {top.display_name} — {'; '.join(top.notes)}."
    else:
        top_finding = "Top finding: no issues detected across any agent."

    lines.append(f"\n{top_finding}")

    return VantaResult(
        mode="audit",
        text="\n".join(lines),
        data={
            "agents": [vars(h).copy() for h in rows],
            "top_finding": top_finding,
        },
    )


# ---------------------------------------------------------------------------
# Mode: diagnose
# ---------------------------------------------------------------------------

def _resolve_target_agent(query: str, manifests: list[dict]) -> dict[str, Any] | None:
    text = query.lower()
    for m in manifests:
        for candidate in (m.get("name", ""), m.get("display_name", "")):
            if candidate and re.search(rf"\b{re.escape(candidate.lower())}\b", text):
                return m
    return None


def _run_diagnose(
    query: str,
    target: dict[str, Any],
    health: AgentHealth | None,
) -> VantaResult:
    name = target.get("name", "unknown")
    display = target.get("display_name", name.title())
    version = target.get("version", "0.1.0")
    description = target.get("description", "")
    health_text = health.summary_line() if health else f"{display} — no health data available"
    notes_text = "; ".join(health.notes) if health and health.notes else "none"

    prompt = (
        f"You are Vanta, Zero OS's system-evolution agent. Cyph asked: {query!r}\n\n"
        f"Target agent: {display} ({name}, v{version})\n"
        f"Description: {description}\n"
        f"Health snapshot: {health_text}\n"
        f"Observed issues: {notes_text}\n\n"
        "Write a structured improvement brief grounded in the health data above. "
        "Do not invent problems the data does not support. "
        "Reply with ONLY valid JSON, no markdown, no explanation:\n"
        "{\n"
        '  "whats_wrong": "one to two sentences — root cause grounded in the data",\n'
        '  "proposed_change": "concrete scoped change — Prompt/Architecture/Code/Integration/UI",\n'
        '  "acceptance_criteria": ["2 to 4 testable criteria"],\n'
        '  "risk": "Low | Medium | High — one clause explaining why",\n'
        '  "effort": "Small | Medium | Large — one clause explaining why"\n'
        "}"
    )

    try:
        resp = chat(prompt, tier="capable", max_tokens=600)
        m = _JSON_RE.search(resp.text.strip())
        if not m:
            raise ValueError("no JSON block found in LLM response")
        data = json.loads(m.group(0))
        brief = ImprovementBrief(
            agent_name=name,
            agent_version=version,
            whats_wrong=str(data.get("whats_wrong", "")).strip(),
            proposed_change=str(data.get("proposed_change", "")).strip(),
            acceptance_criteria=_coerce_list(data.get("acceptance_criteria", [])),
            risk=str(data.get("risk", "")).strip(),
            effort=str(data.get("effort", "")).strip(),
        )
    except Exception as exc:
        logger.warning(f"[vanta] Diagnose LLM/parse error for {name}: {exc}")
        brief = ImprovementBrief(
            agent_name=name,
            agent_version=version,
            whats_wrong=f"Could not generate a grounded brief: {exc}",
            proposed_change="",
            acceptance_criteria=[],
            risk="Unknown",
            effort="Unknown",
        )

    return VantaResult(mode="diagnose", text=brief.as_text(), data=brief.to_dict())


# ---------------------------------------------------------------------------
# Mode: implement — reads agent code, generates + writes the fix
# ---------------------------------------------------------------------------

def _run_implement(
    query: str,
    target: dict[str, Any],
    health: AgentHealth | None,
) -> VantaResult:
    name = target.get("name", "unknown")
    display = target.get("display_name", name.title())
    version = target.get("version", "0.1.0")
    agent_dir: Path = target["_dir"]
    run_py = agent_dir / "run.py"

    if not run_py.exists():
        return VantaResult(
            mode="implement",
            text=f"{display} has no run.py at {run_py} — cannot implement a fix.",
        )

    current_code = run_py.read_text(encoding="utf-8")
    if len(current_code) > _MAX_CODE_CHARS:
        current_code = current_code[:_MAX_CODE_CHARS] + "\n# ... (truncated)"

    health_text = health.summary_line() if health else f"{display} — no health data"
    notes_text = "; ".join(health.notes) if health and health.notes else "none"

    prompt = (
        f"You are Vanta, Zero OS's system-evolution agent. Cyph asked: {query!r}\n\n"
        f"Target: {display} ({name}, v{version})\n"
        f"Health: {health_text}\n"
        f"Issues: {notes_text}\n\n"
        f"Current run.py:\n```python\n{current_code}\n```\n\n"
        f"Write an improved version of run.py that fixes the diagnosed issues. "
        f"Preserve all existing public interfaces (run() signature, to_dict(), dataclass fields). "
        f"Keep every existing feature — only change what needs fixing. "
        f"Reply with ONLY the complete improved Python source, no markdown fences, no explanation. "
        f"Start the reply with the module docstring or first import."
    )

    try:
        resp = chat(prompt, tier="capable", max_tokens=4096)
        new_code = resp.text.strip()

        # Strip any accidental markdown fences the LLM added
        if new_code.startswith("```"):
            lines = new_code.splitlines()
            new_code = "\n".join(
                l for l in lines
                if not l.strip().startswith("```")
            ).strip()

        if len(new_code) < 100:
            raise ValueError(f"LLM returned suspiciously short code ({len(new_code)} chars)")

        # Syntax check before writing
        import ast as _ast
        try:
            _ast.parse(new_code)
        except SyntaxError as se:
            raise ValueError(f"Generated code has syntax error: {se}") from se

    except Exception as exc:
        logger.error(f"[vanta] Implement LLM/parse failed for {name}: {exc}")
        return VantaResult(
            mode="implement",
            text=(
                f"I tried to generate an improved {display} but the LLM output wasn't "
                f"usable: {exc}. Run a diagnose query first to review the issue."
            ),
        )

    # Back up original
    bak_path = run_py.with_suffix(".py.bak")
    try:
        bak_path.write_text(current_code, encoding="utf-8")
    except OSError as exc:
        logger.warning(f"[vanta] Could not write backup for {name}: {exc}")

    # Write improved version
    try:
        run_py.write_text(new_code, encoding="utf-8")
    except OSError as exc:
        logger.error(f"[vanta] Failed to write improved {name}/run.py: {exc}")
        return VantaResult(
            mode="implement",
            text=f"Generated the fix but couldn't write it to disk: {exc}",
        )

    # Auto-write changelog
    new_version = _bump_patch(version)
    changelog_path = agent_dir / "CHANGELOG.md"
    existing_cl = changelog_path.read_text(encoding="utf-8") if changelog_path.exists() else f"# Changelog — {display}\n\n"
    cl_entry = (
        f"## {new_version} — {time.strftime('%Y-%m-%d')}\n"
        f"- Vanta implement: {query.strip()}\n"
        f"- Original backed up to run.py.bak\n\n"
    )
    try:
        changelog_path.write_text(existing_cl + cl_entry, encoding="utf-8")
    except OSError:
        pass  # changelog failure doesn't invalidate the fix

    logger.info(f"[vanta] Implemented fix for {name} → {new_version} ({len(new_code)} chars written)")

    return VantaResult(
        mode="implement",
        text=(
            f"Done. Rewrote {display} run.py ({len(current_code)} → {len(new_code)} chars). "
            f"Original backed up to run.py.bak. "
            f"Changelog updated: {display} {new_version}. "
            f"Restart the backend to load the new version."
        ),
        data={
            "agent": name,
            "old_version": version,
            "new_version": new_version,
            "old_chars": len(current_code),
            "new_chars": len(new_code),
            "bak": str(bak_path),
        },
    )


# ---------------------------------------------------------------------------
# Mode: changelog
# ---------------------------------------------------------------------------

def _bump_patch(version: str) -> str:
    parts = version.split(".")
    try:
        parts[-1] = str(int(parts[-1]) + 1)
        return ".".join(parts)
    except (ValueError, IndexError):
        return version


def _extract_change_description(query: str, target: dict[str, Any]) -> str:
    if ":" in query:
        after_colon = query.split(":", 1)[1].strip()
        if after_colon:
            return after_colon
    name = target.get("name", "")
    display = target.get("display_name", "")
    text = query
    for phrase in _CONFIRM_SIGNALS:
        text = re.sub(re.escape(phrase), "", text, flags=re.IGNORECASE)
    for word in (name, display):
        if word:
            text = re.sub(rf"\b{re.escape(word)}\b", "", text, flags=re.IGNORECASE)
    return text.strip(" .,;-") or query.strip()


def _run_changelog(query: str, manifests: list[dict[str, Any]]) -> VantaResult:
    target = _resolve_target_agent(query, manifests)
    if not target:
        return VantaResult(
            mode="changelog",
            text=(
                "I didn't catch which agent that change applies to. "
                "Name it directly, for example: "
                "\"log this change for research: switched to advanced search depth\"."
            ),
        )

    name = target.get("name", "")
    display = target.get("display_name", name.title())
    agent_dir: Path = target["_dir"]
    current_version = target.get("version", "0.1.0")
    new_version = _bump_patch(current_version)
    description = _extract_change_description(query, target)

    changelog_path = agent_dir / "CHANGELOG.md"
    if changelog_path.exists():
        existing = changelog_path.read_text(encoding="utf-8")
    else:
        existing = f"# Changelog — {display}\n\n"

    entry = f"## {new_version} — {time.strftime('%Y-%m-%d')}\n- {description}\n\n"

    try:
        changelog_path.write_text(existing + entry, encoding="utf-8")
        logger.info(f"[vanta] Wrote changelog for {name} → {new_version}: {description}")
    except OSError as exc:
        logger.error(f"[vanta] Failed to write changelog for {name}: {exc}")
        return VantaResult(
            mode="changelog",
            text=f"Couldn't write the changelog for {display}: {exc}",
        )

    return VantaResult(
        mode="changelog",
        text=f"Logged — {display} {new_version}: {description}",
        data={"agent": name, "old_version": current_version, "new_version": new_version, "description": description},
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _coerce_list(val: object) -> list[str]:
    if isinstance(val, list):
        return [str(v) for v in val if v]
    if isinstance(val, str):
        return [val]
    return []


def _log_action(query: str, result: VantaResult) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / "vanta.log"
    entry = (
        f"timestamp={time.strftime('%Y-%m-%dT%H:%M:%S')} "
        f"agent={AGENT_NAME} "
        f"version={AGENT_VERSION} "
        f"action={result.mode} "
        f"query={query!r} "
        f"duration_ms={result.duration_ms}\n"
    )
    try:
        with log_path.open("a", encoding="utf-8") as f:
            f.write(entry)
    except OSError as exc:
        logger.error(f"[vanta] Failed to write log: {exc}")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run(query: str, bus: "ContextBus | None" = None) -> VantaResult:
    """
    Execute a VANTA task.

    Args:
        query: The user's command — audit / diagnose / changelog.
        bus:   Optional ContextBus. Publishes mode + summary when provided.

    Returns:
        VantaResult with mode, text, and optional structured data.
    """
    start_ms = int(time.time() * 1000)
    logger.info(f"[vanta] Query: {query!r}")
    text = query.lower()

    manifests = _load_manifests()
    health = _load_agent_health(manifests)

    if any(sig in text for sig in _AUDIT_SIGNALS):
        result = _run_audit(health)
    elif any(sig in text for sig in _CONFIRM_SIGNALS):
        result = _run_changelog(query, manifests)
    else:
        target = _resolve_target_agent(query, manifests)
        if target:
            # "improve/fix/optimize X" → implement (read + write the fix)
            # "why/diagnose/analyze X" → diagnose only (brief, no write)
            # bare agent name → default to implement (act, don't advise)
            diagnose_only = any(sig in text for sig in _DIAGNOSE_ONLY_SIGNALS)
            if diagnose_only:
                result = _run_diagnose(query, target, health.get(target.get("name", "")))
            else:
                result = _run_implement(query, target, health.get(target.get("name", "")))
        else:
            result = VantaResult(
                mode="info",
                text=(
                    "I can run a system audit ('system audit'), improve a specific agent "
                    "by name ('improve Herald'), diagnose without changing ('why is Herald slow'), "
                    "or log a confirmed change ('log this change for research: ...'). "
                    "Which would you like?"
                ),
            )

    result.duration_ms = int(time.time() * 1000) - start_ms
    _log_action(query, result)

    if bus is not None:
        bus.publish("vanta", "mode", result.mode)
        bus.publish("vanta", "summary", result.text[:300])

    logger.info(f"[vanta] Done in {result.duration_ms}ms — mode={result.mode}")
    return result


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "system audit"
    r = run(q)
    print(f"\nMode: {r.mode}")
    print(r.text)
