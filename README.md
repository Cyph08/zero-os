# Zero OS

A personal multi-agent AI operating system. Not a chatbot wrapper — a mesh of 14
specialist agents behind a CEO orchestrator, with persistent memory, voice I/O,
scheduled autonomy, and real access to the machine it runs on.

Built and run daily on Windows 11 (RTX 4050 6GB, Ryzen 7 7435HS, 24GB DDR5).

---

## How it works

```
voice / text / cron trigger
        │
        ▼
  core/intent.py ......... risk gate: read | write | high
        │
        ▼
  core/ceo.py ............ CEO orchestrator (persona: Zero or V)
        │
        ├─ learned skill store ...... reuse a proven agent plan if one matches
        ├─ build/iterate override ... route "make/fix an app" straight to Forge
        └─ keyword registry + LLM rank
        │
        ▼
  two-wave parallel dispatch (ThreadPoolExecutor)
    wave 1: producers (research, brainstorm, schedule) → publish to bus
    wave 2: dependents read the bus and enrich their own work
        │
        ▼
  external MCP tools (Zero is also an MCP *client*)
        │
        ▼
  synthesis: persona voice → build/grade/fix quality loop → memory write
```

Agents never talk to each other directly. They publish to a per-request
`ContextBus`, and the next wave reads it. Iris researching "latest EEG papers"
and Forge building a dashboard from those findings is the same mechanism.

---

## The agents

| Agent | Name | Does |
|---|---|---|
| `research` | **Iris** | Web + academic research. Decomposes a question into sub-queries, searches them in parallel (Tavily / arXiv / Semantic Scholar), dedupes, and answers with verified citations |
| `code` | **Forge** | Builds self-contained web apps, **saves and opens them**, then re-opens its own last build to fix it. Auto QA pass before handoff |
| `system` | **Helm** | Laptop access: find, read, open, write, move, copy, delete, run. Reversible by design |
| `vanta` | **Vanta** | System self-improvement. Audits every agent from manifests + logs, writes improvement briefs, and can rewrite a target agent's `run.py` |
| `news` | **Herald** | Morning briefing: weather, today's schedule, world + AI news |
| `bci` | **Synapse** | EEG / BCI research, motor imagery, CSP |
| `study` | **Sage** | MSc AI coursework, paper summaries, explanations |
| `schedule` | **Chrono** | Reminders, planning, calendar entries |
| `brainstorm` | **Spark** | Idea structuring, MVP planning |
| `career` | **Maven** | CV, cover letters, job strategy |
| `comms` | **Echo** | Email drafting — never auto-sends |
| `linkedin` | **Nexus** | Job search, profile, message drafts |
| `health` | **Pulse** | Training, sleep, hydration logs |
| `photo` | **Lens** | Nikon D3400 batch processing |

Two CEO personas share the same agent mesh and memory: **Zero** (sharp,
execution-focused) and **V** (warm). They are graded against different rubrics so
the quality loop doesn't strip V's warmth as "filler".

---

## Memory

Four tiers, fused rather than layered:

- **hot** — session RAM, last 50 turns, last 10 injected into every prompt
- **warm** — Redis 24h cache with a transparent in-memory fallback
- **cold** — ChromaDB vectors **+ a SQLite FTS5 keyword index**, fused via
  reciprocal rank fusion. Vectors alone miss exact terms like `RTX 4050` or
  `CSP`; the hybrid catches them
- **vault** — Obsidian markdown notes are synced into cold memory at startup

---

## Model routing

`core/llm.py` picks a tier from the question's depth — `fast`, `capable`, or
`deep` — and the same signal sets the self-fix budget, so they never drift apart.

Providers are a failover chain: **Anthropic → DeepSeek → Groq → Ollama**. If the
preferred provider errors (billing, rate limit, network), the next one serves the
call and the preferred one resumes automatically on the next request. Every call
is time-bounded, so a stalled provider fails over instead of hanging.

---

## Voice

- **STT** — Whisper `large-v3` on CUDA (auto-detects, falls back to CPU), with
  RMS voice-activity detection so silence is never transcribed
- **TTS** — Edge TTS with ElevenLabs upgrade, distinct voice per persona, markdown
  stripped before synthesis, and a global playback lock so two agents can't talk
  over each other
- **Wake word** — openWakeWord, both personas scored on a *single* shared
  microphone stream (two streams on one mic was the cause of missed wakes)

---

## Layout

```
.zero/
  core/          CEO, registry, intent gate, LLM router, bus, quality loop,
                 scheduler, MCP client, structured error log
  agents/        14 agents — each is {manifest.json, run.py}
  memory/        hot / warm / cold / fts
  voice/         stt, tts, wake
  api/           FastAPI app + MCP server (StreamableHTTP)
  skills/        auto-distilled multi-agent skill store (SQLite)
  sandbox/       subprocess code execution with hard timeouts
  integrations/  gmail, calendar, notion, github, slack
  phone/         mobile REST bridge + chat UI
  ui/            React + Vite + Tauri v2 desktop app
  unity/         HDRP project for the orb render
  docs/          audit + improvement reports
index.html       standalone single-file demo UI (no build step)
```

---

## Running it

Requires Python 3.11+ and [`uv`](https://github.com/astral-sh/uv).

```bash
uv pip install -r .zero/requirements.txt
cp .zero/.env.example .zero/.env      # then fill in your keys
```

Start the backend (from `.zero/`):

```bash
uvicorn api.main:app --host 127.0.0.1 --port 8000
```

Then `POST /ask {"input": "..."}`, or open the desktop app:

```bash
cd .zero/ui && npm install && npm run tauri:dev
```

MCP server is exposed at `http://localhost:8000/mcp` — every agent is a tool.

---

## Adding an agent

Drop a folder into `.zero/agents/`. The registry discovers it on restart.

```
agents/myagent/
  manifest.json    name, description, trigger_keywords, risk_level, version
  run.py           run(query, bus=None) -> dataclass with .to_dict()
```

`risk_level` is enforced: `read` runs immediately, `write` reports what it did,
`high` requires a preview and explicit confirmation.

---

## Logs

Every action is structured and on disk — `logs/<agent>.log` per agent, plus
`ceo_actions.jsonl` (routing, cost, duration), `error_log.jsonl` (full
tracebacks) and `quality_log.jsonl` (self-fix pass rates). Vanta reads these to
audit the system.

There is no pytest suite by design; verification is standalone agent runs plus a
live request after restart. Agents with non-trivial logic carry their own
self-check — e.g. `python -m agents.system.run`.

---

## Status

Phases 1–7 complete: brain, memory, phone bridge, agent mesh, proactive
scheduling, desktop app, per-agent tuning, plus Vanta (self-improvement) and Helm
(laptop access).

Next: streaming token output end-to-end, and ATLAS — a visual canvas where
research and news render as maps, cards and charts instead of prose.

---

*Personal project. Secrets are environment-only and never committed.*
