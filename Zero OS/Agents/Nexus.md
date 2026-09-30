---
name: Nexus
folder: agents/linkedin
risk: high
version: 0.1.0
tags: [zero-os, agent]
---

# Nexus

> LinkedIn profile viewing, job search, and connection drafting

| | |
|---|---|
| Folder | `.zero/agents/linkedin/` |
| Risk level | `high` |
| Version | 0.1.0 |
| Works with | [[Maven]], [[Iris]], [[Echo]] |
| Log | `.zero/logs/linkedin.log` |

## What it does

Profile viewing, job search, connection and message drafts. `high` risk — drafts only, never posts or sends.

## Triggers

It is selected when your message matches any of these (multi-word phrases count):

`linkedin`, `connection request`, `connect on linkedin`, `linkedin message`, `job search`, `linkedin profile`, `linkedin jobs`, `reach out on linkedin`, `linkedin outreach`, `networking`, `linkedin post`, `recruiter`

## Capabilities

`web_search`, `file_read`, `email_draft`

## Run it on its own

```bash
cd K:\Zero\.zero && K:\Zero\.venv\Scripts\python.exe -c "from dotenv import load_dotenv; load_dotenv(); from agents.linkedin.run import run; print(run('your query here'))"
```

See [[Commands#Test one agent]] for why `load_dotenv()` is needed.

---
Part of [[Agents]] · [[Zero OS]]
