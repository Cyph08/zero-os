# ZERO OS — Project Context File
# Read this file at the start of every session before touching any code.
# Update the Session Log and Phase Checklist after every build session.
# Always call the user: Cyph

---

## Project Identity

**Name:** Zero OS — always use Astra)  
**Owner:** Cyph (MSc AI, University of Manchester)  
**Goal:** A multi-agent AI operating system — not a chatbot. Layered architecture where Cyph speaks or types a command and a mesh of AI agents plans, executes, and reports back.

---

## Hardware

- **GPU:** NVIDIA RTX 4050 — 6GB VRAM
- **CPU:** AMD Ryzen 7 7435HS — 8 cores / 16 threads
- **RAM:** 24GB DDR5
- **OS:** Windows — use PowerShell unless told otherwise
- **Storage:** SSD

**Model size constraints:**
- Local LLM: max ~7B params at Q4/Q5 GGUF (fits 6GB VRAM)
- Whisper: `large-v3` fits with fp16 — use for best STT accuracy
- SD: 1.5 or SDXL-Turbo at low res — flag if a task exceeds VRAM
- Never recommend cloud-only without checking local first

---

## Architecture Overview

```
Input (voice/text/image/trigger)
  → core/intent.py     — intent classifier + risk gate (read / write / high)
  → core/ceo.py        — CEO agent: plans, routes to department agents
  → agents/*           — department agents run, share via context bus
  → core/bus.py        — agent-to-agent communication
  → CEO synthesises result
  → voice/tts.py       — speaks response back
  → logs/              — every action logged
```

---

## Folder Structure

```
K:\Astra\.zero\
├── CLAUDE.md
├── core/
│   ├── registry.py      ← auto-discovers agents from /agents/
│   ├── ceo.py           ← Zero CEO orchestrator
│   ├── intent.py        ← intent classifier + risk gate
│   └── bus.py           ← agent-to-agent context bus
├── agents/
│   ├── research/        ← manifest.json + run.py  [LIVE]
│   ├── career/          ← [LIVE]
│   ├── schedule/        ← [LIVE]
│   ├── brainstorm/      ← [LIVE] idea structuring + MVP planning
│   ├── code/            ← [LIVE] AI pair programmer
│   ├── study/           ← [LIVE] MSc AI coursework assistant
│   ├── bci/             ← [LIVE] EEG/BCI specialist + Lumineth
│   ├── health/          ← [LIVE] gym/sleep/hydration tracker
│   ├── comms/           ← [LIVE] email drafting (risk=high)
│   ├── photo/           ← [LIVE] Nikon D3400 batch processor
│   └── [drop new agent folder here — auto-discovered]
├── memory/
│   ├── hot.py           ← session RAM context
│   ├── warm.py          ← Redis recent-weeks cache
│   └── cold.py          ← ChromaDB long-term vector store
├── integrations/
│   ├── gmail.py
│   ├── calendar.py
│   ├── notion.py
│   ├── github.py
│   ├── linkedin.py
│   └── slack.py
├── voice/
│   ├── stt.py           ← Whisper large-v3 STT
│   ├── tts.py           ← Edge TTS (primary) + ElevenLabs (premium)
│   └── wake.py          ← Porcupine wake word ("Zero")
├── visual/
│   ├── vision.py        ← OpenCV + Pillow
│   └── capture.py       ← mss screen capture
├── api/
│   ├── main.py          ← FastAPI entry point
│   ├── mcp_server.py    ← MCP server (StreamableHTTP, /mcp endpoint)
│   └── routes/
├── phone/
│   └── bridge.py        ← Mobile REST bridge
├── logs/                ← auto-generated, never delete
├── docs/
│   ├── architecture.md
│   └── roadmap.md
├── tests/
└── requirements.txt
```

---

## Agent Manifest Format

Every agent MUST have this exact structure in `manifest.json`:

```json
{
  "name": "agent_name",
  "description": "One sentence: what this agent does",
  "trigger_keywords": ["keyword1", "keyword2"],
  "capabilities": ["web_search", "file_read", "email_draft", "code_run"],
  "risk_level": "read | write | high",
  "collaborates_with": ["other_agent_name"],
  "model_preference": "claude-haiku | claude-sonnet | local-7b",
  "entry_point": "agents/name/run.py",
  "version": "0.1.0"
}
```

**risk_level rules — enforce without exception:**
- `read` — reads only, runs immediately, no confirmation
- `write` — creates/modifies files. Tells Cyph what it will do, then proceeds
- `high` — sends emails, submits forms, applies for jobs, posts publicly, spends money. Shows full preview, waits for explicit "yes". No exceptions.

---

## Tech Stack

| Layer | Tool |
|---|---|
| Language | Python 3.11+ |
| Package manager | `uv` — always `uv pip install` |
| Backend | FastAPI |
| Orchestration | LangGraph (preferred) / CrewAI |
| Vector memory | ChromaDB |
| Warm cache | Redis |
| STT | openai-whisper (local, large-v3) |
| TTS primary | edge-tts |
| TTS premium | ElevenLabs (env: ELEVENLABS_API_KEY) |
| Wake word | pvporcupine |
| Vision | OpenCV + Pillow |
| Screen capture | mss |
| MCP | Python MCP SDK — StreamableHTTP only (no SSE) |
| Shell | PowerShell (Windows) |

---

## LLM Routing (core/llm.py handles this automatically)

Priority order based on which key is set in .env:
| Provider | Key | Cost | Notes |
|---|---|---|---|
| Anthropic | ANTHROPIC_API_KEY | ~£0.20/1M tokens | Best quality |
| DeepSeek | DEEPSEEK_API_KEY | ~£0.06/1M tokens | **Current default** |
| Groq | GROQ_API_KEY | Free | Rate limited |
| Ollama | (none needed) | Free | Local, offline |

Tier routing: fast = quick tasks (haiku/llama-8b/deepseek-chat), capable = complex tasks.

---

## Code Standards

- Type hints on every function and class
- Docstrings: one-line summary + Args + Returns
- `pathlib.Path` not `os.path`
- f-strings not `.format()`
- Every agent action logged: timestamp, agent, action_type, input_summary, outcome, duration_ms, cost_usd
- Error handling on every external call — catch specific exceptions, log, do not silently pass
- No hardcoded paths — use `Path(__file__).parent` relative paths
- No hardcoded API keys — always from environment variables
- `uv pip install` not `pip install`

---

## MCP Server

FastAPI exposes MCP at:
```
http://localhost:8000/mcp
```

Add in Cowork: Settings → Connectors → Add custom connector → `http://localhost:8000/mcp`

Every agent in the registry is exposed as an MCP tool.

---

## Connected Integrations

```
[ ] Google Drive      — MCP connector in Cowork
[ ] Gmail             — MCP connector in Cowork
[ ] Google Calendar   — MCP connector in Cowork
[ ] Notion            — MCP connector in Cowork
[ ] GitHub            — MCP connector in Cowork
[ ] Slack             — MCP connector in Cowork
[ ] Custom MCP        — http://localhost:8000/mcp  ← build this first
```

---

## Build Phases

### Phase 1 — Brain + Voice (COMPLETE ✅)

- [x] Create folder structure
- [x] Write CLAUDE.md
- [x] core/registry.py — plugin registry + file watcher
- [x] agents/research/ — manifest + run.py
- [x] core/intent.py — intent classifier + risk gate
- [x] core/ceo.py — CEO orchestrator
- [x] api/main.py + api/mcp_server.py — FastAPI + MCP endpoint
- [x] voice/stt.py — Whisper large-v3 pipeline
- [x] voice/tts.py — Edge TTS pipeline
- [x] voice/wake.py — Porcupine wake word

### Phase 2 — Memory + Integrations
- [x] memory/cold.py — ChromaDB vector store
- [x] memory/warm.py — Redis (with in-memory fallback if Redis not running)
- [x] memory/hot.py — session RAM context
- [x] Gmail, Notion, Google Calendar wrappers (integrations/gmail.py, calendar.py, notion.py)
- [x] career + schedule agents

### Phase 3 — Phone + Security (COMPLETE ✅)
- [x] phone/bridge.py — REST endpoints: /phone/status, /ask, /voice, /history, /tts
- [x] Security hardening of intent classifier — expanded HIGH_SIGNALS list
- [x] CUDA fix: stt.py auto-detects device; fp16 only on CUDA; PHONE_MODEL="base"
- [x] Phone latency: bridge.py uses PHONE_MODEL (base ~1-2s CPU) not large-v3 (10-20s)
- [x] Async fix: ceo.handle() and all agents wrapped in asyncio.to_thread() — event loop never blocked
- [x] API confirmation: CEO.use_api_mode() called on startup — high-risk never hangs on stdin
- [x] Synthesis fix: CEO reads response/explanation/findings/draft_body, not just summary
- [x] Whisper pre-warm: API startup loads base model in background — zero cold-start on first voice request
- [ ] Voice biometric auth (Phase 5+ stretch goal)

### Phase 4 — Agent Mesh (COMPLETE ✅)
- [x] core/bus.py — agent-to-agent context bus (ContextBus + BusMessage, thread-safe)
- [x] CEO updated — runs all matched agents (removed [:1] limit), passes bus to each dispatch, includes bus context in synthesis prompt
- [x] All 3 agents updated — research/schedule/career accept bus=None kwarg, publish outputs to bus; career reads research bus data to enrich prompts
- [x] Inter-agent dependency resolution — career agent automatically uses research findings if research ran first in same request

### Phase 4.5 — Agent Expansion (COMPLETE ✅)
- [x] agents/brainstorm/ — idea structuring, MVP planning, reads research bus
- [x] agents/code/ — AI pair programmer, writes/reviews/debugs Python, reads brainstorm bus
- [x] agents/study/ — MSc AI coursework, explanations, paper summaries, flashcards
- [x] agents/bci/ — EEG/BCI specialist, motor imagery, CSP, Lumineth support
- [x] agents/health/ — gym/sleep/hydration tracker, health_log.json, streak tracking
- [x] agents/comms/ — professional email drafting, risk=high, never auto-sends
- [x] agents/photo/ — Nikon D3400 batch resize/rename/analyse via OpenCV + Pillow
- [x] Total: 10 agents live (research, career, schedule, brainstorm, code, study, bci, health, comms, photo)

### Phase 5 — Proactive OS (COMPLETE ✅)
- [x] core/scheduler.py — AsyncIOScheduler wrapper, SQLite job store, cron/interval/date triggers
- [x] core/alerts.py — in-memory alert queue (scheduler pushes, phone polls)
- [x] core/jobs.py — 3 scheduled jobs: morning_briefing (08:00 UTC), world_news_digest (18:00 UTC), research_digest (Sundays 09:00)
- [x] agents/news/ — world news + morning briefing agent (11th agent, auto-discovered)
- [x] Scheduler REST API — GET /scheduler/jobs, POST /scheduler/jobs/{id}/pause|resume|run-now, DELETE /scheduler/jobs/{id}
- [x] Alert REST API — GET /alerts (phone polls), GET /alerts/all (full history)
- [x] Phone UI updated — proactive alerts appear as amber messages, polls every 30s
- [x] requirements.txt — apscheduler + sqlalchemy + linkedin-api added
- [x] agents/linkedin/ — 12th agent, profile view, job search, person search, draft connection/message, risk=high
- [x] integrations/github.py — list/read/create repos, issues, files, migrate_repo() (old→new account)
- [x] integrations/slack.py — send message, list channels, channel history, upload snippet
- [x] .env — LinkedIn, GitHub (old+new accounts), Slack credentials all set
- [x] .gitignore created — .env, tokens, chroma_db, logs all protected
- [x] Server confirmed live at localhost:8000 — 12 agents, 3 cron jobs running

### Phase 6 — Desktop App (Visual OS Interface)

**Vision:** Not a chat window. A full visual display that responds to voice.
When Cyph says "what's the weather", Zero opens a map with pins and speaks key info.
When Cyph asks for research, visual cards appear. Calendar → timeline view.
Voice + visuals working together. Think Iron Man's Friday, not a chatbot.

**Tech stack for Phase 6:**
| Layer | Tool |
|---|---|
| Desktop framework | Tauri v2 (Rust shell + WebView — lightweight, ~10MB) |
| Frontend | React + TypeScript |
| Animations | Framer Motion (UI transitions) + Three.js (3D/particle effects) |
| Maps | Leaflet.js (weather pins, location display) |
| Charts/data | Recharts or D3.js |
| Voice waveform | Web Audio API (animated when Zero is listening) |
| App ↔ backend | HTTP to FastAPI at localhost:8000 |
| System tray | Tauri tray plugin — wake word runs in background |

**Checklist:**
- [x] Tauri project scaffold — `ui/` folder in Zero root (index.html + src/main.js)
- [ ] System tray process — Zero runs in background, icon in taskbar
- [ ] Wake word triggers app window open/focus
- [ ] Main HUD — dark techy theme, neon accents, glass panels
- [ ] Voice input visualiser — animated waveform when listening
- [ ] Response panel — streamed text with typewriter animation
- [ ] Weather module — map view with location pins + spoken summary
- [ ] Research module — card grid with sources + summary
- [ ] Calendar module — timeline view + spoken agenda
- [ ] Agent status panel — live view of which agent is running
- [ ] Settings panel — API keys, voice selection, agent toggles
- [ ] Packaged Windows installer (.exe / .msi)

### Phase 7 — Agent Improvement (NEXT)

**Goal:** Go through every agent one by one, test them with real queries, rewrite their prompts, improve their output quality, and tune their behavior until each one is exactly how Cyph wants it.

**How to work:** Use the IMPROVE phase in the UI (click LIVE chip) to test each agent live. Then edit the agent's `run.py` prompt directly. Repeat until satisfied. Approve and move on.

**Checklist:**
- [x] Zero CEO — VOICE: sharpened persona (knows Cyph specifically: MSc AI Manchester, BCI/EEG, RTX 4050), anti-filler + no-padding rubric rules (quality.py rules 6-7), adaptive self-fix (recommend_iters: deep/long/high-risk → full ceiling, small tasks → 1 pass). Verified live: small 14s / deep 107s / continuity 13s.
      ORCHESTRATION (same P7 pass): #3 smarter agent routing — registry.find() now does regex tokenization (punctuation-safe), multi-word keyword phrases (dozens of dead keywords like "motor imagery"/"world news"/"job search" now fire), and light stemming. #4 parallel two-wave dispatch — producers (research/brainstorm/schedule) run first, dependents read their bus output in a second parallel wave (preserves Phase-4 enrichment, cuts deep-query latency ~2x). #5 question-aware risk gate — informational questions ("how do I delete my account") no longer trip HIGH. #6 synthesis model tier now follows the same depth signal as self-fix. #8 cold-memory recall widened to 4 hits (kept distance<0.5 bar). All verified by standalone tests; live deploy needs a backend restart. #7 (Anthropic provider) = optional .env key, Cyph's call.
      CLAUDE PROVIDER + 3-TIER MODELS (live): ANTHROPIC_API_KEY wired → router auto-prefers Claude. llm.py now has THREE tiers — fast=Haiku 4.5, capable=Sonnet 4.6, deep=Opus 4.8 — chosen by quality.assess_depth() (small/mid/deep), which also sets self-fix passes (1/2/3; ZERO_SELF_FIX_MAX_ITERS raised to 3 in .env). Two layers of graceful fallback: (a) within-provider deep→capable if Opus unavailable; (b) provider-level chain (anthropic→deepseek→ollama) in chat() — if Claude errors (e.g. billing/credit 400) the next provider serves the call, so Zero never goes dark, and Claude auto-resumes on the next call once it works. NOTE: Anthropic account currently has $0 credits, so Zero is transparently running on DeepSeek via failover until Cyph tops up at console.anthropic.com → Plans & Billing. KNOWN BUG (recurring): schedule agent (Chrono) crashes with "'str' object has no attribute 'time'" — fix when tuning Chrono.
      HERMES-BORROW TRACK COMPLETE ✅ (1) FTS5 hybrid recall ✅, (2) bidirectional MCP client ✅, (3) skill auto-generation ✅, (4) sandboxed execution ✅.
      #4 SANDBOXED EXECUTION (done): new sandbox/ package — executor.py (ExecutionResult dataclass; execute(code, language, timeout) writes code to tempfile, runs via subprocess.run with hard timeout, captures stdout+stderr, truncates at 4k chars, cleans up via TemporaryDirectory; supports python/shell/batch); sandbox.py (run_agent_sandboxed() spawns _worker.py via subprocess with stdin JSON IPC; is_enabled() checks ZERO_SANDBOX_AGENTS env; falls back to in-process on failure); _worker.py (reads JSON from stdin, importlib-loads agent, runs it, writes JSON result to stdout — self-contained for subprocess env). CEO._dispatch() now checks is_enabled() before in-process dispatch — on hit, calls run_agent_sandboxed() with automatic in-process fallback if subprocess fails. Forge (agents/code/run.py): added _wants_execution() gating check; when user says "run it"/"execute this" etc AND code_block exists, calls executor.execute(code_block, timeout=15) and appends the ExecutionResult to the response text — Forge can now actually run generated code. ZERO_SANDBOX_AGENTS=false added to .env (opt-in, default off).
      #3 SKILL AUTO-GENERATION (done): new skills/ package — skill_store.py (SQLite, Skill dataclass, token-overlap find() with MIN_OVERLAP=2) + skill_generator.py (qualifies multi-agent tasks ≥2 agents + >80 char response, calls fast-tier LLM to extract name/description/trigger_phrases/synthesis_hint as JSON, deduplicates by agent_sequence). CEO wired in three places: (a) _select_agents() checks skill_store.find() FIRST — on hit, reuses agent_sequence directly (skips keyword index + LLM ranking), publishes synthesis_hint to bus, increments use_count; (b) _synthesise() reads bus.get("skill_hint") and injects as "Approach note" in prompt; (c) _maybe_save_skill() called after _save_to_memory() — fire-and-forget. Effect: after a successful BCI+research+study query, Zero auto-learns the routing. Next time a similar query comes in, it skips the planning step entirely and the synthesis LLM gets a proven hint. Skills accumulate in skills/skills.db.
      #2 BIDIRECTIONAL MCP CLIENT (done): new core/mcp_client.py — McpClientRegistry singleton. Loads server configs from mcp_client_servers.json (or MCP_CLIENT_SERVERS env var). Each _ServerSession lazy-connects (MCP initialize handshake), caches tools/list, calls tools/call — all via JSON-RPC over httpx (StreamableHTTP + SSE fallback). find_tools() does token-overlap scoring (same approach as registry.find()) so no extra LLM call per request. CEO._run_mcp_tools() runs after both dispatch waves: skips instantly if server_count()==0, otherwise calls matching external tools and injects results into ctx.agent_outputs so synthesis sees them alongside agent outputs. Zero is now a bidirectional MCP participant — both a server (exposes agents) and a client (consumes external tools). Add servers via mcp_client_servers.json; no restart needed for runtime .register() calls.
      #1 FTS5 HYBRID RECALL (done, live): new memory/fts.py — SQLite FTS5 keyword index (stdlib, self-disabling if FTS5 absent) alongside ChromaDB vectors. cold.store()/delete() mirror into it; cold._connect() backfills existing history once (88 docs indexed). New cold.hybrid_search() fuses vector + keyword via Reciprocal Rank Fusion (k=60), degrades to pure vector if FTS down. ceo._load_memory_context() now uses hybrid_search. Wins exact-term recall (RTX 4050, Lumineth, CSP) that embeddings miss. Verified standalone + live ("remind me what GPU I have" → "RTX 4050 6GB").
- [x] V CEO — DONE (P7 item 2): voice + quality parity with Zero, V = "warm companion" to Zero's execution focus. THREE changes: (1) personas.py — added `delivery_note` field to Persona dataclass (Zero=tight, V=lead-with-warmth); rewrote V's system_style with P7 concreteness (knows Cyph specifically: MSc AI Manchester, BCI/EEG/Lumineth, RTX 4050, the grind + pressure), framed as the one who checks in, explicitly not saccharine. (2) quality.py — split the single `_RUBRIC` into `_RUBRIC_COMMON` (rules 1-6: no markdown, human-not-bot, actually-answers, no-meta, consistent, no-filler-opener — bind BOTH) + `_RUBRIC_ZERO` (rule 7 tightness, verbatim from before) + `_RUBRIC_V` (rule 7: warmth REQUIRED and NOT padding, still bans empty filler/fake cheer/going cold); new `_rubric_for(persona_name)` picks by name; `_grade()` uses it. This was the key fix — before, the one Zero-flavored rubric graded V's warmth as "padding" and the self-fix loop stripped it. (3) ceo.py — `_synthesise()` and `_direct_response()` now inject `persona.delivery_note` instead of hardcoded "keep it short / no filler" lines (which pulled V toward Zero's terseness). VERIFIED: standalone proof — same warm draft PASSES under V rubric, FAILS under Zero rubric (flagged warm opener as filler). Live A/B (3 prompt pairs: wellbeing/small-talk/technical) — Zero stays crisp+execution-focused, V leads with warmth + checks in + recalls thesis via hybrid memory, BUT stays fully capable on the technical CSP/EEG question (didn't go mushy). Both markdown-free, both pass self-fix. Zero's path is behavior-preserving (its rubric + delivery_note restate prior behavior verbatim). NOTE: in back-to-back A/B tests V referenced "Zero" by name (pulled the sibling's just-saved answer from memory) — charming but a test artifact, won't happen in normal single-persona use.
- [ ] Iris (Research) — test web search depth, citation quality, conversational prose
- [ ] Maven (Career) — test CV advice, cover letter quality, job strategy depth
- [ ] Chrono (Schedule) — test reminder parsing, calendar event creation accuracy
- [ ] Spark (Brainstorm) — test idea structure, MVP planning, startup thinking
- [ ] Forge (Code) — test code quality, debug reasoning, architecture suggestions
- [ ] Sage (Study) — test ML concept explanations, flashcard quality, paper summaries
- [ ] Synapse (BCI) — test EEG/motor imagery knowledge, Lumineth context awareness
- [ ] Pulse (Health) — test log parsing, streak tracking, workout advice
- [ ] Echo (Comms) — test email tone, professional quality, high-risk preview accuracy
- [ ] Lens (Photo) — test batch processing commands, Nikon D3400 workflow
- [ ] Herald (News) — test briefing quality, news relevance, proactive cron output
- [ ] Nexus (LinkedIn) — test job search results, message drafts, high-risk safety

### Phase 7a — VANTA (System Evolution Agent) ✅

**Goal:** Give Zero a self-awareness layer — an agent that reads all other agents' manifests and logs, diagnoses issues, writes improvement briefs in the VANTA format, and records confirmed changes to per-agent CHANGELOG.md files. Automates what P7 has been doing by hand.

**What was built (2026-06-30):** `agents/vanta/` — manifest.json + run.py (213 lines, 0 deps beyond core.llm). Three modes wired in `run()`:

- **Audit** — rule-based AIM scan (`_load_manifests()` → `_load_agent_health()`): reads every `agents/*/manifest.json` for name/display_name/version/risk_level; tails each `logs/<name>.log` for use_count + avg duration_ms; tails `logs/ceo_actions.jsonl` for outcome strings to attribute recent error counts. No LLM call, output is a sorted health table (errors > slow > unused > healthy) + top finding. First audit live result: Iris=2 errors/22 calls/avg 11s, Herald=avg 33s (slowest), Chrono=2 errors/no log, Sage=2 errors/avg 17.9s.
- **Diagnose** — targeted brief for a named agent. Resolves the agent from the query via word-boundary regex on name + display_name; builds a health snapshot + manifest description; calls the LLM (capable tier, Sonnet) asking for a JSON brief `{whats_wrong, proposed_change, acceptance_criteria, risk, effort}`; returns as `ImprovementBrief.as_text()`.
- **Changelog** — gated on explicit confirmation phrases in the query (e.g. "log this change for research: …"). Extracts the description (text after ":"), bumps patch version, appends to `agents/<name>/CHANGELOG.md` (creates it if absent). No manifest.json mutation.

Risk level: `write` in manifest (changelog writes); CEO's intent classifier sees most diagnose/audit queries as READ and proceeds immediately. Verified standalone: all three modes pass CLI test. First real changelog entry written: `agents/research/CHANGELOG.md` v0.1.1.

**Files:** `agents/vanta/manifest.json`, `agents/vanta/run.py`

**Known open question (unresolved):** VANTA may autonomously write CHANGELOG.md on confirmed phrase — this was the "open question for Cyph" in the ATLAS/PRISM/VANTA brief. Default chosen: require explicit confirm phrase ("log this change for X: …") in the same message. If Cyph wants fully autonomous writes (no confirm phrase needed), change `_CONFIRM_SIGNALS` gating.

### Phase B — Helm (Laptop Access Agent) ✅

**Goal:** Cyph's repeated ask — "I want it to access everything in my laptop". Full
read/write/execute control of the machine from voice or text, with safety that doesn't
nag.

**What was built (2026-09-08):** `agents/system/` — manifest.json + run.py. 14th agent,
display name **Helm**. A fast-tier LLM call parses the request into ONE JSON action; plain
stdlib executes it (`pathlib` / `shutil` / `subprocess` / `os.startfile`).

**Ops:** find · list · read · open · write · append · move · copy · delete · run.

**Path resolution:** if the literal path doesn't exist, the bare filename is searched for
across Desktop/Documents/Downloads/Pictures/Videos, `K:\Zero` and home (bounded os.walk,
prunes node_modules/.git/AppData/PackageCache/etc, caps at 20k dirs / 25 hits). So
"open my dissertation notes" works without knowing the folder.

**Safety model — reversible by default, so no confirmation round-trip is needed:**
- deletes move to `.zero/trash/<timestamp>_<name>` (never `os.remove`) — `undo_hint`
  tells Cyph exactly where it went
- overwrites copy the original to `<name>.bak` first
- `C:\Windows`, `Program Files`, `Program Files (x86)`, `ProgramData` and `K:\Zero\.venv`
  are refused outright (`_is_protected`)
- `run` executes through `sandbox/executor.py` (60s hard timeout, captured stdout/stderr)
  and **destructive** commands (`format`, `del /f`, `rmdir /s`, `rm -rf`, `shutdown`,
  `diskpart`, `reg delete`, `mkfs`…) are refused unless the SAME message contains a
  confirm phrase ("yes run: …") — same-message gating, no cross-turn state needed
- `trash/` added to .gitignore

**Why no confirm-then-execute flow:** a follow-up "yes" wouldn't route back to this agent
(registry matching is static keyword-based), so it would need module state + hijacked
trigger words. Making every file action undoable removes the need entirely. Only genuinely
irreversible things (destructive shell commands) are gated, and gated in one message.

Risk level `high` in the manifest (honest about capability) — note this is metadata only;
the CEO's actual gate runs on the user's text via `core/intent.py`.

**Verified live:** registry discovers 14 agents; `find` located restart-zero.bat; `list`
read Zero Tech (15 items); `run` executed echo; write → read → delete round trip on the
Desktop left a recoverable trash entry. Offline self-check: `python -m agents.system.run`
(asserts write/backup/append/trash/protected-path/dangerous-command-refusal).

**Files:** `agents/system/manifest.json`, `agents/system/run.py`, `agents/system/CHANGELOG.md`

### Phase 8 — ATLAS · PRISM (Planned — Canvas blocked)

**Goal:** Visual render hub (ATLAS) and sectioned anatomy explorer (PRISM). Blocked on prerequisite: **the Dynamic Context Canvas does not exist** in the current React UI. Required groundwork before either can be built:

1. New `Canvas.tsx` React panel (split-screen or slide-over) + idle/active states
2. SSE or WebSocket push channel so agents can send renders asynchronously
3. Typed Canvas component library (`MapView`, `ChartView`, `TableView`, `FlowView`, `ImageGrid`, `SectionExplorer`) — pre-built parametric components ATLAS/PRISM fill with data (runtime agents **cannot** call 21st.dev MCP; that's a build-time Claude Code tool)
4. `/canvas/interact` endpoint for click → follow-up dispatch

Full implementation briefs at `C:\Users\deepe\.claude\plans\binary-puzzling-hejlsberg.md`.

### Phase 9 — UI Polish (After Agent Improvement)

**Goal:** Dedicated pass to make the Zero OS desktop UI exactly how Cyph wants it visually and functionally. Separate from agent work so both can be done properly.

**Checklist:**
- [ ] System tray — Zero runs in background, icon in taskbar, click to focus window
- [ ] Wake word triggers window open/focus from tray
- [ ] Wispr Flow integration — better STT (sign up at wisprflow.ai/developers first)
- [ ] Weather module — map view with location pins + spoken summary
- [ ] Research module — card grid with sources + summary panel
- [ ] Calendar module — timeline view + spoken agenda
- [ ] Agent status panel — real-time view of which agent is firing
- [ ] Settings panel — API keys, voice selection, agent toggles, model routing
- [ ] Animation polish — active agent node pulse, beam brightness on fire
- [ ] Packaged Windows installer (.exe / .msi via Tauri)

---

## Session Log

| Date | What was built | What's next |
|------|---------------|-------------|
| 2026-06-15 | Full Phase 1 complete: folder scaffold, CLAUDE.md, registry.py, research agent, intent.py, ceo.py, api/main.py, api/mcp_server.py, voice/stt.py, voice/tts.py, voice/wake.py, requirements.txt | Phase 2: memory (ChromaDB, Redis), integrations, career + schedule agents. First: install deps with `uv pip install -r requirements.txt` and test the MCP server |
| 2026-06-16 | Phase 2 partial complete: fixed all MCP server boot errors (FastMCP method names, OAuth handshake, host validation, mount ordering), connected Zero to Cowork via ngrok, built memory/hot.py + warm.py + cold.py, built agents/schedule + agents/career | Remaining Phase 2: Gmail/Calendar/Notion integration wrappers. Then Phase 3: phone bridge + security hardening |
| 2026-06-16 | Phase 2 COMPLETE: built integrations/gmail.py (Google OAuth 2.0, read/draft/send), integrations/calendar.py (list/create/delete events, shared OAuth token), integrations/notion.py (search/read/write pages, API token), wired memory into CEO + research agent, updated requirements.txt with Google + Notion packages | Phase 3: phone/bridge.py + security hardening. One-time setup needed: Google Cloud credentials.json + Notion API key |
| 2026-06-16 | Fixed calendar.py → google_calendar.py (was shadowing Python stdlib), added load_dotenv() to all integration __main__ blocks, Notion confirmed working. Gmail OAuth flow pending (add deependk10@gmail.com as test user in GCP → run python integrations/gmail.py) | Phase 3 next session: phone/bridge.py REST API for mobile |
| 2026-06-16 | Phase 3 COMPLETE: phone/bridge.py (5 REST endpoints: /status, /ask, /voice, /history, /tts), mobile chat UI at /phone/ui (dark theme, mic button, TTS playback, PWA-ready), speak_to_bytes() added to voice/tts.py, phone router wired into main.py, PHONE_API_KEY added to .env, intent.py security hardened (expanded HIGH_SIGNALS). Phone connected and working via ngrok. | Phase 4: core/bus.py agent mesh. UI polish later in Phase 6. |
| 2026-06-16 | Phase 4 COMPLETE: core/bus.py (ContextBus + BusMessage, thread-safe, LLM-ready as_context_string()), CEO updated to run all matched agents (removed [:1] limit) + passes fresh bus per request + includes bus in synthesis prompt, research/schedule/career agents updated with bus=None kwarg and publish outputs, career agent reads research bus data to enrich prompts automatically | Phase 5: APScheduler cron triggers, proactive push alerts. Or jump to Phase 6: Tauri desktop app. |
| 2026-06-16 | Phase 4.5 COMPLETE: 7 new agents — brainstorm, code, study, bci, health, comms, photo. All have manifest.json + run.py + bus integration. Total: 10 agents live, all auto-discovered. | Phase 5: APScheduler + push alerts. Or Phase 6: Tauri desktop app. |
| 2026-06-16 | Full project audit + critical fixes: (1) CUDA error fixed — stt.py now auto-detects device, fp16 disabled on CPU, PHONE_MODEL=base added; (2) phone latency fixed — bridge.py uses base model for voice; (3) async fixed — ceo/agents run in thread pool, event loop never blocked; (4) API high-risk fix — CEO.use_api_mode() prevents stdin hang; (5) synthesis fixed — reads all agent output fields; (6) mcp_server.py fixed — individual agent tools also non-blocking. | Phase 5 (APScheduler proactive OS) or Phase 6 (Tauri desktop app). Start server: `uvicorn api.main:app --host 0.0.0.0 --port 8000` |
| 2026-06-16 | Phase 5 ACTIVE: core/scheduler.py (AsyncIOScheduler + SQLite), core/alerts.py (poll queue), core/jobs.py (morning briefing 8am + world news 6pm + research digest Sundays), agents/news/ (11th agent — world news + BCI research), scheduler REST API (/scheduler/jobs), alert REST API (/alerts), phone UI updated with amber alert messages polling every 30s. Install new deps: `pip install apscheduler sqlalchemy` | Phase 5 remaining: business/LinkedIn/Lumineth agents. Phase 6: Tauri desktop app. |
| 2026-06-16 | Phase 5 COMPLETE: agents/linkedin/ (12th agent — job search, profile, draft messages, risk=high), integrations/github.py (dual-account, list/create/migrate repos), integrations/slack.py (send/read/channels), .env fully populated (LinkedIn + GitHub old+new + Slack), .gitignore created. 12 agents live, all syntax clean. | Phase 6: Tauri desktop app (Visual OS Interface). |

| 2026-06-17 | Global rename Astra→Zero complete (39 files). All 12 agents given display names: Iris/Maven/Chrono/Spark/Forge/Sage/Synapse/Pulse/Echo/Lens/Herald/Nexus. wake.py rewritten to use openWakeWord (no account needed). Desktop UI scaffold built: ui/index.html + ui/src/main.js — neural network graph HUD with Three.js, voice waveform, agent nodes, left/right panels, transcript strip. V confirmed as second personal agent (equal control, mellow voice). | Phase 6: Tauri scaffold + run UI. Rename folder K:\\Zero → K:\\Zero\\.zero on Windows. Train zero.onnx wake word model. |
| 2026-06-17 | Phase 6 v0.9 COMPLETE: Tauri v2 app running live. zero.js full brightness/contrast overhaul — all panels readable, bright hexagonal nodes with per-node idle glows, scan arc bright with trail + white head dot, orbit ring visible (38% opacity dashed), idle edge lines visible (18%, was 4%), corner brackets glowing, nucleus orbital rings boosted (32%), input field border/placeholder visible. Tauri v2 maximize fixed (getCurrentWindow). /ask accepts both {input} and {query}. /tts endpoint (no auth) added for desktop TTS. Run UI: `cd K:\Zero\.zero\ui && npm run tauri:dev` | Phase 6 next: system tray, wake word triggers window open, active-state animation polish, then packaged installer. |
| 2026-06-18 | Phase 6 v2.0 — GROUND-UP REWRITE of zero.js. Full-screen neural web replacing 3-column layout. Changes: (1) canvas now fills 100vw×100vh behind glass overlay panels; (2) 12 agent nodes in organic cluster (not circular orbit) positioned as fractions of W×H; (3) drawBeam() extends lines 2x past both node endpoints toward screen edges — "starburst/explosion" effect matching reference video; (4) drawNucleusBeam() extends past each agent toward screen edge; (5) radar sweep from nucleus replacing orbit scan; (6) floating label cards on every node (name + fn/FIRING status); (7) sparks on active connections; (8) /ask now sends {input:query} to fix "input is required" error with old server; (9) left panel 288px (response+input), right panel 172px (roster+active+log), transcript bar 34px bottom between panels. API fix: send {input:query} not {query:query} — works with current server without restart. | Phase 6 next: restart backend server (`uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload`), reload Tauri dev (`npm run tauri:dev`), verify neural web looks like reference. Then: system tray, packaged installer. |
| 2026-06-18 | Reliability + V Persona session. Backend: core/personas.py (Zero=cyan/Charlotte, V=purple/Rachel), voice/wake.py rewritten (DualWakeDetector, openWakeWord, Zero=hey_jarvis/V=hey_mycroft fallbacks), voice/tts.py (strip_markdown_for_speech, per-persona voice routing), core/ceo.py (_direct_response now pulls hot+cold memory context, persona.system_style injected into all synthesis), core/info_store.py (explicit save system, SAVE_TRIGGERS, REST API), api/main.py (persona endpoints /persona/current+switch, /info CRUD, /tts accepts persona param, /health endpoint). UI v3.0: zero.js ground-up rewrite — topbar status chips (persona, active agent with glow, mic/web/mem indicators), left panel replaced with scrolling ACTIVITY feed (30s cap, type-coloured), INFO STORED mini-drawer (collapsed by default, fetches /info, delete buttons), subtitle strip replaces old transcript bar (2-line streaming text, persona-coloured, cursor animation, 3.5s fade), V persona visual theming (purple accent via --pc CSS var, persona-tag overlay, chip v-mode, logo/placeholder switch), persona toggle via chip click → /persona/switch. | Phase 6 next: system tray, wake word triggers window open, packaged installer. |
| 2026-06-18 | Full debug audit PASSED. Verified on-machine: (1) UI renders correctly in browser — all 12 agent nodes (Iris/Maven/Chrono/Spark/Forge/Sage/Synapse/Pulse/Echo/Lens/Herald/Nexus) in organic neural cluster, topbar chips, activity feed, roster, info stored drawer, input field, tab title "Zero OS"; (2) Backend boots cleanly — 12 agents active, DeepSeek LLM, ChromaDB connected, Redis→in-memory fallback, 3 cron jobs, MCP StreamableHTTP, CEO API mode, Whisper base loaded in 1.1s on CPU; (3) End-to-end connectivity confirmed — activity feed showed "[ ZERO ] Zero online. What do you need?" from backend ping on fresh page load. One non-critical warning: Redis not running (in-memory fallback active). | Phase 6 next: system tray (Tauri tray plugin), wake word triggers window focus, packaged Windows installer (.exe/.msi). |
| 2026-06-18 | Reliability + persona pass per build brief. (1) V architecture confirmed: V is a full second CEO persona (not just a skin) — same orchestrator + agent roster + shared memory, but completely distinct personality. (2) Personas deepened: Zero = sharp/confident/casual "brilliant friend", V = warmest/kindest/sweetest person imaginable, genuinely caring, soft and patient. Both have "you are SPEAKING OUT LOUD" instruction, no markdown ever. (3) Voices: Zero = AriaNeural/Charlotte, V = JennyNeural/Rachel — distinct, casual, not formal. (4) Status bar full remodel (v3.1): PERSONA chip | LIVE phase chip | AGENT-NAME · IDLE/LISTENING/THINKING/SPEAKING chip (animated states) | MIC (pulsing when listening) | WISPR (slot ready, disconnected) | WEB · OK/ERR (green/red with 4s timeout back to dim) | MEM (flash animation on write) | clock on right. All wired to real JS state. (5) Info Stored expand button (⤢) opens in-app overlay modal — full list, delete buttons, no native file open. | Next: Wispr Flow integration (Cyph must sign up at wisprflow.ai/developers first), Agent Improvement Phase UI, wake word debug pass, conversation memory audit. |
| 2026-06-18 | On-machine visual audit + bug fix. Full UI verified on screen: all chips rendering (ZERO/LIVE/ZERO·IDLE/MIC/WISPR/WEB/MEM), activity feed clean, 12 agent nodes in neural cluster, roster/active/log panels correct, subtitle strip visible, Info Stored drawer with ⤢ modal wired. Bug fixed: pingBackend() was adding "Zero online" to the feed every 60s — now only logs on first ping or reconnect after offline. Feed stays clean across long sessions. | Next: Wispr Flow integration, Agent Improvement Phase UI, system tray, packaged installer. |
| 2026-06-18 | Agent Improvement Phase UI built (v3.2). New IMPROVE overlay in zero.js: click the LIVE chip to enter IMPROVE mode. 14-card sequential flow: Zero CEO → V CEO → 12 department agents. Each card shows color strip, name, role, description, handles tags, notes textarea, approve badge. Test console on right side shows real agent responses. askZero() wired to route replies into console when improveMode=true. persona_switched handled in askZero() to call applyPersona(). Back/Approve/Next navigation + progress dots. Phase chip toggles LIVE↔IMPROVE. | Next: visual verify on laptop, Wispr Flow integration, system tray. |
| 2026-06-18 | Opus session — 3 upgrades wired in. (1) core/quality.py: self-fixing Build->Grade->Fix loop — every Zero/V answer is graded against a rubric (no markdown, human/calm tone, actually answers, no meta-talk) and auto-rewritten if it fails, up to ZERO_SELF_FIX_MAX_ITERS (default 2); gated by ZERO_SELF_FIX, wired into ceo._synthesise + _direct_response, never raises. (2) core/info_store.py: markdown vault mirror — every saved item now also writes an Obsidian-ready .md (YAML frontmatter + tags) into K:\Zero\Zero Memory as the human-readable source of truth; JSON store stays as the index; added rebuild_vault(). (3) core/llm.py: optional AirLLM "deep brain" backend (Provider.AIRLLM + chat_deep() + airllm_available()) — runs a 70B-class local model on the 6GB GPU, strictly opt-in via AIRLLM_ENABLED/AIRLLM_MODEL, never auto-selected, falls back to capable tier. Backups in _backups/2026-06-18-202346/. All 4 files py_compile clean. | Test on-machine: restart uvicorn + reload UI, say "save this: ..." and check Zero Memory vault, watch a reply get auto-graded. Then Phase 7 per-agent rubrics; optional: pip install airllm to try the deep brain. |

| 2026-06-18 | UI v3.4 (Opus) — decluttered left panel per Cyph. Removed the ACTIVITY feed entirely; replaced with (a) a compact live STATUS widget (agents online / queries / memory writes / persona) and (b) a small RESPONSE window showing the full latest Zero/V answer, themed cyan/glass. Subtitle strip kept for the spoken line. addFeed() now guards on null + forwards to the small right-side LOG so nothing breaks. showResponse()/updateZStatus() added; version bumped v3.2->v3.4. node --check clean. UI backup in _backups/2026-06-18-210325-ui/. | Reload UI (npm run tauri:dev). Next UI: active-agent glow in roster, show V in roster, then match neural-web density to the reference videos. |

| 2026-06-18 | UI v3.5 (Opus) — live-tuned the neural web to match the reference videos, verified in-browser via Claude-in-Chrome. Added dense multicolour starburst filaments (drawBurst, 76 rays), brighter idle beams (edge alpha 0.11->0.22, nucleus 0.13->0.30), extended nucleus beams (ext 2.8->3.2), bigger central bloom, +10 cross-edges for density. Confirmed END-TO-END live: typed a query, Iris fired (bright glow + beams + roster highlight + ACTIVE panel), RESPONSE window filled with clean human non-markdown prose (self-fix loop working), STATUS counters incremented. Note: self-fix loop adds latency (~30-45s on DeepSeek) — tune ZERO_SELF_FIX_MAX_ITERS or set ZERO_SELF_FIX=0 for speed. Backup _backups/2026-06-18-210325-ui/zero.before-viz.js. node --check clean. | Optional next: lower self-fix latency, add V to roster, active-agent glow polish. |

| 2026-06-18 | UI v3.6 (Opus) — close-up rework per Cyph (was "too zoomed out, like an atom from far"). Added ZOOM=0.62 transform in nPos() pulling all 12 nodes toward the nucleus = tight central cluster; enlarged nucleus (rings 22->34, core 15->24, dot 3.5->5.5), bigger nodes (8/11 -> 11/15), longer+denser starburst (76->92 rays, len up to 350), nucleus beams ext 3.2->5.0 so they still reach screen edges. Verified live in Chrome — now reads as a close-up explosion matching the reference video. ONE KNOB to tune feel: ZOOM in nPos() (lower=tighter). Backup _backups/2026-06-18-210325-ui/zero.before-zoom.js. node --check clean. | Fine-tune ZOOM with Cyph; optional active-agent glow polish, add V to roster. |

| 2026-06-18 | UI v4.0 (Opus) — LIVING ATOM ENGINE. Replaced the static ring/radar/burst draw with a physics system: electrons (agent nodes) drift continuously (spring-to-orbit + noise), curved organic links via quadraticCurveTo (NO straight lines), traveling light-pulse particles along bezier paths, emotion state machine currentMood() (idle/listening/thinking/speaking) driving motion energy + glow + pulse rate, energy ripples from nucleus on query. Idle tuned livelier (energy 0.42, constant gentle pulses). Verified live in Chrome: renders, electrons drift, query fires ripples. Backup _backups/2026-06-18-210325-ui/zero.before-atom.js. node --check clean. Tunables for Cyph: ZOOM (cluster tightness), currentMood() idle energy/pulse. NOTE: backend (uvicorn :8000) was offline during test so /ask returned OFFLINE — start it for live answers. | Fine-tune motion/colours with Cyph; verify thinking/speaking pulses once backend up. |

| 2026-06-18 | UI v4.2 (Opus) — nucleus reworked per Cyph into a LIVING morphing blob. (1) Removed solid white core; nucleus is now a hollow set of concentric wave-rings drawn as a continuously-morphing organic blob (blobR/blobPath sum-of-sines, never a perfect circle), as big as the old 2nd ring (~120px). (2) Each agent now sprays multiple task-string filaments (drawFilaments, 7-12 per agent) outward = mini-atom; agent name on the label, tasks as the strings. (3) Audio/mood reactive: real TTS analyser feeds _realAudio (synthetic fallback) -> audioLevel grows the blob + filament length/brightness when speaking. (4) Directional: blob bulges (Gaussian) toward the firing agent — "wave goes toward the agent working" (verified live: asked a query, Iris fired, blob visibly swelled toward Iris). Removed costly per-frame nucleus shadowBlur. Backups: zero.before-v41.js / zero.before-blob.js. node --check clean. | Tunables: blobR harmonics + base(120), drawFilaments len/count, currentMood energies, ZOOM 0.82. Fine-tune feel with Cyph. |

| 2026-06-18 | UI v4.3 (Opus) — nucleus = BLACK HOLE per Cyph. Calmer morph (reduced harmonics, no erratic jitter). Interior filled dark/black (void). ONE highlighted glowing morphing border (no inner concentric rings). Live voice WAVEFORM line(s) inside the void (nucWaveY, amplitude grows with audioLevel/thinking). Agent links now attach to the waveform centre anchor (nucAnchor) so they move WITH the wave. Border still bulges toward the firing agent. Backups: zero.before-blob.js / zero.before-waveform.js. node --check clean. | If black interior not liked, easy revert. Tunables: NBASE, nucWaveAmp, blobR harmonics. |

| 2026-06-18 | UI v4.4+v4.5 (Opus) — big design overhaul per Cyph. v4.4: pure-black universe bg + twinkling star shapes (sparkles); each agent node rebuilt as a STAR-CLUSTER constellation (multiple stars + connecting lines + sparkle); links now attach to the OUTSIDE of the nucleus ring (ringPoint) not the centre; waveform made VERTICAL and only shows on speech; idle = a bright highlight arc rotating on the ring; more depth-varied task-strings (9-16, per-filament depth). v4.5: nucleus reads as a 3D SPHERE (latitude + rotating longitude wireframe arcs clipped inside); side panels blended into the starfield (opacity 0.82->0.30, response box shrunk to 150px, roster rows as small bordered boxes). All node positions ring-anchored. Backups before-v44/before-waveform/before-blob. node --check clean. | Verify 3D sphere + vertical waveform when speaking; tune panel blend / star density with Cyph. |

| 2026-06-19 | UI v5 BRAIN redesign — mockup for approval (Opus). Studied Markdown 4 + 5 references. Built ui/mockup.html: rainbow BRAIN of two hemispheres made of mesh-node clusters, thin VERTICAL voice-core line in centre (hollow, size changes with speech, not waving), agent labels (name + objective, NO numbers) floating on each side with connector lines, subtle starry techy bg, blended corner status/performance text, Cyberpunk-style small subtitle. 4 phases rendered: idle / listening / thinking (active hemisphere brightens) / speaking (core grows + answer subtitle). Awaiting Cyph approval before rewriting real zero.js. | On approval: rebuild zero.js engine to this design (DPR-crisp), then replicate for V with her colour scheme. |

| 2026-06-19 | UI v5.0 BRAIN — REBUILT real zero.js to the approved Markdown 4/5 design (mockup confirmed). Engine replaced: two hemispheres of ~560 glowing additive mesh-nodes (left 6 agents / right 6 agents, coloured per agent), precomputed mesh edges, gentle continuous node drift, thin VERTICAL voice core whose size grows with speech (audioLevel via TTS analyser + synthetic), agent labels (name + objective, no numbers) floating each side with connector lines + active highlight, blended SYSTEM STATUS / PERFORMANCE corner text, subtle starfield, full devicePixelRatio (crisp, no pixelation via soft radial-gradient glow). DOM panels hidden (#right roster, #zstatus, #resp-wrap, #info-drawer); #left slimmed to just the input; subtitle strip recentred (cyberpunk). Verified live: query fired Iris -> its hemisphere brightened, chip THINKING. Backup zero.before-v5brain.js. node --check clean. Mockup at ui/mockup.html. | Next: tune brain density/feel with Cyph; then replicate for V with purple scheme. |

| 2026-06-19 | UI v5.1 — densified the brain to match Markdown 4: ~1150 nodes packed (uniform fill), each linked to nearest neighbours (continuous mesh, not separated blobs), centre gap shrunk to 8px so hemispheres meet at the core line. Switched per-node glow to pre-rendered glow SPRITES (drawImage) for smooth high-quality density at 60fps. Verified live. | Tune density/edge brightness/colour grading with Cyph. |

| 2026-06-19 | UI v5.2 — matched Markdown 4: pure-black bg, dense connected rainbow brain (hue by angle, glow sprites), LOGIC/CREATIVE hemisphere headers, boxed agent labels (name+objective) with connector lines, vertical AI CORE line, corner SYSTEM STATUS/PERFORMANCE. 2D, live (drift + active-region brighten + speech-reactive core). Base to build forward from. Backup zero.before-v52.js. | Next (step by step with Cyph): per-agent region tuning, brain silhouette shape, then V purple variant. |

| 2026-06-19 | UI v5.3 — tightened to Markdown 4: bigger centre GAP (46px) + tall bright vertical core column cleanly splitting the two hemispheres; AI CORE label beside the line; FEWER nodes (~440) with MORE connectors (side-locked triangulated mesh, threshold 72, up to 6 links/node); brightness graded toward centre; ~16% hub stars (bright/large). Backup zero.before-v53.js. | Next: flatter vertical inner edge if wanted; then V purple variant. |

| 2026-06-19 | UI v5.4 — smaller nodes (connector-dominant network) + circular brain dimensions (equal radius R=min(W*0.27,H*0.40,440)), gap 42. Matches Markdown 4 fullscreen. Backup zero.before-v53.js (v53), engine current. | Next: V purple variant, or per-agent stat line. |

| 2026-06-19 | UI v5.5 — matched Markdown 4 layout: removed topbar + side label columns; agent names now drawn at each cluster centroid (near the nodes), coloured; centre line PURPLE (#b06cff); brighter/vivid nodes + connectors (less bland). Kept LOGIC/CREATIVE headers, AI CORE, SYSTEM STATUS/PERFORMANCE corners, bottom input. Backup zero.before-v55.js. | Next: refine name readability if needed; then V purple variant. |

| 2026-06-19 | UI v5.6/5.7 — center line made a clean uniform bright purple BAR (no sword taper); nodes smaller + crisper (tighter glow sprite, sharper core); agent names now CONNECTED to clusters via leader lines + node dot, offset just outside the brain (readable); added outward light STREAKS from outer nodes (shimmer); brightness graded toward centre. Backups before-v55/v57. | Base solid — next: V purple variant, or final polish. |

| 2026-06-20 | UI v7.0 (Opus) — CLEAN REACT+VITE REWRITE of the front-end (Cyph: "scrap the website, start again" — UI only, backend untouched). Replaced the ~1,600-line accreted zero.js with a tidy React+TS+Vite app: `index.html` (root + module entry), `vite.config.ts` (@vitejs/plugin-react), `tsconfig.json`, `src/main.tsx`, `src/App.tsx` (shell: query flow + TTS analyser→audioLevel + persona + health poll), `src/api.ts` (/ask {input}, /tts {text,persona}, /persona/*, /health), `src/brain/agents.ts` (AGENTS, hueFor, geometry), `src/brain/BrainEngine.ts` (imperative three.js node field via ESM `three` + 2D HUD overlay), `src/components/{BrainCanvas,InputBar,Subtitle}.tsx`, `src/styles.css`. three.js now a normal npm ESM dep (dropped vendored global). Tauri shell UNCHANGED (already serves :5173 / builds dist; CSP already OK). SWORD FIXED to the real Markdown 4 shape (studied a 3× PIL crop `_md4_center.png`): a THIN ~6px tapered violet beam + white-hot core + ONE central bloom/lens-flare (NOT the wrong fat blade/nucleus). Brain dead-centred (NF 0.5/0.5), ~0.38×0.71, boxed labels at lobe edges, green-on-left kept. Verified: `tsc --noEmit` clean, dev renders (centre pixel white, AI CORE centred x=0.5, all 12 label boxes, nodes), `npm run build` → dist OK. Old front-end archived in _backups/2026-06-20-174902-pre-react/. | Next: on-screen polish with Cyph (bloom size, node density); port info-store/scheduler/IMPROVE later; V purple theming; tray + installer. |
| 2026-06-19 | UI v6.0–v6.2 (Opus) — three.js/WebGL rewrite of the brain field (Cyph chose WebGL over more 2D tuning). HYBRID renderer: WebGL canvas #bgl draws the node field (THREE.Points custom radial-glow shader, additive LineSegments mesh, outward streaks, CPU drift); 2D canvas #gc stays as the HUD overlay (center line, headers, AI CORE, agent labels, corner status). three.js loaded as a VENDORED GLOBAL build (ui/src/vendor/three.min.js r0.150, UMD window.THREE) so the plain-script/file://-portable architecture survives — NO ESM/bundler dependency. v6.1: hue grading per side (left blue→cyan→GREEN kept per Cyph; right magenta→pink→red→orange→yellow), leaf/wing lobe silhouette. v6.2 (this session): (1) center line rebuilt to Cyph's colour-spec — white-hot #FFFFFF core + violet aura #8A2BE2/#9D4EDD, brightest white bloom at exact centre (removed the hollow-erase band), slim tapered tips, FIXED height + voice-driven WIDTH; (2) line height TIED to brain radius (BRY) so it always matches the lobes; (3) brain shrunk + dead-centred on page (NF=0.5/0.5, R=min(W*0.195,H*0.27,310)) — now ~30%×57% with margins; (4) agent labels pulled IN next to each lobe (dot at BRX+1.8%W, short leaders, anti-overlap) instead of pinned to screen edges. Cyph approved center line + size + green-on-left. Backup _backups/2026-06-19-203307-ui/ (zero.before-three.js, index.before-three.html). node --check clean. NOTE: Claude desktop app masks screen-centre in computer-use screenshots — verified centre via canvas pixel-reads (preview_eval getImageData) instead. | Next: node/connector quality polish + 5 brightness states (dormant→highlighted) from the spec; then V purple variant. |

| 2026-06-19 | UI v6.1 — EXACT Markdown 4 match pass. Sampled the real PNG with PIL (1672x941, 16:9): bg pure black; center line dead-centre violet #7c4ddb / white core #f6f0ff, HOLLOW middle, tips y0.16-0.82; left lobe blue~210->cyan~199 (some green kept per Cyph); right lobe magenta308->pink->red355->yellow-green66. Rendered a faithful static replica (visualize widget) for Cyph to approve as the target. Cyph decisions OVERRIDING pure image-fidelity: labels keep AGENT BRAND COLOURS (not rainbow-by-position), NO numbers (name+objective), KEEP some green left. Changes to zero.js: (1) drawCenterBar body H*0.26 + slim blade tips (H*0.11, base mw*1.5) + destination-out HOLLOW centre ellipse + exact violet; height fixed, WIDTH grows with voice (per earlier Cyph note); (2) hueFor right stops -> 305/322/352/18/58 (left unchanged, green retained); (3) agent labels moved OUT of centroid+/-95 (was overlapping headers) into clean edge COLUMNS — 6 left x~0.035W / 6 right x~0.965W, sorted by centroid-y, stacked y0.21-0.82, leader line + node dot into the lobe, brand colour, NAME + objective, no numbers. ver v6.1. Verified live in preview (screenshot OK this session): columns clean, no header/corner overlap, tips slim, hollow centre reads. node --check clean. | Next: V purple variant; optional fine-tune (tip length, lobe width margins on full-screen). |

| 2026-06-30 | VANTA v0.1.0 — 13th agent, system-evolution. `agents/vanta/manifest.json` + `agents/vanta/run.py` (213 lines). AIM loader: reads every `agents/*/manifest.json` for name/display/version/risk + tails each `logs/<name>.log` for use_count+avg_duration + tails `logs/ceo_actions.jsonl` for error attribution. Three modes: (1) audit — rule-based health table (13 agents, sorted errors>slow>unused>healthy), no LLM; (2) diagnose — LLM (capable/Sonnet) writes `{whats_wrong, proposed_change, acceptance_criteria, risk, effort}` JSON brief for a named agent; (3) changelog — gated on explicit confirm phrase + agent name + description → appends `agents/<name>/CHANGELOG.md` + bumps patch version. First live audit: Iris=2 errors/22 calls/avg 11s, Herald=avg 33s (slowest), Chrono=2 errors/no log, Sage=2 errors. Changelog tested: `agents/research/CHANGELOG.md` v0.1.1 written. Registered automatically by registry.py file watcher on restart. | Restart backend to pick up Vanta. Next: continue P7 agent tuning — VANTA can now be used to generate improvement briefs for each agent. Then: ATLAS/PRISM (Canvas groundwork required first). |

| 2026-06-19 | UI v6.0 — THREE.JS/WebGL REWRITE of the brain (Cyph chose WebGL over more 2D tuning). HYBRID renderer: new `<canvas id="bgl">` (z behind) runs three.js — node `THREE.Points` with a custom radial-glow ShaderMaterial (additive, crisp at full DPR, replaces canvas glow sprites), additive vertex-coloured `LineSegments` mesh, and outward streak LineSegments; existing `#gc` (z front) is now a TRANSPARENT 2D HUD overlay (center bar + headers + agent leader-labels + corners, no black fill). three.js loaded as a VENDORED GLOBAL build at `ui/src/vendor/three.min.js` (r150 UMD, `window.THREE`) via a plain `<script>` before zero.js — keeps the no-bundler file://+Tauri+http.server portability; no package.json/ESM change. Node positions computed CPU-side each frame (drift) into shared Float32 buffers so the mesh + leader lines stay attached. Engine: `initGL/buildBrain/buildGLBuffers/glFrame/glResize/drawCenterBar`. THREE 3 PRIORITISED ELEMENTS done: (1) center voice line = flat UNIFORM bright purple bar (halo+mid+core + soft radial end caps, NO top/bottom taper), height grows with audioLevel; (2) side-specific RAINBOW grading (hueFor: left blue222→cyan→green134, right purple288→pink→orange→yellow52) on LEAF/WING hemispheres (flat vertical inner edge at ±GAP via half-ellipse envelope, RY=R*1.16); (3) node/connector quality — ~470 nodes, ~15% bright/large hubs, side-locked triangulated edges (thr=R*0.17, ≤6/node), streaks brighter toward centre. active-agent brighten wired (brightArr*1.9, sizeArr*1.5). Verified live in preview: THREE r150 loaded, #bgl buffer scaled by DPR 1.25 (crisp), no console errors. Backups `_backups/2026-06-19-203307-ui/` (zero.before-three.js, index.before-three.html). node --check clean. | Cyph to annotate v6.0 vs Markdown 4 for the next one-at-a-time tweak. Known follow-ups: agent labels into clean edge COLUMNS (currently centroid±95, overlaps headers near top); tune brain height/center-bar length; then V purple variant. |

| 2026-09-08 | **Phase B — Helm (14th agent, laptop access)**. `agents/system/{manifest.json,run.py,CHANGELOG.md}`. LLM parses the request into one JSON action; stdlib executes it. Ops: find/list/read/open/write/append/move/copy/delete/run. Filename search falls back across Desktop/Documents/Downloads/K:\Zero/home when the literal path misses (bounded os.walk, skip-list, 20k dir cap). Safety = reversibility: deletes go to `.zero/trash/` with an undo_hint, overwrites make a `.bak`, Windows/Program Files/ProgramData/.venv refused, `run` goes through sandbox/executor.py (60s timeout) and destructive commands need "yes run: ..." in the SAME message. `trash/` gitignored. Verified live: find restart-zero.bat, list Zero Tech, run echo, write→read→delete round trip with recoverable trash. Offline self-check: `python -m agents.system.run`. | Restart backend to load Helm. Then Phase C (ATLAS visualization — needs Canvas groundwork), or Phase D (VANTA-UI). |

| 2026-09-08 | **Repo cleanup sweep (Tier 1 + Tier 2, approved by Cyph).** Removed ~50,600 files: `unity/ZeroOS/{Library,Temp,Logs}` (50,553 regenerable Unity cache files — Unity rebuilds on open; `Assets/` 68 source files, `Packages/`, `ProjectSettings/` all KEPT), the two never-built agent scaffolds `agents/business` + `agents/learning` (.gitkeep only, registry never saw them), 21 `__pycache__` dirs, empty `Claude code memory/`, empty `logs/restart_stdout.log`, all 4 dead UI backup folders in `_backups/` (14 obsolete `zero.js` variants + pre-React snapshot — superseded by the React rewrite; `Zero_OS_Guide.v3.2.backup.pdf` KEPT), the stray second Obsidian vault `K:\Zero\Zero\` (only empty Untitled files — the real vault is `Zero Memory/`, wired to `cold.sync_vault`), 2 stale status pages (`status.html`, `Zero_OS_Status.html` — superseded by this file + the guide PDF), the superseded `2026-06-19-zero-os-handoff.md`, and 10 superseded `Zero Tech` build iterations (kept the newest of each chain; ALSO kept the Donkey Kong base because its "newest" fix is 13KB vs 23.6KB and looks truncated). `.gitignore` extended: unity Library/Temp/Logs/UserSettings, ui/node_modules, ui/dist. Verified after: `api.main` imports clean, registry discovers all 14 agents, .env/logs/memory/vault/Assets/guide/index.html/restart-zero.bat all intact. KEPT deliberately: `Zero Exports/` (32MB UI reference media), `ui/node_modules`, `.agents/skills`, empty `tests/` + `visual/` scaffolds, all of `logs/`. | Restart backend to load Helm. Then Phase C (ATLAS — needs Canvas groundwork) or Phase D (VANTA-UI). |
