# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> Full project history, phase checklists, agent personas, and the session log live in
> **`.zero/CLAUDE.md`** — read it for deep context. This file is the operational
> quick-reference (commands + big-picture architecture). Note: `.zero/CLAUDE.md`'s
> folder header still says `K:\Astra\.zero` from an old rename — the real root is
> **`K:\Zero\.zero`**. Always address the user as **Cyph**.

## Layout (real paths)
- `K:\Zero\.zero\` — the Python backend (FastAPI multi-agent OS). Most work happens here.
- `K:\Zero\.venv\` — the Python venv that runs the backend (**parent of `.zero`**, NOT `.zero\.venv`).
- `K:\Zero\.zero\ui\` — the real desktop frontend (React + Vite + Tauri v2).
- `K:\Zero\.zero\unity\ZeroOS\` — Unity HDRP project; source of the "neural sphere/orb" render.
- `K:\Zero\index.html` — a standalone single-file demo UI (no build step; opened via `file://`).
- `K:\Zero\Zero Tech\` — where the code agent (Forge) saves generated web apps.

## Commands
Python 3.11. Deps via `uv pip install -r requirements.txt` (requirements in `.zero`).

**Run / restart the backend** (port 8000, admin-owned process — see gotcha below):
- `K:\Zero\restart-zero.bat` — kills whatever holds :8000 and relaunches from
  `K:\Zero\.venv` on `127.0.0.1`. Run as administrator if it says "Access is denied".
- `K:\Zero\.zero\start_backend.bat` — `uv pip install` then uvicorn on `0.0.0.0` with
  `--reload` (use `0.0.0.0` only if the phone bridge needs LAN access).

**Test one agent standalone** (agents' `__main__` do NOT load `.env`, so load it explicitly):
```
K:\Zero\.venv\Scripts\python.exe -c "from dotenv import load_dotenv; load_dotenv(); from agents.research.run import run; print(run('compare mamba vs transformers').summary)"
```
(run this with cwd = `K:\Zero\.zero`).

**Syntax-check before restarting** (there is no unit-test suite — `tests/` is empty):
```
K:\Zero\.venv\Scripts\python.exe -c "import ast; ast.parse(open('agents/<name>/run.py',encoding='utf-8').read())"
K:\Zero\.venv\Scripts\python.exe -c "import api.main"   # full import check (cwd=.zero)
```
Verification is done by **standalone agent runs + live `/ask` after a restart**, not pytest.

**Frontend** (`cd K:\Zero\.zero\ui`): `npm run tauri:dev` (desktop app) or `npm run dev`
(Vite dev server at :5173). It talks to the backend at `http://localhost:8000` — `POST
/ask {"input": "..."}`, plus `/tts`, `/persona/*`, `/health`, `/info`, `/scheduler/*`.

## CRITICAL: backend restart is required to load code changes
The running backend is usually **admin-owned** and cannot be killed by a normal shell.
Editing `agents/*/run.py`, `core/*.py`, or a `manifest.json` has **no effect until a full
restart** — the registry file-watcher does not reliably reload existing-agent code or
manifest keyword changes, and `--reload` is unreliable for these. After any backend edit,
tell Cyph to run `restart-zero.bat`, then test via `/ask`.

## Model state (important)
`core/llm.py` routes by `.env` keys with three tiers (`fast`=Haiku, `capable`=Sonnet,
`deep`=Opus) chosen by `quality.assess_depth()`. **The Anthropic key is set but the account
is at $0 credits**, so every call transparently fails over to **DeepSeek** (deepseek-reasoner).
Don't assume Claude-quality output; the failover chain is anthropic→deepseek→ollama.

## Architecture big-picture (spans many files)
- **Entry:** `api/main.py` (FastAPI). `POST /ask` accepts `{input}` or `{query}` → runs
  `core.ceo.ceo.handle(text)` in a thread. CORS is `*` so the `file://` demo UI can call it.
- **Orchestrator:** `core/ceo.py` — intent/risk gate (`core/intent.py`) → `_select_agents`
  (checks the learned **skill store** first, then a **build/iterate override** that routes
  "make/fix an app/game/website" to Forge only, then the keyword registry + LLM ranking) →
  **two-wave parallel dispatch** (producers `research/brainstorm/schedule` run first and
  publish to the bus; dependents read that in wave 2) → external MCP tools → `_synthesise`
  (persona voice + a self-fix quality loop in `core/quality.py`; **short-circuits to a clean
  "saved to …" message when an agent wrote a file**) → save to memory.
- **Agents:** each is `agents/<name>/{manifest.json, run.py}`, auto-discovered by
  `core/registry.py`. Contract: `run(query, bus=None) -> dataclass` with `.to_dict()`.
  `risk_level` = `read | write | high` (**high** = emails/purchases/destructive → must show a
  preview and wait for explicit "yes"). Display names differ from folder names (research=**Iris**,
  code=**Forge**, news=**Herald**, vanta=**Vanta**, etc.).
- **Bus:** `core/bus.py` — per-request `ContextBus`. Agents `bus.publish(agent, key, val)` and
  `bus.get_from(agent, key)`. Live pipeline: **Iris publishes `summary`/`sources`/`findings` →
  Forge reads them** when a build needs facts.
- **Memory:** `memory/hot|warm|cold`. `cold.py` = ChromaDB + an FTS5 keyword index fused via
  RRF (`hybrid_search`, `search_all`); `warm.py` = Redis with in-memory fallback (Redis is
  usually not running — the fallback warning is benign).
- **Notable agents:** `research/` (**Iris**, v0.2 — query decomposition, parallel multi-search,
  academic arXiv/Semantic-Scholar, personalization from Cyph's notes, verified citations);
  `code/` (**Forge** — builds self-contained web apps, saves+opens them from `Zero Tech`, and
  re-opens the last build to *fix* it); `vanta/` (**Vanta** — audits all agents from
  manifests+logs and its `implement` mode auto-rewrites a target agent's `run.py`).
- **Personas:** `core/personas.py` — Zero (sharp/execution) and V (warm) are two CEO personas
  over the same agent mesh + memory; graded by persona-aware rubrics in `core/quality.py`.

## Conventions
- Type hints + docstrings everywhere; `pathlib.Path`; f-strings; specific exception handling
  (log, don't silently pass); no hardcoded paths (use `Path(__file__).parent`) or API keys.
- Every agent action appends a structured line to `logs/<name>.log`; the CEO logs to
  `logs/ceo_actions.jsonl` (both are read by Vanta's audit). Never delete `logs/`.
- The planning/roadmap file for in-flight work is
  `C:\Users\deepe\.claude\plans\binary-puzzling-hejlsberg.md`.
