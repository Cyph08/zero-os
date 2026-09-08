"""
agents/code/run.py — Zero OS Code Agent

Cyph's AI pair programmer. Can:
  - Write new Python functions/classes/modules from a description
  - Review and critique existing code (paste it in or give a file path)
  - Debug errors — paste the traceback and the relevant code
  - Explain what a piece of code does
  - Refactor code for readability, performance, or style

Specialised in Cyph's stack: Python 3.11+, FastAPI, LangGraph, PyTorch,
ChromaDB, OpenCV, and the Zero OS codebase structure.

Risk level: write — may produce code to save to files. Always shows
what it's about to write before doing it. Never auto-executes code.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.llm import chat

if TYPE_CHECKING:
    from core.bus import ContextBus

logger = logging.getLogger(__name__)

AGENT_NAME = "Forge"
AGENT_VERSION = "0.2.0"
LOG_DIR = Path(__file__).parent.parent.parent / "logs"
ZERO_ROOT = Path(__file__).parent.parent.parent
# Where built web apps / sites / games are saved and opened from.
# ZERO_ROOT is K:\Zero\.zero, so .parent is K:\Zero → K:\Zero\Zero Tech.
TECH_DIR = ZERO_ROOT.parent / "Zero Tech"

# Words that signal "build me a runnable web thing" rather than a Python snippet.
_BUILD_VERBS = ("make", "build", "create", "generate", "design", "develop", "give me")
_WEB_SIGNALS = (
    "app", "website", "web app", "webpage", "web page", "site", "game",
    "landing page", "dashboard", "ui", "frontend", "front-end", "html page", "web page",
)

# Cyph's tech stack context for the code agent
STACK_CONTEXT = """
Cyph's tech stack:
- Language: Python 3.11+ (type hints required on everything)
- Backend: FastAPI + uvicorn
- Agent orchestration: LangGraph (preferred)
- LLM routing: core/llm.py — chat(prompt, tier="fast"|"capable")
- Memory: ChromaDB (cold), Redis (warm), in-memory dict (hot)
- Voice: openai-whisper (STT), edge-tts (TTS), pvporcupine (wake word)
- Vision: OpenCV + Pillow, mss for screen capture
- Package manager: uv (always uv pip install, never pip install)
- Code style: pathlib.Path not os.path, f-strings, specific error handling, no silent pass
- Project root: K:\\Astra\\.zero\\
"""


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class CodeResult:
    """Structured output from the code agent."""
    query: str
    action_type: str           # "write" | "review" | "debug" | "explain" | "refactor"
    response: str              # Full LLM response (explanation + code)
    code_block: str = ""       # Extracted code block if present
    filename_hint: str = ""    # Suggested filename if writing new code
    saved_path: str = ""       # Absolute path if the artifact was saved to disk
    opened: bool = False       # True if it was opened in the browser
    model_used: str = ""
    duration_ms: int = 0
    cost_usd: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialise to plain dict for MCP / CEO response."""
        return {
            "query": self.query,
            "action_type": self.action_type,
            "response": self.response,
            "code_block": self.code_block,
            "filename_hint": self.filename_hint,
            "saved_path": self.saved_path,
            "opened": self.opened,
            "model_used": self.model_used,
            "duration_ms": self.duration_ms,
            "cost_usd": self.cost_usd,
        }


# ---------------------------------------------------------------------------
# Action classifier
# ---------------------------------------------------------------------------

def _detect_action(query: str) -> str:
    """
    Classify the coding request into an action type.

    Args:
        query: Raw user query.

    Returns:
        One of: "write", "review", "debug", "explain", "refactor"
    """
    q = query.lower()
    if any(w in q for w in ["debug", "fix", "error", "traceback", "exception", "bug", "broken"]):
        return "debug"
    if any(w in q for w in ["review", "check", "feedback", "critique", "improve", "is this good"]):
        return "review"
    if any(w in q for w in ["explain", "what does", "how does", "walk me through", "understand"]):
        return "explain"
    if any(w in q for w in ["refactor", "clean up", "optimise", "optimize", "restructure"]):
        return "refactor"
    return "write"


def _wants_iteration(query: str) -> bool:
    """
    Return True if the user wants to fix / improve / change a previously built app.

    These requests ("the game isn't starting", "fix it", "make the website better")
    must re-open the actual file Forge built and edit THAT code — not regenerate a
    new app from scratch. Agent-improvement ("improve the X agent") is excluded so it
    keeps routing to Vanta.

    Args:
        query: Raw user query.

    Returns:
        True for iterate-on-last-build intent.
    """
    q = query.lower()
    if "agent" in q:
        return False
    change = (
        "fix", "debug", "not working", "not starting", "won't start", "wont start",
        "doesn't work", "does not work", "isn't working", "not opening", "not loading",
        "broken", "error", "bug", "improve", "make it better", "better", "change",
        "add ", "remove", "update", "tweak", "redo", "blank", "white screen",
        "still not", "the problem", "find the fix", "doesn't start", "won't run",
    )
    artifact = (
        "game", "website", "web site", "web app", "webpage", "web page",
        " site", " page", " html", " app", " ui ", "it ", "this", "that",
    )
    return any(c in q for c in change) and any(a in q for a in artifact)


def _find_last_build(query: str = "") -> "Path | None":
    """
    Return the build in Zero Tech that the user most likely means, or None.

    Forge's "memory" of what it built. If the query names the project (e.g. "fix the
    donkey kong game"), match it to a filename by word overlap; otherwise fall back to
    the most recently modified file.

    Args:
        query: The user's request, used to disambiguate which build to edit.

    Returns:
        Path to the chosen .html build, or None if the folder is empty/missing.
    """
    import re
    try:
        builds = list(TECH_DIR.glob("*.html"))
        if not builds:
            return None
        if query:
            stop = {"the", "a", "an", "my", "it", "this", "that", "fix", "make",
                    "game", "website", "site", "app", "web", "page", "better",
                    "improve", "and", "is", "not", "working", "starting", "please"}
            qwords = {w for w in re.findall(r"[a-z0-9]+", query.lower()) if w not in stop}
            best, best_score = None, 0
            for b in builds:
                fwords = set(re.findall(r"[a-z0-9]+", b.stem.lower()))
                score = len(qwords & fwords)
                if score > best_score:
                    best, best_score = b, score
            if best is not None and best_score >= 1:
                return best
        return max(builds, key=lambda p: p.stat().st_mtime)
    except OSError:
        return None


def _build_iterate_prompt(query: str, existing_html: str) -> str:
    """
    Prompt that hands Forge the real current file and asks for a corrected full file.

    Args:
        query:         What Cyph wants fixed/changed.
        existing_html: The full current contents of the last-built file.

    Returns:
        A debug/improve prompt containing the actual code.
    """
    return (
        "You are Zero's code agent. Cyph already has this single-file HTML app/game "
        "that YOU built, but it has a problem. Here is the CURRENT full file:\n\n"
        "```html\n" + existing_html + "\n```\n\n"
        f"Cyph says: {query}\n\n"
        "Find and fix the ACTUAL bug(s) in this exact code. Read it carefully. "
        "Common culprits: a Start button with no click listener attached; an overlay "
        "that never hides so the game is unreachable; the game loop never starting; a "
        "JavaScript error that halts execution; the canvas not sized; or referencing an "
        "element/asset that doesn't exist. "
        "Return the COMPLETE corrected HTML file (the whole thing, not a snippet, not a "
        "diff), wrapped in a single ```html ... ``` block and ending with </html>. "
        "Keep everything that already works — change only what's needed to fix it. "
        "On the last line: FILENAME: keep the same name."
    )


def _complete_if_truncated(text: str, system_prompt: str, max_rounds: int = 5) -> tuple[str, float]:
    """
    If an HTML build was cut off (no closing </html>), continue it and stitch.

    Args:
        text:          The (possibly truncated) model output so far.
        system_prompt: System message to keep the continuation in builder mode.
        max_rounds:    Safety cap on continuation calls.

    Returns:
        (completed_text, extra_cost_usd).
    """
    cost = 0.0
    rounds = 0
    while text and "</html>" not in text.lower() and rounds < max_rounds:
        rounds += 1
        try:
            cont = chat(
                "You are continuing an HTML file that was cut off mid-output. "
                "Continue from EXACTLY where it stops — do not repeat earlier lines, "
                "no commentary, no code fences. Output only the remaining HTML/CSS/JS, "
                "and make sure it ends with </html>.\n\n"
                "Tail of the file so far:\n" + text[-1600:],
                tier="capable", system=system_prompt, max_tokens=8192,
            )
            chunk = (cont.text or "").replace("```html", "").replace("```", "")
            if not chunk.strip():
                break
            text += chunk
            cost += cont.cost_usd
            logger.info(f"[forge] Continuation {rounds}: +{len(chunk)} chars (total {len(text)})")
        except Exception as exc:
            logger.warning(f"[forge] Continuation failed: {exc}")
            break
    return text, cost


def _review_build_html(html: str, system_prompt: str) -> tuple[str, float]:
    """
    One automatic QA pass over a fresh build: catch run-blocking bugs before it ships.

    This is the "debug it" step Cyph used to have to ask for — Forge now does it itself
    so builds work on the first attempt.

    Args:
        html:          The freshly-built HTML document.
        system_prompt: Builder system message.

    Returns:
        (reviewed_text, cost_usd). reviewed_text is raw model output (still needs
        _extract_html); on any error the original html is returned unchanged.
    """
    review_prompt = (
        "You just built this single-file HTML app. Do a STRICT pre-ship QA pass for "
        "bugs that would stop it from RUNNING when opened in a browser. Verify and fix:\n"
        "  - every button/control and key has its event listener actually attached;\n"
        "  - init/start/setup is actually CALLED on load (not just defined);\n"
        "  - the main loop actually starts (requestAnimationFrame/setInterval invoked);\n"
        "  - no undefined variables/functions; every getElementById id exists in the HTML;\n"
        "  - canvas (if any) is sized and getContext('2d') works;\n"
        "  - nothing throws before setup finishes (a thrown error silently kills the page).\n\n"
        "Here is the file:\n```html\n" + html + "\n```\n\n"
        "Return the COMPLETE corrected HTML file in one ```html ... ``` block, ending with "
        "</html>. Keep ALL features and content — only fix what's broken. If it is already "
        "correct, return it unchanged. No commentary."
    )
    try:
        resp = chat(review_prompt, tier="capable", system=system_prompt, max_tokens=8192)
        return resp.text, resp.cost_usd
    except Exception as exc:
        logger.warning(f"[forge] Build review pass failed (keeping original): {exc}")
        return "", 0.0


def _wants_execution(query: str) -> bool:
    """
    Return True if the user explicitly asked to run / execute / test the code.

    Forge never auto-executes — this is the gating check that keeps it opt-in.

    Args:
        query: Raw user query.

    Returns:
        True only for clear run/execute/test intent.
    """
    q = query.lower()
    return any(
        phrase in q for phrase in (
            "run it", "run the code", "run this", "execute it", "execute this",
            "execute the code", "test it", "test the code", "test this",
            "and run", "then run", "also run", "run and show",
        )
    )


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _wants_app_build(query: str) -> bool:
    """
    Return True if the user is asking Forge to build a runnable web app / site / game.

    These get written to disk in `Zero Tech` and opened in the browser, instead of
    being returned as copy-paste code.

    Args:
        query: Raw user query.

    Returns:
        True for clear "build me a website/app/game" intent.
    """
    q = query.lower()
    has_verb = any(v in q for v in _BUILD_VERBS)
    has_web = any(s in q for s in _WEB_SIGNALS)
    return has_verb and has_web


def _build_prompt(query: str, action_type: str, brainstorm_context: str = "",
                  app_build: bool = False, research_context: str = "") -> str:
    """
    Build the code agent prompt.

    Args:
        query:               The user's coding request.
        action_type:         Classified action (write/review/debug/explain/refactor).
        brainstorm_context:  Optional structured plan from the brainstorm agent.
        app_build:           True if this is a runnable web app/site/game to be
                             saved and opened (forces a single self-contained HTML file).
        research_context:    Optional facts gathered by Iris (the research agent),
                             passed via the bus when the build needs real-world data.

    Returns:
        Formatted prompt string.
    """
    brainstorm_block = (
        f"\n\nBrainstorm plan (implement according to this):\n{brainstorm_context}"
        if brainstorm_context else ""
    )
    research_block = (
        f"\n\nResearched facts to use in the build (from Iris — bake these real "
        f"values into the page, don't invent them):\n{research_context}"
        if research_context else ""
    )

    # Web-app builds get a dedicated instruction: ONE self-contained HTML file that
    # Zero saves to disk and opens in the browser — no copy-paste, no build step.
    if app_build:
        return (
            "You are Zero's code agent — Cyph's AI pair programmer and builder.\n\n"
            f"Request: {query}\n"
            f"{brainstorm_block}"
            f"{research_block}\n\n"
            "Build this as ONE complete, self-contained HTML file that runs by simply "
            "opening it in a browser. Requirements:\n"
            "- Everything in a single .html file — inline <style> and <script>, no external "
            "build step, no separate files. CDN links are fine.\n"
            "- Fully working, not a stub. If a game or app, the logic must actually work.\n"
            "- Clean, modern, good-looking UI (sensible layout, spacing, colours, responsive).\n"
            "- Self-contained: it must work when double-clicked as a local file.\n"
            "\n"
            "MUST-RUN CHECKLIST — the #1 rule is that it WORKS the moment it loads. Before "
            "you output, mentally trace the code and guarantee ALL of these:\n"
            "  1. Every button and control has its event listener actually attached.\n"
            "  2. The app initialises on load — call your init()/start()/setup at the very end "
            "of the script (or on DOMContentLoaded); never leave it uncalled.\n"
            "  3. The main loop actually starts (requestAnimationFrame/setInterval is invoked).\n"
            "  4. No references to elements/variables/functions that don't exist; every "
            "getElementById target exists in the HTML; no typos in IDs.\n"
            "  5. If it uses <canvas>, the canvas has a width/height and getContext('2d') works.\n"
            "  6. No JavaScript error can throw before setup finishes (that silently kills the page).\n"
            "A first load that shows nothing or does nothing is a FAILURE, even if the rest is great.\n"
            "\n"
            "- Wrap the ENTIRE file in a single ```html ... ``` fenced block.\n"
            "- On the last line, suggest a short filename like: FILENAME: tic-tac-toe.html\n"
            "- Keep any prose before the code to 1–2 sentences; the file is the deliverable."
        )

    base = f"""You are Zero's code agent — Cyph's AI pair programmer.

{STACK_CONTEXT}
{brainstorm_block}{research_block}

Request: {query}

"""
    instructions = {
        "write": (
            "Write the requested code. Requirements:\n"
            "- Type hints on every function and class\n"
            "- Docstring on every function: one-line summary + Args + Returns\n"
            "- pathlib.Path not os.path\n"
            "- f-strings not .format()\n"
            "- Specific error handling — no bare except, no silent pass\n"
            "- If it's an agent, include bus=None kwarg and bus.publish() at the end\n"
            "- Wrap the code in ```python ... ``` fences\n"
            "- After the code, suggest a filename in the format: FILENAME: path/to/file.py"
        ),
        "review": (
            "Review the code. Structure your response as:\n"
            "1. OVERALL VERDICT (1 line: good/needs work/major issues)\n"
            "2. STRENGTHS (what's done well)\n"
            "3. ISSUES (specific problems with line references if possible)\n"
            "4. REWRITES (provide improved versions of weak sections in ```python``` blocks)"
        ),
        "debug": (
            "Debug the issue. Structure your response as:\n"
            "1. ROOT CAUSE (what's actually wrong, 1–2 sentences)\n"
            "2. WHY IT HAPPENS (brief explanation)\n"
            "3. FIX (the corrected code in ```python``` fences)\n"
            "4. PREVENTION (how to avoid this class of error in future)"
        ),
        "explain": (
            "Explain the code clearly. Cyph is an MSc AI student — go as deep as needed, "
            "but don't over-explain basics. Focus on the design decisions and why things work the way they do."
        ),
        "refactor": (
            "Refactor the code. Provide:\n"
            "1. What you're changing and why (brief)\n"
            "2. The refactored code in ```python``` fences\n"
            "3. What improved (performance, readability, maintainability)"
        ),
    }
    return base + instructions.get(action_type, instructions["write"])


# ---------------------------------------------------------------------------
# Code block extractor
# ---------------------------------------------------------------------------

def _extract_code(text: str) -> str:
    """
    Pull the first Python code block from the LLM response.

    Args:
        text: Raw LLM response.

    Returns:
        Code string, or empty string if none found.
    """
    import re
    match = re.search(r"```python\s*(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    # Fallback: plain ``` block
    match = re.search(r"```\s*(.*?)```", text, re.DOTALL)
    return match.group(1).strip() if match else ""


def _extract_html(text: str) -> str:
    """
    Pull a full HTML document out of the LLM response.

    Prefers a ```html fenced block; falls back to a plain fenced block that looks
    like HTML, then to a raw <!doctype html>…</html> span if the model didn't fence it.

    Args:
        text: Raw LLM response.

    Returns:
        HTML string, or empty string if none found.
    """
    import re
    m = re.search(r"```html\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    # Any fenced block whose contents look like an HTML document.
    for blk in re.findall(r"```[a-zA-Z]*\s*(.*?)```", text, re.DOTALL):
        low = blk.lower()
        if "<!doctype html" in low or "<html" in low:
            return blk.strip()
    # Unfenced raw document.
    m = re.search(r"(<!doctype html.*?</html>)", text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    m = re.search(r"(<html[ >].*?</html>)", text, re.DOTALL | re.IGNORECASE)
    return m.group(1).strip() if m else ""


def _salvage_html(text: str) -> str:
    """
    Recover a usable HTML file from a truncated build that never reached </html>.

    A big build that gets cut off mid-output would otherwise be thrown away (no
    complete document to extract) and the user gets nothing. Instead, grab from the
    doctype/<html> to the end, drop any trailing code fence, and best-effort close the
    document so the browser still runs it (a partial game beats an empty response).

    Args:
        text: The raw (likely truncated) model output.

    Returns:
        A closed HTML string, or "" if there's no usable document start.
    """
    if not text:
        return ""
    low = text.lower()
    idx = low.find("<!doctype html")
    if idx == -1:
        idx = low.find("<html")
    if idx == -1:
        return ""
    frag = text[idx:].split("```")[0].rstrip()
    if "</html>" not in frag.lower():
        if "</body>" not in frag.lower():
            frag += "\n</body>"
        frag += "\n</html>"
    return frag.strip() if len(frag) > 400 else ""


def _slugify(text: str, default: str = "app") -> str:
    """
    Turn free text into a short safe filename stem.

    Args:
        text:    Source text (usually the user query).
        default: Fallback stem if nothing usable remains.

    Returns:
        A lowercase hyphenated stem, max ~6 words.
    """
    import re
    words = re.findall(r"[a-z0-9]+", text.lower())
    # Drop common build-verb noise so the name is about the thing, not the verb.
    stop = {"make", "build", "create", "generate", "a", "an", "the", "me", "for",
            "my", "please", "app", "website", "web", "site", "game", "and", "with"}
    kept = [w for w in words if w not in stop][:5]
    if not kept:
        kept = [w for w in words if w][:5]
    stem = "-".join(kept) if kept else default
    return stem[:48] or default


def _save_and_open(html: str, query: str, filename_hint: str) -> tuple[str, bool]:
    """
    Write a built web artifact into the Zero Tech folder and open it in the browser.

    Args:
        html:          The full HTML document to write.
        query:         The user query (used to derive a filename if no hint).
        filename_hint: Optional FILENAME: suggestion from the model.

    Returns:
        (absolute_path, opened) — path is "" if writing failed; opened is True
        only if the browser was launched successfully.
    """
    import re
    # Choose a filename: prefer the model hint's basename, else slugify the query.
    name = ""
    if filename_hint:
        name = Path(filename_hint.strip().strip('"\'')).name
    if not name:
        name = _slugify(query) + ".html"
    if not name.lower().endswith((".html", ".htm")):
        name = re.sub(r"\.[^.]*$", "", name) + ".html"

    try:
        TECH_DIR.mkdir(parents=True, exist_ok=True)
        path = TECH_DIR / name
        if path.exists():
            path = TECH_DIR / f"{path.stem}_{int(time.time())}{path.suffix}"
        path.write_text(html, encoding="utf-8")
        logger.info(f"[forge] Saved web app → {path}")
    except OSError as exc:
        logger.error(f"[forge] Failed to save artifact: {exc}")
        return "", False

    opened = False
    try:
        import webbrowser
        opened = webbrowser.open(path.as_uri())
        logger.info(f"[forge] Opened in browser: {opened}")
    except Exception as exc:  # browser launch is best-effort; saving already succeeded
        logger.warning(f"[forge] Could not open browser: {exc}")

    return str(path), opened


def _extract_filename(text: str) -> str:
    """
    Extract a suggested filename from the LLM response.

    Args:
        text: Raw LLM response.

    Returns:
        Filename string, or empty string if none found.
    """
    import re
    match = re.search(r"FILENAME:\s*(.+)", text)
    return match.group(1).strip() if match else ""


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _log_action(query: str, result: CodeResult) -> None:
    """
    Append structured log line to logs/code.log.

    Args:
        query:  The coding request.
        result: The completed CodeResult.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / "code.log"
    entry = (
        f"timestamp={time.strftime('%Y-%m-%dT%H:%M:%S')} "
        f"agent={AGENT_NAME} "
        f"action={result.action_type} "
        f"query={query!r} "
        f"has_code={bool(result.code_block)} "
        f"model={result.model_used} "
        f"duration_ms={result.duration_ms} "
        f"cost_usd={result.cost_usd:.6f}\n"
    )
    try:
        with log_file.open("a", encoding="utf-8") as f:
            f.write(entry)
    except OSError as exc:
        logger.error(f"[forge] Failed to write log: {exc}")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run(query: str, bus: "ContextBus | None" = None) -> CodeResult:
    """
    Execute a coding task.

    Args:
        query: Natural language coding request — write/review/debug/explain/refactor.
        bus:   Optional shared ContextBus. Reads brainstorm plans if present,
               publishes generated code so other agents can reference it.

    Returns:
        CodeResult with response, extracted code block, and filename hint.
    """
    start_ms = int(time.time() * 1000)
    logger.info(f"[forge] Query: {query!r}")

    action_type = _detect_action(query)
    app_build = _wants_app_build(query)

    # Iteration: "fix it / the game won't start / make the website better" — re-open
    # the actual file Forge last built and edit THAT code, instead of regenerating a
    # new app blind. This is Forge using its memory of what it shipped.
    iterate = _wants_iteration(query)
    last_build = _find_last_build(query) if iterate else None
    iterate_filename = ""
    logger.info(
        f"[forge] Action: {action_type} (app_build={app_build}, "
        f"iterate={iterate}, last_build={last_build.name if last_build else None})"
    )

    # Read upstream context from the bus: a brainstorm plan and/or Iris's research
    # findings (when the CEO ran research first in the build pipeline).
    brainstorm_context = ""
    research_context = ""
    if bus is not None:
        brainstorm_summary = bus.get_from("brainstorm", "summary")
        if brainstorm_summary:
            brainstorm_context = brainstorm_summary
            logger.info("[forge] Injecting brainstorm plan from bus")
        research_summary = bus.get_from("research", "summary")
        if research_summary:
            research_context = research_summary
            logger.info("[forge] Injecting research findings from bus")

    if last_build is not None:
        # Editing an existing build — load its real code and fix THAT.
        try:
            existing_html = last_build.read_text(encoding="utf-8", errors="ignore")
            prompt = _build_iterate_prompt(query, existing_html)
            app_build = True            # save + open the corrected file
            iterate_filename = last_build.name
            logger.info(f"[forge] Iterating on {last_build.name} ({len(existing_html)} chars)")
        except OSError as exc:
            logger.warning(f"[forge] Couldn't read last build, falling back to fresh build: {exc}")
            last_build = None
            prompt = _build_prompt(query, action_type, brainstorm_context,
                                   app_build=app_build, research_context=research_context)
    else:
        prompt = _build_prompt(query, action_type, brainstorm_context,
                               app_build=app_build, research_context=research_context)
    model_used = ""
    cost_usd = 0.0
    response_text = ""

    # Whole HTML files are large — give app builds more room so they don't truncate.
    system_prompt = (
        "You are Zero's builder. Output a single complete, self-contained, working HTML file."
        if app_build else
        "You are Zero's code agent. Write clean, production-quality Python."
    )
    try:
        response = chat(
            prompt,
            tier="capable",      # code tasks always need the stronger model
            system=system_prompt,
            max_tokens=8192 if app_build else 2048,
        )
        response_text = response.text
        cost_usd = response.cost_usd
        model_used = f"{response.provider.value}/{response.model}"
        logger.info(f"[forge] Response: {len(response_text)} chars")
    except Exception as exc:
        logger.error(f"[forge] LLM error: {exc}")
        response_text = f"Code agent encountered an error: {exc}"

    # Big single-file builds can exceed the model's per-reply output cap and get cut
    # off mid-file. Stitch any continuation back on so the file is complete.
    if app_build:
        response_text, cont_cost = _complete_if_truncated(response_text, system_prompt)
        cost_usd += cont_cost

    # Automatic QA pass on FRESH builds — Forge debugs its own work so it runs on the
    # first attempt (the "debug it" step Cyph used to have to ask for). Skipped for
    # iteration (that's already a fix pass) and toggleable via FORGE_BUILD_REVIEW=0.
    review_enabled = os.getenv("FORGE_BUILD_REVIEW", "1").lower() not in ("0", "false", "no")
    if app_build and last_build is None and review_enabled:
        draft_html = _extract_html(response_text)
        # Skip the QA regen on very large files — re-emitting them risks truncating a
        # good draft into nothing. Big builds rely on the build + continuation instead.
        if draft_html and len(draft_html) > 16000:
            logger.info(f"[forge] QA review skipped — draft too large ({len(draft_html)} chars)")
            draft_html = ""
        if draft_html:
            reviewed_text, rcost = _review_build_html(draft_html, system_prompt)
            cost_usd += rcost
            if reviewed_text:
                reviewed_text, rcont = _complete_if_truncated(reviewed_text, system_prompt)
                cost_usd += rcont
                reviewed_html = _extract_html(reviewed_text)
                # Only accept the reviewed version if it's plausibly complete (guards
                # against a truncated/garbled review replacing a good draft).
                if reviewed_html and len(reviewed_html) >= 0.6 * len(draft_html):
                    response_text = reviewed_text
                    logger.info(
                        f"[forge] QA review applied ({len(draft_html)} → {len(reviewed_html)} chars)"
                    )
                else:
                    logger.info("[forge] QA review rejected (too short) — keeping original draft")

    code_block = _extract_code(response_text)
    filename_hint = _extract_filename(response_text)

    # App build — save the HTML to the Zero Tech folder and open it in the browser,
    # instead of handing Cyph code to copy-paste. This is the deliverable he asked for.
    saved_path = ""
    opened = False
    if app_build:
        html = _extract_html(response_text)
        partial = False
        if not html:
            # Truncated big build — salvage what was generated rather than returning
            # nothing, so the user gets a (possibly incomplete) runnable file.
            html = _salvage_html(response_text)
            if html:
                partial = True
                logger.warning("[forge] Salvaged a truncated/partial build")
        if html:
            code_block = html  # the file IS the artifact
            # When iterating, keep the original file's name so versions stay grouped.
            name_hint = iterate_filename or filename_hint
            saved_path, opened = _save_and_open(html, query, name_hint)
            if saved_path:
                where = saved_path
                tail = (
                    "Heads up: this one was large and got cut off, so it may be "
                    "incomplete — if something's missing, say \"continue the <name> game\" "
                    "or \"fix the <name> game\" and I'll finish it."
                    if partial else
                    "It's a single self-contained HTML file, so you can double-click it "
                    "anytime to run it again."
                )
                note = (
                    f"Done — I built it and saved it to {where}. "
                    + ("I've opened it in your browser now. "
                       if opened else
                       "Open it from that folder to run it. ")
                    + tail
                )
                response_text = f"{note}\n\n{response_text}"
            else:
                response_text = (
                    "I built the app but couldn't write it to the Zero Tech folder — "
                    "the code is below so it isn't lost.\n\n" + response_text
                )
        else:
            logger.warning("[forge] app_build requested but no HTML document found in response")
            if not response_text.strip():
                response_text = (
                    "I couldn't generate a complete file this time — the build was too "
                    "large and the model returned nothing usable. Try again, or ask for a "
                    "simpler first version (we can add the extra features afterwards)."
                )

    # Sandboxed execution — only runs when user explicitly asked to run/test/execute.
    # Uses sandbox/executor.py to spawn an isolated subprocess with a timeout so
    # generated code can't crash the backend or run forever.
    execution_output = ""
    if code_block and not app_build and _wants_execution(query):
        try:
            from sandbox.executor import execute
            exec_result = execute(code_block, language="python", timeout=15)
            execution_output = exec_result.as_text()
            logger.info(
                f"[forge] Executed code: success={exec_result.success} "
                f"in {exec_result.duration_ms}ms"
            )
            # Append execution output to the response so CEO synthesis sees it
            response_text = (
                f"{response_text}\n\n"
                f"--- Execution output ---\n{execution_output}"
            )
        except Exception as exc:
            logger.warning(f"[forge] Code execution failed: {exc}")
            execution_output = f"Execution error: {exc}"

    duration_ms = int(time.time() * 1000) - start_ms
    result = CodeResult(
        query=query,
        action_type=action_type,
        response=response_text,
        code_block=code_block,
        filename_hint=filename_hint,
        saved_path=saved_path,
        opened=opened,
        model_used=model_used,
        duration_ms=duration_ms,
        cost_usd=cost_usd,
    )

    _log_action(query, result)

    # Publish to bus — other agents may need the generated code as context
    if bus is not None:
        if code_block:
            bus.publish("code", "code_block", code_block)
        if filename_hint:
            bus.publish("code", "filename_hint", filename_hint)
        if saved_path:
            bus.publish("code", "saved_path", saved_path)
        bus.publish("code", "action_type", action_type)
        logger.debug(f"[forge] Published to bus: code_block={bool(code_block)}")

    logger.info(f"[forge] Done in {duration_ms}ms — cost=${cost_usd:.6f}")
    return result


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "Write a Python function that takes an EEG signal array and returns the power spectral density for each channel using scipy"
    logging.basicConfig(level=logging.INFO)
    result = run(q)
    print(f"\n{'='*60}")
    print(f"CODE AGENT — {result.action_type.upper()}")
    print(f"{'='*60}")
    print(result.response)
    if result.filename_hint:
        print(f"\nSuggested file: {result.filename_hint}")
    print(f"\nModel: {result.model_used} | Time: {result.duration_ms}ms | Cost: ${result.cost_usd:.6f}")
