---
tags: [zero-os, architecture]
---

# Architecture

One request, end to end. Every step is a real file in `K:\Zero\.zero`.

```
input (Telegram text / voice note / scheduled job / REST)
  → api/main.py          FastAPI. POST /ask accepts {input} or {query}
  → core/intent.py       intent classifier + risk gate
  → core/ceo.py          orchestrator: select agents, dispatch, synthesise
  → agents/*/run.py      the specialists
  → core/bus.py          agent ↔ agent shared context
  → core/quality.py      grade the draft, rewrite if it fails
  → memory/*             hot + warm + cold
  → logs/                every action, cost and duration
```

## 1. Entry — `api/main.py`

FastAPI. `POST /ask` takes `{"input": "..."}` or `{"query": "..."}` and runs
`core.ceo.ceo.handle(text)` in a worker thread, so the event loop never blocks. CORS is
`*` so the old `file://` demo UI could call it.

The `lifespan` also starts: the [[Telegram Interface|Telegram bot]], the scheduler, the
Obsidian vault sync, a Whisper pre-warm, and a local-model pre-warm.

Other routes: `/health`, `/agents`, `/tts`, `/persona/current`, `/persona/switch/{name}`,
`/info` (CRUD), `/alerts`, `/scheduler/jobs/*`, and `/mcp` — Zero exposes every agent as
an MCP tool. See [[Integrations]].

## 2. Risk gate — `core/intent.py`

Classifies the request and assigns a risk level:

| Level | Meaning |
|---|---|
| `read` | Reads only. Runs immediately. |
| `write` | Creates or modifies files. Says what it will do, then proceeds. |
| `high` | Emails, purchases, destructive ops. Full preview, explicit yes required. |

> [!important] The gate runs on **your text**, not the agent's manifest
> A manifest's `risk_level` is metadata — honest labelling of what the agent *can* do.
> The actual gate reads what you said. [[Helm]] is `high` in its manifest but "what's in
> my downloads folder" classifies as `read` and just runs.

`_is_informational_question()` keeps questions out of the gate — "how do I delete a file
in python" is a question, not a delete.

`handle(user_input, confirmed=False)` — `confirmed=True` classifies for the audit trail
but skips the gate, for callers that already have an explicit yes (the bot's **Yes**
button). Without it, HIGH-risk could never be approved in API mode, because
`_api_confirm` returns False unconditionally.

`is_build_followup(history, query)` also lives here — see [[Memory#Follow-ups]].

## 3. Agent selection — `core/ceo.py`

In order, first hit wins:

1. **Build / iterate override** — "make me a game/app/website", or a follow-up to a
   build earlier in the conversation → [[Forge]] alone (plus [[Iris]] first if the build
   needs real facts, like a weather dashboard). Stops the analysis agents hijacking a
   build request.
2. **Learned skill store** — `skills/skills.db`. If this class of task succeeded before,
   reuse its agent sequence directly and publish a synthesis hint.
3. **Keyword registry** — `core/registry.py`. Regex tokenisation, multi-word phrases,
   light stemming.
4. **LLM ranking** — only when several agents match.

> [!warning] The skill store used to hijack routing
> It matched on raw token overlap against the *union* of a skill's trigger phrases —
> ~30 mostly-filler words, needing just 2 in common. A stale calendar skill was catching
> "find the restart-zero.bat file on my laptop", and Zero replied *"I don't have
> filesystem access to your laptop"* — flatly untrue, because [[Helm]] never ran. Fixed
> by stripping stopwords and requiring the match to **cover** the query.

## 4. Dispatch — two parallel waves

**Wave 1 (producers):** `research`, `brainstorm`, `schedule` run concurrently and publish
to the bus.
**Wave 2 (dependents):** everything else runs concurrently and reads wave 1's output.

Concurrency is a `ThreadPoolExecutor`; the bus is thread-safe. A three-agent query no
longer costs 3× the latency.

## 5. The context bus — `core/bus.py`

A fresh `ContextBus` per request. Agents `bus.publish(agent, key, value)` and
`bus.get_from(agent, key)` / `bus.get(key)`.

Live uses:

| Publisher | Key | Consumer |
|---|---|---|
| CEO | `recent_conversation` | every agent — [[Memory#Follow-ups]] |
| CEO | `skill_hint` | synthesis prompt |
| [[Iris]] | `summary`, `sources`, `findings` | [[Forge]], [[Maven]] |
| [[Iris]] | `images` | [[Telegram Interface]] → `sendPhoto` |
| [[Spark]] | `summary` | [[Forge]] |

The bus is also how conversation history reaches agents **without changing the
`run(query, bus)` contract** — every agent already receives it.

## 6. Synthesis — `_synthesise()`

Collects every agent's richest text field (`summary` → `response` → `explanation` →
`findings` → `draft_body`), adds memory context, the bus, and the active persona's system
style, then asks one model for a single answer in one voice.

**Short-circuit:** if any agent wrote a file to disk, it skips synthesis and returns a
clean *"saved to …"* message instead of letting the model regurgitate the code as
"paste this".

**Depth drives everything.** `quality.assess_depth()` returns `small` / `mid` / `deep`,
which picks the model tier *and* the self-fix budget (1 / 2 / 3 passes) so they can't
drift apart. Multi-agent or high-risk lifts a `small` request to `mid`.

## 7. Self-fix — `core/quality.py`

Build → grade → fix. Every draft is graded against a rubric (no markdown, human not bot,
actually answers the question, no meta-talk, no filler opener) and rewritten if it fails,
up to `ZERO_SELF_FIX_MAX_ITERS`.

Rules 1–6 are common; rule 7 is persona-specific — tightness for Zero, **warmth required
and explicitly not padding** for V. Before that split, the single Zero-flavoured rubric
graded V's warmth as filler and the self-fix loop stripped it out.

Graded output goes to `logs/quality_log.jsonl`. Disable with `ZERO_SELF_FIX=0`.

## 8. Memory write

Every completed interaction is written to all three tiers, then a skill is optionally
distilled from it. See [[Memory]].

---

## The agent contract

```
agents/<name>/
  manifest.json     name, display_name, description, trigger_keywords,
                    capabilities, risk_level, collaborates_with, version
  run.py            run(query, bus=None) -> dataclass with .to_dict()
  CHANGELOG.md      optional, written by Vanta
```

Auto-discovered by `core/registry.py` — drop a folder in and it's live after a restart.
Folder names differ from display names: `research` = [[Iris]], `code` = [[Forge]],
`system` = [[Helm]]. Full list in [[Agents]].

Every action appends a structured line to `logs/<name>.log`; the CEO logs to
`logs/ceo_actions.jsonl`. [[Vanta]] audits from both, so **never delete `logs/`**.

## Conventions

Type hints and docstrings everywhere · `pathlib.Path` not `os.path` · f-strings ·
specific exception handling (log, never silently pass) · no hardcoded paths (use
`Path(__file__).parent`) · no hardcoded keys · `uv pip install`.

---
[[Zero OS]] · [[Agents]] · [[Memory]] · [[Models and Routing]]
