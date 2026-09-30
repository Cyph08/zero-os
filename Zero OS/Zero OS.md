---
tags: [zero-os, moc]
---

# Zero OS

A personal multi-agent AI operating system. Not a chatbot — you say what you want, an
orchestrator plans it, a mesh of 14 specialist agents executes in parallel, and one
voice answers.

**Owner:** Cyph (Deepen Khandelwal) · MSc AI, University of Manchester
**Interface:** Telegram — [[Telegram Interface|@cyph_zero_os_bot]]
**Backend:** `K:\Zero\.zero` · FastAPI on `127.0.0.1:8000`
**Repo:** Cyph08/zero-os (private)

---

## Start here

- **[[Commands]]** — every command you'll actually type
- **[[Using Zero]]** — day to day: what to say, what arrives on its own, what it costs
- **[[Troubleshooting]]** — when it goes wrong

## How it works

- **[[Architecture]]** — the request path, end to end
- **[[Agents]]** — all 14, what each one is for
- **[[Memory]]** — the three tiers, and why continuity used to break
- **[[Models and Routing]]** — local Qwen + cloud, tiers, failover, cost
- **[[Telegram Interface]]** — the bot, voice notes, confirmations, proactive push
- **[[Configuration]]** — every `.env` variable
- **[[Integrations]]** — Gmail, Notion, GitHub, Slack, and MCP in both directions
- **[[Hardware]]** — the RTX 4050 constraint that decides most model choices

## Project

- **[[Roadmap]]** — what's live, what's parked and why
- **[[Project History]]** — what was built when

---

## The shape of it in one diagram

```
you (Telegram: text or voice)
      ↓
api/main.py                     FastAPI · POST /ask
      ↓
core/intent.py                  intent + risk gate (read / write / high)
      ↓
core/ceo.py                     pick agents → dispatch in two parallel waves
      ↓
agents/*/run.py                 14 specialists, sharing a context bus
      ↓
core/ceo.py                     synthesise in one voice, self-grade, fix
      ↓
memory/{hot,warm,cold}          hot → disk · warm → Redis · cold → ChromaDB + FTS5
      ↓
you (reply, plus any files or images)
```

## Two personas, one mesh

**Zero** is sharp and execution-focused. **V** is warm. Same orchestrator, same agents,
same memory — different voice, and graded against different rubrics so the self-fix loop
doesn't strip V's warmth as "padding". Switch with `/persona v` or `/persona zero`.

---

## Rules of the road

- **Restart after every code change.** [[Commands#Start / stop]]
- **The venv is `K:\Zero\.venv`** — parent of `.zero`.
- **No test suite.** Verification is syntax check → import check → live `/ask`.
- **The bot is locked to one Telegram user ID** and refuses to start unlocked. [[Helm]]
  can delete files and run shell commands, so there is no public mode.
- **`logs/` is never deleted** — [[Vanta]] audits from it.
