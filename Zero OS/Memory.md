---
tags: [zero-os, architecture]
---

# Memory

Three tiers, plus an Obsidian mirror. All under `K:\Zero\.zero\memory\`.

| Tier | Store | Lifetime | Read back by |
|---|---|---|---|
| **Hot** | RAM + `hot_session.jsonl` | 50 entries, **survives restart** | every request |
| **Warm** | Redis, in-memory fallback | 7 days | *nothing* — see below |
| **Cold** | ChromaDB + SQLite FTS5 | permanent | semantic + keyword recall |
| **Notes** | your vaults + PDFs, chunked | synced each start | relevant chunks only |
| **Feedback** | your 👍/👎 | permanent | similar questions |

## Hot — `memory/hot.py`

The last 50 entries of conversation: user messages, Zero's replies, agent outputs. The
10 most recent are injected into every synthesis prompt.

Mirrored line-by-line to `memory/hot_session.jsonl` and restored on startup — you'll see
`[hot] Restored N entries from previous session` in the log. The file is trimmed to the
kept tail on load, so it can't grow without bound, and a half-written line from a hard
kill is skipped rather than crashing the load.

> [!bug] This used to be RAM-only
> Zero autostarts on login, so **every reboot wiped the conversation**. Telegram still
> showed the history, so it looked like Zero was ignoring you — it genuinely had no
> record. `hot_session.jsonl` is the fix.

Self-check: `K:\Zero\.venv\Scripts\python.exe -m memory.hot` (from `.zero`).

## Warm — `memory/warm.py`

Redis at `localhost:6379`, with an in-memory dict fallback. **Redis is usually not
running** — the fallback warning on startup is benign.

> [!note] Warm is write-only today
> `cache_interaction()` is called on every turn, but `get_recent_interactions()` is never
> called by anything. The tier documented as "survives restarts" doesn't, because the
> fallback is in-memory. Hot's disk mirror now covers that job. Warm is harmless but
> currently dead weight.

It does still serve `cache_research()` / `get_cached_research()` and the preference store.

## Cold — `memory/cold.py` + `memory/fts.py`

ChromaDB vector store for semantic recall, plus a SQLite **FTS5 keyword index** fused via
Reciprocal Rank Fusion (`k=60`). Vectors alone miss exact terms — "RTX 4050", "Lumineth",
"CSP" — so `hybrid_search()` runs both and fuses the rankings. Degrades to pure vector if
FTS is unavailable.

`store()` and `delete()` mirror into the keyword index; existing history was backfilled
once on first connect.

`_load_memory_context()` pulls the top 4 hybrid hits for every request, alongside hot
memory's recent turns.

### Obsidian mirror

`core/info_store.py` writes every explicitly saved item ("save this: …") to
`K:\Zero\Zero Memory\` as a `.md` file with YAML frontmatter and tags — the
human-readable source of truth. The JSON store stays as the index. `rebuild_vault()`
regenerates it.

---

## Your notes

Zero reads and remembers your Obsidian vaults and PDFs — set in `.env`:

```
ZERO_KNOWLEDGE_DIRS=K:\Dissertation;K:\foresight;K:\Zero\Zero OS
```

Synced on every backend start: every `.md` and `.pdf`, recursively, split into
~1,000-character chunks (the embedder only reads about that much, so whole notes lost
everything past the first paragraph or two). Only changed files are re-read. **Delete a
note, or remove a folder from the list, and it leaves Zero's memory on the next start.**
Virtualenvs and caches are skipped — `K:\foresight\.venv` had contributed 33 package files
against your 8 real notes.

First sync: 71 files, ~1,500 chunks, ~9 minutes on CPU. After that, seconds.

### Only when relevant

The keyword index matches any word, so every note "matches" every message. Notes reach
the prompt only if they're semantically close — **cosine distance ≤ 0.60**
(`ZERO_NOTES_MAX_DISTANCE`). Measured on your vaults:

| | distance |
|---|---|
| questions about your dissertation | 0.25 – 0.51 |
| cricket, weather, gym, email, news, file search | 0.70 – 0.82 |

So *"what's my dissertation about"* gets your notes and *"India Pakistan result"* sends
**none** of them to the cloud model.

> [!warning] Privacy
> When a note is relevant, an excerpt of it is sent to DeepSeek (or Kimi) with the
> question. That's how it answers from your notes. Remove a folder from
> `ZERO_KNOWLEDGE_DIRS` to stop that.

---

## The feedback loop

Every Telegram answer has **👍 / 👎** under it. That's how Zero improves over time —
without retraining a model, because its brain is a hosted API whose weights can't be
trained. `core/feedback.py`:

| You tap | Zero does |
|---|---|
| 👍 | Similar future questions see this answer as *"match what worked"*. On a multi-agent answer, it **learns the route** as a skill so next time skips the routing step |
| 👎 | Similar future questions see it as *"don't repeat what went wrong"*. **Deletes the learned route** that produced it |
| either | Logged to `logs/feedback.jsonl` with the question and answer — a preference dataset, which is what fine-tuning the local model would need later |

Tapping again overwrites — the latest rating wins. Buttons work on old messages after any
number of restarts: they carry the cold-memory id, not state held in the bot.

Ratings steer only **genuinely similar** questions (distance ≤ 0.35).

> [!bug] Why skills are only learned from 👍 now
> They used to be learned from every multi-agent answer — including failures. The broken
> cricket reply became a skill called `live_score_handling` whose hint was *"acknowledge
> inability to provide live scores, suggest Cricbuzz"*. Every future score question would
> have been told to say it couldn't find scores, even after the search was fixed.

---

## Follow-ups

The hard part isn't storing memory, it's **getting it to the agents**.

Agents receive `run(query, bus=None)` — the current message and nothing else. The CEO
injected history at *synthesis*, which is after the work has already happened. So a
follow-up was handled as a brand-new, context-free request:

```
you: make me a snake game
     → snake-first-basic.html          ✓

you: create levels with three lives each, boss every 10 points
     → levels-three-lives-each-after.html    ✗ a second, unrelated game

you: you have created a totally different game, create a snake game
     with all the things i have said before
     → you-have-created-totally-different.html   ✗ the filename is your complaint
```

Three fixes, all in the request path:

**1. History reaches agents via the bus.** `core/ceo.py` snapshots hot memory *before*
adding the current turn and publishes it as `recent_conversation`. Every agent already
receives the bus, so no agent contract changed.

**2. One shared follow-up decision.** `core.intent.is_build_followup(history, query)` —
used by both the CEO (to route to [[Forge]] at all) and Forge (to edit the real file).
They each used to guess from their own keyword list on the current sentence alone, which
is why "make it faster and harder" reached **no agent** and the CEO answered directly,
*claiming it had made the change* when nothing ran.

The rule: a request for a whole new artifact says "**a**/an/another/new *thing*" —
"make me *a* snake game". A follow-up names features — "create levels with three lives",
"end **the** game at 30 points". That article is the cheapest reliable signal.

**3. The build to edit comes from history, not the filename.** Forge used to match your
query against filenames in `Zero Tech`, so "create levels with three lives each" scored
four words against a stale `levels-three-lives-each-after.html` and edited *that*. The
conversation knows which file was just built, so it's asked instead.

Verified: the same three turns now produce one snake game that gains lives and bosses —
the pre-edit `.bak` has zero mentions of lives/boss/level, the edited file has 13/26/18,
and the snake code is intact.

> [!note] Related guard
> The direct-answer path (no agent matched) is now told explicitly that nothing ran and
> it must never claim to have done anything.

---
[[Architecture]] · [[Forge]] · [[Zero OS]]
