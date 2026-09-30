---
tags: [zero-os, project]
---

# Project History

What was built when, and the bugs worth remembering. The full blow-by-blow session log
lives in `.zero\CLAUDE.md`.

| Date | What |
|---|---|
| 2026-06-15 | Phase 1 — scaffold, registry, intent gate, CEO, FastAPI + MCP, Whisper, Edge TTS, wake word |
| 2026-06-16 | Phase 2–5 — memory tiers, Gmail/Calendar/Notion, phone bridge, [[Architecture#5. The context bus — core/bus.py\|context bus]], 7 new agents, scheduler + alerts, LinkedIn agent. 12 agents live |
| 2026-06-17 | Global rename Astra → Zero (39 files). Display names assigned. V confirmed as a second persona |
| 2026-06-18 → 06-20 | Long UI arc: Tauri v2 → neural web → living atom → black-hole nucleus → rainbow brain → clean React + Vite + three.js rewrite. Also `core/quality.py` self-fix loop, Obsidian vault mirror, optional AirLLM deep brain |
| 2026-06-30 | [[Vanta]] — 13th agent. Audit / diagnose / changelog |
| 2026-09-08 | [[Helm]] — 14th agent, full laptop access. Repo cleanup sweep: ~50,600 files removed (Unity caches, dead scaffolds, obsolete UI backups, stray vault, superseded builds) |
| 2026-09-28 | [[Telegram Interface]], Kimi provider, hybrid local routing. All 14 agents verified live |
| 2026-09-29 | Routing hijack by stale learned skills fixed · autostart + [[Using Zero\|usage guide]] |
| 2026-09-29 | Conversation continuity fixed — [[Memory#Follow-ups]] |
| 2026-09-30 | This vault |

---

## Bugs worth remembering

Each of these cost real time, and several were invisible until something ran for real.

### `'str' object has no attribute 'time'` — [[Chrono]] dead for months

A dataclass field named `time: str` shadowed the `time` **module** inside the class body, so
`field(default_factory=time.time)` resolved against the string. It crashed on **import**, so
Chrono never ran at all.

```python
_NOW = time.time          # captured BEFORE the dataclass
...
    created_at: float = field(default_factory=_NOW)
```

### Reasoning models return empty content

`deepseek-reasoner` and `qwen3.5` burn the whole token budget on chain-of-thought and return
empty `content` with finish reason `length`. Zero replied with nothing — and was billed.
Full detail: [[Models and Routing#The thinking-model trap]].

### A stale skill made Zero deny having Helm

Asked to find a file, Zero said *"I don't have filesystem access to your laptop"*. The
learned-skill store matched on 2 raw tokens against the union of a skill's trigger phrases —
~30 filler-heavy words — and short-circuited routing before the keyword registry. Fixed with
stopwords plus a coverage threshold; 5 polluted skills purged.
[[Architecture#3. Agent selection — core/ceo.py]]

### Agents never saw the conversation

`run(query, bus)` got the current sentence only, so every follow-up was a brand-new request
and [[Forge]] shipped unrelated games. [[Memory#Follow-ups]].

### Hot memory was RAM-only

Zero autostarts on login, so every reboot wiped the conversation while Telegram still showed
the history. [[Memory#Hot — memory/hot.py]].

### The Telegram alert pump crashed on import

It imported `alerts` when the singleton is `alert_queue`. The `ImportError` inside the task
silently killed all proactive briefings. **Only running the bot live caught it** — the
offline self-check couldn't.

### `_api_confirm` always returned False

HIGH-risk actions could therefore **never** be approved in API mode, so the phone bridge's
"confirm in the next message" promise was unfulfillable. Fixed with
`handle(user_input, confirmed=True)`.

### `import time` missing from `llm.py`

Would have raised `NameError` on the 429 retry path — a branch that only runs under rate
limiting, so it would have surfaced at the worst moment.

### A live Anthropic key was hardcoded

In `ClaudeBridge.cs:8` and a Unity scene file. Caught pre-commit; never reached GitHub.
`.gitignore` also had a gap — `credentials.json` didn't match `google_credentials.json`.
Both fixed with broad patterns. [[Configuration]].

### My own test harness had no API keys

`load_dotenv()` resolves relative to the calling file, so a scratchpad harness loaded
nothing. It produced a confident, wrong diagnosis of DeepSeek rate limiting. Harnesses now
use an explicit path and assert the key is present.

---

## Lessons that stuck

- **Offline self-checks cannot replace running it.** The alert-pump `ImportError` and the
  routing hijack were both invisible to passing tests.
- **Read the routing, not just pass/fail.** A 14/14 pass table hid an agent claiming it
  couldn't do something it can. `agents_used` is the column that matters.
- **Fix it where all callers route through.** A guard in one shared function beats a guard in
  every caller — and patching only the reported path leaves the siblings broken.
- **Use the right tool.** Image generation is an image-generation call, not a Pillow pipeline.

---
[[Roadmap]] · [[Zero OS]]
