# Changelog — Helm (system)

## 0.1.0 — 2026-09-08
- NEW: 14th agent, Phase B "laptop access". Gives Zero real hands on the machine.
- Ops: find, list, read, open, write, append, move, copy, delete, run.
  A fast-tier LLM call turns the request into one JSON action; stdlib
  (pathlib/shutil/subprocess/os.startfile) executes it.
- Path resolution: if the literal path doesn't exist, the bare filename is
  searched for across Desktop/Documents/Downloads/Pictures/Videos, K:\Zero and
  home — so "open my dissertation notes" works without knowing the folder.
- Safety is reversibility, not nagging:
  - deletes move to `.zero/trash/<ts>_<name>` (never os.remove),
  - overwrites copy the original to `<name>.bak` first,
  - C:\Windows, Program Files(x86), ProgramData and the venv are refused,
  - `run` goes through sandbox.executor (60s hard timeout, captured output),
    and destructive shell commands (format, del /f, rm -rf, shutdown, diskpart,
    reg delete, mkfs...) are refused unless the SAME message says "yes run: ...".
- Verified live: find (located restart-zero.bat), list (Zero Tech, 15 items),
  run (echo), write→read→delete round trip on the Desktop with a recoverable
  trash entry. Self-check: `python -m agents.system.run`.
