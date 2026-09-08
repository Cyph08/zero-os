# Changelog — Iris

## 0.2.0 — 2026-06-30
Depth upgrade so Iris "thinks like Claude and gives real answers + results":
- Query decomposition — deep queries split into 2-4 focused sub-queries (`_decompose`),
  searched in parallel; simple queries stay single-shot.
- Tiered depth (`_assess_depth`) — quick (1 search, fast model, 5 sources) vs deep
  (parallel sub-searches, capable/deep model, up to 10 merged+deduped sources).
- Academic mode (`_is_scholarly`) — scholarly queries (any topic) also hit arXiv +
  Semantic Scholar. NOTE: arXiv API currently times out from this machine and S2 free
  tier 429s without a key — both fail fast, in parallel, degrade gracefully; Tavily
  already surfaces papers. A free S2 key + reachable arXiv would make paper metadata solid.
- Personalization (`_personal_context`) — pulls Cyph's own notes via
  cold_memory.search_all() and grounds the answer in them.
- Verified citations (numbered sources, only-existing-[n]) + structured `findings`
  (title+url+snippet) on ResearchBrief/to_dict/bus for Forge + future ATLAS.
- Reliability — all searches concurrent; Tavily retries once; arXiv/S2 never block/crash.
- Interface preserved: run(query, fetch_pages, bus) + ResearchBrief.to_dict() shape kept.
- Verified live: "compare mamba vs transformer for long sequences" → 4 sub-queries,
  10 sources, cited multi-paragraph answer, $0.002, 42s on DeepSeek.
- manifest → 0.2.0, added academic_search capability + paper keywords.

## 0.1.1 — 2026-06-30
- switched Tavily to advanced search depth by default

