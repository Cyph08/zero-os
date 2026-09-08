"""
core/mcp_client.py — Zero OS Bidirectional MCP Client

Zero's built-in MCP server lets external tools (Cowork, Claude Desktop) CALL Zero.
This module is the reverse: Zero CALLS external MCP servers, pulling their tools
into the orchestration loop — borrowed from Hermes Agent's bidirectional MCP design.

Transport: JSON-RPC 2.0 over HTTP (MCP StreamableHTTP). Handles both plain JSON
and SSE response bodies. Uses httpx (already in the project via the research agent).

Config
------
Create ``mcp_client_servers.json`` in the ``.zero`` root (or set
``MCP_CLIENT_SERVERS`` env var to a JSON array with the same schema):

    [
      {
        "name": "my-tools",
        "url": "http://localhost:8001/mcp",
        "description": "Custom tool server",
        "enabled": true
      }
    ]

If neither is set the registry stays empty and every public method is a fast no-op.
Connections are lazy — each server connects on first use. Tool lists are cached for
the process lifetime (restart to pick up new tools from a live server).
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_ZERO_ROOT = Path(__file__).parent.parent
_CONFIG_FILE = _ZERO_ROOT / "mcp_client_servers.json"
_WORD_RE = re.compile(r"[a-z0-9]+")
_REQUEST_TIMEOUT = 10  # seconds per HTTP call


# ---------------------------------------------------------------------------
# Config + data models
# ---------------------------------------------------------------------------

@dataclass
class McpServerConfig:
    """One external MCP server connection."""
    name: str
    url: str
    description: str = ""
    enabled: bool = True


@dataclass
class McpTool:
    """A tool discovered from an external MCP server."""
    server_name: str
    name: str
    description: str
    input_schema: dict = field(default_factory=dict)

    def _tokens(self) -> set[str]:
        return set(_WORD_RE.findall((self.name + " " + self.description).lower()))


# ---------------------------------------------------------------------------
# JSON-RPC / MCP transport
# ---------------------------------------------------------------------------

def _parse_sse(text: str) -> dict:
    """Extract the first JSON payload from an SSE response body."""
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            try:
                return json.loads(line[5:].strip())
            except json.JSONDecodeError:
                pass
    return {}


def _rpc(
    url: str,
    method: str,
    params: dict | None = None,
    session_id: str | None = None,
) -> tuple[Any, str | None]:
    """
    Send one JSON-RPC 2.0 request to an MCP endpoint.

    Args:
        url:        MCP endpoint URL.
        method:     JSON-RPC method, e.g. "tools/list".
        params:     Optional params dict.
        session_id: Mcp-Session-Id from a prior initialize call.

    Returns:
        (result, returned_session_id)
    """
    import httpx

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if session_id:
        headers["Mcp-Session-Id"] = session_id

    body: dict[str, Any] = {"jsonrpc": "2.0", "method": method, "id": 1}
    if params is not None:
        body["params"] = params

    resp = httpx.post(url, json=body, headers=headers, timeout=_REQUEST_TIMEOUT)
    resp.raise_for_status()

    returned_sid = resp.headers.get("Mcp-Session-Id") or session_id
    ct = resp.headers.get("content-type", "")
    payload = _parse_sse(resp.text) if "text/event-stream" in ct else resp.json()

    if "error" in payload:
        raise RuntimeError(f"MCP error: {payload['error']}")
    return payload.get("result"), returned_sid


# ---------------------------------------------------------------------------
# Per-server session
# ---------------------------------------------------------------------------

class _ServerSession:
    """Manages one connection to an external MCP server. Thread-safe."""

    def __init__(self, config: McpServerConfig) -> None:
        self.config = config
        self._session_id: str | None = None
        self._tools: list[McpTool] = []
        self._connected = False
        self._lock = threading.Lock()

    def connect(self) -> bool:
        """Initialize the MCP session. Returns True on success."""
        with self._lock:
            if self._connected:
                return True
            try:
                _, sid = _rpc(
                    self.config.url,
                    "initialize",
                    params={
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "clientInfo": {"name": "zero-os", "version": "0.1.0"},
                    },
                )
                self._session_id = sid
                self._connected = True
                logger.info(f"[mcp_client] Connected to {self.config.name!r} at {self.config.url}")
                return True
            except Exception as exc:
                logger.warning(f"[mcp_client] Cannot connect to {self.config.name!r}: {exc}")
                return False

    def discover_tools(self) -> list[McpTool]:
        """Fetch tools/list. Cached after first successful call."""
        with self._lock:
            if self._tools:
                return list(self._tools)
            if not self._connected:
                return []
            try:
                result, _ = _rpc(
                    self.config.url, "tools/list", session_id=self._session_id
                )
                raw = (result or {}).get("tools", []) if result else []
                self._tools = [
                    McpTool(
                        server_name=self.config.name,
                        name=t.get("name", ""),
                        description=t.get("description", ""),
                        input_schema=t.get("inputSchema", {}),
                    )
                    for t in raw
                    if t.get("name")
                ]
                logger.info(
                    f"[mcp_client] Discovered {len(self._tools)} tools "
                    f"from {self.config.name!r}"
                )
                return list(self._tools)
            except Exception as exc:
                logger.warning(
                    f"[mcp_client] tools/list failed for {self.config.name!r}: {exc}"
                )
                return []

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """
        Call a tool and return its text content.

        MCP tools/call result shape:
            {"content": [{"type": "text", "text": "..."}], "isError": false}
        """
        if not self._connected:
            raise RuntimeError(f"Not connected to {self.config.name!r}")
        result, _ = _rpc(
            self.config.url,
            "tools/call",
            params={"name": tool_name, "arguments": arguments},
            session_id=self._session_id,
        )
        content = (result or {}).get("content", [])
        texts = [c.get("text", "") for c in content if c.get("type") == "text"]
        return "\n".join(texts) if texts else str(result)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class McpClientRegistry:
    """
    Registry of external MCP servers Zero can consume.

    Configure via ``mcp_client_servers.json`` or ``MCP_CLIENT_SERVERS`` env var.
    If neither is set the registry is empty and every method is a fast no-op.

    Thread-safe. Connections and tool discovery are lazy and cached.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, _ServerSession] = {}
        self._lock = threading.Lock()
        self._load_config()

    def _load_config(self) -> None:
        raw: list[dict] = []

        env_val = os.environ.get("MCP_CLIENT_SERVERS", "").strip()
        if env_val:
            try:
                raw = json.loads(env_val)
                logger.info(
                    f"[mcp_client] {len(raw)} server(s) from MCP_CLIENT_SERVERS env"
                )
            except json.JSONDecodeError as exc:
                logger.warning(f"[mcp_client] MCP_CLIENT_SERVERS invalid JSON: {exc}")

        if not raw and _CONFIG_FILE.exists():
            try:
                raw = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
                logger.info(
                    f"[mcp_client] {len(raw)} server(s) from {_CONFIG_FILE.name}"
                )
            except Exception as exc:
                logger.warning(f"[mcp_client] Cannot read {_CONFIG_FILE}: {exc}")

        if not raw:
            logger.debug(
                "[mcp_client] No external MCP servers configured — "
                "bidirectional MCP inactive"
            )
            return

        for entry in raw:
            try:
                cfg = McpServerConfig(
                    name=entry["name"],
                    url=entry["url"],
                    description=entry.get("description", ""),
                    enabled=entry.get("enabled", True),
                )
                if cfg.enabled:
                    self._sessions[cfg.name] = _ServerSession(cfg)
            except (KeyError, TypeError) as exc:
                logger.warning(
                    f"[mcp_client] Skipping invalid server config {entry}: {exc}"
                )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register(self, name: str, url: str, description: str = "") -> None:
        """
        Register an external MCP server at runtime (no restart needed).

        Args:
            name:        Unique server identifier.
            url:         HTTP URL of the server's MCP endpoint.
            description: Optional description for logging.
        """
        cfg = McpServerConfig(name=name, url=url, description=description)
        with self._lock:
            self._sessions[name] = _ServerSession(cfg)
        logger.info(f"[mcp_client] Registered {name!r} at {url}")

    def connect_all(self) -> dict[str, bool]:
        """
        Initialize connections to all configured servers.

        Returns:
            {server_name: connected_bool}
        """
        with self._lock:
            sessions = list(self._sessions.items())
        return {name: session.connect() for name, session in sessions}

    def discover_all(self) -> list[McpTool]:
        """
        Discover tools from all servers (connects if needed). Cached.

        Returns:
            Flat list of all tools across all servers.
        """
        with self._lock:
            sessions = list(self._sessions.values())
        tools: list[McpTool] = []
        for s in sessions:
            if not s._connected:
                s.connect()
            tools.extend(s.discover_tools())
        return tools

    def list_all_tools(self) -> list[McpTool]:
        """All discovered tools (discovers if needed)."""
        return self.discover_all()

    def find_tools(self, query: str, top_k: int = 3) -> list[McpTool]:
        """
        Keyword-score external tools against the query.

        Same token-overlap approach as registry.find() — no LLM call per request.
        Empty list when no servers are configured (common case, instant return).

        Args:
            query:  Natural language query.
            top_k:  Max tools to return.

        Returns:
            Best-matching McpTool objects, scored by token overlap.
        """
        if not self._sessions:
            return []
        query_tokens = set(_WORD_RE.findall(query.lower()))
        if not query_tokens:
            return []
        scored: list[tuple[int, McpTool]] = []
        for tool in self.list_all_tools():
            overlap = len(query_tokens & tool._tokens())
            if overlap > 0:
                scored.append((overlap, tool))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [t for _, t in scored[:top_k]]

    def call_tool(
        self, server_name: str, tool_name: str, arguments: dict[str, Any]
    ) -> str:
        """
        Call a tool on a specific server.

        Args:
            server_name: Registered server name.
            tool_name:   Tool name from discover_all().
            arguments:   Arguments matching the tool's inputSchema.

        Returns:
            Tool output as a string.

        Raises:
            KeyError:      Server not registered.
            RuntimeError:  Call failed.
        """
        with self._lock:
            session = self._sessions.get(server_name)
        if session is None:
            raise KeyError(f"No MCP server registered as {server_name!r}")
        if not session._connected:
            session.connect()
        return session.call_tool(tool_name, arguments)

    def as_tool_descriptions(self) -> str:
        """
        Formatted tool list for LLM prompts. Returns "" if no tools available.
        """
        tools = self.list_all_tools()
        if not tools:
            return ""
        lines = ["External tools available:"]
        for t in tools:
            lines.append(f"  [{t.server_name}] {t.name}: {t.description}")
        return "\n".join(lines)

    def server_count(self) -> int:
        """Number of registered servers."""
        return len(self._sessions)

    def tool_count(self) -> int:
        """Total discovered tools across all servers (0 if none discovered yet)."""
        return sum(len(s._tools) for s in self._sessions.values())


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

mcp_registry = McpClientRegistry()
