"""
voice/wake.py — Zero OS Wake Word Detection

Supports two personas: Zero and V.
  Zero — activated by "Zero" (uses hey_jarvis model as fallback).
  V    — activated by "Hey V" (uses hey_mycroft model as fallback).

Both use openWakeWord (fully open source, no account required, offline).

Fallback plan:
  1. Custom models: models/zero.onnx and models/hey_v.onnx (train to remove fallback)
  2. Until trained: Zero = hey_jarvis, V = hey_mycroft (both wake Zero's orchestrator,
     but the on_wake callback receives the persona name so the system switches accordingly)

Train custom wake words (~10 min each on CPU):
  python -m openwakeword.train --target_phrase "zero"  --output_dir models/
  python -m openwakeword.train --target_phrase "hey v" --output_dir models/

Usage:
  from voice.wake import DualWakeDetector
  detector = DualWakeDetector(on_wake=my_callback)
  detector.start()
  # my_callback receives ("zero") or ("v") as the persona string

  Single detector (legacy):
  from voice.wake import WakeWordDetector
  detector = WakeWordDetector(callback=my_function)
  detector.start()
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SAMPLE_RATE = 16000
CHUNK_SIZE = 1280            # 80ms at 16kHz — openWakeWord default
DETECTION_THRESHOLD = float(os.getenv("WAKE_THRESHOLD", "0.5"))
COOLDOWN_S = 2.0             # seconds between consecutive detections

ZERO_MODEL_PATH = Path(__file__).parent.parent / "models" / "zero.onnx"
V_MODEL_PATH    = Path(__file__).parent.parent / "models" / "hey_v.onnx"


# ---------------------------------------------------------------------------
# Single-persona detector (legacy / standalone use)
# ---------------------------------------------------------------------------

class WakeWordDetector:
    """
    Listens on the default microphone and fires a callback when the
    wake word is detected (single-persona version).

    Args:
        callback:  Called (with no args) on detection.
        threshold: Confidence threshold 0.0–1.0.
        persona:   Which persona model to load ('zero' or 'v').
    """

    def __init__(
        self,
        callback: Callable[[], None] | None = None,
        threshold: float = DETECTION_THRESHOLD,
        persona: str = "zero",
    ) -> None:
        self.callback = callback
        self.threshold = threshold
        self.persona = persona
        self._running = False
        self._thread: threading.Thread | None = None
        self._oww = None
        self._stream = None

    # ------------------------------------------------------------------
    # Initialisation helpers
    # ------------------------------------------------------------------

    def _load_model(self) -> bool:
        """
        Load the appropriate openWakeWord model for this persona.

        Returns True on success.
        """
        try:
            import openwakeword
            from openwakeword.model import Model

            if self.persona == "v":
                if V_MODEL_PATH.exists():
                    logger.info(f"[wake] V: loading custom model {V_MODEL_PATH}")
                    self._oww = Model(
                        wakeword_models=[str(V_MODEL_PATH)],
                        inference_framework="onnx",
                    )
                else:
                    logger.info("[wake] V: hey_v.onnx not found — using hey_mycroft fallback")
                    logger.info("[wake] Train: python -m openwakeword.train --target_phrase 'hey v' --output_dir models/")
                    self._oww = Model(wakeword_models=["hey_mycroft"], inference_framework="onnx")
            else:
                if ZERO_MODEL_PATH.exists():
                    logger.info(f"[wake] Zero: loading custom model {ZERO_MODEL_PATH}")
                    self._oww = Model(
                        wakeword_models=[str(ZERO_MODEL_PATH)],
                        inference_framework="onnx",
                    )
                else:
                    logger.info("[wake] Zero: zero.onnx not found — using hey_jarvis fallback")
                    logger.info("[wake] Train: python -m openwakeword.train --target_phrase zero --output_dir models/")
                    self._oww = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")

            openwakeword.utils.download_models()
            logger.info(f"[wake] Model loaded for persona={self.persona}")
            return True

        except ImportError:
            logger.error("[wake] openWakeWord not installed. Run: uv pip install openwakeword")
            return False
        except Exception as exc:
            logger.error(f"[wake] Failed to load model: {exc}")
            return False

    def _open_mic(self) -> bool:
        """Open the default microphone stream. Returns True on success."""
        try:
            import pyaudio
            pa = pyaudio.PyAudio()
            self._stream = pa.open(
                rate=SAMPLE_RATE,
                channels=1,
                format=pyaudio.paInt16,
                input=True,
                frames_per_buffer=CHUNK_SIZE,
            )
            logger.info(f"[wake] Mic stream open (persona={self.persona})")
            return True
        except Exception as exc:
            logger.error(f"[wake] Microphone error: {exc}")
            return False

    # ------------------------------------------------------------------
    # Detection loop
    # ------------------------------------------------------------------

    def _listen_loop(self) -> None:
        """Read audio chunks, run inference, fire callback on detection."""
        import numpy as np

        label = self.persona.upper()
        logger.info(f"[wake] Listening for '{label}'…")
        last_detection = 0.0

        while self._running:
            try:
                chunk = self._stream.read(CHUNK_SIZE, exception_on_overflow=False)
                audio = np.frombuffer(chunk, dtype=np.int16)
                self._oww.predict(audio)

                for model_name, score in self._oww.prediction_buffer.items():
                    latest = score[-1] if score else 0.0
                    if latest >= self.threshold:
                        now = time.time()
                        if now - last_detection > COOLDOWN_S:
                            last_detection = now
                            logger.info(
                                f"[wake] '{label}' detected "
                                f"(score={latest:.3f}, model={model_name})"
                            )
                            if self.callback:
                                threading.Thread(
                                    target=self.callback, daemon=True
                                ).start()

            except OSError as exc:
                logger.warning(f"[wake] Audio read error: {exc}")
                time.sleep(0.1)
            except Exception as exc:
                logger.error(f"[wake] Loop error: {exc}")
                time.sleep(0.5)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def start(self) -> bool:
        """
        Start the detector in a background thread.

        Returns:
            True if started successfully, False otherwise.
        """
        if self._running:
            logger.warning("[wake] Already running")
            return True

        if not self._load_model():
            return False
        if not self._open_mic():
            return False

        self._running = True
        self._thread = threading.Thread(
            target=self._listen_loop,
            name=f"zero-wake-{self.persona}",
            daemon=True,
        )
        self._thread.start()
        logger.info(f"[wake] Detector started — persona={self.persona}")
        return True

    def stop(self) -> None:
        """Stop the detector and release audio resources."""
        self._running = False
        if self._stream:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception:
                pass
        if self._thread:
            self._thread.join(timeout=2.0)
        logger.info(f"[wake] Detector stopped — persona={self.persona}")

    def run(self, callback: Callable[[], None] | None = None) -> None:
        """
        Start detector and block until KeyboardInterrupt.

        Args:
            callback: Optional override callback.
        """
        if callback:
            self.callback = callback
        if self.start():
            try:
                while True:
                    time.sleep(0.5)
            except KeyboardInterrupt:
                logger.info("[wake] Interrupted")
            finally:
                self.stop()


# ---------------------------------------------------------------------------
# Dual-persona detector — Zero and V listen simultaneously
# ---------------------------------------------------------------------------

class DualWakeDetector:
    """
    Listens for BOTH personas on a single microphone stream.

    Previous design ran two WakeWordDetector instances — i.e. two PyAudio input
    streams competing for the same default mic. On Windows that contention was
    the root of the known wake-word unreliability. This version opens ONE mic
    stream and loads ONE openWakeWord Model with both wake models, so both
    personas are scored on every audio chunk with no device contention.

    When Zero fires: the on_wake callback receives "zero".
    When V fires: the on_wake callback receives "v".

    Debugging: set WAKE_DEBUG=1 to log the best confidence score once per second
    even below threshold, so misses are visible instead of silent.

    Args:
        on_wake:   Callable[str] — receives the persona name string.
        threshold: Shared detection threshold.
    """

    def __init__(
        self,
        on_wake: Callable[[str], None] | None = None,
        threshold: float = DETECTION_THRESHOLD,
    ) -> None:
        self._on_wake = on_wake
        self._threshold = threshold
        self._last_switch = 0.0
        self._switch_cooldown = 3.0   # 3s between persona switches
        self._running = False
        self._thread: threading.Thread | None = None
        self._oww = None
        self._pa = None
        self._stream = None
        self._debug = os.getenv("WAKE_DEBUG", "0").strip() in ("1", "true", "True")
        # model name (as reported in prediction_buffer) → persona
        self._model_persona: dict[str, str] = {}

    def _load_models(self) -> bool:
        """
        Load both persona wake models into a single openWakeWord Model.

        Returns:
            True on success.
        """
        try:
            import openwakeword
            from openwakeword.model import Model

            # Ensure base feature models exist BEFORE constructing Model —
            # the old order (Model first) failed on a fresh machine.
            try:
                openwakeword.utils.download_models()
            except Exception as exc:
                logger.warning(f"[wake] download_models: {exc} (continuing — may be cached)")

            zero_model = str(ZERO_MODEL_PATH) if ZERO_MODEL_PATH.exists() else "hey_jarvis"
            v_model = str(V_MODEL_PATH) if V_MODEL_PATH.exists() else "hey_mycroft"
            self._model_persona = {
                Path(zero_model).stem: "zero",
                Path(v_model).stem: "v",
            }
            logger.info(f"[wake] Zero model: {zero_model} | V model: {v_model}")
            self._oww = Model(
                wakeword_models=[zero_model, v_model],
                inference_framework="onnx",
            )
            return True
        except ImportError:
            logger.error("[wake] openWakeWord not installed. Run: uv pip install openwakeword")
            return False
        except Exception as exc:
            logger.error(f"[wake] Failed to load models: {exc}")
            return False

    def _open_mic(self) -> bool:
        """Open ONE shared microphone stream. Returns True on success."""
        try:
            import pyaudio
            self._pa = pyaudio.PyAudio()
            self._stream = self._pa.open(
                rate=SAMPLE_RATE,
                channels=1,
                format=pyaudio.paInt16,
                input=True,
                frames_per_buffer=CHUNK_SIZE,
            )
            logger.info("[wake] Single shared mic stream open (dual personas)")
            return True
        except Exception as exc:
            logger.error(f"[wake] Microphone error: {exc}")
            self._release_audio()
            return False

    def _release_audio(self) -> None:
        """Close the stream and terminate PyAudio (previously leaked)."""
        if self._stream is not None:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        if self._pa is not None:
            try:
                self._pa.terminate()
            except Exception:
                pass
            self._pa = None

    def _listen_loop(self) -> None:
        """Read chunks from the one mic, score BOTH personas each chunk."""
        import numpy as np

        logger.info("[wake] Listening for ZERO and V on one stream…")
        last_debug = 0.0

        while self._running:
            try:
                chunk = self._stream.read(CHUNK_SIZE, exception_on_overflow=False)
                audio = np.frombuffer(chunk, dtype=np.int16)
                self._oww.predict(audio)

                best_name, best_score = "", 0.0
                for model_name, scores in self._oww.prediction_buffer.items():
                    latest = scores[-1] if len(scores) else 0.0
                    if latest > best_score:
                        best_name, best_score = model_name, latest
                    if latest >= self._threshold:
                        persona = self._persona_for(model_name)
                        self._fire(persona, latest, model_name)

                # Visibility for tuning: log the best score once/second when debugging
                if self._debug and best_name:
                    now = time.time()
                    if now - last_debug >= 1.0:
                        last_debug = now
                        logger.info(
                            f"[wake] best={best_name} score={best_score:.3f} "
                            f"(threshold={self._threshold})"
                        )

            except OSError as exc:
                logger.warning(f"[wake] Audio read error: {exc}")
                time.sleep(0.1)
            except Exception as exc:
                logger.error(f"[wake] Loop error: {exc}")
                time.sleep(0.5)

    def _persona_for(self, model_name: str) -> str:
        """Map a prediction-buffer model name back to 'zero' or 'v'."""
        for stem, persona in self._model_persona.items():
            if stem in model_name:
                return persona
        return "zero"

    def _fire(self, persona: str, score: float, model_name: str) -> None:
        """
        Fire the wake callback for a persona, honouring the switch cooldown.

        Args:
            persona:    'zero' or 'v'.
            score:      Detection confidence.
            model_name: Which model triggered (for the log).
        """
        now = time.time()
        if now - self._last_switch < self._switch_cooldown:
            logger.debug(f"[wake] {persona} detected but in cooldown — ignored")
            return
        self._last_switch = now
        logger.info(f"[wake] '{persona.upper()}' activated (score={score:.3f}, model={model_name})")
        if self._on_wake:
            threading.Thread(target=self._on_wake, args=(persona,), daemon=True).start()

    def start(self) -> bool:
        """
        Start the shared-stream detector in a background thread.

        Returns:
            True if started successfully.
        """
        if self._running:
            logger.warning("[wake] Dual detector already running")
            return True
        if not self._load_models():
            return False
        if not self._open_mic():
            return False
        self._running = True
        self._thread = threading.Thread(
            target=self._listen_loop, name="zero-wake-dual", daemon=True
        )
        self._thread.start()
        logger.info("[wake] Dual detector running — Zero and V share one mic stream")
        return True

    def stop(self) -> None:
        """Stop the detector and release all audio resources."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
        self._release_audio()
        logger.info("[wake] Dual detector stopped")

    def run(self) -> None:
        """Start the detector and block until KeyboardInterrupt."""
        if self.start():
            try:
                while True:
                    time.sleep(0.5)
            except KeyboardInterrupt:
                logger.info("[wake] Interrupted")
            finally:
                self.stop()


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    parser = argparse.ArgumentParser(description="Zero Wake Word Detector")
    parser.add_argument("--dual",   action="store_true", help="Run both Zero and V detectors")
    parser.add_argument("--persona", default="zero",      help="Persona: zero or v (single mode)")
    args = parser.parse_args()

    print("=" * 50)
    print("Zero Wake Word Detector")
    print(f"Threshold : {DETECTION_THRESHOLD}")
    print(f"Zero model: {'custom zero.onnx' if ZERO_MODEL_PATH.exists() else 'hey_jarvis (fallback)'}")
    print(f"V model   : {'custom hey_v.onnx' if V_MODEL_PATH.exists() else 'hey_mycroft (fallback)'}")
    print("=" * 50)

    if args.dual:
        print("Mode: DUAL (both Zero and V listening)")
        print("Say 'Zero' to activate Zero | Say 'Hey V' to activate V\n")

        def on_wake(persona: str) -> None:
            label = "ZERO" if persona == "zero" else "V"
            print(f"\n>>> {label} ACTIVATED\n")

        det = DualWakeDetector(on_wake=on_wake)
        det.run()
    else:
        print(f"Mode: SINGLE — persona={args.persona.upper()}")
        print("Listening... Press Ctrl+C to stop.\n")

        def on_wake_single() -> None:
            print(f"\n>>> {args.persona.upper()} ACTIVATED\n")

        det = WakeWordDetector(callback=on_wake_single, persona=args.persona)
        det.run()
