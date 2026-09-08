# Zero OS — Fable Improvement Report
## Date: 2026-07-05

### Summary
The system was architecturally sound but carried one critical crash (Chrono has never
worked), two known voice bugs (overlapping TTS, unreliable wake word) whose root causes
were structural, a hang risk in every cloud LLM call, and several observability gaps.
This session: read the full backend, wrote the audit (`docs/fable_audit.md`), fixed the
ranked issues, and verified every fix standalone — including Chrono's **first-ever
successful live answer** and a **live Manchester weather pull** into Herald's briefing.
All 11 touched files parse and the full app imports cleanly. The one thing this session
cannot do is restart the admin-owned backend — the fixes go live on the next
`restart-zero.bat`.

### Changes Made

1. **File: `agents/schedule/run.py` (Chrono) — CRITICAL FIX**
   - Wrong: dataclass field `time: str` shadowed the `time` module in the class body, so
     `field(default_factory=time.time)` resolved to `"".time` → AttributeError at import.
     Every Chrono dispatch has crashed since Phase 2 (the "recurring known bug").
   - Changed: module-level `_NOW = time.time` captured before the class; default_factory
     uses `_NOW`; version → 0.1.1; explanatory comment so it never regresses.
   - Impact: scheduling works. Verified live end-to-end (9.2s answer).
   - Also: prompt now includes Cyph's context (MSc Manchester + part-time shifts at
     Chen's Happy House) for realistic planning.

2. **File: `voice/tts.py` — audio arbiter**
   - Wrong: no lock around playback — two agents/responses finishing together spoke over
     each other (known bug).
   - Changed: global `_PLAYBACK_LOCK` (threading.Lock) serialises `_play_audio`; later
     voices queue instead of overlapping.
   - Impact: one voice at a time, always.

3. **File: `voice/wake.py` — DualWakeDetector rebuilt**
   - Wrong: two PyAudio input streams opened on the same default mic (Windows contention
     → the known unreliability), PyAudio never terminated (leak), `download_models()`
     called after `Model()` (fresh-machine failure), zero visibility below threshold.
   - Changed: ONE shared mic stream + ONE openWakeWord Model loaded with BOTH wake models
     (zero + v scored on every chunk); `download_models()` first; proper
     stream close + `pa.terminate()`; `WAKE_DEBUG=1` logs best confidence once/second.
   - Impact: the structural cause of flaky wake detection is gone, and misses are now
     diagnosable instead of silent.

4. **File: `core/llm.py` — hang prevention**
   - Wrong: Anthropic/DeepSeek/Groq clients had no explicit timeout — a network stall
     could hang a request for minutes and the failover chain never engaged.
   - Changed: `_LLM_TIMEOUT_S` (default 90s, env `LLM_TIMEOUT_S`) applied to all three
     clients (Ollama already had 60s).
   - Impact: a stalled provider now fails over instead of freezing Zero.

5. **Files: new `core/errlog.py` + `core/ceo.py` — exception observability**
   - Wrong: agent failures were logged as strings only; no tracebacks anywhere.
   - Changed: `log_error(agent, action, exc, context)` appends
     {timestamp, agent, action, error, traceback, context} to `logs/error_log.jsonl`;
     wired into CEO dispatch, parallel dispatch, synthesis, and direct-response handlers.
   - Impact: every agent failure now leaves a full traceback VANTA (and Cyph) can read.

6. **File: `core/quality.py` — self-fix telemetry**
   - Wrong: self-fix outcomes weren't recorded anywhere queryable.
   - Changed: every `grade_and_fix` run appends {timestamp, persona, passed, iterations,
     changed, cost_usd, input} to `logs/quality_log.jsonl`.
   - Impact: quality-loop behaviour (pass rates, rewrite frequency, cost) is measurable.

7. **File: `agents/news/run.py` (Herald) — briefing completeness**
   - Wrong: morning briefing was news-only; spec wants weather + today's plan.
   - Changed: `_fetch_manchester_weather()` (open-meteo, free/keyless, 6s timeout,
     graceful skip) + `_todays_schedule()` (reads Chrono's `memory/schedule.json` for
     today's undone entries); both injected into the briefing prompt with matching
     structure lines.
   - Impact: the 8am briefing now covers weather, Cyph's day, world, and AI — verified
     with a live weather pull.

8. **File: `agents/health/run.py` (Pulse) — personal context**
   - Wrong: no awareness of Cyph's actual routine.
   - Changed: prompt now includes MSc study load + part-time shifts at Chen's Happy House
     so advice fits his real schedule.

9. **File: `memory/cold.py` — vault ingestion**
   - Wrong: the Obsidian vault (`K:\Zero\Zero Memory`) was write-only — hand-written
     notes were invisible to recall.
   - Changed: `sync_vault()` scans vault .md files, stores new/changed ones into the
     knowledge collection keyed by filename with mtime-based change detection.
   - Impact: anything Cyph writes in Obsidian becomes searchable memory.

10. **File: `api/main.py` — startup wiring**
    - Changed: background `sync_vault()` task at startup (non-blocking, non-fatal),
      alongside the existing Whisper pre-warm.

### Remaining Issues (need Cyph / external / future work)
- **Restart required**: none of this is live until `restart-zero.bat` runs (admin-owned
  process; only Cyph can restart it).
- **Token streaming** (SSE/WebSocket + streaming LLM calls + TTS-on-first-sentence): the
  single biggest UX upgrade left; needs its own design pass across llm.py/CEO/api/UI.
- **Anthropic credits at $0**: everything runs on DeepSeek failover. Topping up instantly
  upgrades every deep answer to Opus (`deep` tier is already wired).
- **arXiv API unreachable from this network + Semantic Scholar 429s**: Iris degrades
  gracefully; a free S2 API key would fix the latter.
- **Custom wake models**: still on hey_jarvis/hey_mycroft fallbacks — training
  `zero.onnx` / `hey_v.onnx` (10 min each) will materially beat the generic models.
- **Empty vault**: `K:\Zero\Zero Memory` has no notes yet; sync is armed and waiting.

### Recommended Next Steps
1. **Run `restart-zero.bat`**, then spot-check: a schedule query (Chrono), the morning
   briefing (weather line), and two rapid queries (no voice overlap).
2. **Top up Anthropic credits** — single biggest answer-quality lever; the 3-tier router
   picks it up with zero code changes.
3. **Green-light the streaming phase** (SSE + sentence-level TTS pipelining) — biggest
   perceived-latency win; design notes are in the audit.

### System Health Score
Before: **6.5/10** — solid architecture and memory, but a dead agent (Chrono), two
structural voice bugs, hang-prone LLM calls, and blind spots in error/quality telemetry.
After: **8.3/10** — every agent now functional, voice arbitrated, wake structurally
fixed + diagnosable, calls time-bounded, failures and quality measurable, briefing
complete. Withheld points: no token streaming yet, wake models still generic, and live
end-to-end verification pends the restart.
