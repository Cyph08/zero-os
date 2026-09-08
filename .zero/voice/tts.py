"""
voice/tts.py — Zero OS Text-to-Speech Pipeline

Primary: edge-tts (Microsoft Edge TTS — free, no API key, female voice)
Premium: ElevenLabs (free tier: 10,000 chars/month — higher quality female voice)

Auto-selects ElevenLabs if ELEVENLABS_API_KEY is set, falls back to Edge TTS.

Voice assignments:
    Zero (persona="zero"):
        ElevenLabs: Charlotte  XB0fDUnXU5powFXDhCwa  British female — direct, clear
        Edge TTS:   en-GB-SoniaNeural
        Env override: ZERO_VOICE_ID

    V (persona="v"):
        ElevenLabs: Rachel  21m00Tcm4TlvDq8ikWAM  American female — calm, warm
        Edge TTS:   en-US-JennyNeural
        Env override: V_VOICE_ID

    Legacy env ELEVENLABS_VOICE_ID still respected (overrides both).

Markdown stripping:
    All text passes through strip_markdown_for_speech() before synthesis.
    This converts **bold**, *italic*, bullet points, headers, code blocks, etc.
    to natural spoken language equivalents.

Dependencies:
    uv pip install edge-tts elevenlabs pygame
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import tempfile
import threading
import time
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)

# Global audio arbiter — only one voice may play at a time. Concurrent speak()
# calls (e.g. two agents finishing together, or a cron alert during a reply)
# queue behind this lock instead of overlapping — the known two-voices bug.
_PLAYBACK_LOCK = threading.Lock()

LOG_DIR = Path(__file__).parent.parent / "logs"

# ---------------------------------------------------------------------------
# Config — reads from .env (loaded by api/main.py on startup)
# ---------------------------------------------------------------------------

# Edge TTS voices per persona
EDGE_VOICE_ZERO   = "en-GB-SoniaNeural"    # Zero — British female, direct
EDGE_VOICE_V      = "en-US-JennyNeural"    # V — American female, warm
EDGE_FEMALE_VOICE = EDGE_VOICE_ZERO        # legacy alias
EDGE_DEFAULT_RATE   = "+0%"
EDGE_DEFAULT_VOLUME = "+0%"

# ElevenLabs voice IDs per persona
_EL_VOICE_ZERO = "XB0fDUnXU5powFXDhCwa"   # Charlotte — British female
_EL_VOICE_V    = "21m00Tcm4TlvDq8ikWAM"   # Rachel — American female, calm

def _el_voice_for_persona(persona: str = "zero") -> str:
    """Return the ElevenLabs voice ID for the given persona."""
    # Legacy override still respected
    legacy = os.getenv("ELEVENLABS_VOICE_ID")
    if legacy:
        return legacy
    if persona == "v":
        return os.getenv("V_VOICE_ID", _EL_VOICE_V)
    return os.getenv("ZERO_VOICE_ID", _EL_VOICE_ZERO)

# Keep for backward compatibility
def _el_voice_id() -> str:
    return _el_voice_for_persona("zero")


class TTSBackend(str, Enum):
    EDGE       = "edge"
    ELEVENLABS = "elevenlabs"


# ---------------------------------------------------------------------------
# Markdown → spoken language pre-processor
# ---------------------------------------------------------------------------

def strip_markdown_for_speech(text: str) -> str:
    """
    Convert markdown-formatted text to natural spoken language before TTS.

    LLMs often return responses with asterisks, bullet points, headers, and
    code fences. Feeding these to TTS produces robotic output like
    "asterisk asterisk bold asterisk asterisk" — this function fixes that.

    Args:
        text: Raw LLM response (may contain markdown formatting).

    Returns:
        Clean plain-text suitable for speech synthesis.
    """
    if not text:
        return text

    # ── Code blocks — replace with verbal cue ──────────────────────────────
    text = re.sub(r"```[\w]*\n?(.*?)```", r" — code block: \1 — ", text, flags=re.DOTALL)
    text = re.sub(r"`([^`]+)`", r"\1", text)   # inline code: just keep text

    # ── Headers (#, ##, ###) ────────────────────────────────────────────────
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)

    # ── Bold and italic ──────────────────────────────────────────────────────
    text = re.sub(r"\*{3}(.+?)\*{3}", r"\1", text)   # ***bold italic***
    text = re.sub(r"\*{2}(.+?)\*{2}", r"\1", text)   # **bold**
    text = re.sub(r"\*(.+?)\*",       r"\1", text)   # *italic*
    text = re.sub(r"__(.+?)__",       r"\1", text)   # __bold__
    text = re.sub(r"_(.+?)_",         r"\1", text)   # _italic_

    # ── Bullet / numbered lists ──────────────────────────────────────────────
    # Convert "- item" or "* item" → "item," (comma pause)
    text = re.sub(r"^\s*[-*•]\s+", "", text, flags=re.MULTILINE)
    # Numbered lists: "1. item" → "item"
    text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.MULTILINE)

    # ── URLs ─────────────────────────────────────────────────────────────────
    # [text](url) → just text
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
    # Bare URLs — skip reading them
    text = re.sub(r"https?://\S+", "link", text)

    # ── Horizontal rules ─────────────────────────────────────────────────────
    text = re.sub(r"^[-*_]{3,}\s*$", " — ", text, flags=re.MULTILINE)

    # ── Tables ───────────────────────────────────────────────────────────────
    text = re.sub(r"\|", " ", text)
    text = re.sub(r"^\s*[-:]+\s*$", "", text, flags=re.MULTILINE)

    # ── Blockquotes ──────────────────────────────────────────────────────────
    text = re.sub(r"^>\s+", "", text, flags=re.MULTILINE)

    # ── Emoji shortcodes (e.g. :rocket:) ─────────────────────────────────────
    text = re.sub(r":[a-z_]+:", "", text)

    # ── Collapse runs of whitespace ───────────────────────────────────────────
    # Preserve paragraph breaks (double newline → brief pause marker)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)

    return text.strip()


# ---------------------------------------------------------------------------
# pygame audio init (done once)
# ---------------------------------------------------------------------------

_pygame_ready = False

def _init_pygame() -> bool:
    """
    Initialise pygame mixer for audio playback. Safe to call multiple times.

    Returns:
        True if pygame is ready, False if import failed.
    """
    global _pygame_ready
    if _pygame_ready:
        return True
    try:
        import pygame
        pygame.mixer.init()
        _pygame_ready = True
        return True
    except Exception as exc:
        logger.error(f"[tts] pygame init failed: {exc}")
        return False


def _play_audio(path: Path) -> None:
    """
    Play an audio file using pygame. Blocks until playback finishes.

    Serialised by the global playback lock: if another voice is already
    speaking, this call waits its turn instead of talking over it.

    Args:
        path: Path to the mp3 audio file.
    """
    if not _init_pygame():
        logger.error("[tts] Cannot play audio — pygame not available")
        return
    with _PLAYBACK_LOCK:
        try:
            import pygame
            pygame.mixer.music.load(str(path))
            pygame.mixer.music.play()
            # Block until done
            while pygame.mixer.music.get_busy():
                time.sleep(0.05)
        except Exception as exc:
            logger.error(f"[tts] Playback failed for {path}: {exc}")


# ---------------------------------------------------------------------------
# Edge TTS (primary / fallback)
# ---------------------------------------------------------------------------

async def _edge_generate_async(
    text: str,
    voice: str,
    rate: str,
    volume: str,
    output_path: Path,
) -> None:
    """
    Generate Edge TTS audio and save to file.

    Args:
        text: Text to synthesise.
        voice: Edge TTS voice name string.
        rate: Speaking rate (e.g. '+10%').
        volume: Volume (e.g. '+0%').
        output_path: Destination mp3 path.
    """
    import edge_tts
    communicate = edge_tts.Communicate(text, voice, rate=rate, volume=volume)
    await communicate.save(str(output_path))


def edge_speak(
    text: str,
    voice: str = EDGE_FEMALE_VOICE,
    rate: str = EDGE_DEFAULT_RATE,
    play: bool = True,
    output_path: Path | None = None,
) -> Path:
    """
    Synthesise text with Edge TTS (free, British female by default).

    Args:
        text: Text to speak.
        voice: Edge TTS voice name. Default is Sonia (British female).
        rate: Speaking rate adjustment.
        play: Play immediately if True.
        output_path: Optional path to save the audio file.

    Returns:
        Path to the generated mp3 file.
    """
    if output_path is None:
        tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        output_path = Path(tmp.name)
        tmp.close()

    t0 = time.time()
    asyncio.run(_edge_generate_async(text, voice, rate, EDGE_DEFAULT_VOLUME, output_path))
    logger.info(f"[tts] Edge TTS generated in {time.time()-t0:.2f}s")

    if play:
        _play_audio(output_path)

    _log_tts("edge", text, time.time() - t0)
    return output_path


# ---------------------------------------------------------------------------
# ElevenLabs TTS (premium — free tier: 10k chars/month)
# ---------------------------------------------------------------------------

def elevenlabs_speak(
    text: str,
    voice_id: str | None = None,
    play: bool = True,
    output_path: Path | None = None,
    persona: str = "zero",
) -> Path:
    """
    Synthesise text with ElevenLabs (higher quality, female voice).

    Free tier: 10,000 characters/month — no payment needed.
    Get key at: https://elevenlabs.io (sign up → Profile → API Key)

    Requires ELEVENLABS_API_KEY in .env.

    Args:
        text: Text to speak.
        voice_id: ElevenLabs voice ID. Reads ELEVENLABS_VOICE_ID from .env if None.
        play: Play immediately if True.
        output_path: Optional path to save the audio file.

    Returns:
        Path to the generated mp3 file.
    """
    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not api_key:
        raise EnvironmentError("ELEVENLABS_API_KEY not set in .env")

    resolved_voice = voice_id or _el_voice_for_persona(persona)

    from elevenlabs import ElevenLabs

    client = ElevenLabs(api_key=api_key)

    if output_path is None:
        tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        output_path = Path(tmp.name)
        tmp.close()

    t0 = time.time()

    # ElevenLabs v1.0+ SDK — text_to_speech.convert returns a generator of bytes
    audio_stream = client.text_to_speech.convert(
        voice_id=resolved_voice,
        text=text,
        model_id="eleven_multilingual_v2",
        output_format="mp3_44100_128",
    )

    with output_path.open("wb") as f:
        for chunk in audio_stream:
            f.write(chunk)

    logger.info(
        f"[tts] ElevenLabs generated in {time.time()-t0:.2f}s "
        f"voice={resolved_voice}"
    )

    if play:
        _play_audio(output_path)

    _log_tts("elevenlabs", text, time.time() - t0)
    return output_path


# ---------------------------------------------------------------------------
# Unified speak() — auto-selects backend
# ---------------------------------------------------------------------------

def speak(
    text: str,
    play: bool = True,
    output_path: Path | None = None,
    force_backend: TTSBackend | None = None,
    persona: str = "zero",
) -> Path:
    """
    Synthesise and optionally play text.

    Strips markdown formatting before synthesis so LLM responses don't get
    spoken literally (e.g. "asterisk asterisk bold asterisk asterisk").

    Auto-selects ElevenLabs if ELEVENLABS_API_KEY is set in .env,
    otherwise falls back to Edge TTS.

    Voice routing by persona:
        persona="zero" → Charlotte (EL) / Sonia (Edge) — British female
        persona="v"    → Rachel (EL) / Jenny (Edge) — American female, calm

    Args:
        text: Text to speak (markdown OK — stripped automatically).
        play: Play immediately if True.
        output_path: Optional path to save the audio file.
        force_backend: Override auto-selection (TTSBackend.EDGE or .ELEVENLABS).
        persona: Active persona — 'zero' or 'v'. Determines voice.

    Returns:
        Path to generated audio file.
    """
    # Strip markdown before anything else
    clean = strip_markdown_for_speech(text)
    if not clean:
        logger.warning("[tts] Empty text after markdown strip — skipping")
        return Path()

    use_elevenlabs = (
        force_backend == TTSBackend.ELEVENLABS
        or (force_backend is None and bool(os.getenv("ELEVENLABS_API_KEY")))
    )

    if use_elevenlabs:
        try:
            return elevenlabs_speak(clean, play=play, output_path=output_path, persona=persona)
        except Exception as exc:
            logger.warning(f"[tts] ElevenLabs failed ({exc}) — falling back to Edge TTS")

    # Edge TTS: pick voice based on persona
    edge_voice = EDGE_VOICE_V if persona == "v" else EDGE_VOICE_ZERO
    return edge_speak(clean, voice=edge_voice, play=play, output_path=output_path)


# ---------------------------------------------------------------------------
# speak_to_bytes — for phone bridge (returns audio bytes, no playback)
# ---------------------------------------------------------------------------

def speak_to_bytes(
    text: str,
    voice: str = EDGE_FEMALE_VOICE,
    force_backend: TTSBackend | None = None,
    persona: str = "zero",
) -> bytes:
    """
    Synthesise text and return raw MP3 bytes without playing audio.

    Used by phone/bridge.py and /tts API endpoint to send audio over HTTP.
    Markdown is stripped before synthesis.

    Args:
        text: Text to synthesise (markdown OK — stripped automatically).
        voice: TTS voice name (Edge TTS voice string, only used if force_backend=EDGE).
        force_backend: Override auto-selection.
        persona: Active persona — 'zero' or 'v'.

    Returns:
        MP3 audio as raw bytes.
    """
    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    tmp_path = Path(tmp.name)
    tmp.close()

    try:
        speak(text, play=False, output_path=tmp_path, force_backend=force_backend, persona=persona)
        return tmp_path.read_bytes()
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Voice listing helper (ElevenLabs)
# ---------------------------------------------------------------------------

def list_elevenlabs_voices() -> list[dict]:
    """
    List all available voices on your ElevenLabs account.
    Useful for finding voice IDs to set in .env.

    Returns:
        List of dicts with name, voice_id, gender, and description.
    """
    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not api_key:
        raise EnvironmentError("ELEVENLABS_API_KEY not set in .env")

    from elevenlabs import ElevenLabs
    client = ElevenLabs(api_key=api_key)
    response = client.voices.get_all()

    voices = []
    for v in response.voices:
        voices.append({
            "name": v.name,
            "voice_id": v.voice_id,
            "gender": (v.labels or {}).get("gender", "unknown"),
            "accent": (v.labels or {}).get("accent", ""),
            "description": (v.labels or {}).get("description", ""),
        })
    return voices


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _log_tts(backend: str, text: str, duration_s: float) -> None:
    """
    Append TTS event to logs/tts.log.

    Args:
        backend: 'edge' or 'elevenlabs'.
        text: Text synthesised.
        duration_s: Generation time in seconds.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / "tts.log"
    entry = (
        f"timestamp={time.strftime('%Y-%m-%dT%H:%M:%S')} "
        f"agent=tts "
        f"backend={backend} "
        f"chars={len(text)} "
        f"duration_s={duration_s:.2f} "
        f"text={text[:80]!r}\n"
    )
    try:
        with log_file.open("a", encoding="utf-8") as f:
            f.write(entry)
    except OSError as exc:
        logger.error(f"[tts] Failed to write log: {exc}")


# ---------------------------------------------------------------------------
# CLI test / voice browser
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)

    if "--list-voices" in sys.argv:
        print("\nAvailable ElevenLabs voices:")
        for v in list_elevenlabs_voices():
            print(f"  [{v['gender']:6}] {v['name']:20} id={v['voice_id']}  {v['description']}")
    else:
        text = " ".join(a for a in sys.argv[1:] if not a.startswith("--"))
        text = text or "Hello Cyph. Zero OS is online and ready."
        print(f"Speaking: {text!r}")
        speak(text)
