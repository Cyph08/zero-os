---
name: Sage
folder: agents/study
risk: read
version: 0.1.0
tags: [zero-os, agent]
---

# Sage

> MSc AI coursework, paper summaries, and deep explanations

| | |
|---|---|
| Folder | `.zero/agents/study/` |
| Risk level | `read` |
| Version | 0.1.0 |
| Works with | [[Iris]], [[Synapse]] |
| Log | `.zero/logs/study.log` |

## What it does

MSc AI coursework: concept explanations, paper summaries, flashcards. Pairs with [[Synapse]] on anything EEG-shaped.

## Triggers

It is selected when your message matches any of these (multi-word phrases count):

`study`, `learn`, `explain`, `revision`, `exam`, `lecture`, `concept`, `understand`, `course`, `module`, `university`, `MSc`, `paper`, `summarise paper`, `summarize paper`, `teach me`, `how does`, `what is`, `transformer`, `reinforcement learning`, `neural network`, `backprop`, `gradient`, `attention`, `flashcard`, `quiz`, `assignment`

## Capabilities

`web_search`, `file_read`

## Run it on its own

```bash
cd K:\Zero\.zero && K:\Zero\.venv\Scripts\python.exe -c "from dotenv import load_dotenv; load_dotenv(); from agents.study.run import run; print(run('your query here'))"
```

See [[Commands#Test one agent]] for why `load_dotenv()` is needed.

---
Part of [[Agents]] · [[Zero OS]]
