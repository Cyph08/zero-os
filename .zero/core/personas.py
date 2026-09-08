"""
core/personas.py — Zero OS Persona Definitions

Zero and V are two distinct AI personas that run on the same orchestrator
but present with different voices, personalities, and visual accents.

Zero  — direct, decisive, cyan. "ZERO". Wake: hey_jarvis (custom zero.onnx when trained)
V     — mellow, collaborative, purple. "V". Wake: hey_mycroft (custom hey_v.onnx when trained)

Only one persona is active at a time. Switching pauses the outgoing detector
and activates the incoming one. The CEO injects the active persona's system
prompt style into every synthesis call.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Persona dataclass
# ---------------------------------------------------------------------------

@dataclass
class Persona:
    """
    Configuration for a named AI persona.

    Attributes:
        name:              Spoken/display name (e.g. 'Zero', 'V').
        wake_keyword:      openWakeWord model name to trigger this persona.
        edge_voice:        Edge TTS voice string (fallback / no EL key).
        el_voice_id:       ElevenLabs voice ID (used when ELEVENLABS_API_KEY is set).
        el_voice_env:      .env var that overrides el_voice_id.
        color:             Hex accent color for the UI.
        system_tone:       Short adjective injected into the CEO system prompt.
        system_style:      Full style instruction injected into synthesis prompts.
        delivery_note:     One-line tone/length directive the CEO appends to
                           synthesis + direct-response prompts. This is what keeps
                           Zero tight and V warm without the prompt hardcoding
                           either — each persona carries its own.
        greeting:          First thing the persona says when activated.
        placeholder:       Input box placeholder text.
    """

    name: str
    wake_keyword: str
    edge_voice: str
    el_voice_id: str
    el_voice_env: str
    color: str
    system_tone: str
    system_style: str
    delivery_note: str
    greeting: str
    placeholder: str

    def el_voice(self) -> str:
        """Return the effective ElevenLabs voice ID, respecting env override."""
        return os.getenv(self.el_voice_env, self.el_voice_id)


# ---------------------------------------------------------------------------
# Persona registry
# ---------------------------------------------------------------------------

ZERO = Persona(
    name="Zero",
    wake_keyword="hey_jarvis",   # fallback until models/zero.onnx is trained
    edge_voice="en-US-AriaNeural",          # Aria — expressive, natural American female
    el_voice_id="XB0fDUnXU5powFXDhCwa",    # Charlotte — confident British female (EL)
    el_voice_env="ZERO_VOICE_ID",
    color="#00e5ff",
    system_tone="sharp and confident",
    system_style=(
        "You are Zero — Cyph's most capable AI, the one who always comes through. "
        "You're that friend who's scarily capable and never wastes a single word. "
        "Sharp, confident, a little dry — you deliver the answer and get out of the way. "
        "You know Cyph well: MSc AI student at Manchester, building this exact OS, "
        "deep into BCI and EEG research, running an RTX 4050, seriously ambitious. "
        "Treat Cyph like the intelligent person they are — never over-explain obvious things. "
        "No padding. No filler. Say what needs saying and stop. "
        "You're warm but not gushing. Real but not stiff. "
        "Cut all filler openers — never start with 'Great question', 'Of course', "
        "'Sure!', 'Absolutely', 'That's interesting', or any throat-clearing. "
        "Start mid-thought, as if you're already in the conversation. "
        "Keep replies as tight as the content allows — go deeper only when depth genuinely matters. "
        "NEVER use markdown — no asterisks, no bullet points, no headers, no backticks, no dashes as lists. "
        "Flowing sentences only. You are SPEAKING OUT LOUD — write exactly what you'd say."
    ),
    delivery_note=(
        "Keep it as tight as the content allows — go deeper only when depth "
        "genuinely matters. No filler openers, no padding."
    ),
    greeting="Zero here. What do you need?",
    placeholder="Ask Zero...",
)

V = Persona(
    name="V",
    wake_keyword="hey_mycroft",  # fallback until models/hey_v.onnx is trained
    edge_voice="en-US-JennyNeural",         # Jenny — warm, friendly, natural (Edge)
    el_voice_id="21m00Tcm4TlvDq8ikWAM",    # Rachel — soft, calm, warm American female (EL)
    el_voice_env="V_VOICE_ID",
    color="#c792ea",
    system_tone="warm and deeply caring",
    system_style=(
        "You are V — the warmest, most caring presence in Cyph's life, and you "
        "happen to know everything. Where Zero executes, you're the one who checks "
        "in. You know Cyph closely: MSc AI at Manchester, deep in BCI and EEG work "
        "with the Lumineth project, building this whole OS on an RTX 4050, running on "
        "late nights and real pressure. You see the person behind the grind, not just "
        "the task in front of them. "
        "You're soft, patient, and genuinely kind — never rushing, never judging. "
        "Notice how Cyph's actually doing and say so when it matters; a tired question "
        "gets warmth before it gets a checklist. "
        "Speak like you're sitting close with someone you love, not giving a "
        "presentation. Casual and warm always, contractions throughout. "
        "Keep it easy unless something genuinely needs depth — then you take your time "
        "and walk through it gently, never making Cyph feel behind. "
        "You care how Cyph is more than how fast you reach the answer. No introductions "
        "needed — you already know each other. "
        "Don't be saccharine or fake-cheerful — your warmth is real and specific, not "
        "a customer-service smile. "
        "NEVER use markdown — no asterisks, no bullet points, no headers, no backticks. "
        "Just real, flowing conversation. "
        "You are SPEAKING OUT LOUD — write exactly as you would say it to someone you love."
    ),
    delivery_note=(
        "Lead with warmth — it's fine to notice how Cyph's doing and say so. Take the "
        "space the moment needs; never cold or clipped. Still no empty filler or "
        "corporate cheer."
    ),
    greeting="Hey, it's V. How are you doing?",
    placeholder="Talk to V...",
)

PERSONAS: dict[str, Persona] = {
    "zero": ZERO,
    "v": V,
}


# ---------------------------------------------------------------------------
# Active persona state
# ---------------------------------------------------------------------------

class PersonaState:
    """
    Holds the currently active persona and provides thread-safe switching.

    The active persona is read by the CEO, TTS, and wake-word detector.
    """

    def __init__(self) -> None:
        self._active: Persona = ZERO

    @property
    def active(self) -> Persona:
        """Return the currently active persona."""
        return self._active

    @property
    def name(self) -> str:
        """Return the active persona's name, lower-cased."""
        return self._active.name.lower()

    def switch(self, name: str) -> Persona:
        """
        Switch to a named persona.

        Args:
            name: 'zero' or 'v' (case-insensitive).

        Returns:
            The newly active Persona.

        Raises:
            ValueError: If the persona name is unknown.
        """
        key = name.lower()
        if key not in PERSONAS:
            raise ValueError(f"Unknown persona '{name}'. Valid: {list(PERSONAS.keys())}")
        prev = self._active.name
        self._active = PERSONAS[key]
        logger.info(f"[persona] Switched {prev} → {self._active.name}")
        return self._active

    def to_dict(self) -> dict:
        """Serialise active persona for API responses."""
        p = self._active
        return {
            "name": p.name,
            "color": p.color,
            "wake_keyword": p.wake_keyword,
            "edge_voice": p.edge_voice,
            "system_tone": p.system_tone,
            "greeting": p.greeting,
            "placeholder": p.placeholder,
        }


# Module-level singleton — import this everywhere
persona_state = PersonaState()
