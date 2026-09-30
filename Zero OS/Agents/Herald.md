---
name: Herald
folder: agents/news
risk: read
version: 0.1.0
tags: [zero-os, agent]
---

# Herald

> world news briefings, AI/tech updates, and BCI research digest

| | |
|---|---|
| Folder | `.zero/agents/news/` |
| Risk level | `read` |
| Version | 0.1.0 |
| Works with | [[Iris]] |
| Log | `.zero/logs/news.log` |

## What it does

World news, AI/tech updates and the BCI research digest. Drives three scheduled pushes — see [[Commands#Scheduled jobs]]. The morning briefing opens with live Manchester weather.

Historically the slowest agent (~33s) because it fans out across several sources.

## Triggers

It is selected when your message matches any of these (multi-word phrases count):

`news`, `headlines`, `today`, `what's happening`, `whats happening`, `current events`, `briefing`, `digest`, `update`, `latest`, `world news`, `global`, `ai news`, `tech news`, `research digest`, `bci news`, `papers`, `arxiv`, `morning briefing`, `daily briefing`

## Capabilities

`web_search`, `file_read`

## Run it on its own

```bash
cd K:\Zero\.zero && K:\Zero\.venv\Scripts\python.exe -c "from dotenv import load_dotenv; load_dotenv(); from agents.news.run import run; print(run('your query here'))"
```

See [[Commands#Test one agent]] for why `load_dotenv()` is needed.

---
Part of [[Agents]] · [[Zero OS]]
