---
tags: [zero-os, reference]
---

# Configuration

Everything lives in **`K:\Zero\.zero\.env`**. It is gitignored, and `.env.example` in the
same folder documents the shape without the values.

> [!danger] Never commit a key
> `.gitignore` covers `.env`, `.env.*`, and anything matching `*credential*`, `*token*`,
> `*secret*`, `*.pem`, `*.key`. A live Anthropic key was once found hardcoded in
> `ClaudeBridge.cs` and a Unity scene file — caught before it reached GitHub, but rotate
> anything you suspect.

---

## Models

| Variable | Notes |
|---|---|
| `MOONSHOT_API_KEY` | Kimi. **Empty — waiting for a key.** [[Models and Routing#Kimi — the honest numbers]] |
| `ANTHROPIC_API_KEY` | **Commented out** — account at $0, and an active key costs a failed round-trip on every call |
| `DEEPSEEK_API_KEY` | Currently doing the real work |
| `GROQ_API_KEY` | Free, rate limited |
| `GEMINI_API_KEY` | Text works; **image generation is quota-blocked** — see below |
| `LLM_TIMEOUT_S` | Cloud call timeout |

## Local model

| Variable | Value | Notes |
|---|---|---|
| `ZERO_LOCAL_FAST` | `1` | Route the `fast` tier to Ollama first |
| `OLLAMA_MODEL` | `qwen3.5:4b` | 3.4GB — [[Hardware]] explains why not 8B |
| `OLLAMA_KEEP_ALIVE` | `30m` | Keeps it warm; cold start is ~90s |
| `OLLAMA_TIMEOUT_S` | `180` | The old hard-coded 60s was blown by cold start |
| `OLLAMA_THINK` | `0` | **Leave at 0.** [[Models and Routing#The thinking-model trap]] |
| `AIRLLM_ENABLED` | `0` | Opt-in 70B-class local deep brain |

## Telegram

| Variable | Notes |
|---|---|
| `TELEGRAM_BOT_TOKEN` | From BotFather |
| `TELEGRAM_ALLOWED_USER_ID` | Your numeric ID. **The bot refuses to start without it.** |
| `TELEGRAM_VOICE_REPLIES` | Spoken replies on/off |

## Behaviour

| Variable | Notes |
|---|---|
| `ZERO_SELF_FIX` | Build→grade→fix loop. `0` disables it |
| `ZERO_SELF_FIX_MAX_ITERS` | `3`. Set to `1` for speed |
| `ZERO_SANDBOX_AGENTS` | `false`. Run agents in a subprocess |
| `FORGE_BUILD_REVIEW` | `0` skips [[Forge]]'s automatic QA pass |
| `WAKE_DEBUG` | Wake-word diagnostics |

## Tools and integrations

| Variable | For |
|---|---|
| `TAVILY_API_KEY` | Web + image search — [[Iris]] |
| `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID` | Premium TTS |
| `PORCUPINE_ACCESS_KEY` | Wake word (openWakeWord is the default and needs no key) |
| `NOTION_API_KEY` | Notion integration |
| `LINKEDIN_EMAIL`, `LINKEDIN_PASSWORD` | [[Nexus]] |
| `GITHUB_TOKEN`, `GITHUB_USERNAME` | Cyph08 |
| `GITHUB_OLD_TOKEN`, `GITHUB_OLD_USERNAME` | Deepen-cyph, for repo migration |
| `SLACK_BOT_TOKEN`, `SLACK_DEFAULT_CHANNEL` | Slack |
| `PHONE_API_KEY` | The older REST phone bridge |
| `PHONE_MODEL` | Whisper size for voice — `base` for latency |

Google OAuth (Gmail, Calendar) uses `google_credentials.json` / `google_token.json`, not
env vars. Both are gitignored.

---

## Known blocker: Gemini image generation

All seven image models return **429** with
`quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier, limit: 0`. Text models on the
same key work fine. A "premium" key made no difference.

It needs **Cloud billing enabled on the key's project**. Gemini Advanced / Google One
subscriptions do **not** grant API quota — that's a common and expensive misunderstanding.
Until then, use the Gemini web app for images.

---
[[Commands]] · [[Models and Routing]] · [[Troubleshooting]] · [[Zero OS]]
