---
tags: [zero-os, models]
---

# Models and Routing

`core/llm.py`. Every call picks a **tier**, then walks a **provider chain** until one
answers.

## Tiers

`quality.assess_depth()` returns `small` / `mid` / `deep`, which maps to:

| Tier | Used for | Self-fix passes |
|---|---|---|
| `fast` | agent ranking, query decomposition, draft grading — most of the 5–15 calls per request | 1 |
| `capable` | normal synthesis | 2 |
| `deep` | genuinely hard questions | 3 |

## Provider chain

**moonshot → anthropic → deepseek → groq → ollama.** First one with a key and a working
response wins; the rest are silent failover.

| Provider | Model (fast / capable / deep) | Status |
|---|---|---|
| Moonshot (Kimi) | `kimi-k2.6` / `kimi-k2.6` / `kimi-k3` | **key not added yet** |
| Anthropic | Haiku / Sonnet / Opus | **commented out in `.env`** — account at $0 |
| DeepSeek | `deepseek-chat` / `deepseek-chat` / `deepseek-reasoner` | **currently doing the work** |
| Groq | free tier, rate limited | fallback |
| Ollama | `qwen3.5:4b`, local | `fast` tier + last resort |

> [!warning] Anthropic is commented out on purpose
> The key is set but the account has no credits. Leaving it active cost a **failed HTTP
> round-trip on every one of the 5–15 calls per request**. The value is preserved in
> `.env`; uncomment it the moment there are credits and the router prefers it again.

## Hybrid local routing

`ZERO_LOCAL_FAST=1` puts Ollama at the front of the chain **for the `fast` tier only**:

```python
if tier == "fast" and _local_fast_enabled():
    chain = [Provider.OLLAMA] + [p for p in chain if p != Provider.OLLAMA]
```

Three lines, reusing the existing failover machinery — if Ollama is down it falls straight
through to cloud with no config change. The frequent cheap calls run free on the GPU while
real synthesis goes to the cloud.

## Cost

Per-model cost tables log real spend to `logs/ceo_actions.jsonl`. A typical question is
**under a penny**. Check with `/status` in Telegram.

---

## The local model — and why it's 4B

See [[Hardware]]. On 6GB of VRAM:

| Model | Size | Verdict |
|---|---|---|
| `qwen3:8b` Q4_K_M | 5.0GB + ~1GB context ≈ **6.0GB** | leaves nothing |
| `qwen3.5:4b` | 3.4GB | ~2GB headroom |

Whisper `large-v3` on CUDA needs ~3GB. **An 8B model and Whisper cannot coexist in 6GB.**
Since the `fast` tier only does short prompts and short outputs, `qwen3.5:4b` is the right
pick and it keeps voice transcription on the GPU. Keep local context ≤ 8K.

**Measured:** cold start 93s · warm 2.9s · 48 tok/s · 100% GPU · 3.1GB VRAM.

That cold start blew the old hard-coded 60s timeout, hence `OLLAMA_TIMEOUT_S=180`,
`OLLAMA_KEEP_ALIVE=30m`, and a `prewarm_local()` call on backend startup.

---

## The thinking-model trap

> [!bug] Reasoning models return **empty content**
> Both `deepseek-reasoner` (R1) and `qwen3.5` burn the entire `max_tokens` / `num_predict`
> budget on chain-of-thought, then return an empty `content` with finish reason `length`.
> Zero replied with nothing at all — and was still billed.

Proven with Ollama: `think: false` → content `"ok"`, `done_reason: stop`. Without it →
empty, `length`.

Fixes:

- DeepSeek `capable` moved from `deepseek-reasoner` to **`deepseek-chat`**.
- `_chat_deepseek` salvages `reasoning_content` when `content` is empty.
- `_chat_ollama` sends `"think": os.getenv("OLLAMA_THINK", "0")` and salvages the same way.

## Kimi — the honest numbers

Moonshot is **not free**. No permanent free tier: a new account needs a **$1 minimum
recharge**, though there's a **7-day trial with no card**. A **$5 recharge earns a $5
bonus voucher**.

| Model | $/1M in | $/1M out |
|---|---|---|
| `kimi-k2.6` | 0.95 | 4.00 |
| `kimi-k2.7-code` | 0.95 | 4.00 |
| `kimi-k3` (2.8T params, 1M context) | 3.00 | 15.00 (0.30 cache hits) |

`https://api.moonshot.ai/v1` is OpenAI-compatible, so the provider is a clone of
`_chat_deepseek`.

**Genuinely free alternatives** worth wiring as fallbacks: Zhipu **GLM-4-Flash**
(permanently free, 20M signup tokens) · **Qwen DashScope** (70M signup tokens,
OpenAI-compatible) · **Groq** (fastest free tier, hosts Qwen3).

To switch: put the key in `MOONSHOT_API_KEY=` in `.zero\.env` (already there, empty) and
restart. Full guide in `.zero\docs\model_setup.md`.

---

## Voice

| | |
|---|---|
| STT | `openai-whisper` local. `large-v3` for accuracy, `base` (`PHONE_MODEL`) for phone/Telegram latency |
| TTS primary | `edge-tts` — Zero = AriaNeural, V = JennyNeural |
| TTS premium | ElevenLabs (`ELEVENLABS_API_KEY`) |
| Wake word | openWakeWord — Zero = `hey_jarvis`, V = `hey_mycroft` |

> [!note] Whisper is on CPU
> The installed torch is CPU-only (`[stt] CUDA not available`). Voice notes transcribe,
> just slower than the GPU would. Fixing it means installing a CUDA build of torch.

## Optional deep brain

`AIRLLM_ENABLED=1` runs a 70B-class model layer-by-layer on the 6GB GPU. Strictly
opt-in, never auto-selected, falls back to the `capable` tier.

---
[[Configuration]] · [[Hardware]] · [[Architecture]] · [[Zero OS]]
