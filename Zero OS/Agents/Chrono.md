---
name: Chrono
folder: agents/schedule
risk: write
version: 0.1.0
tags: [zero-os, agent]
---

# Chrono

> schedule management, time-keeping, and calendar planning

| | |
|---|---|
| Folder | `.zero/agents/schedule/` |
| Risk level | `write` |
| Version | 0.1.0 |
| Works with | [[Iris]], [[Maven]] |
| Log | `.zero/logs/schedule.log` |

## What it does

Reminders, deadlines and calendar planning. Knows Cyph's actual context — MSc at Manchester and shifts at Chen's Happy House — so "plan my week" accounts for both.

Historically the buggiest agent: it crashed on **import** for months with `'str' object has no attribute 'time'` because a dataclass field named `time` shadowed the `time` module, so `field(default_factory=time.time)` resolved against the string. Fixed by capturing `_NOW = time.time` before the class body.

## Triggers

It is selected when your message matches any of these (multi-word phrases count):

`schedule`, `calendar`, `remind`, `reminder`, `meeting`, `plan my day`, `when`, `deadline`, `appointment`, `time`, `today`, `tomorrow`, `week`, `agenda`

## Capabilities

`file_read`, `file_write`, `calendar_read`, `calendar_write`

## Run it on its own

```bash
cd K:\Zero\.zero && K:\Zero\.venv\Scripts\python.exe -c "from dotenv import load_dotenv; load_dotenv(); from agents.schedule.run import run; print(run('your query here'))"
```

See [[Commands#Test one agent]] for why `load_dotenv()` is needed.

---
Part of [[Agents]] · [[Zero OS]]
