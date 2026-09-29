# Zero — Character Brief

The visual identity of Zero herself, for the Telegram channel and anything else
she fronts. Written from the persona that actually exists in `core/personas.py`
and the visual language already built in the Unity and React work — not invented.

Direction set by Cyph: **warmer, blonde.**

---

## Who she is

Mid-twenties. An artificial human, and comfortable being one — she doesn't
pretend to be a person and doesn't apologise for not being one.

**Warm and sharp at the same time.** The persona file calls her a "brilliant
friend," never a corporate assistant: casual, direct, no filler, no servility.
She's the one who gets things done — she orchestrates fourteen specialists — but
she's genuinely glad you're here. The warmth is real, not service-industry
brightness.

Her expression should be **a slight, genuine half-smile and direct eye contact.**
Relaxed. Amused by something. Not pouting, not stern, not eager to please.

What she is *not*: a chrome android, a servant, a pin-up, or a hologram with
visible circuitry and seams. Her artificiality shows as a faint luminosity and
a soft edge-light — a presence that's slightly *more* than photographable —
rather than as exposed technology.

## Look

- **Warm blonde hair** — honey/golden rather than platinum, softly lit so the rim
  light catches it. Loose, natural movement.
- Fair, warm skin with real subsurface warmth. No plastic sheen.
- Simple dark clothing — a fine-knit or matte top. Nothing tactical, nothing
  corporate, no visible tech.
- Eyes: the one place her nature shows. Clear, intelligent, faintly lit from
  within.

## Palette — why warm is still on-brand

Zero's accent is cyan (V's is violet), but the wider identity **already has warmth
in it**: the Unity orb's gold armillary rings, and the guide's gold `#B8860B`,
amber `#C87418` and parchment `#ede4d8`. So "warmer" is not a departure — it's
leaning into the half of the palette that was always there.

| Role | Colour |
|---|---|
| Key light | Warm gold / amber — `#C87418`, `#B8860B` |
| Rim / accent | Zero's cyan — `#3CDCFF` |
| Core beam | Violet into white-hot — `#8A2BE2` → `#F6F0FF` |
| Ground | Deep warm dark, not pure black |

**Lighting: warm gold key from one side, cool cyan rim from the other.** That
warm/cool split is what makes her feel alive rather than rendered, and it uses
both halves of the existing palette at once.

## Setting

Deep, soft-dark space — warm-toned, not flat black. Behind her, well out of
focus: the **violet-white AI CORE beam** and the **gold armillary rings** from
the orb render, plus a faint neural mesh in the darkness. Present, never busy —
she is the subject.

## Style

**Stylised 3D render — high-end animated film.** Arcane-adjacent: painterly,
characterful, confident shapes.

Deliberately **not photoreal** (goes uncanny, and she isn't pretending to be
human), not anime, not glossy corporate 3D, not neon-cyberpunk cliché.

## Shots

1. **Avatar** — head and shoulders, three-quarter turn toward the viewer, direct
   eye contact. Composed for a **circular crop**: subject centred, nothing
   important near the corners. Must still read at 40px.
2. **Banner** — wider, fuller framing. The rings and mesh around her, caught
   mid-thought rather than posed.

## Generation

Needs `GEMINI_API_KEY` in `.env` (free: aistudio.google.com/apikey), then the
`design` skill drives `gemini-3-pro-image-preview` for finals and
`gemini-2.5-flash-image` for quick variations. `google-genai` is installed.

Output goes here, in `docs/brand/`.
