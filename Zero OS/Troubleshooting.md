---
tags: [zero-os, guide]
---

# Troubleshooting

Symptom → cause → fix. Commands are in [[Commands]].

---

## Zero doesn't reply at all

The backend isn't running. Start it visibly and watch the window:

```bash
K:\Zero\restart-zero.bat
```

If that says **"Access is denied"**, the old process is admin-owned — right-click →
*Run as administrator*.

Check the port directly: `netstat -ano | findstr :8000`, or `curl http://127.0.0.1:8000/health`.

---

## A change I made did nothing

**You didn't restart.** The registry's file-watcher does not reliably reload existing agent
code or manifest keyword changes, and `--reload` is unreliable for these. Editing
`agents/*/run.py`, `core/*.py` or a `manifest.json` has **no effect** until a full restart.

This is the single most common wasted debugging hour on this project.

---

## Replies are slow

Normal is 10–40s; a build can take 90s. If it's worse:

- **Cold local model** — first call after boot is ~90s while `qwen3.5:4b` loads. Warm it:
  `ollama run qwen3.5:4b "ok"`.
- **Self-fix loop** — up to 3 grade-and-rewrite passes. Set
  `ZERO_SELF_FIX_MAX_ITERS=1` in [[Configuration]].
- **Ollama is down** — every `fast` call waits for the local timeout before falling through
  to cloud. Check `curl http://127.0.0.1:11434/api/tags`.

---

## Zero replies with nothing / an empty message

A reasoning model burned its whole token budget on chain-of-thought. Check
`OLLAMA_THINK=0` and that DeepSeek's `capable` tier is `deepseek-chat`, not
`deepseek-reasoner`. Full explanation: [[Models and Routing#The thinking-model trap]].

---

## It says it can't do something you know it can

e.g. *"I don't have filesystem access to your laptop"* — that is false, [[Helm]] exists.

A **stale learned skill hijacked the routing**. Skills are consulted *before* the keyword
registry, so a bad one short-circuits everything. They live in `.zero\skills\skills.db`
and can be cleared. Tell me when this happens — it's a real bug, not a quirk.

The matcher was fixed (stopwords + a coverage threshold) and five polluted skills purged,
but the mechanism can still learn a bad pattern.

---

## Wrong agent answered

Same cause as above, or a keyword collision. Check the routing in
`logs/ceo_actions.jsonl` — `agents_used` tells you exactly who ran, which is far more
useful than the reply itself.

---

## It claims it did something it didn't

If no agent ran, the CEO answers directly — and with build history in its prompt it used to
fabricate having done the work (*"I baked in higher frame rates"* when no file was
touched). The direct path is now told explicitly that nothing ran.

If you see this again, check `agents_used` in the log. Empty means nothing executed.

---

## A follow-up got treated as a new request

"now add levels" building a second game instead of editing the first. Fixed —
[[Memory#Follow-ups]]. If it recurs, check that `recent_conversation` is on the bus and
that `hot_session.jsonl` is being written.

---

## Voice notes fail

Needs **`ffmpeg` on PATH** to decode Telegram's `.oga`. The bot says so explicitly if it's
missing rather than failing silently.

Transcription is slow because torch is CPU-only (`[stt] CUDA not available`). Works, just
not GPU-fast.

---

## "Redis unavailable … using in-memory fallback"

**Benign.** Redis usually isn't running. Warm memory is not read back by anything anyway —
[[Memory#Warm — memory/warm.py]].

---

## Image generation fails with 429

Gemini's free tier has `limit: 0` for image models — it needs Cloud billing on the key's
project. Gemini Advanced / Google One do **not** grant API quota.
[[Configuration#Known blocker: Gemini image generation]].

---

## Where to look

| | |
|---|---|
| Every request: routing, cost, duration, outcome | `logs/ceo_actions.jsonl` |
| One agent's activity | `logs/<name>.log` |
| Errors with context | `logs/error_log.jsonl` |
| Self-fix grades | `logs/quality_log.jsonl` |
| Live output | the `restart-zero.bat` window |

**Never delete `logs/`** — [[Vanta]] audits from it.

---
[[Commands]] · [[Using Zero]] · [[Zero OS]]
