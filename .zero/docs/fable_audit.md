# Zero OS — Fable Audit Report
## Date: 2026-07-01

> Path correction applied throughout: the backend root is `K:\Zero\.zero\` (not `K:\Zero\`).
> Docs land in `K:\Zero\.zero\docs\`, logs in `K:\Zero\.zero\logs\`, the Obsidian vault is
> `K:\Zero\Zero Memory\`. Agent count correction: there are **13** department agents
> (research, career, schedule, brainstorm, code, study, bci, health, comms, photo, news,
> linkedin, vanta) — "14" in the UI counts the ZERO and V persona pills.

### System Overview
Zero OS is in far better shape than a cold audit would expect: the architecture is coherent
(keyword+LLM routing → two-wave parallel dispatch → bus → persona synthesis → self-fix loop →
4-tier memory), there are **zero bare `except:` clauses** in the backend, every agent logs
structured lines, hot-memory injection genuinely happens on every CEO prompt, STT has CUDA
auto-detect + real VAD, warm memory has a working in-memory fallback, and the persona-aware
quality rubric exists and is wired. The real problems are concentrated: one **critical crash
bug in Chrono** (root cause found — a dataclass field shadowing the `time` module), a
**missing TTS audio lock** (the known overlapping-voices bug), a **structurally unreliable
dual wake-word design** (two PyAudio streams fighting over one mic), **no response streaming**,
and several observability gaps (no error_log.jsonl, no quality-score log, no LLM timeouts).

### File-by-File Findings

**core/ceo.py** — Orchestrator. GOOD: skill-store shortcut, build/iterate override to Forge,
research→build pipeline, two-wave ThreadPoolExecutor parallel dispatch (achieves the
"parallel dispatch" goal without asyncio), depth-driven tier + self-fix budget, hot+cold
hybrid memory injected in BOTH `_synthesise` and `_direct_response`, saved-file short-circuit.
WEAK: agent errors are caught and stuffed into outputs but nothing writes a machine-readable
error log; no retry on agent failure. Severity: Minor (logging), Minor (retry).

**core/registry.py** — Auto-discovery + keyword index with regex tokenization, multi-word
phrases, light stemming (verified by session log + routing behaviour). GOOD. Not re-read in
full this pass. Severity: —

**core/intent.py** — Keyword risk gate; HIGH>WRITE>READ; informational-question downgrade;
confirmation handler; logs every classification. GOOD. Note: single-word signals like
"send"/"buy" only match as whole tokens (sane). Severity: —

**core/quality.py** — Build→Grade→Fix. GOOD: env gate `ZERO_SELF_FIX`, bounded iters,
persona-aware rubrics (V's warmth explicitly not filler; rule 6 bans "Great question/Of
course/Certainly/As an AI" openers), never raises, cheap fast-tier grading, actionable
critique fed to the fix prompt. GAP vs prompt spec: grader is PASS/FAIL not 0-10 scores —
functionally equivalent and cheaper; keeping. MISSING: per-response score logging to
`logs/quality_log.jsonl`. Severity: Minor.

**core/llm.py** — 3-tier router (fast/capable/deep) with provider failover
(anthropic→deepseek→groq→ollama), within-provider deep→capable fallback, honest per-model
cost accounting, opt-in AirLLM deep brain. WEAK: Anthropic/DeepSeek/Groq clients constructed
with **no explicit timeout** (SDK defaults can hang for minutes); Ollama has one (60s).
Severity: Major (hang risk under network trouble).

**core/mcp_client.py / api/mcp_server.py** — Bidirectional MCP verified working in prior
sessions (StreamableHTTP, agents exposed as tools, `zero_list_agents`/`zero_ask` utility
tools registered at import — seen in live boot logs this session). Not re-read line-by-line.
Severity: —

**agents/schedule/run.py (Chrono)** — **CRITICAL, root cause found.** In `ScheduleEntry`,
the field `time: str = ""` binds `time = ""` into the class namespace; the next line
`created_at: float = field(default_factory=time.time)` then resolves `time` to that empty
string → `AttributeError: 'str' object has no attribute 'time'` **at import**, so every
dispatch to Chrono crashes. This is exactly the recurring bug in the session log
("Chrono=2 errors/no log" in VANTA's audit — no log because run() never executes).
Severity: **Critical**.

**agents/research/run.py (Iris)** — v0.2.0 (upgraded this week): query decomposition,
parallel multi-search, dedup, academic arXiv/S2 (fail-fast; arXiv unreachable from this
network, S2 429s without key), personalization from cold memory, verified citations,
structured findings, Tavily retry. Real results confirmed live (10 sources, cited answer).
Tavily calls have no explicit timeout parameter (SDK default). No image search (Tavily
`include_images` unused). Severity: Minor ×2.

**agents/code/run.py (Forge)** — v0.2.x: app builds saved to `K:\Zero\Zero Tech` + opened,
iterate-on-last-build (reads the real file), truncation continuation, QA self-review pass,
build-only routing. GOOD. Severity: —

**agents/news/run.py (Herald)** — v0.2.0 parallel basic-depth searches (33s→~5s fix already
applied). GAP vs Cyph's spec: morning briefing has world+AI news only — **no Manchester
weather, no today's schedule/reminders**. Severity: Major (briefing incomplete).

**agents/bci/run.py (Synapse)** — Rich Lumineth context confirmed (vision, latent-space
mapping, P300 plans, CSP/motor imagery). GOOD; prompt is not thin. Severity: —

**agents/study/run.py (Sage)** — Grounded in MSc AI Manchester curriculum. GOOD. Severity: —

**agents/career/comms/photo/linkedin/brainstorm/health** — All prompts are
Cyph-specific (MSc/Manchester/D3400/Zero OS context confirmed by sweep). GAP: **"Chen's Happy
House" (part-time job) appears nowhere** — Cyph explicitly wants Chrono and Pulse aware of it
for scheduling. Severity: Minor.

**agents/vanta/run.py** — Audit/diagnose/implement/changelog all working (implement rewrites
target run.py with backup + changelog). GOOD. Severity: —

**memory/hot.py** — 50-entry cap enforced, `as_context_string(n=10)` injected first in every
CEO prompt path, cleared only on restart. GOOD. Severity: —

**memory/warm.py** — Redis with verified `_InMemoryFallback` (TTL-aware). Research cache
read/write confirmed live. GOOD. Severity: —

**memory/cold.py + fts.py** — ChromaDB + FTS5 hybrid RRF (`hybrid_search`, `search_all`)
verified live earlier ("RTX 4050" recall test passed; 88 docs backfilled). GAP: the Obsidian
vault `K:\Zero\Zero Memory\` is **write-only** (info_store mirrors saves out) — cold memory
never reads vault edits back in. Severity: Minor.

**voice/stt.py** — CUDA auto-detect, fp16 only on CUDA, OOM fallback to medium/CPU, real VAD
(`record_until_silence`, RMS threshold + 1.5s silence stop), model cache, phone uses base
model. GOOD. Severity: —

**voice/tts.py** — Per-persona voices (Zero=Sonia/Charlotte, V=Jenny/Rachel), thorough
`strip_markdown_for_speech` (code/headers/bold/bullets/links/tables/quotes), EL→Edge
fallback. **MISSING: global audio lock** — two concurrent `speak()` calls overlap playback
(the known simultaneous-voices bug). `edge_speak` uses `asyncio.run` (safe only from sync
threads — currently true). Severity: **Major**.

**voice/wake.py** — Both personas registered; fallback models (hey_jarvis/hey_mycroft); BUT
`DualWakeDetector` opens **two PyAudio input streams on one default mic** (classic Windows
contention → the known unreliability), PyAudio instances are never `terminate()`d,
`download_models()` runs *after* `Model()` (first run can fail), and there is **no
below-threshold confidence logging** so failures are invisible. No window-focus trigger
(that's a UI/tray concern — Phase 9). Severity: **Major**.

**api/main.py** — /ask (both {input}/{query}), /tts, /persona/*, /health, /info, /scheduler,
/alerts, phone bridge, CORS `*`, whisper pre-warm, CEO API-mode. **No streaming of any kind**
(no WebSocket/SSE/StreamingResponse) — responses arrive all-at-once; the UI fakes word-by-word
client-side. Severity: Major (perceived latency; real token streaming needs llm.py + CEO
pipeline changes — scheduled as next-phase work, not a quick fix).

**skills/ + sandbox/** — Skill store checked FIRST in `_select_agents` (verified in ceo.py),
auto-distillation after multi-agent success; sandbox opt-in via env with in-process fallback.
GOOD (per code + session-log verification). Severity: —

**core/jobs.py** — Three crons exactly as specced: daily 08:00, daily 18:00, Sunday 09:00.
Briefing quality inherits Herald's gaps (no weather/schedule). Severity: see Herald.

### Ranked Issue List
1. **[Critical]** Chrono crashes on import — dataclass field `time` shadows `time` module →
   `'str' object has no attribute 'time'` — File: `agents/schedule/run.py` — Impact: the
   entire scheduling agent has never worked reliably.
2. **[Major]** No global TTS audio lock — File: `voice/tts.py` — Impact: overlapping voices
   when two responses/agents speak (known bug).
3. **[Major]** Dual wake detector = 2 streams on 1 mic + leaked PyAudio + no confidence
   visibility — File: `voice/wake.py` — Impact: the known wake-word unreliability.
4. **[Major]** No LLM client timeouts (Anthropic/DeepSeek/Groq) — File: `core/llm.py` —
   Impact: a network stall can hang a request for minutes.
5. **[Major]** Herald briefing missing Manchester weather + today's schedule — Files:
   `agents/news/run.py` — Impact: the 8am briefing under-delivers vs spec.
6. **[Major]** No `logs/error_log.jsonl` with tracebacks — Files: new `core/errlog.py` +
   CEO dispatch — Impact: failures are hard to diagnose after the fact.
7. **[Minor]** No `logs/quality_log.jsonl` of self-fix outcomes — File: `core/quality.py`.
8. **[Minor]** Chen's Happy House absent from Chrono + Pulse context — Files:
   `agents/schedule/run.py`, `agents/health/run.py`.
9. **[Minor]** Obsidian vault not synced INTO cold memory — File: `memory/cold.py`.
10. **[Major-but-deferred]** No token streaming (SSE/WebSocket) end-to-end — Files:
    `api/main.py` + `core/llm.py` + CEO — Impact: perceived latency; requires a streaming
    pipeline redesign, scheduled as its own phase, not a patch.

### Improvement Plan (execution order)
1. Fix Chrono dataclass bug (critical crash; 2-line fix, huge win).
2. Add global TTS playback lock + queue semantics (threading.Lock in `_play_audio`).
3. Rework DualWakeDetector: ONE mic stream + ONE openWakeWord Model loaded with BOTH wake
   models, per-model thresholds, WAKE_DEBUG=1 confidence logging, proper PyAudio terminate,
   download_models() before Model().
4. Add explicit timeouts to Anthropic/DeepSeek/Groq clients (60s) in `core/llm.py`.
5. Create `core/errlog.py` (`log_error()` → `logs/error_log.jsonl` with traceback) and wire
   it into CEO agent-dispatch exception paths + llm failover.
6. Add quality-score logging to `logs/quality_log.jsonl` in `grade_and_fix`.
7. Enrich Herald briefing: Manchester weather via open-meteo (free, keyless) + today's
   entries from `memory/schedule.json`.
8. Add Chen's Happy House context lines to Chrono + Pulse prompts.
9. Add `sync_vault()` to cold memory (scan `K:\Zero\Zero Memory\*.md`, store new/changed) —
   best-effort at startup.
10. Defer: token streaming (document design), image search in Iris, window-focus on wake
    (Phase 9 tray work).

Order rationale: crash first, then the two known-bad voice bugs, then hang-prevention, then
observability, then content quality, then nice-to-haves.
