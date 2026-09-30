---
name: Maven
folder: agents/career
risk: high
version: 0.1.0
tags: [zero-os, agent]
---

# Maven

> career navigation, CV, job applications, and strategy

| | |
|---|---|
| Folder | `.zero/agents/career/` |
| Risk level | `high` |
| Version | 0.1.0 |
| Works with | [[Iris]], [[Echo]] |
| Log | `.zero/logs/career.log` |

## What it does

CV, applications, interview and strategy. `risk_level: high` because it can draft outbound applications — nothing is ever sent without an explicit yes.

## Triggers

It is selected when your message matches any of these (multi-word phrases count):

`cv`, `resume`, `job`, `apply`, `application`, `linkedin`, `career`, `interview`, `cover letter`, `internship`, `graduate`, `placement`, `hire`, `opportunity`, `role`, `position`

## Capabilities

`file_read`, `file_write`, `web_search`, `email_draft`

## Run it on its own

```bash
cd K:\Zero\.zero && K:\Zero\.venv\Scripts\python.exe -c "from dotenv import load_dotenv; load_dotenv(); from agents.career.run import run; print(run('your query here'))"
```

See [[Commands#Test one agent]] for why `load_dotenv()` is needed.

---
Part of [[Agents]] · [[Zero OS]]
