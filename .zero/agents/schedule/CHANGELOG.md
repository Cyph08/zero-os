# Changelog — Chrono

## 0.1.1 — 2026-07-05
- FIXED the recurring crash ('str' object has no attribute 'time'): the ScheduleEntry
  dataclass field `time: str` shadowed the `time` module inside the class body, so
  `field(default_factory=time.time)` resolved to `"".time` and the module failed at
  import — every dispatch to Chrono died before run() executed. Root-caused and fixed
  by capturing `_NOW = time.time` at module level before the class. Verified live:
  first successful Chrono answer (schedule query, 9.2s via DeepSeek).
- Prompt now includes Cyph's real context: MSc AI at Manchester + part-time shifts at
  Chen's Happy House, so planning accounts for his actual commitments.
