---
name: Synapse
folder: agents/bci
risk: read
version: 0.1.0
tags: [zero-os, agent]
---

# Synapse

> EEG/BCI specialist, motor imagery, and Lumineth research

| | |
|---|---|
| Folder | `.zero/agents/bci/` |
| Risk level | `read` |
| Version | 0.1.0 |
| Works with | [[Iris]], [[Sage]] |
| Log | `.zero/logs/bci.log` |

## What it does

EEG/BCI specialist — motor imagery, CSP, Euclidean alignment, cross-subject transfer, and Lumineth. This is the agent closest to Cyph's dissertation work, so it gets the most technically demanding questions.

## Triggers

It is selected when your message matches any of these (multi-word phrases count):

`BCI`, `EEG`, `motor imagery`, `brain computer interface`, `electrode`, `signal`, `classification`, `neural`, `P300`, `SSVEP`, `ERD`, `ERS`, `Lumineth`, `MNE`, `epochs`, `bandpass`, `CSP`, `common spatial pattern`, `artifact`, `alpha`, `beta`, `gamma`, `mu rhythm`, `brainwave`, `openBCI`, `neurofeedback`, `decoder`, `spike`, `LFP`

## Capabilities

`web_search`, `file_read`

## Run it on its own

```bash
cd K:\Zero\.zero && K:\Zero\.venv\Scripts\python.exe -c "from dotenv import load_dotenv; load_dotenv(); from agents.bci.run import run; print(run('your query here'))"
```

See [[Commands#Test one agent]] for why `load_dotenv()` is needed.

---
Part of [[Agents]] · [[Zero OS]]
