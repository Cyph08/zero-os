---
tags: [zero-os, interface]
---

# Telegram Interface

**@cyph_zero_os_bot** — this is how you use Zero. It replaced the website and the desktop
app entirely; see [[Roadmap]].

One file: `.zero\phone\telegram_bot.py`. **Zero new dependencies** — it talks to the
Telegram Bot API directly over the `httpx` already in `requirements.txt`, using long
polling (`getUpdates`, 25s timeout).

> [!note] Deliberately not `python-telegram-bot`
> That library runs its own asyncio loop, which fights FastAPI's. Raw Bot API calls avoid
> the whole problem.

Started from `api/main.py`'s `lifespan` when `TELEGRAM_BOT_TOKEN` is set. One process, one
restart script — [[Commands#Start / stop]].

## `/start` does not start Zero

It's a greeting message to a bot that is **already listening**. The bot lives *inside* the
backend, so if the backend isn't running your messages sit unanswered until it is.

Zero autostarts on login, so in practice there's nothing to launch.

## Security

Locked to a single `TELEGRAM_ALLOWED_USER_ID`. Every other sender is ignored and logged,
and `build_from_env()` **raises rather than starting unlocked**.

> [!danger] Do not add a public mode
> [[Helm]] can delete files and run shell commands on the machine. There is no safe
> multi-user configuration of this bot.

## What it handles

| Input | Behaviour |
|---|---|
| Text | `ceo.handle()` in a worker thread, with a live typing indicator |
| Voice note | `getFile` → download → Whisper (`PHONE_MODEL`) → same path as text |
| Built file | Replies are scanned for a real on-disk path → `sendDocument` |
| Images | [[Iris]] publishes Tavily image URLs to the bus → `sendPhoto` |

Replies are split at 4096 characters on paragraph boundaries. `parse_mode` is left unset
on purpose, so a stray character in an answer can't cause a Telegram parse error.

The typing indicator replaces token streaming, which is meaningless for discrete Telegram
messages.

> [!warning] Voice notes need `ffmpeg` on PATH
> Telegram sends `.oga`. If ffmpeg is missing the bot says so explicitly rather than
> failing silently.

## 👍 / 👎

Every answer gets two buttons. Tapping one shows a toast (*"👍 Noted — learned the route
…"*) and removes the buttons. `callback_data` is `fb:+:<interaction id>` — 31 bytes, under
Telegram's 64 — so it works on old messages after restarts. What a rating does:
[[Memory#The feedback loop]].

## Confirmations

Anything destructive — delete, move, overwrite, or running a shell command — or anything
the intent gate rates HIGH gets a preview with **Yes / Cancel** inline buttons. Nothing
happens until you tap. Pending text is held in one module dict keyed by callback token; a
**Yes** calls `ceo.handle(text, confirmed=True)`.

It reuses `intent._is_informational_question()`, so "how do I delete a file in python" is
a question and is not gated.

Even after **Yes** it's reversible: deletes go to `K:\Zero\.zero\trash\` and Zero tells
you the recovery path. Overwrites leave a `.bak`. See [[Helm]].

## Proactive push

A 30s pump drains `core.alerts.alert_queue.get_undelivered()`, sends each alert, then
marks it delivered. The 08:00 briefing, 18:00 news and Sunday research digest land in
Telegram with no extra plumbing — [[Commands#Scheduled jobs]].

> [!bug] The pump crashed silently on import
> It imported `alerts` when the singleton is `alert_queue`. An `ImportError` inside the
> task killed proactive briefings without any visible error. Only running the bot live
> caught it — the offline self-check couldn't.

## Commands

| | |
|---|---|
| `/help` | What Zero can do |
| `/agents` | List all 14 — see [[Agents]] |
| `/health` | Backend, model and memory status |
| `/status` | Today's request count and spend |
| `/persona v` · `/persona zero` | Switch persona |

## Offline self-check

```bash
cd K:\Zero\.zero && K:\Zero\.venv\Scripts\python.exe -m phone.telegram_bot
```

Asserts message splitting at 4096, auth rejection of a wrong user ID, and
destructive-pattern detection. No token or network needed.

## Setup

BotFather walkthrough and how to find your numeric user ID:
`.zero\docs\telegram_setup.md`. Two variables — see [[Configuration]].

---
[[Using Zero]] · [[Commands]] · [[Architecture]] · [[Zero OS]]
