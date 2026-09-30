---
tags: [zero-os, reference]
---

# Integrations

Wrappers in `.zero\integrations\`, plus Zero's own MCP surface. Keys in
[[Configuration]].

| Module | Does |
|---|---|
| `gmail.py` | Google OAuth 2.0 — read, draft, send |
| `google_calendar.py` | List, create, delete events |
| `notion.py` | Search, read, write pages |
| `github.py` | List / read / create repos, issues, files, plus `migrate_repo()` for the Deepen-cyph → Cyph08 move |
| `slack.py` | Send message, list channels, channel history, upload snippet |
| `linkedin.py` | Used by [[Nexus]] |

> [!note] `google_calendar.py`, not `calendar.py`
> The original name shadowed Python's stdlib `calendar` module. Renaming it was the fix.

Google OAuth uses `google_credentials.json` and `google_token.json` — both gitignored, not
env vars. Every integration's `__main__` loads `.env` explicitly.

---

## Zero as an MCP server

FastAPI exposes MCP at **`http://localhost:8000/mcp`** (StreamableHTTP only, no SSE). Every
agent in the registry is published as an MCP tool, so an external client can call
[[Iris]] or [[Helm]] directly.

Add it in a client via *Settings → Connectors → Add custom connector*.

## Zero as an MCP client

`core/mcp_client.py` — `McpClientRegistry`. Loads server configs from
`mcp_client_servers.json` (or the `MCP_CLIENT_SERVERS` env var), lazy-connects each one,
caches `tools/list`, and calls `tools/call` over JSON-RPC via httpx.

`find_tools()` scores by token overlap, the same approach as the agent registry, so matching
costs no extra LLM call. `ceo._run_mcp_tools()` runs after both dispatch waves and injects
results into `ctx.agent_outputs`, so synthesis sees external tools alongside Zero's own
agents. It skips instantly when no servers are configured — the normal case.

Zero is therefore **bidirectional**: a server that exposes its agents, and a client that
consumes other people's tools.

---

## Sandboxed execution

`sandbox/` — `executor.py` writes code to a temp file and runs it via `subprocess.run` with a
hard timeout, capturing stdout and stderr (truncated at 4k). Supports Python, shell and
batch.

`sandbox.py` can run a whole **agent** in a subprocess (`_worker.py`, JSON over stdin/stdout)
when `ZERO_SANDBOX_AGENTS` is set, falling back in-process on any failure. Default off.

[[Forge]] uses `executor.execute()` only when you explicitly say "run it". [[Helm]] routes
its `run` op through the same executor with a 60s timeout.

---
[[Architecture]] · [[Configuration]] · [[Zero OS]]
