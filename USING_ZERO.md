# Using Zero

Everything you need day to day. Zero lives in Telegram now — **@cyph_zero_os_bot**.

---

## Do I have to start anything?

**No — not any more.** Zero starts automatically when you log into Windows.

I added a shortcut to your Startup folder, so on every boot:
1. **Ollama** starts (it was already set up this way) — the free local model
2. **Zero's backend** starts hidden — and the Telegram bot starts with it

Then you just open Telegram and talk to it. Nothing to launch, no window to keep open.

**`/start` in Telegram does NOT start Zero.** It's only a greeting message to a bot
that's already listening. The bot lives *inside* the backend, so if the backend
isn't running your messages just sit there unanswered until it is.

### If Zero isn't answering

| | |
|---|---|
| Start it | Double-click **`K:\Zero\start-zero-hidden.vbs`** (silent, no window) |
| Start it, visibly | **`K:\Zero\restart-zero.bat`** — keeps a window open with the live log. Best for debugging |
| Stop it | **`K:\Zero\stop-zero.bat`** |
| Is it alive? | Send `/health` in Telegram, or open http://localhost:8000/health |

Disable autostart any time: press `Win+R`, type `shell:startup`, delete `ZeroOS.lnk`.

---

## Talking to Zero

Just say what you want. No commands, no syntax. Zero picks the right specialist.

| You say | What happens |
|---|---|
| "latest research on motor imagery BCI" | **Iris** searches the web + papers, answers with citations, sends any images |
| "make me a snake game" | **Forge** builds it, saves it to `Zero Tech`, **sends you the file** |
| "find my dissertation notes" | **Helm** searches your laptop and gives you the real paths |
| "what's in my downloads folder" | **Helm** lists it |
| "explain CSP for EEG" | **Sage** / **Synapse** explain it properly |
| "remind me to submit the report Friday" | **Chrono** schedules it |
| "draft an email to my supervisor" | **Echo** writes it — it never sends anything |
| "how should I train around study days" | **Pulse** — it knows about your Chen's shifts |
| "give me a briefing" | **Herald** — Manchester weather, your day, world + AI news |
| *send a voice note* | Whisper transcribes it, then it's handled like any message |

### Commands

| | |
|---|---|
| `/help` | What Zero can do |
| `/agents` | List all 14 agents |
| `/health` | Backend, model and memory status |
| `/status` | Today's request count and spend |
| `/persona v` | Switch to **V** (warm). `/persona zero` switches back |

### Things that arrive on their own

You don't ask for these — they turn up:

- **08:00** morning briefing — weather, your schedule, world + AI news
- **18:00** news digest
- **Sunday 09:00** research digest

---

## When Zero asks "Run it?"

Anything destructive — delete, move, overwrite, or running a shell command — shows
you a preview with **Yes / Cancel** buttons first. Nothing happens until you tap.

Even then it's reversible: **deletes go to `K:\Zero\.zero\trash\`**, not gone, and
Zero tells you exactly where. Overwrites leave a `.bak` beside the original.
Windows and Program Files are refused outright.

---

## What it costs

Almost nothing. Two models share the work:

- **Local (Qwen on your GPU)** handles the cheap, frequent calls — deciding which
  agent to use, splitting up questions, grading drafts. **Free.**
- **Cloud (DeepSeek, or Kimi when you add the key)** does the actual thinking.

A typical question costs **under a penny**. Check any time with `/status`.

To switch to Kimi: put the key in `MOONSHOT_API_KEY=` in `K:\Zero\.zero\.env`
(it's already there, waiting) and restart. See `docs/model_setup.md`.

---

## If something's wrong

**Zero doesn't reply at all** → the backend isn't running. Run
`restart-zero.bat` and watch the window for errors.

**Replies are slow** → normal is 10–40s; a build can take 90s. The typing
indicator means it's working. For speed, set `ZERO_SELF_FIX_MAX_ITERS=1` in `.env`.

**Voice notes fail** → needs `ffmpeg` (you have it). If it breaks, Zero says so.

**Wrong agent answered** → tell me. Zero learns routing patterns and occasionally
learns a bad one; they're stored in `skills/skills.db` and can be cleared.

**It says it can't do something you know it can** → same cause as above. Worth
reporting, that's a real bug.

---

## Where things live

```
K:\Zero\
  start-zero-hidden.vbs   start silently (this is what autostart uses)
  restart-zero.bat        start with a visible log window
  stop-zero.bat           stop it
  Zero Tech\              apps Forge builds for you
  .zero\
    .env                  all keys and settings
    logs\                 every action, cost and error
    trash\                deleted files, recoverable
    docs\                 setup guides and audit reports
```
