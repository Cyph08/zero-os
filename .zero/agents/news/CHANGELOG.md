# Changelog — Herald

## 0.2.0 — 2026-06-30
- Replaced serial advanced-depth research-agent web searches with direct parallel Tavily calls
- search_depth changed from "advanced" to "basic"; include_raw_content=False (snippets sufficient for news)
- All queries for a given news type now run concurrently via ThreadPoolExecutor
- Briefing mode: 4 queries (world + AI) run in one parallel batch instead of two serial batches
- Expected latency: ~3-5s vs ~33s (avg from AIM audit)
- Added "tag" field to results for typed world/AI splitting in briefing prompt
- Added version field to log lines
