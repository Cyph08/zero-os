---
name: Spark
folder: agents/brainstorm
risk: read
version: 0.1.0
tags: [zero-os, agent]
---

# Spark

> idea structuring, MVP planning, and product thinking

| | |
|---|---|
| Folder | `.zero/agents/brainstorm/` |
| Risk level | `read` |
| Version | 0.1.0 |
| Works with | [[Iris]], [[Forge]] |
| Log | `.zero/logs/brainstorm.log` |

## What it does

Idea structuring, MVP scoping and product thinking. A **producer** — runs in wave 1 and publishes plans that [[Forge]] reads when a build needs a spec.

## Triggers

It is selected when your message matches any of these (multi-word phrases count):

`brainstorm`, `ideas`, `idea`, `plan`, `think`, `feature`, `concept`, `design`, `architect`, `propose`, `what if`, `how should`, `structure`, `outline`, `roadmap`, `strategy`, `vision`, `build`, `create`

## Capabilities

`file_read`, `code_run`

## Run it on its own

```bash
cd K:\Zero\.zero && K:\Zero\.venv\Scripts\python.exe -c "from dotenv import load_dotenv; load_dotenv(); from agents.brainstorm.run import run; print(run('your query here'))"
```

See [[Commands#Test one agent]] for why `load_dotenv()` is needed.

---
Part of [[Agents]] · [[Zero OS]]
