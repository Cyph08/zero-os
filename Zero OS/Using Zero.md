---
tags: [zero-os, guide]
---

# Using Zero

Day to day. Zero lives in Telegram — **@cyph_zero_os_bot**.

## Do I have to start anything?

**No.** Zero starts automatically when you log into Windows. On every boot: Ollama comes
up (the free local model), then Zero's backend starts hidden, and the Telegram bot starts
with it. Open Telegram and talk.

**`/start` does not start Zero** — it's a greeting to a bot that's already listening. The
bot lives *inside* the backend. If the backend isn't running, your messages sit unanswered
until it is. Commands to start it manually: [[Commands#Start / stop]].

## Talking to it

Just say what you want. No commands, no syntax — Zero picks the specialist.

**Everything comes back in Telegram, as text or images.** The one exception is games: those are built as a file, opened on the laptop, and sent to you.

| You say | What happens |
|---|---|
| "latest research on motor imagery BCI" | [[Iris]] searches the web and papers, answers with citations, sends any images |
| "make me a snake game" | [[Forge]] builds it, opens it on the laptop, **sends you the file** |
| "now add levels and three lives" | [[Forge]] **edits that same game** — [[Memory#Follow-ups]] |
| "find my dissertation notes" | [[Helm]] searches your laptop and gives you real paths |
| "what's in my downloads folder" | [[Helm]] lists it |
| "explain CSP for EEG" | [[Sage]] / [[Synapse]] explain it properly |
| "remind me to submit the report Friday" | [[Chrono]] schedules it |
| "draft an email to my supervisor" | [[Echo]] writes it — it never sends anything |
| "how should I train around study days" | [[Pulse]] — it knows your Chen's shifts |
| "give me a briefing" | [[Herald]] — Manchester weather, your day, world + AI news |
| "India vs Pakistan result" | [[Herald]] searches it and gives you the score |
| *send a voice note* | Whisper transcribes it, then it's handled like any message |

### 👍 / 👎 — teach it

Every answer has 👍 and 👎 under it. Use them. Zero repeats what you 👍, avoids what you
👎, learns routes only from answers you liked, and drops routes that produced answers you
didn't. It's the only way it improves over time — see [[Memory#The feedback loop]].

### What it knows about you

Your **Dissertation** and **foresight** vaults (including the PDFs) and this vault. Ask
*"what did I conclude about data reduction"* and it answers from your notes. Unrelated
questions don't touch them. Change the list in [[Configuration]].

### Commands

`/help` · `/agents` · `/health` · `/status` · `/persona v` · `/persona zero`

### Things that arrive on their own

- **08:00** morning briefing — weather, your schedule, world + AI news
- **18:00** news digest
- **Sunday 09:00** research digest

## When Zero asks "Run it?"

Anything destructive — delete, move, overwrite, or a shell command — shows a preview with
**Yes / Cancel** first. Nothing happens until you tap.

Even then it's reversible: **deletes go to `K:\Zero\.zero\trash\`**, not gone, and Zero
tells you exactly where. Overwrites leave a `.bak`. Windows and Program Files are refused
outright.

## What it costs

Almost nothing. Two models share the work — **local Qwen on your GPU** handles the cheap
frequent calls (which agent to use, splitting questions, grading drafts) for **free**, and
the cloud does the actual thinking. A typical question is **under a penny**. Check with
`/status`.

Details: [[Models and Routing]].

## Speed

Normal is 10–40s; a build can take 90s. The typing indicator means it's working. For
speed, set `ZERO_SELF_FIX_MAX_ITERS=1` — [[Configuration]].

---
[[Troubleshooting]] · [[Commands]] · [[Telegram Interface]] · [[Zero OS]]
