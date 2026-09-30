---
name: Iris
folder: agents/research
risk: read
version: 0.2.0
tags: [zero-os, agent]
---

# Iris

> Zero's deep research and information retrieval agent

| | |
|---|---|
| Folder | `.zero/agents/research/` |
| Risk level | `read` |
| Version | 0.2.0 |
| Works with | [[Maven]], [[Forge]] |
| Log | `.zero/logs/research.log` |

## What it does

Zero's workhorse. v0.2 does **query decomposition** (splits a question into sub-queries), runs them in parallel via Tavily, and adds academic search (arXiv + Semantic Scholar) for research questions. Personalises answers from Cyph's saved notes and verifies citations before quoting them.

Also pulls **images** — `include_images=True` rides free on the same Tavily call, and the images are published to the bus so [[Telegram Interface]] can send them as photos.

It is a **producer**: it runs in wave 1 and publishes `summary` / `sources` / `findings` to the [[Architecture|context bus]] so dependent agents can read them.

## Triggers

It is selected when your message matches any of these (multi-word phrases count):

`research`, `find`, `search`, `look up`, `what is`, `who is`, `explain`, `summarise`, `summarize`, `information`, `paper`, `papers`, `study`, `arxiv`, `compare`, `deep dive`, `article`, `news`, `latest`, `current`, `facts`, `overview`, `define`, `definition`

## Capabilities

`web_search`, `academic_search`, `file_read`, `summarise`

## Run it on its own

```bash
cd K:\Zero\.zero && K:\Zero\.venv\Scripts\python.exe -c "from dotenv import load_dotenv; load_dotenv(); from agents.research.run import run; print(run('your query here'))"
```

See [[Commands#Test one agent]] for why `load_dotenv()` is needed.

---
Part of [[Agents]] · [[Zero OS]]
