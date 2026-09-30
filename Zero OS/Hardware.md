---
tags: [zero-os, reference]
---

# Hardware

The machine Zero runs on. Most model decisions trace back to one number: **6GB of VRAM.**

| | |
|---|---|
| GPU | NVIDIA RTX 4050 — **6GB** |
| CPU | AMD Ryzen 7 7435HS — 8 cores / 16 threads |
| RAM | 24GB DDR5 |
| Storage | SSD |
| OS | Windows 11 — PowerShell |

## The VRAM budget

Two things want the GPU at the same time: the local LLM and Whisper.

| | Size |
|---|---|
| Whisper `large-v3` (fp16, CUDA) | ~3GB |
| `qwen3:8b` Q4_K_M + 4K context | ~6.0GB |
| `qwen3.5:4b` | 3.4GB |

**An 8B model and Whisper cannot coexist in 6GB.** That's the whole reason the local model
is 4B — see [[Models and Routing#The local model — and why it's 4B]]. Keep local context
≤ 8K.

Measured for `qwen3.5:4b`: cold 93s · warm 2.9s · 48 tok/s · 100% GPU · 3.1GB VRAM.

## Practical limits

- **Local LLM:** ~7B max at Q4/Q5 GGUF, and only if nothing else wants the GPU.
- **Whisper:** `large-v3` fits alone; `base` (`PHONE_MODEL`) is used for Telegram and phone
  latency.
- **Stable Diffusion:** 1.5 or SDXL-Turbo at low resolution only.

> [!note] Whisper is currently on CPU anyway
> The installed torch is CPU-only, so `[stt] CUDA not available`. That frees VRAM but makes
> transcription slower. Installing a CUDA build of torch would move it to the GPU — and
> then the 6GB budget above starts to matter again.

Always check whether something fits locally before reaching for cloud.

---
[[Models and Routing]] · [[Zero OS]]
