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

---

## Ready-to-paste prompt

For any image tool — the Gemini web app (free, no API quota needed), ChatGPT,
Midjourney, Leonardo. Paste verbatim:

> Character portrait of "Zero", an artificial human woman — the face of a personal
> AI operating system. Stylised 3D render in the style of a high-end animated
> feature (Arcane-adjacent): painterly, characterful, confident shapes. NOT
> photorealistic, NOT anime, NOT glossy corporate 3D, NOT cyberpunk cliché.
>
> She is mid-twenties, warm and sharp at the same time — brilliant and completely
> at ease, a trusted friend who is genuinely glad you're here, never a servant and
> never eager to please. Expression: a slight, genuine, knowing half-smile and
> direct eye contact with the viewer. Relaxed, quietly amused, intelligent.
>
> Warm honey-blonde hair, soft and natural with loose movement, catching the rim
> light. Fair skin with real subsurface warmth, no plastic sheen. Simple dark
> fine-knit top. No visible technology, no circuitry, no seams, no chrome, no
> headset. Her artificial nature shows only as a faint inner luminosity in the eyes
> and a soft glowing edge-light along her silhouette.
>
> Lighting: warm golden-amber key light from one side, cool cyan rim light from the
> other — this warm/cool split is essential.
>
> Setting: deep warm-toned darkness, not flat black. Far behind her, well out of
> focus: a vertical violet-into-white-hot beam of light, thin elegant gold
> armillary rings, and a faint constellation-like neural mesh. Atmospheric and
> subtle — she is unmistakably the subject.
>
> Composition: head and shoulders, three-quarter turn toward the viewer, eyes to
> camera, subject centred with generous margin (this will be cropped to a circle
> for a profile picture — keep everything important away from the corners).
> Square 1:1.

For the banner, swap the last paragraph for: *"Composition: wider three-quarter
shot, caught mid-thought rather than posed, the rings and mesh around her. 16:9."*

## Why the API route is blocked

The Gemini API key works for text, but every image model returns HTTP 429 with:

```
quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier
limit:   0
```

`limit: 0` — the free tier allows **zero** image-generation requests. It is not
exhausted, it is zero by design.

**A Gemini Advanced / Google One subscription does not fix this** — that is a
consumer product and grants no API quota. Image generation needs **billing enabled
on the Google Cloud project behind the API key**:
aistudio.google.com → the key's project → Billing → link an account. Then
`gemini-3-pro-image` and `nano-banana-pro-preview` start working immediately, at
roughly $0.03–0.14 per image.

The free Gemini **web app** has no such restriction — pasting the prompt above into
gemini.google.com costs nothing.
