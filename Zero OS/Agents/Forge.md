---
name: Forge
folder: agents/code
risk: write
version: 0.2.0
tags: [zero-os, agent]
---

# Forge

> AI pair programmer, code writing, review, and debugging

| | |
|---|---|
| Folder | `.zero/agents/code/` |
| Risk level | `write` |
| Version | 0.2.0 |
| Works with | [[Iris]], [[Spark]] |
| Log | `.zero/logs/code.log` |

## What it does

Builds **self-contained single-file HTML apps and games**, saves them to `K:\Zero\Zero Tech\`, and opens them in the browser. The file is sent to you in Telegram as a document.

**Iteration.** A follow-up in the same conversation edits the file it just built rather than creating a new one — "create levels with three lives each" after a snake game modifies the snake game. It keeps the same filename and leaves the previous version as `<name>.html.bak`. A request for a whole new artifact ("make me *a* racing game") starts a fresh file but still carries every requirement from earlier in the conversation. See [[Memory]] for why this needed fixing.

One automatic QA pass runs over each fresh build to catch bugs that would stop it opening (unattached listeners, a loop that never starts). Skipped on large drafts and on iterations. Disable with `FORGE_BUILD_REVIEW=0`.

Can **execute** code only when you explicitly say "run it" — through `sandbox/executor.py` with a hard timeout.

## Triggers

It is selected when your message matches any of these (multi-word phrases count):

`code`, `write`, `debug`, `fix`, `review`, `implement`, `function`, `script`, `python`, `error`, `bug`, `refactor`, `class`, `module`, `import`, `test`, `unittest`, `pytest`, `explain this code`, `what does`, `app`, `website`, `web app`, `webpage`, `web page`, `make an app`, `build a website`, `make a website`, `build an app`, `create a game`, `make a game`, `landing page`, `html`, `frontend`, `build me`, `make me`

## Capabilities

`file_read`, `file_write`, `code_run`

## Run it on its own

```bash
cd K:\Zero\.zero && K:\Zero\.venv\Scripts\python.exe -c "from dotenv import load_dotenv; load_dotenv(); from agents.code.run import run; print(run('your query here'))"
```

See [[Commands#Test one agent]] for why `load_dotenv()` is needed.

---
Part of [[Agents]] · [[Zero OS]]
