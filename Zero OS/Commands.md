---
tags: [zero-os, reference]
---

# Commands

Everything you'd actually type. Paths are absolute so they work from any shell.

> [!tip] You rarely need any of this
> Zero **starts automatically when you log into Windows**, and you talk to it in
> Telegram. This page is for when something is wrong, or when you're working on
> the code. See [[Using Zero]].

---

## Start / stop

| What                                                | Command                         |
| --------------------------------------------------- | ------------------------------- |
| **Start it (silent)** — what autostart uses         | `K:\Zero\start-zero-hidden.vbs` |
| **Start it with a visible log** — use this to debug | `K:\Zero\restart-zero.bat`      |
| **Stop it**                                         | `K:\Zero\stop-zero.bat`         |

`restart-zero.bat` kills whatever holds port 8000, waits, then launches uvicorn from
`K:\Zero\.venv` on `127.0.0.1:8000`. If it says **"Access is denied"**, right-click →
*Run as administrator* — the running backend is often admin-owned.

**Restart is mandatory after any code change.** The registry's file-watcher does not
reliably reload existing agent code or manifest keyword changes, and `--reload` is
unreliable for these. See [[Troubleshooting#A change I made did nothing]].

```bash
K:\Zero\restart-zero.bat
```

### Autostart

A shortcut `ZeroOS.lnk` lives in the Startup folder. To remove it:

```
Win+R  →  shell:startup  →  delete ZeroOS.lnk
```

Ollama is in the same folder, so the local model comes up on login too.

---

## Manual launch

When you want full control of the flags:

```bash
cd K:\Zero\.zero && K:\Zero\.venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

`.zero\start_backend.bat` does `uv pip install` first and binds `0.0.0.0` with
`--reload` — only use `0.0.0.0` if the phone bridge genuinely needs LAN access.

> [!warning] The venv is at `K:\Zero\.venv`
> Parent of `.zero`, **not** `.zero\.venv`. Wrong interpreter = missing packages.

---

## Is it alive?

```bash
curl http://127.0.0.1:8000/health
```

Or send `/health` in Telegram. To see what's holding the port:

```bash
netstat -ano | findstr :8000
```

---

## Ask Zero from the shell

```bash
curl -s -X POST http://127.0.0.1:8000/ask -H "Content-Type: application/json" -d "{\"input\":\"give me a briefing\"}"
```

Useful when you want to see the raw `agents_used`, cost and routing rather than the
Telegram-formatted reply.

---

## Test one agent

Agents' `__main__` blocks do **not** load `.env`, so load it explicitly or every API
call fails with no key:

```bash
cd K:\Zero\.zero && K:\Zero\.venv\Scripts\python.exe -c "from dotenv import load_dotenv; load_dotenv(); from agents.research.run import run; print(run('compare mamba vs transformers').summary)"
```

Swap `research` for any folder name in [[Agents]]. Run it with cwd = `K:\Zero\.zero`.

---

## Checks before restarting

There is no test suite (`tests/` is empty). Verification is **syntax check → import
check → live `/ask` after a restart**.

```bash
cd K:\Zero\.zero && K:\Zero\.venv\Scripts\python.exe -c "import ast; ast.parse(open('agents/code/run.py',encoding='utf-8').read()); print('ok')"
```

```bash
cd K:\Zero\.zero && K:\Zero\.venv\Scripts\python.exe -c "import api.main; print('imports OK')"
```

### Self-checks that actually assert something

```bash
cd K:\Zero\.zero && K:\Zero\.venv\Scripts\python.exe -m memory.hot
```

```bash
cd K:\Zero\.zero && K:\Zero\.venv\Scripts\python.exe -m agents.system.run
```

```bash
cd K:\Zero\.zero && K:\Zero\.venv\Scripts\python.exe -m phone.telegram_bot
```

`memory.hot` proves the conversation survives a restart. `agents.system.run` asserts
Helm's write/backup/append/trash/protected-path/dangerous-command refusals.
`phone.telegram_bot` asserts message splitting, auth rejection and destructive-pattern
detection — all offline, no token needed.

---

## Local model (Ollama)

| What | Command |
|---|---|
| Is it up? | `curl http://127.0.0.1:11434/api/tags` |
| Start the server | `ollama serve` |
| Pull the model | `ollama pull qwen3.5:4b` |
| Warm it | `ollama run qwen3.5:4b "ok"` |
| What's loaded in VRAM | `ollama ps` |
| GPU usage | `nvidia-smi` |

Cold start is ~90s, warm is ~3s. See [[Models and Routing]] for why it's a 4B model
and not 8B.

---

## Scheduled jobs

```bash
curl http://127.0.0.1:8000/scheduler/jobs
```

```bash
curl -X POST http://127.0.0.1:8000/scheduler/jobs/morning_briefing/run-now
```

| Job | When | What |
|---|---|---|
| `morning_briefing` | 08:00 UTC | Manchester weather, your day, world + AI news |
| `world_news_digest` | 18:00 UTC | News digest |
| `research_digest` | Sundays 09:00 | BCI/AI research digest |

Also `POST /scheduler/jobs/{id}/pause`, `/resume`, and `DELETE /scheduler/jobs/{id}`.
Output lands in Telegram via the alert pump — see [[Telegram Interface]].

---

## Dependencies

```bash
cd K:\Zero\.zero && uv pip install -r requirements.txt
```

Always `uv pip install`, never bare `pip`.

---

## Frontend (parked)

The React/Tauri desktop app still builds but is **not** the interface any more — see
[[Roadmap]].

```bash
cd K:\Zero\.zero\ui && npm run tauri:dev
```

`npm run dev` alone serves Vite at `:5173` and talks to the backend on `:8000`.

---

## Git

```bash
cd K:\Zero && git status
```

Repo is **Cyph08/zero-os, private**. `.env`, `logs/`, `trash/`, `*.db`,
`chroma_db/`, `hot_session.jsonl` and anything matching `*credential*` / `*token*` /
`*secret*` are gitignored — check before committing anything new that holds a key.

---

## Where things live

```
K:\Zero\
  restart-zero.bat        start with a visible log
  start-zero-hidden.vbs   start silently (autostart uses this)
  stop-zero.bat           stop it
  Zero Tech\              apps Forge builds for you
  Zero OS\                this vault
  .venv\                  the Python environment
  .zero\                  the backend
    .env                  all keys and settings
    logs\                 every action, cost and error
    trash\                deleted files, recoverable
    docs\                 setup guides and audit reports
```

---
[[Zero OS]] · [[Troubleshooting]] · [[Configuration]]
