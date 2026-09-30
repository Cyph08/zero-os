---
tags: [zero-os, project]
---

# Roadmap

## Live

| Phase | What |
|---|---|
| 1 | Brain + voice — registry, intent gate, CEO, FastAPI + MCP, Whisper, Edge TTS, wake word |
| 2 | Memory — [[Memory\|hot/warm/cold]], Gmail/Calendar/Notion wrappers |
| 3 | Phone bridge + security hardening, async everywhere, API confirmation mode |
| 4 | Agent mesh — the [[Architecture#5. The context bus — core/bus.py\|context bus]], all matched agents run, inter-agent enrichment |
| 4.5 | 7 more agents — brainstorm, code, study, bci, health, comms, photo |
| 5 | Proactive OS — scheduler, alert queue, 3 cron jobs, news + LinkedIn agents |
| 7a | [[Vanta]] — system-evolution agent, audit / diagnose / changelog |
| B | [[Helm]] — full laptop access with reversible safety |
| B2 | [[Telegram Interface]] + Kimi provider + hybrid local routing |

## Parked

All three were superseded by [[Telegram Interface|Telegram]]. The code stays on disk and in
git; it is **not active work**.

| Phase | What | Why parked |
|---|---|---|
| 6 | Desktop app — tray, HUD, installer | Telegram needs no window, no build step, and works from the phone |
| 8 | ATLAS / PRISM visual render hub | Blocked on a Dynamic Context Canvas that doesn't exist; Telegram removed the need |
| 9 | UI polish — modules, settings panel, animations | Same |

The React + Vite + Tauri app in `.zero\ui` still builds (`npm run tauri:dev`) and the Unity
HDRP orb project is intact. Revisit only if a desktop HUD is genuinely wanted again.

## In progress — Phase 7: agent tuning

Going through each agent with real queries and rewriting prompts until the output is right.

**Done:** Zero CEO (persona, anti-filler rubric, adaptive self-fix, smarter routing,
parallel dispatch, question-aware risk gate, hybrid recall) · V CEO (persona parity, split
rubrics so warmth isn't graded as padding).

**Remaining:** [[Iris]], [[Maven]], [[Chrono]], [[Spark]], [[Forge]], [[Sage]],
[[Synapse]], [[Pulse]], [[Echo]], [[Lens]], [[Herald]], [[Nexus]].

[[Vanta]]'s audit mode flags candidates from real log data rather than guesswork.

## Open items

- **Kimi key** — `MOONSHOT_API_KEY=` is empty. Once added, re-verify and compare quality
  against the DeepSeek baseline. [[Models and Routing#Kimi — the honest numbers]]
- **Gemini image generation** — blocked on Cloud billing.
  [[Configuration#Known blocker: Gemini image generation]]
- **CUDA torch** — Whisper is CPU-only. [[Hardware]]
- **Warm memory is write-only** — `get_recent_interactions()` is never called.
  [[Memory#Warm — memory/warm.py]]
- **Voice biometric auth** — Phase 5+ stretch goal, never started.

## Verification standard

There is no test suite; `tests/` is empty. The bar is: **syntax check → import check →
standalone agent run → live `/ask` after a restart**, plus the `assert`-based self-checks
in [[Commands#Self-checks that actually assert something]].

Results go to `.zero\docs\final_verification.md`.

---
[[Project History]] · [[Zero OS]]
