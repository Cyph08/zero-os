---
tags: [zero-os, moc]
---

# Agents

14 specialists, auto-discovered from `.zero\agents\*\manifest.json` by
`core/registry.py`. Drop a new folder in and it's live after a restart.

**Folder names differ from display names.** Zero speaks the display name; the code uses
the folder.

| Agent | Folder | Risk | For |
|---|---|---|---|
| [[Iris]] | `research` | `read` | Deep research, web + academic search, citations, images |
| [[Sage]] | `study` | `read` | MSc AI coursework, paper summaries, explanations |
| [[Synapse]] | `bci` | `read` | EEG/BCI, motor imagery, CSP, Lumineth |
| [[Spark]] | `brainstorm` | `read` | Idea structuring, MVP planning |
| [[Herald]] | `news` | `read` | World news, AI/tech, morning briefing |
| [[Forge]] | `code` | `write` | Builds and fixes runnable apps and games |
| [[Chrono]] | `schedule` | `write` | Reminders, deadlines, calendar |
| [[Pulse]] | `health` | `write` | Gym, sleep, hydration, streaks |
| [[Lens]] | `photo` | `write` | Nikon D3400 batch processing |
| [[Vanta]] | `vanta` | `write` | Audits and diagnoses the other agents |
| [[Helm]] | `system` | `high` | Full laptop access — find, read, run, move, delete |
| [[Echo]] | `comms` | `high` | Email drafting. Never sends |
| [[Maven]] | `career` | `high` | CV, applications, strategy |
| [[Nexus]] | `linkedin` | `high` | LinkedIn jobs, profiles, message drafts |

## Risk levels

| | |
|---|---|
| `read` | Reads only. Runs immediately. |
| `write` | Creates or modifies files. Says what it will do, then proceeds. |
| `high` | Emails, purchases, destructive ops. Preview and explicit yes. |

A manifest's risk level is **honest labelling of capability**, not the gate. The real gate
runs on your text — [[Architecture#2. Risk gate — core/intent.py]].

## Producers vs dependents

[[Iris]], [[Spark]] and [[Chrono]] run in **wave 1** and publish to the context bus.
Everything else runs in **wave 2** and can read that output. Both waves are internally
parallel.

## Writing a new one

```
agents/<name>/
  manifest.json     name, display_name, description, trigger_keywords,
                    capabilities, risk_level, collaborates_with,
                    model_preference, entry_point, version
  run.py            run(query, bus=None) -> dataclass with .to_dict()
```

Log every action to `logs/<name>.log`. Restart to register it.

## Health

Ask Zero for a system audit and [[Vanta]] builds a live table from every manifest plus
each agent's log tail — use count, average duration, recent errors. No LLM call.

---
[[Architecture]] · [[Zero OS]]
