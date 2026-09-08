"""
voice/stt.py — Zero OS Speech-to-Text Pipeline

Uses OpenAI Whisper (local) for transcription.
Auto-detects CUDA; falls back to CPU gracefully.

Model strategy:
  - DEFAULT_MODEL = "large-v3"  → high accuracy, use for desktop STT
  - PHONE_MODEL   = "base"      → ~1–2s on CPU, use for phone voice endpoint

Dependencies (install with uv):
    uv pip install openai-whisper sounddevice numpy
"""

from __future__ import annotations

import logging
import queue
import tempfile
import time
from pathlib import Path
from typing import Callable

import numpy as np
import sounddevice as sd
import whisper

logger = logging.getLogger(__name__)

LOG_DIR = Path(__file__).parent.parent / "logs"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_MODEL    = "large-v3"     # fits RTX 4050 6GB at fp16; use for desktop STT
PHONE_MODEL      = "base"         # fast on CPU (~1–2s); use for phone voice endpoint
FALLBACK_MODEL   = "medium"       # fallback if VRAM is too tight for large-v3
SAMPLE_RATE      = 16_000         # Hz — Whisper expects 16kHz mono
CHUNK_DURATION   = 0.5            # seconds per audio chunk
SILENCE_THRESHOLD = 0.01          # RMS amplitude below this = silence
SILENCE_DURATION = 1.5            # seconds of silence to trigger end-of-speech
MAX_RECORD_SEC   = 30             # hard cap on recording length


# ---------------------------------------------------------------------------
# Device selection — CUDA if available, else CPU
# ---------------------------------------------------------------------------

def _select_device() -> str:
    """
    Pick the best device for Whisper at import time.

    Returns:
        "cuda" if torch detects a GPU, otherwise "cpu".
    """
    try:
        import torch
        if torch.cuda.is_available():
            logger.info("[stt] CUDA available — Whisper will use GPU")
            return "cuda"
    except ImportError:
        pass
    logger.info("[stt] CUDA not available — Whisper will use CPU")
    return "cpu"


_DEVICE: str = _select_device()


# ---------------------------------------------------------------------------
# Whisper loader (singleton — expensive to load)
# ---------------------------------------------------------------------------

_model_cache: dict[str, whisper.Whisper] = {}


def load_model(model_name: str = DEFAULT_MODEL) -> whisper.Whisper:
    """
    Load a Whisper model onto the best available device. Cached after first load.

    Args:
        model_name: Whisper model size string ('large-v3', 'base', 'medium', etc.).

    Returns:
        Loaded Whisper model.
    """
    if model_name not in _model_cache:
        device = _DEVICE
        logger.info(f"[stt] Loading Whisper {model_name} on {device}…")
        t0 = time.time()
        try:
            _model_cache[model_name] = whisper.load_model(model_name, device=device)
            logger.info(f"[stt] Whisper {model_name} loaded in {time.time()-t0:.1f}s on {device}")
        except RuntimeError as exc:
            if "out of memory" in str(exc).lower() and device == "cuda":
                logger.warning(
                    f"[stt] VRAM insufficient for {model_name} — retrying with {FALLBACK_MODEL} on CPU"
                )
                _model_cache[model_name] = whisper.load_model(FALLBACK_MODEL, device="cpu")
            else:
                raise
    return _model_cache[model_name]


# ---------------------------------------------------------------------------
# Transcription
# ---------------------------------------------------------------------------

def transcribe_file(audio_path: Path, model_name: str = DEFAULT_MODEL) -> str:
    """
    Transcribe an audio file to text.

    Args:
        audio_path: Path to audio file (wav, mp3, m4a, etc.).
        model_name: Whisper model to use.

    Returns:
        Transcribed text string.
    """
    model = load_model(model_name)
    logger.info(f"[stt] Transcribing: {audio_path}")
    t0 = time.time()
    result = model.transcribe(str(audio_path), fp16=(_DEVICE == "cuda"), language="en")
    text: str = result["text"].strip()
    elapsed = time.time() - t0
    logger.info(f"[stt] Transcription done in {elapsed:.2f}s: {text!r}")
    _log_transcription(Path(audio_path) if not isinstance(audio_path, Path) else audio_path, text, elapsed)
    return text


def transcribe_array(audio: np.ndarray, model_name: str = DEFAULT_MODEL) -> str:
    """
    Transcribe a numpy audio array directly (no file I/O).

    Args:
        audio: Float32 numpy array at 16kHz mono.
        model_name: Whisper model to use.

    Returns:
        Transcribed text string.
    """
    model = load_model(model_name)
    t0 = time.time()
    result = model.transcribe(audio, fp16=(_DEVICE == "cuda"), language="en")
    text: str = result["text"].strip()
    logger.info(f"[stt] Array transcription done in {time.time()-t0:.2f}s: {text!r}")
    return text


# ---------------------------------------------------------------------------
# Microphone recording with VAD (voice activity detection)
# ---------------------------------------------------------------------------

def record_until_silence(
    sample_rate: int = SAMPLE_RATE,
    silence_threshold: float = SILENCE_THRESHOLD,
    silence_duration: float = SILENCE_DURATION,
    max_seconds: float = MAX_RECORD_SEC,
    on_speech_start: Callable[[], None] | None = None,
) -> np.ndarray:
    """
    Record from the default microphone until silence is detected.

    Args:
        sample_rate: Audio sample rate in Hz.
        silence_threshold: RMS amplitude below which audio is considered silent.
        silence_duration: Seconds of continuous silence before stopping.
        max_seconds: Hard cap on recording length.
        on_speech_start: Optional callback fired when speech is first detected.

    Returns:
        Float32 numpy array containing the recorded audio.
    """
    chunk_size = int(sample_rate * CHUNK_DURATION)
    audio_queue: queue.Queue[np.ndarray] = queue.Queue()
    speech_started = False
    silence_chunks_needed = int(silence_duration / CHUNK_DURATION)
    silence_count = 0
    chunks_recorded = 0
    max_chunks = int(max_seconds / CHUNK_DURATION)

    def audio_callback(
        indata: np.ndarray,
        frames: int,
        time_info: object,
        status: sd.CallbackFlags,
    ) -> None:
        nonlocal speech_started, silence_count, chunks_recorded
        if status:
            logger.warning(f"[stt] Audio callback status: {status}")
        audio_queue.put(indata.copy())

    recorded_chunks: list[np.ndarray] = []

    with sd.InputStream(
        samplerate=sample_rate,
        channels=1,
        dtype="float32",
        blocksize=chunk_size,
        callback=audio_callback,
    ):
        logger.info("[stt] Recording… (speak now)")

        while chunks_recorded < max_chunks:
            try:
                chunk = audio_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            rms = float(np.sqrt(np.mean(chunk ** 2)))
            chunks_recorded += 1

            if rms > silence_threshold:
                if not speech_started:
                    speech_started = True
                    if on_speech_start:
                        on_speech_start()
                    logger.debug("[stt] Speech detected")
                silence_count = 0
                recorded_chunks.append(chunk)
            else:
                if speech_started:
                    silence_count += 1
                    recorded_chunks.append(chunk)
                    if silence_count >= silence_chunks_needed:
                        logger.debug("[stt] Silence detected — stopping")
                        break

    if not recorded_chunks:
        return np.zeros(0, dtype=np.float32)

    audio = np.concatenate(recorded_chunks, axis=0).flatten()
    logger.info(f"[stt] Recorded {len(audio)/sample_rate:.1f}s of audio")
    return audio


def listen_and_transcribe(
    model_name: str = DEFAULT_MODEL,
    on_speech_start: Callable[[], None] | None = None,
) -> str:
    """
    Record from the microphone and transcribe end-to-end.

    Args:
        model_name: Whisper model to use.
        on_speech_start: Optional callback fired when speech begins.

    Returns:
        Transcribed text string (empty string if no speech detected).
    """
    audio = record_until_silence(on_speech_start=on_speech_start)
    if audio.size == 0:
        logger.warning("[stt] No audio captured")
        return ""
    return transcribe_array(audio, model_name=model_name)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _log_transcription(audio_path: Path, text: str, duration_s: float) -> None:
    """
    Log transcription event.

    Args:
        audio_path: Path to the audio file transcribed.
        text: Transcription output.
        duration_s: Time taken in seconds.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / "stt.log"
    entry = (
        f"timestamp={time.strftime('%Y-%m-%dT%H:%M:%S')} "
        f"agent=stt "
        f"file={audio_path.name} "
        f"duration_s={duration_s:.2f} "
        f"text={text!r}\n"
    )
    try:
        with log_file.open("a", encoding="utf-8") as f:
            f.write(entry)
    except OSError as exc:
        logger.error(f"[stt] Failed to write log: {exc}")


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Speak now… (will stop after 1.5s of silence)")
    text = listen_and_transcribe()
    print(f"\nTranscription: {text!r}")
