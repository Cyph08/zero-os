# Zero OS — Telegram Setup

Five minutes, two environment variables. After this, Zero lives in your pocket and you
never need to open the desktop app again.

---

## 1. Create the bot

1. Open Telegram and message **@BotFather**.
2. Send `/newbot`.
3. Give it a display name — e.g. `Zero`.
4. Give it a username ending in `bot` — e.g. `cyph_zero_os_bot` (must be globally unique).
5. BotFather replies with a token like `8123456789:AAH...`. **Copy it.**

Optional polish, same chat:
- `/setdescription` → "Zero OS — my personal multi-agent AI."
- `/setuserpic` → upload an image.
- `/setcommands` → paste this so Telegram shows a command menu:
  ```
  help - what Zero can do
  agents - list every agent
  health - backend and model status
  status - today's usage and cost
  persona - switch between Zero and V
  ```

## 2. Get your numeric user ID

The bot must know which account is *you*. **This is the security boundary** — Zero can
delete files and run shell commands on your laptop, so the bot answers exactly one user ID
and silently ignores everyone else.

Message **@userinfobot** on Telegram. It replies with your `Id:` — a number like
`123456789`. That's what you need (a username is not enough).

## 3. Add both values to `.env`

In `K:\Zero\.zero\.env`:

```
TELEGRAM_BOT_TOKEN=8123456789:AAH...
TELEGRAM_ALLOWED_USER_ID=123456789
```

Optional — also get a spoken reply to every message:
```
TELEGRAM_VOICE_REPLIES=1
```

⚠️ **If you set the token but not the user ID, Zero refuses to start the bot** and logs why.
That's deliberate: an unlocked bot would give shell access to anyone who found it.

## 4. Restart

```
K:\Zero\restart-zero.bat
```

The bot starts inside the backend — no second process, no extra window. Look for this in
the log:

```
[main] Telegram bot starting…
[tg] Bot online as @your_bot — locked to user id 123456789
```

## 5. Use it

Message your bot `/start`. Then just talk to it:

| You say | What happens |
|---|---|
| "latest papers on motor imagery BCI" | Iris researches, cites sources, sends any images she found |
| "make me a snake game" | Forge builds it and **sends you the .html file** |
| "find my dissertation notes" | Helm searches your laptop |
| "what's in my downloads folder" | Helm lists it |
| "delete helm_test.txt from my desktop" | **Asks first** — Yes/Cancel buttons |
| *(voice note)* | Whisper transcribes it, then it's treated as a normal request |
| "remind me to submit the report Friday" | Chrono schedules it |

**Proactive messages arrive on their own.** The 8am briefing, 6pm news digest, and Sunday
research digest are pushed to the chat with no action from you.

---

## Voice notes need ffmpeg

Telegram sends voice as `.oga` (Opus), and Whisper shells out to ffmpeg to decode it. If
you haven't got ffmpeg, voice notes fail with a clear message telling you this. Install:

```
winget install Gyan.FFmpeg
```

Then restart the backend. Text works fine without it.

## Troubleshooting

**Bot doesn't respond at all**
- Is the backend running? `curl http://localhost:8000/health`
- Check the log for `[tg] Bot online` — if it's missing, the token is wrong or unset.

**"IGNORED message from unauthorised user id=..." in the log**
- That ID is what messaged the bot. If it's you, your `TELEGRAM_ALLOWED_USER_ID` is wrong —
  copy the number from @userinfobot exactly.

**Replies are slow**
- Normal: 10–30s for research, up to ~90s for a build. The typing indicator stays on while
  agents work. To speed up, set `ZERO_SELF_FIX_MAX_ITERS=1` in `.env` (fewer quality passes)
  or enable the local fast tier (see `model_setup.md`).

**It answers, but the file never arrives**
- Zero only sends files under 50MB, and only known types (.html/.png/.pdf/.py/...).
  The path still appears in the text so you can open it yourself.

## Security notes

- One user ID. No public mode. Don't add one — Helm has shell access.
- The token is a password. It's in `.env`, which is gitignored and was never pushed.
- If the token ever leaks, message @BotFather → `/revoke` → issue a new one.
- Destructive actions (delete/move/overwrite/run) always confirm first, and deletes go to
  `.zero/trash/` rather than being erased, so a mistake is recoverable.
