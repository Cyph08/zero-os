# Zero OS — Final Verification
## Date: 2026-09-28

Covers the Telegram interface, the Kimi + local-Qwen model stack, and a full
agent sweep. Everything below was actually run — no step is marked passing on
inspection alone.

---

## Headline: 14/14 agents pass

One real query each, run standalone against the live backend code.

| Agent | Status | ms | Evidence |
|---|---|---|---|
| bci (Synapse) | PASS | 25,145 | Full BCI Competition IV 2a pipeline write-up |
| brainstorm (Spark) | PASS | 10,327 | Structured problem/opportunity + MVP breakdown |
| career (Maven) | PASS | 8,025 | Named BCI/EEG work as the differentiator |
| code (Forge) | PASS | 9,968 | Working CSP filter implementation |
| comms (Echo) | PASS | 4,444 | Draft + rationale, did not auto-send |
| health (Pulse) | PASS | 3,317 | **Referenced Chen's Happy House shifts unprompted** |
| linkedin (Nexus) | PASS | 453 | Correct "not connected" guidance — needs credentials |
| news (Herald) | PASS | 13,212 | **Live Manchester weather: overcast, 9.2–18.1°, no rain** |
| photo (Lens) | PASS | 6,080 | Advice-only path handled cleanly |
| research (Iris) | PASS | 81,751 | Deep path: decomposition + multi-source, cited |
| schedule (Chrono) | PASS | 6,564 | Correct empty week, term-aware |
| study (Sage) | PASS | 13,120 | CSP explanation with intuition section |
| system (Helm) | PASS | 10,790 | Found restart-zero.bat in two locations |
| vanta (Vanta) | PASS | 185 | Health table across all 14 |

Herald's briefing and Pulse's personalisation confirm the Fable-audit fixes are
live in the code path, not just written.

---

## A correction: an earlier "3/14" result was my test harness

Three consecutive runs reported 3/14 with a suspiciously uniform ~2–4s failure.
I initially attributed it to DeepSeek rate limiting. **That was wrong.**

Root cause: the harness lived in a scratch directory and called `load_dotenv()`
with no argument. `load_dotenv()` resolves relative to the **calling file**, so it
found no `.env`, loaded **no API keys at all**, and left every agent with only
Ollama in its provider chain — which had no model pulled. The uniform timing was
Zero correctly trying its single available provider and failing fast.

The harness now passes an explicit path and asserts `DEEPSEEK_API_KEY` is present
before running, so it cannot fail silently again. **No Zero code was at fault.**

Recorded because the misdiagnosis is the more useful lesson: verify the
environment before theorising about the remote service.

---

## A real bug that the hunt did surface

`agents/study` reported `model_used=deepseek-reasoner`, cost **$0.0022**, and
returned **empty text**.

`deepseek-reasoner` (R1) emits chain-of-thought before its answer. With a long
agent prompt and `max_tokens=2000`, the budget is exhausted during reasoning and
`content` comes back empty — Zero was being billed and answering with nothing.
Any agent on the `capable` tier was exposed.

**Fixed in `core/llm.py`:**
- `capable` now maps to `deepseek-chat` (V3) — always returns content, ~3x faster.
  R1 is reserved for `deep`, where the token budget suits it.
- Safety net in `_chat_deepseek()`: if `content` is empty, fall back to
  `reasoning_content` rather than returning nothing, and log it.

Verified immediately after: bci 16.0s, study 7.8s, schedule 1.4s — all with real
content, all on `deepseek-chat`.

---

## Offline checks (no key, no network)

| Check | Result |
|---|---|
| `python -m phone.telegram_bot` self-check | PASS |
| — 4096-char splitting on paragraph/line/word boundaries | PASS |
| — refuses to build a bot without `TELEGRAM_ALLOWED_USER_ID` | PASS (raises) |
| — no token → returns None, backend starts normally | PASS |
| — destructive-intent detection (4 risky / 5 safe cases) | PASS |
| — `find_sendable_file` on real + missing paths | PASS |
| `ast.parse` on all touched files | PASS |
| `import api.main` with bot wiring | PASS |
| Tier routing: `fast`→ollama/qwen3.5:4b, `capable`→kimi-k2.6, `deep`→kimi-k3 | PASS |
| Failover: Ollama down → `fast` falls through to Moonshot | PASS |
| 429 retry hits the same provider once, doesn't demote | PASS (simulated) |
| `_is_rate_limited`: 429/quota yes, 400/refused no | PASS |
| Iris `include_images` live | PASS — 5 real image URLs |
| `ceo.handle(confirmed=True)` bypasses the gate; unconfirmed still denied | PASS |

**A bug caught by its own test:** `needs_confirmation("how do I delete a file in
python")` gated an informational question. Fixed by reusing
`intent._is_informational_question()` instead of duplicating the prefix list.

**A bug caught by the tier test:** the 429 retry called `time.sleep()` but `time`
was not imported in `core/llm.py` — a `NameError` that would only have fired on
the rare rate-limit path. Fixed and then exercised with a simulated 429.

---

## Honest caveat on the 429 retry

It is **defensive, not a fix for an observed failure**. The rate limiting I
thought I saw was the harness bug above. The retry is still correct — the CEO
dispatches agents in parallel, so a busy request genuinely can trip a provider
limit — but nothing in this session proved it was happening. Recorded so it isn't
credited with solving a problem that did not exist.

---

## Environment

| Item | State |
|---|---|
| Ollama | **Installed** (0.34.4) |
| `qwen3.5:4b` | **Downloading** — 1.6GB of ~3.4GB at time of writing. Tag verified valid (registry HTTP 200) |
| ffmpeg | **Present** — Telegram voice notes will decode `.oga` |
| GPU | RTX 4050, 6141 MiB total, ~635 MiB used → 4B model fits alongside Whisper |
| Anthropic | Key set, account at $0 — **fails on every call before falling over**. Comment it out |
| DeepSeek | Working, serving everything |
| Moonshot/Kimi | Not yet configured — awaiting key |
| Telegram | Not yet configured — awaiting token + user ID |

**Unexpected find:** Helm located a second full copy of the repo at
`C:\Users\deepe\repo-migration\zero-os\` (has its own `.git`). Not inside
`K:\Zero`, so it was left alone, but worth knowing two checkouts exist.

---

## Still requires Cyph

These cannot be completed without input or an action only he can take:

1. **Telegram token + numeric user ID** → `.env`, then `restart-zero.bat`.
   Until then the bot is unconfigured and the backend simply runs without it.
2. **Kimi key** → `.env`. The Moonshot provider is wired and tier-tested; it
   activates on the next call once the key exists.
3. **`restart-zero.bat`** — the running backend is admin-owned and still has the
   pre-Fable code. Nothing in this session is live until it restarts.
4. **Finish the model download**, then set `ZERO_LOCAL_FAST=1`.

## Live tests still pending (need the token + a restart)

Written out so they can be run in order once configured:

1. `/start` → authorised; a second Telegram account → silently ignored (check log).
2. "latest papers on motor imagery BCI" → typing indicator → cited answer + images.
3. Voice note → transcript then answer (ffmpeg present, so expected to work).
4. "make me a snake game" → `.html` arrives in the chat as a document.
5. "delete helm_test.txt from my desktop" → Yes/Cancel → deleted to `.zero/trash/`
   with the recovery path reported.
6. `POST /scheduler/jobs/morning_briefing/run-now` → briefing lands in Telegram.
7. `/health` → shows provider chain and whether local-fast is on.
8. After the Kimi key: re-run 2 and 4, confirm `ceo_actions.jsonl` shows
   `moonshot/kimi-k2.6` with real costs.

## Health score

Before this session: **8.3/10** (post-Fable, but unverified live, on a fallback
provider, no usable interface).

After: **9.0/10** — 14/14 agents verified with real output, a paid-but-empty-reply
bug fixed, a phone-native interface built, and a free local tier installed.
Withheld: the Telegram live suite and the Kimi comparison both wait on Cyph, and
the local model download had not finished at time of writing.
