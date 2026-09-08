# Zero OS — Fable Test Results
## Date: 2026-07-05

All tests run standalone from `K:\Zero\.zero` with `K:\Zero\.venv\Scripts\python.exe`
(loading `.env` explicitly). The running backend is admin-owned and was NOT restarted by
this session — live `/ask` tests through the full CEO pipeline require Cyph to run
`K:\Zero\restart-zero.bat` first (see "Deferred live tests" below).

### Passed (verified this session)

| # | Test | Result |
|---|------|--------|
| T0 | Syntax check on all 11 touched files | **PASS** — all parse clean |
| T0b | Full app import (`import api.main`) with all new wiring | **PASS** |
| T1 | `core/errlog.log_error()` writes a JSONL record with full traceback | **PASS** — record verified in `logs/error_log.jsonl` |
| T2 | `quality._log_quality()` writes pass/iters/cost per response | **PASS** — record verified in `logs/quality_log.jsonl` |
| T3 | Herald Manchester weather (open-meteo, live network call) | **PASS** — real data returned: "light drizzle, 15.4 to 20.5 degrees, 67% chance of rain" |
| T4 | Herald `_todays_schedule()` reader | **PASS** — degrades to empty gracefully (no entries today) |
| T5 | `cold_memory.sync_vault()` | **PASS** — runs clean; 0 notes synced because `K:\Zero\Zero Memory` is currently empty (will ingest as notes appear) |
| T6 | **Chrono end-to-end LIVE** (the critical crash fix) | **PASS** — first successful Chrono answer ever recorded: schedule query answered in 9.2s via DeepSeek. Before the fix, every dispatch died at import with `'str' object has no attribute 'time'` |
| T7 | Rebuilt `DualWakeDetector` constructs (models/mic not started headless) | **PASS** |
| T8 | `ScheduleEntry` dataclass instantiates with a `time=` value | **PASS** — the shadowing bug is gone |
| — | LLM failover observed live during T6 (Anthropic $0 credits → DeepSeek) | Working as designed |

### Deferred live tests (need `restart-zero.bat` — admin-owned process)
The code for these is verified; the running server still has the OLD code in memory:

1. **Basic routing** — "What's the latest news in AI today?" → Herald/Iris. (Routing logic
   verified standalone in earlier sessions; briefing now includes weather.)
2. **Memory continuity** — Lumineth/theta-wave fact recall across turns. (Hot-memory
   injection verified in code path; hybrid recall verified live in a prior session.)
3. **Multi-agent parallel dispatch** — two-wave ThreadPoolExecutor verified by code read;
   live latency check pending restart.
4. **Self-fix loop live** — grading now also logs to `quality_log.jsonl`; watch entries
   appear after restart.
5. **Wake word on-mic** — the single-stream dual detector needs a real microphone session:
   run `K:\Zero\.venv\Scripts\python.exe voice\wake.py --dual` (set `WAKE_DEBUG=1` to see
   live confidence scores — new capability).
6. **TTS clean output + no overlap** — `strip_markdown_for_speech` was already good;
   the new playback lock needs two overlapping speaks to prove serialisation.
7. **Memory persistence across sessions** — cold memory verified in a prior session
   ("remind me what GPU I have" → RTX 4050); vault sync now also ingests hand-written
   notes at startup.

### Not fixed in this pass (documented, deliberate)
- **Token streaming (SSE/WebSocket)** — requires a streaming redesign of llm.py + CEO +
  /ask; scheduled as its own phase.
- **arXiv unreachable / Semantic Scholar 429** — network-side; both fail fast in parallel.
- **Iris image search** — Tavily `include_images` not yet wired.
