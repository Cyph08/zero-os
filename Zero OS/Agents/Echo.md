---
name: Echo
folder: agents/comms
risk: high
version: 0.1.0
tags: [zero-os, agent]
---

# Echo

> professional email drafting and outbound communications

| | |
|---|---|
| Folder | `.zero/agents/comms/` |
| Risk level | `high` |
| Version | 0.1.0 |
| Works with | [[Maven]], [[Chrono]] |
| Log | `.zero/logs/comms.log` |

## What it does

Drafts professional email. **Never sends.** It produces `draft_body` and stops; sending is yours.

## Triggers

It is selected when your message matches any of these (multi-word phrases count):

`email`, `message`, `reply`, `contact`, `write to`, `reach out`, `draft`, `professor`, `supervisor`, `respond to`, `send to`, `follow up`, `follow-up`, `introduction`, `introduce myself`, `cold email`, `networking`, `thank you email`, `write an email`, `compose`, `get back to`

## Capabilities

`email_draft`, `file_read`

## Run it on its own

```bash
cd K:\Zero\.zero && K:\Zero\.venv\Scripts\python.exe -c "from dotenv import load_dotenv; load_dotenv(); from agents.comms.run import run; print(run('your query here'))"
```

See [[Commands#Test one agent]] for why `load_dotenv()` is needed.

---
Part of [[Agents]] · [[Zero OS]]
