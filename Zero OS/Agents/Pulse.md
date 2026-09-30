---
name: Pulse
folder: agents/health
risk: write
version: 0.1.0
tags: [zero-os, agent]
---

# Pulse

> daily wellness tracker for gym, sleep, and hydration

| | |
|---|---|
| Folder | `.zero/agents/health/` |
| Risk level | `write` |
| Version | 0.1.0 |
| Works with | [[Chrono]] |
| Log | `.zero/logs/health.log` |

## What it does

Gym, sleep, hydration and mood, logged to `memory/health_log.json` with streak tracking. Knows the Chen's Happy House shift pattern, so it schedules training around real availability rather than an ideal week.

## Triggers

It is selected when your message matches any of these (multi-word phrases count):

`health`, `gym`, `workout`, `exercise`, `sleep`, `water`, `hydration`, `mood`, `weight`, `nutrition`, `tired`, `energy`, `rest`, `run`, `training`, `log workout`, `how am i doing`, `streak`, `calories`, `steps`, `recovery`, `sick`, `feeling`, `did gym`, `went to gym`

## Capabilities

`file_read`, `file_write`

## Run it on its own

```bash
cd K:\Zero\.zero && K:\Zero\.venv\Scripts\python.exe -c "from dotenv import load_dotenv; load_dotenv(); from agents.health.run import run; print(run('your query here'))"
```

See [[Commands#Test one agent]] for why `load_dotenv()` is needed.

---
Part of [[Agents]] · [[Zero OS]]
