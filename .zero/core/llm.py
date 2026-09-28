"""
core/llm.py — Zero OS LLM Router

Auto-selects the best available LLM provider based on .env keys.
Priority: Anthropic → Groq → Ollama (local)

This means:
  - Set ANTHROPIC_API_KEY  → uses Claude (Haiku/Sonnet)
  - Set GROQ_API_KEY       → uses Llama 3.1 / Mixtral via Groq (free tier)
  - Neither set            → uses Ollama locally (Mistral 7B on RTX 4050)

All agents import from here — never import anthropic/groq directly in agents.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Provider + model constants
# ---------------------------------------------------------------------------

class Provider(str, Enum):
    MOONSHOT  = "moonshot"   # Kimi — preferred cloud provider
    ANTHROPIC = "anthropic"
    DEEPSEEK  = "deepseek"
    GROQ      = "groq"
    OLLAMA    = "ollama"     # local (Qwen via Ollama) — also serves the hybrid fast tier
    AIRLLM    = "airllm"     # local "deep brain" — big model on tiny GPU (opt-in, slow)


# Model names per provider.
# Three tiers: fast (small tasks) < capable (normal synthesis) < deep (the
# deepest, thesis-level questions). Providers without a stronger model reuse
# capable for deep — the tier still exists so the router never KeyErrors.
_MODELS: dict[Provider, dict[str, str]] = {
    Provider.MOONSHOT: {
        # Kimi (Moonshot). OpenAI-compatible API. k2.6 is the cheap workhorse;
        # k3 is the flagship (2.8T params, 1M context) reserved for the deep tier.
        "fast":    os.getenv("MOONSHOT_FAST_MODEL", "kimi-k2.6"),
        "capable": os.getenv("MOONSHOT_MODEL", "kimi-k2.6"),
        "deep":    os.getenv("MOONSHOT_DEEP_MODEL", "kimi-k3"),
    },
    Provider.ANTHROPIC: {
        "fast":    "claude-haiku-4-5-20251001",
        "capable": "claude-sonnet-4-6",
        "deep":    "claude-opus-4-8",           # Opus — max reasoning for deep work
    },
    Provider.DEEPSEEK: {
        # capable used to be deepseek-reasoner (R1). R1 spends its token budget on
        # chain-of-thought first, so with a long prompt and a modest max_tokens it
        # returns EMPTY content — agents were billed and answered with nothing.
        # V3 for normal synthesis (reliable + ~3x faster), R1 only for deep work.
        "fast":    "deepseek-chat",             # DeepSeek V3
        "capable": "deepseek-chat",             # DeepSeek V3 — always returns content
        "deep":    "deepseek-reasoner",         # DeepSeek R1 — reasoning, needs room
    },
    Provider.GROQ: {
        "fast":    "llama-3.1-8b-instant",     # fast, free
        "capable": "llama-3.3-70b-versatile",  # powerful, free
        "deep":    "llama-3.3-70b-versatile",  # no stronger tier — reuse 70b
    },
    Provider.OLLAMA: {
        # Qwen3.5 4B Q4 ≈ 3.4GB — fits the RTX 4050's 6GB *alongside* Whisper
        # (an 8B Q4 at ~5GB would starve STT). Has tool calling + thinking.
        # Keep the context ≤8K; every extra token eats the same 6GB.
        "fast":    os.getenv("OLLAMA_MODEL", "qwen3.5:4b"),
        "capable": os.getenv("OLLAMA_MODEL", "qwen3.5:4b"),
        "deep":    os.getenv("OLLAMA_MODEL", "qwen3.5:4b"),
    },
    Provider.AIRLLM: {
        # Layer-by-layer inference: a 70B-class model on the 6GB RTX 4050.
        # Slow (minutes/answer) + disk-heavy — opt-in only. Override via AIRLLM_MODEL.
        "fast":    os.getenv("AIRLLM_MODEL", "garage-bAInd/Platypus2-70B-instruct"),
        "capable": os.getenv("AIRLLM_MODEL", "garage-bAInd/Platypus2-70B-instruct"),
        "deep":    os.getenv("AIRLLM_MODEL", "garage-bAInd/Platypus2-70B-instruct"),
    },
}

# Per-model Anthropic pricing (USD per 1M tokens) for honest cost logging across
# the three tiers. Falls back to Sonnet rates for anything unlisted.
_ANTHROPIC_COST: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5-20251001": (0.80, 4.00),
    "claude-sonnet-4-6":         (3.00, 15.00),
    "claude-opus-4-8":           (5.00, 25.00),
}

# Per-model Moonshot pricing (USD per 1M tokens, input/output) — k3 is ~3x k2.6,
# so log it honestly rather than averaging. Unlisted models fall back to k2.6.
_MOONSHOT_COST: dict[str, tuple[float, float]] = {
    "kimi-k2.6":                  (0.95, 4.00),
    "kimi-k2.7-code":             (0.95, 4.00),
    "kimi-k2.7-code-highspeed":   (1.90, 8.00),
    "kimi-k3":                    (3.00, 15.00),
}

# Cost per 1M tokens (usd) — for logging/tracking
_COST: dict[Provider, dict[str, float]] = {
    Provider.MOONSHOT:  {"input": 0.95,   "output": 4.00},   # k2.6 default
    Provider.ANTHROPIC: {"input": 0.25,   "output": 1.25},
    Provider.DEEPSEEK:  {"input": 0.07,   "output": 1.10},   # extremely cheap
    Provider.GROQ:      {"input": 0.0,    "output": 0.0},
    Provider.OLLAMA:    {"input": 0.0,    "output": 0.0},
    Provider.AIRLLM:    {"input": 0.0,    "output": 0.0},   # local — only electricity
}


# ---------------------------------------------------------------------------
# Provider detection
# ---------------------------------------------------------------------------

def _key_set(env_var: str) -> bool:
    """Check if an env var is set and not a placeholder."""
    val = os.getenv(env_var, "")
    return bool(val) and "your_" not in val


_RATE_LIMIT_BACKOFF_S = float(os.getenv("LLM_RATE_LIMIT_BACKOFF_S", "3"))


def _is_rate_limited(exc: BaseException) -> bool:
    """
    True when an exception looks like a provider rate limit (HTTP 429).

    Checked by string because each SDK raises its own class; a wrong guess only
    costs one extra retry, so matching loosely is safer than importing four
    different exception types.

    Args:
        exc: The exception a provider raised.

    Returns:
        True if it should be retried against the same provider.
    """
    text = f"{type(exc).__name__} {exc}".lower()
    return (
        "429" in text
        or "rate limit" in text
        or "ratelimit" in text
        or "too many requests" in text
        or "quota" in text
    )


def _local_fast_enabled() -> bool:
    """
    True when the cheap 'fast' tier should run on the local model first.

    Zero makes 5-15 LLM calls per request; most are short bookkeeping calls
    (agent ranking, query decomposition, draft grading). Serving those from
    local Qwen costs nothing and keeps the cloud spend on real synthesis.
    Set ZERO_LOCAL_FAST=1 in .env to enable. Falls back automatically to the
    normal provider chain if Ollama isn't running.
    """
    return os.getenv("ZERO_LOCAL_FAST", "0").strip() not in ("0", "false", "False", "")


def detect_provider() -> Provider:
    """
    Detect which LLM provider to use based on available API keys in .env.
    Priority: Moonshot → Anthropic → DeepSeek → Groq → Ollama (local)

    Returns:
        Provider enum value.
    """
    if _key_set("MOONSHOT_API_KEY"):
        logger.info("[llm] Provider: Moonshot (Kimi)")
        return Provider.MOONSHOT

    if _key_set("ANTHROPIC_API_KEY"):
        logger.info("[llm] Provider: Anthropic (Claude)")
        return Provider.ANTHROPIC

    if _key_set("DEEPSEEK_API_KEY"):
        logger.info("[llm] Provider: DeepSeek (extremely cheap)")
        return Provider.DEEPSEEK

    if _key_set("GROQ_API_KEY"):
        logger.info("[llm] Provider: Groq (Llama 3.1 — free)")
        return Provider.GROQ

    logger.info("[llm] Provider: Ollama (local Mistral 7B)")
    return Provider.OLLAMA


# ---------------------------------------------------------------------------
# Unified chat function
# ---------------------------------------------------------------------------

@dataclass
class LLMResponse:
    """Unified response object regardless of provider."""
    text: str
    input_tokens: int
    output_tokens: int
    provider: Provider
    model: str
    cost_usd: float


def _provider_chain() -> list[Provider]:
    """
    Ordered list of usable providers, best first, mirroring detect_provider().

    Used by chat() for automatic provider failover: if the top provider errors
    (e.g. Anthropic returns a billing/credit 400), the next one serves the call.
    Ollama is always the local last resort.

    Returns:
        Providers to try in order.
    """
    chain: list[Provider] = []
    if _key_set("MOONSHOT_API_KEY"):
        chain.append(Provider.MOONSHOT)
    if _key_set("ANTHROPIC_API_KEY"):
        chain.append(Provider.ANTHROPIC)
    if _key_set("DEEPSEEK_API_KEY"):
        chain.append(Provider.DEEPSEEK)
    if _key_set("GROQ_API_KEY"):
        chain.append(Provider.GROQ)
    chain.append(Provider.OLLAMA)
    return chain


def chat(
    prompt: str,
    tier: str = "fast",
    system: str = "You are Zero, a personal AI operating system.",
    max_tokens: int = 1024,
    provider: Provider | None = None,
) -> LLMResponse:
    """
    Send a chat message to the best available LLM, with automatic failover.

    Tries providers in priority order (Anthropic → DeepSeek → Groq → Ollama). If
    the preferred one fails for any reason — most importantly an Anthropic
    billing/credit error — the next provider transparently serves the request, so
    Zero never goes dark. The instant the preferred provider works again (e.g.
    credits are topped up), it's used first on the very next call — no restart.

    Args:
        prompt: The user message / prompt.
        tier: 'fast', 'capable', or 'deep'. Unknown tiers degrade to 'capable'.
        system: System prompt.
        max_tokens: Maximum tokens in the response.
        provider: Force a specific provider (skips failover). Auto-detects if None.

    Returns:
        LLMResponse with text and usage metadata.
    """
    # Explicit provider — honour it exactly, only the within-provider tier fallback.
    if provider is not None:
        return _chat_one_provider(provider, prompt, system, tier, max_tokens)

    chain = _provider_chain()

    # Hybrid routing: serve the cheap 'fast' tier from the local model first. If
    # Ollama isn't running the normal chain still follows, so this degrades to
    # cloud-only with no config change.
    if tier == "fast" and _local_fast_enabled():
        chain = [Provider.OLLAMA] + [p for p in chain if p != Provider.OLLAMA]

    last_exc: Exception | None = None
    for i, p in enumerate(chain):
        try:
            resp = _chat_one_provider(p, prompt, system, tier, max_tokens)
            if i > 0:
                logger.info(f"[llm] Served by fallback provider {p.value} (preferred unavailable)")
            return resp
        except Exception as exc:
            # A rate limit is transient and self-clearing — the CEO dispatches
            # agents in parallel, so a busy request can trip one. Back off once
            # and retry the SAME provider before demoting to a weaker one.
            if _is_rate_limited(exc):
                logger.warning(f"[llm] {p.value} rate-limited; retrying in {_RATE_LIMIT_BACKOFF_S}s")
                time.sleep(_RATE_LIMIT_BACKOFF_S)
                try:
                    return _chat_one_provider(p, prompt, system, tier, max_tokens)
                except Exception as retry_exc:
                    exc = retry_exc
            last_exc = exc
            nxt = chain[i + 1].value if i + 1 < len(chain) else "none"
            logger.warning(f"[llm] Provider {p.value} failed ({exc}); falling over to {nxt}")
    raise last_exc if last_exc else RuntimeError("No LLM provider available")


def _chat_one_provider(
    p: Provider, prompt: str, system: str, tier: str, max_tokens: int
) -> LLMResponse:
    """
    Run one chat call against a single provider, with within-provider tier fallback.

    AirLLM is dispatched directly. For the rest, an unknown tier degrades to
    'capable', and a failed 'deep' tier (e.g. no Opus access) drops to 'capable'
    before giving up on this provider.
    """
    if p == Provider.AIRLLM:
        return _chat_airllm(prompt, system, max_tokens)

    # Resilient tier lookup — an unknown tier degrades to 'capable' not a KeyError.
    model = _MODELS[p].get(tier) or _MODELS[p]["capable"]

    try:
        return _dispatch_provider(p, prompt, system, model, max_tokens)
    except Exception as exc:
        # Graceful deep fallback: if the top tier (e.g. Opus) is unavailable to
        # this account, drop to capable rather than failing this provider outright.
        capable_model = _MODELS[p]["capable"]
        if tier == "deep" and model != capable_model:
            logger.warning(
                f"[llm] deep tier {model!r} failed ({exc}); falling back to capable {capable_model!r}"
            )
            return _dispatch_provider(p, prompt, system, capable_model, max_tokens)
        raise


def _dispatch_provider(
    p: Provider, prompt: str, system: str, model: str, max_tokens: int
) -> LLMResponse:
    """Route a single chat call to the concrete provider implementation."""
    if p == Provider.MOONSHOT:
        return _chat_moonshot(prompt, system, model, max_tokens)
    if p == Provider.ANTHROPIC:
        return _chat_anthropic(prompt, system, model, max_tokens)
    elif p == Provider.DEEPSEEK:
        return _chat_deepseek(prompt, system, model, max_tokens)
    elif p == Provider.GROQ:
        return _chat_groq(prompt, system, model, max_tokens)
    else:
        return _chat_ollama(prompt, system, model, max_tokens)


# ---------------------------------------------------------------------------
# Provider implementations
# ---------------------------------------------------------------------------

# Hard ceiling for a single cloud LLM call. Without it, SDK defaults can hang
# for many minutes on a network stall — and the failover chain can't help if
# the first provider never returns. Override via LLM_TIMEOUT_S in .env.
_LLM_TIMEOUT_S = float(os.getenv("LLM_TIMEOUT_S", "90"))


def _chat_anthropic(
    prompt: str, system: str, model: str, max_tokens: int
) -> LLMResponse:
    """Call Anthropic Claude API."""
    import anthropic
    client = anthropic.Anthropic(timeout=_LLM_TIMEOUT_S)
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    text = resp.content[0].text
    inp, out = resp.usage.input_tokens, resp.usage.output_tokens
    in_rate, out_rate = _ANTHROPIC_COST.get(model, _ANTHROPIC_COST["claude-sonnet-4-6"])
    cost = (inp * in_rate + out * out_rate) / 1_000_000
    return LLMResponse(text=text, input_tokens=inp, output_tokens=out,
                       provider=Provider.ANTHROPIC, model=model, cost_usd=cost)


def _chat_moonshot(
    prompt: str, system: str, model: str, max_tokens: int
) -> LLMResponse:
    """Call Moonshot (Kimi). OpenAI-compatible endpoint at api.moonshot.ai/v1."""
    from openai import OpenAI
    client = OpenAI(
        api_key=os.getenv("MOONSHOT_API_KEY"),
        base_url=os.getenv("MOONSHOT_BASE_URL", "https://api.moonshot.ai/v1"),
        timeout=_LLM_TIMEOUT_S,
    )
    resp = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": prompt},
        ],
    )
    text = resp.choices[0].message.content or ""
    inp = resp.usage.prompt_tokens if resp.usage else 0
    out = resp.usage.completion_tokens if resp.usage else 0
    in_rate, out_rate = _MOONSHOT_COST.get(model, _MOONSHOT_COST["kimi-k2.6"])
    cost = (inp * in_rate + out * out_rate) / 1_000_000
    return LLMResponse(text=text, input_tokens=inp, output_tokens=out,
                       provider=Provider.MOONSHOT, model=model, cost_usd=cost)


def _chat_deepseek(
    prompt: str, system: str, model: str, max_tokens: int
) -> LLMResponse:
    """Call DeepSeek API (OpenAI-compatible). ~$0.07/1M input tokens."""
    from openai import OpenAI
    client = OpenAI(
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url="https://api.deepseek.com",
        timeout=_LLM_TIMEOUT_S,
    )
    resp = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": prompt},
        ],
    )
    msg = resp.choices[0].message
    text = (msg.content or "").strip()
    if not text:
        # Safety net for deepseek-reasoner: if the token budget ran out during
        # chain-of-thought, content is empty but reasoning_content holds the
        # thinking. Better to salvage that than hand the caller nothing.
        text = (getattr(msg, "reasoning_content", None) or "").strip()
        if text:
            logger.warning(
                f"[llm] {model} returned empty content "
                f"(finish={resp.choices[0].finish_reason}); salvaged reasoning_content"
            )
    inp = resp.usage.prompt_tokens if resp.usage else 0
    out = resp.usage.completion_tokens if resp.usage else 0
    cost = (inp * 0.07 + out * 1.10) / 1_000_000
    return LLMResponse(text=text, input_tokens=inp, output_tokens=out,
                       provider=Provider.DEEPSEEK, model=model, cost_usd=cost)


def _chat_groq(
    prompt: str, system: str, model: str, max_tokens: int
) -> LLMResponse:
    """Call Groq API (OpenAI-compatible, free tier)."""
    from groq import Groq
    client = Groq(api_key=os.getenv("GROQ_API_KEY"), timeout=_LLM_TIMEOUT_S)
    resp = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": prompt},
        ],
    )
    text = resp.choices[0].message.content or ""
    inp = resp.usage.prompt_tokens if resp.usage else 0
    out = resp.usage.completion_tokens if resp.usage else 0
    return LLMResponse(text=text, input_tokens=inp, output_tokens=out,
                       provider=Provider.GROQ, model=model, cost_usd=0.0)


def _chat_ollama(
    prompt: str, system: str, model: str, max_tokens: int
) -> LLMResponse:
    """Call Ollama local API (must be running: `ollama serve`)."""
    import httpx
    payload = {
        "model": model,
        "messages": [
            {"role": "system",  "content": system},
            {"role": "user",    "content": prompt},
        ],
        "stream": False,
        "options": {"num_predict": max_tokens},
    }
    try:
        resp = httpx.post(
            "http://localhost:11434/api/chat",
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        text = data.get("message", {}).get("content", "")
        return LLMResponse(text=text, input_tokens=0, output_tokens=0,
                           provider=Provider.OLLAMA, model=model, cost_usd=0.0)
    except Exception as exc:
        raise RuntimeError(
            f"Ollama not reachable. Run `ollama serve` then `ollama pull mistral`. Error: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# AirLLM — optional local "deep brain"
# ---------------------------------------------------------------------------

# The layered model is enormous to load, so cache it across calls.
_AIRLLM_MODEL = None


def airllm_available() -> bool:
    """True only if AirLLM is explicitly enabled, installed, and given a model.

    Gate: AIRLLM_ENABLED=1 AND the `airllm` package importable AND AIRLLM_MODEL
    set. Keeps the heavy dependency strictly opt-in.
    """
    if os.getenv("AIRLLM_ENABLED", "0").strip() in ("0", "false", "False", ""):
        return False
    if not os.getenv("AIRLLM_MODEL", ""):
        return False
    try:
        import airllm  # noqa: F401
        return True
    except Exception:
        return False


def chat_deep(
    prompt: str,
    system: str = "You are Zero, a personal AI operating system.",
    max_tokens: int = 512,
) -> LLMResponse:
    """Route a heavy/offline task to the local AirLLM deep brain if enabled,
    else fall back to the normal 'capable' cloud tier.

    Use for privacy-sensitive or fully-offline deep work where quality matters
    more than speed — AirLLM is SLOW (minutes per answer on a 6GB GPU). Never
    use for live conversation.
    """
    if airllm_available():
        try:
            return _chat_airllm(prompt, system, max_tokens)
        except Exception as exc:
            logger.warning(f"[llm] AirLLM failed, falling back to capable tier: {exc}")
    return chat(prompt, tier="capable", system=system, max_tokens=max_tokens)


def _chat_airllm(prompt: str, system: str, max_tokens: int) -> LLMResponse:
    """Generate with a local large model via AirLLM (layer-by-layer from disk
    so a 70B model fits in ~4-6GB VRAM).

    Requires: `pip install airllm`, AIRLLM_ENABLED=1, AIRLLM_MODEL=<hf repo id>.
    Optional: AIRLLM_COMPRESSION=4bit|8bit|none, AIRLLM_MAX_INPUT=<tokens>.
    """
    global _AIRLLM_MODEL
    model_id = os.getenv("AIRLLM_MODEL", "")
    if not model_id:
        raise RuntimeError("AIRLLM_MODEL not set in .env")

    from airllm import AutoModel

    if _AIRLLM_MODEL is None:
        compression = (os.getenv("AIRLLM_COMPRESSION", "4bit") or "").strip()
        kwargs: dict = {}
        if compression and compression.lower() != "none":
            kwargs["compression"] = compression
        logger.info(f"[llm] Loading AirLLM model {model_id!r} (slow on first run)...")
        _AIRLLM_MODEL = AutoModel.from_pretrained(model_id, **kwargs)

    model = _AIRLLM_MODEL
    full_prompt = f"{system}\n\n{prompt}" if system else prompt
    max_input = int(os.getenv("AIRLLM_MAX_INPUT", "512"))
    tokens = model.tokenizer(
        [full_prompt],
        return_tensors="pt",
        return_attention_mask=False,
        truncation=True,
        max_length=max_input,
        padding=False,
    )
    input_ids = tokens["input_ids"]
    try:
        import torch
        if torch.cuda.is_available():
            input_ids = input_ids.cuda()
    except Exception:
        pass

    generation = model.generate(
        input_ids,
        max_new_tokens=max_tokens,
        use_cache=True,
        return_dict_in_generate=True,
    )
    text = model.tokenizer.decode(generation.sequences[0])
    if text.startswith(full_prompt):
        text = text[len(full_prompt):]
    return LLMResponse(
        text=text.strip(),
        input_tokens=0,
        output_tokens=0,
        provider=Provider.AIRLLM,
        model=model_id,
        cost_usd=0.0,
    )
