---
name: Vanta
folder: agents/vanta
risk: write
version: 0.1.0
tags: [zero-os, agent]
---

# Vanta

> Zero's system-evolution agent. Maintains a live Agent Intelligence Map (AIM), diagnoses agents from manifests and logs, writes structured improvement briefs, runs system audits, and tracks changes in per-agent changelogs.

| | |
|---|---|
| Folder | `.zero/agents/vanta/` |
| Risk level | `write` |
| Version | 0.1.0 |
| Works with | — |
| Log | `.zero/logs/vanta.log` |

## What it does

Zero auditing itself. Three modes:

- **audit** — rule-based health table built from every manifest plus each agent's log tail (use count, average duration, recent errors). No LLM call.
- **diagnose** — an LLM brief for one named agent: `{whats_wrong, proposed_change, acceptance_criteria, risk, effort}`.
- **changelog** — appends to `agents/<name>/CHANGELOG.md` and bumps the patch version, but **only** when the message contains an explicit confirm phrase (`log this change for research: …`).

## Triggers

It is selected when your message matches any of these (multi-word phrases count):

`improve`, `diagnose`, `audit`, `system audit`, `agent health`, `system health`, `changelog`, `improvement brief`, `vanta`, `system evolution`, `version`, `what's wrong with`, `why is`, `agent performance`, `fix the agent`, `agent review`

## Capabilities

`read_manifests`, `read_logs`, `write_changelog`, `diagnose`, `audit`

## Run it on its own

```bash
cd K:\Zero\.zero && K:\Zero\.venv\Scripts\python.exe -c "from dotenv import load_dotenv; load_dotenv(); from agents.vanta.run import run; print(run('your query here'))"
```

See [[Commands#Test one agent]] for why `load_dotenv()` is needed.

---
Part of [[Agents]] · [[Zero OS]]
