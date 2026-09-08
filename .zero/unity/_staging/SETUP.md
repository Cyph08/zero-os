# Zero OS — Unity 6 (HDRP + VFX Graph) front-end · SETUP

The renderer/shell is being rebuilt as a native **Unity 6 HDRP** app. The Python backend
(FastAPI on `localhost:8000`, 12 agents, `voice/wake.py`) is **unchanged** — Unity just calls it
over HTTP.

> **Status:** Unity Hub 3.10 is installed, but **no Unity editor is installed** (only old
> leftover projects). You must install the editor first — see Step 0.

---

## Step 0 — Install the Unity 6 editor (required, ~6–9 GB)

1. Open **Unity Hub** → **Installs** tab → **Install Editor**.
2. Pick a **Unity 6 LTS** version — **6000.0.x LTS** (e.g. 6000.0.26f1 or newer 6000.0.x).
3. In **Add modules**, tick:
   - **Microsoft Visual Studio** *or* **Visual Studio Code editor** (for C#) — skip if you already have one.
   - **Windows Build Support (IL2CPP)** — needed to build the standalone `.exe`.
   - (Documentation optional.)
4. Install. HDRP and VFX Graph are **not** modules — they come with the HDRP template in Step 1.

Disk note: the editor goes on C: by default. If C: is tight, set a secondary install path in
Hub (⚙ → Installs → Install location) — but the editor itself is large regardless.

---

## Step 1 — Create the HDRP project

1. Unity Hub → **Projects** → **New project**.
2. Editor version: the Unity 6 you just installed.
3. Template: **3D (HDRP)**  ← important (gives HDRP pipeline asset, sample scene, post Volume).
4. Project name: **ZeroOS**, location: `K:\Zero\.zero\unity` → full path `K:\Zero\.zero\unity\ZeroOS`.
5. Create. First open compiles HDRP (a few minutes).

---

## Step 2 — Add packages (Window ▸ Package Manager ▸ + ▸ Add package by name)

HDRP + VFX Graph already come with the template. Add:
- `com.unity.nuget.newtonsoft-json`  (JSON for the backend client)
- `com.unity.inputsystem`  (input; optional but recommended)

(TextMeshPro / uGUI ship with Unity 6.)

---

## Step 3 — Import the C# scripts (Claude does this)

After the project exists, the staged scripts in `unity/_staging/Scripts/` get copied into
`ZeroOS/Assets/Scripts/`:
- `Agents.cs` — the 12-agent roster, colour palette, hue grading, geometry (ported from the web app).
- `ZeroBackend.cs` — HTTP client for `/ask`, `/tts`, `/persona`, `/health`.
- `AudioReactor.cs` — turns TTS audio into an `audioLevel` (drives the beam + bloom).
- `AppWindow.cs` — 1920×1080, 144 fps target, HDR display request, fullscreen toggle.
- (Later) `BrainController.cs`, `WakeReceiver.cs`, `Editor/BuildZeroOS.cs`.

---

## Step 4 — Visuals (guided, in the editor)

- **HDRP post Volume** (on the scene's Global Volume): enable **Bloom** (intensity ~0.4, scatter
  high), **Tonemapping = ACES**, **Exposure** (fixed or auto). HDR is on by default in HDRP.
- **VFX Graph "Brain"**: two hemisphere particle volumes + a thin HDR-emissive **sword** beam +
  central bloom; per-agent colours; exposed properties (`AudioLevel`, `ActiveAgentEnergy`, etc.)
  driven by `BrainController`.
- **Camera**: perspective, slight orbit/parallax for the 3D feel.

I'll walk you through these node-by-node (teach mode or step list) — they can't be hand-coded.

---

## Step 5 — App-ify

- `Application.targetFrameRate = 144`, `QualitySettings.vSyncCount = 0` (or 1 to sync to 144 Hz).
- `Screen.SetResolution(1920, 1080, FullScreenMode.FullScreenWindow)`.
- HDR display output via `HDROutputSettings` (if your panel supports it).
- Wake bridge: `voice/wake.py` → backend `/wake` event → `WakeReceiver` focuses window + listens.
- Tray + autostart; `Editor/BuildZeroOS.cs` → standalone build in `ZeroOS/Builds/`.

---

## Run order each session
1. Backend: `cd K:\Zero\.zero` → `uvicorn api.main:app --host 0.0.0.0 --port 8000`
2. Unity: open ZeroOS, press **Play** (or run the built `.exe`).
