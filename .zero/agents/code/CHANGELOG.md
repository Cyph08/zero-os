# Changelog — Forge (code agent)

## 0.2.5 — 2026-06-30
- Fixed EMPTY RESPONSE on large builds: a build that truncated before </html> used to
  be discarded entirely (no extractable complete doc) → empty reply. Now:
  - `_salvage_html()` recovers the partial document (from doctype/<html> to the end,
    drops stray fences, best-effort closes </body></html>) so the user gets a runnable
    (if incomplete) file and a note to say "continue/fix the <name> game".
  - QA review pass is skipped when the draft is >16k chars (re-emitting a huge file
    risked truncating a good draft into nothing).
  - Forge never returns empty for an app build — clear fallback message if truly nothing.
- Root cause was deepseek-reasoner output cap on big/complex builds (boss-snake etc.);
  continuation couldn't always reach </html>. Salvage + smaller first builds is the
  workaround; Opus would remove the ceiling.

## 0.2.4 — 2026-06-30
- WORKS-ON-FIRST-ATTEMPT: fresh builds now get an automatic QA pass before they ship.
  Forge reviews its own generated file for run-blocking bugs (unwired buttons/keys,
  init never called, loop never started, undefined refs, missing element ids, canvas
  not sized, errors thrown before setup) and returns the corrected file — the "debug
  it" step Cyph used to do manually, now automatic.
  - `_review_build_html()` does the QA pass; `_complete_if_truncated()` (refactored
    out of the inline continuation) re-completes either the build or the review if it
    truncates. Reviewed output is only accepted if it's ≥60% the draft length (guards
    against a garbled/short review clobbering a good draft).
  - Skipped for iteration requests (those are already a fix pass). Toggle off with
    FORGE_BUILD_REVIEW=0 in .env if you'd rather have speed over reliability.
- Build prompt gained an explicit MUST-RUN CHECKLIST (wire every control, call init on
  load, start the loop, no undefined refs, size the canvas, don't throw before setup).
- Tradeoff: fresh builds now make one extra model call (~30–60s slower on DeepSeek) in
  exchange for running on the first try.

## 0.2.3 — 2026-06-30
- ITERATION / debugging: "fix it", "the game isn't starting", "make the website
  better" now RE-OPEN the actual file Forge built and fix THAT code, instead of
  blindly regenerating a new app. This is Forge using its memory of what it shipped.
  - `_find_last_build(query)` picks the right file by matching project words in the
    query to filenames (e.g. "donkey kong" → classic-donkey-kong-arcade-as.html),
    else most-recent. `_wants_iteration()` detects fix/improve intent (excludes
    "...agent" so agent-tuning still routes to Vanta). `_build_iterate_prompt()`
    hands the model the full current file and asks for the complete corrected file.
  - (CEO) `_is_iterate_request()` routes these to Forge — fixes "improve that" being
    hijacked by Vanta/Schedule and producing generic guesswork.
- Verified failure this enables fixing: the DK build's START button (#ov-btn) had no
  click listener — game never started. An iterate pass now sees the real code.

## 0.2.2 — 2026-06-30
- Build pipeline: builds that need real-world facts (weather/news/prices/"latest"…)
  now run Iris first; Forge reads `research/summary` from the bus and bakes the real
  values into the page. Self-contained builds (games, calculators) skip research and
  go straight to Forge — fast path preserved.
- `_build_prompt` gained `research_context`; injected into both app and code prompts.
- (CEO) `_build_needs_facts()` gates the research round; build chain is
  `[research, code]` when facts are needed, else `[code]`. `_plan_waves` orders Iris
  (wave 1) before Forge (wave 2) automatically via Forge's collaborates_with.

## 0.2.1 — 2026-06-30
- Large-file builds no longer truncate: if an app build's HTML is missing a
  closing </html>, Forge now auto-continues (up to 5 follow-up calls, stitched
  together) so big single-file games/apps complete past the per-reply token cap.
- (CEO) Build requests ("make/build a game/app/website/clone/…") now route to
  Forge ONLY — fixes Donkey Kong etc. being hijacked by research/study/BCI agents.

## 0.2.0 — 2026-06-30
- App/website/game builds now SAVE to disk and OPEN in the browser instead of
  returning copy-paste HTML.
- New `_wants_app_build()` — fires when a build verb (make/build/create/…) meets a
  web signal (app/website/game/landing page/…).
- App builds get a dedicated prompt: produce ONE self-contained HTML file (inline
  CSS/JS, CDN ok, no build step), wrapped in a single ```html block + FILENAME hint.
- New `_extract_html()` (```html block, html-looking fenced block, or raw
  <!doctype>…</html>), `_slugify()` for filenames, `_save_and_open()` writes to
  `K:\Zero\Zero Tech` and launches the default browser (best-effort).
- max_tokens raised to 8192 for app builds so whole HTML files don't truncate.
- Python sandbox execution now skipped for app builds (won't try to run HTML as Python).
- CodeResult gained `saved_path` + `opened`; both published to the bus.
- manifest: added web keywords (app, website, web app, make an app, build a website,
  create a game, landing page, html, frontend, build me, …) so these requests route
  to Forge; capability `file_write` added.
