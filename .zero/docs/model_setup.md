# Zero OS — Model Setup (Kimi + local Qwen)

Written 2026-09-28. Prices verified against Moonshot's published rates the same day —
re-check before you top up, they move.

---

## The short version

**Your assumption that Chinese models are mostly free isn't true for Kimi.** Moonshot has
**no permanent free tier** — a new account needs a **$1 minimum top-up** before the API
answers at all. There *is* a **7-day trial that needs no card**, which is the right way to
test it before paying.

The good news: it's cheap, and there are genuinely free models worth having in the chain
behind it.

**Recommended setup, in order:**
1. Start the free 7-day Moonshot trial → test Zero with it → costs nothing.
2. If you like it, top up **$5 — you get a $5 bonus voucher, so it becomes $10.** At Zero's
   usage that lasts a long time.
3. Install Ollama + `qwen3.5:4b` for the local `fast` tier. Free forever, and it means Zero
   keeps working with no internet.
4. Optionally add a free **GLM-4-Flash** key as a backstop (permanently free).

---

## Which Kimi model

| Model | $/1M in | $/1M out | Use |
|---|---|---|---|
| **`kimi-k2.6`** | **0.95** | **4.00** | **General — what Zero uses for `capable`** |
| `kimi-k2.7-code` | 0.95 | 4.00 | Coding-specific |
| `kimi-k2.7-code-highspeed` | 1.90 | 8.00 | Same, lower latency |
| `kimi-k3` | 3.00 | 15.00 (cache hits 0.30) | Flagship — 2.8T params, 1M context. Zero's `deep` tier |

Zero is already configured for this split: `capable` → `kimi-k2.6`, `deep` → `kimi-k3`.
Deep only fires on genuinely hard questions (`quality.assess_depth()` decides), so the
expensive model is rare.

**If you want to keep costs near zero**, set `MOONSHOT_DEEP_MODEL=kimi-k2.6` in `.env` and
k3 never gets used.

## Getting the key

1. Go to **https://platform.moonshot.ai** and sign up (the `.ai` domain is the
   international one — `.cn` needs a Chinese phone number).
2. **API Keys → Create new key.** Copy it immediately; it's shown once.
3. Free trial: usable straight away, 7 days, no card.
4. To continue: **Billing → top up $5** (triggers the +$5 voucher).
5. Put it in `K:\Zero\.zero\.env`:
   ```
   MOONSHOT_API_KEY=sk-...
   ```
6. Restart: `K:\Zero\restart-zero.bat`

Zero picks it up automatically — `core/llm.py` prefers Moonshot as soon as the key is
present, and falls back to DeepSeek if a call ever fails.

---

## Local model (free, works offline)

Your RTX 4050 has **6GB VRAM**, and that number decides everything.

| Model | Size | Verdict |
|---|---|---|
| `qwen3:8b` Q4_K_M | 5.0GB + ~1GB context ≈ **6.0GB** | Fits, but leaves **nothing** for Whisper |
| **`qwen3.5:4b`** | **3.4GB** | **Use this** — ~2GB headroom, has tool calling + thinking |

This matters because **Whisper `large-v3` needs ~3GB of the same 6GB**. An 8B model and
speech-to-text cannot coexist on your card. Since the local model only serves the `fast`
tier — agent routing, query decomposition, draft grading, all short prompts — the 4B is
plenty and keeps your voice notes on the GPU.

### Install

```bash
winget install Ollama.Ollama
```

Then pull the model and leave the server running:

```bash
ollama pull qwen3.5:4b
```

Enable the hybrid split in `.env`:

```
ZERO_LOCAL_FAST=1
OLLAMA_MODEL=qwen3.5:4b
```

**What this does:** Zero makes 5–15 LLM calls per request. Most are cheap bookkeeping
(which agent should handle this, split this question up, is this draft good enough). Those
now run free on your GPU, while the actual thinking goes to Kimi. If Ollama isn't running,
Zero notices and routes everything to the cloud instead — nothing breaks.

Keep the local context ≤8K tokens. On 6GB, every extra token comes out of the model's
own space.

---

## Genuinely free alternatives

Worth knowing about, and easy to add to the chain later:

| Provider | What's free | Notes |
|---|---|---|
| **Zhipu GLM-4-Flash** | **Permanently free**, 20M signup tokens | The best true-free option |
| **Qwen (DashScope)** | 70M signup tokens | OpenAI-compatible, Alibaba Cloud Bailian |
| **Groq** | Free tier, ~30 req/min | Fastest inference available; hosts Qwen3 |
| **Google Gemini Flash** | Free, no card | Generous throughput |
| **Cerebras** | ~1M tokens/day | |
| **Mistral** | ~1B tokens/month | Requires opting into data training — read that before using |
| **OpenRouter** | ~24 `:free` routes, 50/day | Rises to 1,000/day after $10 lifetime spend |

**DeepSeek, which you already have working, is not free but is cheaper than Kimi**
(~$0.07/1M in). It stays as Zero's automatic fallback, so you're never stranded.

## Cost expectations

A typical Zero request on the hybrid setup: the `fast` calls are free (local), and one or
two `kimi-k2.6` calls run roughly **$0.002–0.01**. A heavy research question with the deep
tier might reach $0.05. Your $10 of credit is therefore hundreds to thousands of requests.

Watch actual spend with `/status` in Telegram, or read `logs/ceo_actions.jsonl` — every
call's real cost is logged per model.

## Verifying it works

After adding the key and restarting:

```bash
cd K:\Zero\.zero && K:\Zero\.venv\Scripts\python.exe -c "from dotenv import load_dotenv; load_dotenv(); from core.llm import chat; r = chat('say hi in five words', tier='capable'); print(r.provider.value, r.model, r.text)"
```

Expect `moonshot kimi-k2.6 ...`. For the local tier, swap `tier='capable'` for
`tier='fast'` and expect `ollama qwen3.5:4b`.

Or just ask the bot `/health` — it prints the active provider, the failover chain, and
whether local-fast is on.
