---
name: Lens
folder: agents/photo
risk: write
version: 0.1.0
tags: [zero-os, agent]
---

# Lens

> Nikon D3400 photo batch processing and analysis

| | |
|---|---|
| Folder | `.zero/agents/photo/` |
| Risk level | `write` |
| Version | 0.1.0 |
| Works with | — |
| Log | `.zero/logs/photo.log` |

## What it does

Nikon D3400 batch work — resize, rename, analyse via OpenCV + Pillow. Knows the D3400 produces 24MP raw files and routes advice by RAW vs JPEG.

## Triggers

It is selected when your message matches any of these (multi-word phrases count):

`photo`, `image`, `picture`, `nikon`, `D3400`, `shoot`, `batch`, `resize`, `crop`, `edit`, `process`, `jpg`, `jpeg`, `raw`, `NEF`, `SD card`, `export`, `rename`, `organise photos`, `organize photos`, `colour grade`, `color grade`, `brightness`, `contrast`, `sharpen`, `watermark`, `thumbnail`, `portfolio`

## Capabilities

`file_read`, `file_write`

## Run it on its own

```bash
cd K:\Zero\.zero && K:\Zero\.venv\Scripts\python.exe -c "from dotenv import load_dotenv; load_dotenv(); from agents.photo.run import run; print(run('your query here'))"
```

See [[Commands#Test one agent]] for why `load_dotenv()` is needed.

---
Part of [[Agents]] · [[Zero OS]]
