---
name: Helm
folder: agents/system
risk: high
version: 0.1.0
tags: [zero-os, agent]
---

# Helm

> laptop access: find, read, open, write, move, copy, delete and run anything on Cyph's machine

| | |
|---|---|
| Folder | `.zero/agents/system/` |
| Risk level | `high` |
| Version | 0.1.0 |
| Works with | [[Forge]], [[Lens]] |
| Log | `.zero/logs/system.log` |

## What it does

The laptop-access agent. Full control: find · list · read · open · write · append · move · copy · delete · run.

**Safety is reversibility, not nagging.** Deletes move to `.zero/trash/<timestamp>_<name>` and it tells you the recovery path. Overwrites leave a `.bak`. `C:\Windows`, Program Files, ProgramData and `K:\Zero\.venv` are refused outright. Destructive shell commands (`format`, `rm -rf`, `shutdown`, `diskpart`…) need a confirm phrase in the **same** message: `yes run: <command>`.

**Path resolution:** if the literal path misses, it searches for the bare filename across Desktop, Documents, Downloads, Pictures, Videos, `K:\Zero` and home — so "open my dissertation notes" works without knowing the folder.

## Triggers

It is selected when your message matches any of these (multi-word phrases count):

`file`, `files`, `folder`, `directory`, `my laptop`, `my computer`, `my pc`, `on my machine`, `desktop`, `downloads`, `documents`, `find file`, `search for file`, `locate`, `open file`, `open folder`, `open app`, `launch`, `read file`, `show me the file`, `list files`, `what's in`, `move file`, `copy file`, `rename file`, `delete file`, `remove file`, `trash`, `run command`, `run this`, `execute command`, `terminal`, `powershell`, `cmd`, `disk`, `path`, `save to`, `create file`, `make a folder`

## Capabilities

`file_read`, `file_write`, `file_search`, `code_run`, `app_launch`

## Run it on its own

```bash
cd K:\Zero\.zero && K:\Zero\.venv\Scripts\python.exe -c "from dotenv import load_dotenv; load_dotenv(); from agents.system.run import run; print(run('your query here'))"
```

See [[Commands#Test one agent]] for why `load_dotenv()` is needed.

---
Part of [[Agents]] · [[Zero OS]]
