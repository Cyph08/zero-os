"""
api/mcp_server.py — Zero OS MCP Server

Exposes every registered agent as an MCP tool using StreamableHTTP transport.
Cowork connects to http://localhost:8000/mcp and sees all agents as callable tools.

Transport: StreamableHTTP (NOT SSE — that's deprecated in the Python MCP SDK).
"""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from core.registry import registry

logger = logging.getLogger(__name__)

# Module-level FastMCP instance — shared so main.py can access session_manager
_mcp: FastMCP | None = None


def get_mcp() -> FastMCP:
    """
    Return the singleton FastMCP instance, creating it if needed.

    Returns:
        Configured FastMCP server with all agent tools registered.
    """
    global _mcp
    if _mcp is None:
        _mcp = FastMCP(
            name="zero-os",
            instructions="Zero OS — multi-agent AI operating system",
        )
        _register_agent_tools(_mcp)
        _register_utility_tools(_mcp)
        logger.info("[mcp] FastMCP instance created")
    return _mcp


def create_mcp_app() -> Any:
    """
    Build the MCP ASGI application.

    Dynamically registers one MCP tool per agent in the registry.
    session_manager is created lazily inside streamable_http_app(), so we
    disable host-header validation immediately after to allow ngrok tunnels.

    Returns:
        ASGI app suitable for mounting in FastAPI.
    """
    mcp = get_mcp()
    asgi_app = _get_mcp_asgi_app(mcp)

    # session_manager now exists — disable host validation for ngrok/tunnels
    try:
        mcp.session_manager.security_settings = None
        logger.info("[mcp] Host validation disabled — external tunnels allowed")
    except Exception as exc:
        logger.warning(f"[mcp] Could not disable host validation: {exc}")

    return asgi_app


def _get_mcp_asgi_app(mcp: FastMCP) -> Any:
    """
    Get the ASGI app from FastMCP, trying method names across SDK versions.

    The MCP Python SDK has renamed this method across versions:
      - mcp 1.0.x: streamable_http_app()
      - mcp 1.1.x: streamable_http_app() or http_app()
    """
    for method_name in ("streamable_http_app", "http_app", "asgi_app", "get_asgi_app"):
        method = getattr(mcp, method_name, None)
        if callable(method):
            logger.info(f"[mcp] Using FastMCP.{method_name}() for ASGI mount")
            return method()

    # None found — report what's actually available so we know what to use
    available = [m for m in dir(mcp) if not m.startswith("_") and callable(getattr(mcp, m))]
    raise RuntimeError(
        f"FastMCP has no recognised ASGI app method. "
        f"Installed mcp version may be unsupported. "
        f"Available methods: {available}"
    )


# ---------------------------------------------------------------------------
# Dynamic agent tool registration
# ---------------------------------------------------------------------------

def _register_agent_tools(mcp: FastMCP) -> None:
    """
    For each agent in the registry, register an MCP tool that:
      1. Runs the agent's run() function
      2. Returns structured output

    Args:
        mcp: The FastMCP instance to register tools on.
    """
    for manifest in registry.all_agents():
        _register_single_agent_tool(mcp, manifest.name)

    logger.info(f"[mcp] Registered {len(registry.all_agents())} agent tools")


def _register_single_agent_tool(mcp: FastMCP, agent_name: str) -> None:
    """
    Register one agent as an MCP tool. Uses a closure to capture agent_name.

    Args:
        mcp: The FastMCP instance.
        agent_name: Name of the agent to register.
    """
    manifest = registry.get(agent_name)
    if manifest is None:
        return

    # Build the tool function with a closure over agent_name
    def make_tool(name: str, risk: str):
        async def agent_tool(query: str) -> dict:
            """
            Args:
                query: Natural language query or command for this agent.

            Returns:
                Structured dict with the agent's response.

            Note:
                Calls this agent directly (no multi-agent bus). For multi-agent
                orchestration use the zero_ask tool instead.
            """
            import asyncio
            import importlib.util
            import sys
            from pathlib import Path

            m = registry.get(name)
            if m is None:
                raise ToolError(f"Agent '{name}' not found in registry")

            entry = Path(__file__).parent.parent / m.entry_point

            def _run_agent() -> dict:
                """Synchronous agent execution — run in thread pool to avoid blocking."""
                try:
                    spec = importlib.util.spec_from_file_location(name, entry)
                    if spec is None or spec.loader is None:
                        raise ToolError(f"Cannot load agent module at {entry}")
                    module = importlib.util.module_from_spec(spec)
                    sys.modules[name] = module
                    spec.loader.exec_module(module)  # type: ignore[attr-defined]

                    if not hasattr(module, "run"):
                        raise ToolError(f"Agent '{name}' has no run() function")

                    result = module.run(query)
                    if hasattr(result, "to_dict"):
                        return result.to_dict()
                    if isinstance(result, dict):
                        return result
                    return {"output": str(result)}
                except ToolError:
                    raise
                except Exception as exc:
                    logger.error(f"[mcp] Agent '{name}' execution error: {exc}")
                    raise ToolError(f"Agent execution failed: {exc}") from exc

            # Run the synchronous agent in a thread pool to avoid blocking the event loop
            try:
                return await asyncio.to_thread(_run_agent)
            except ToolError:
                raise
            except Exception as exc:
                raise ToolError(f"Agent thread error: {exc}") from exc

        # Rename for MCP tool listing
        agent_tool.__name__ = f"zero_{name}"
        agent_tool.__doc__ = (
            f"{manifest.description}\n\n"
            f"Risk level: {risk} | "
            f"Capabilities: {', '.join(manifest.capabilities)}"
        )
        return agent_tool

    tool_fn = make_tool(agent_name, manifest.risk_level)
    mcp.tool(name=f"zero_{agent_name}")(tool_fn)


# ---------------------------------------------------------------------------
# Utility tools (always available, not tied to any agent)
# ---------------------------------------------------------------------------

def _register_utility_tools(mcp: FastMCP) -> None:
    """Register built-in utility tools on the MCP server."""

    @mcp.tool(name="zero_list_agents")
    async def list_agents() -> dict:
        """
        List all active Zero agents with their descriptions and capabilities.

        Returns:
            Dict with list of agent manifests.
        """
        return {
            "agents": [a.to_dict() for a in registry.all_agents()],
            "count": len(registry.all_agents()),
        }

    @mcp.tool(name="zero_ask")
    async def ask(query: str) -> dict:
        """
        Send any command to Zero's CEO agent — it will route to the right specialist.
        This is the recommended tool for most requests (multi-agent orchestration).

        Args:
            query: Your command or question in natural language.

        Returns:
            Dict with response, agents used, risk level, and cost info.
        """
        import asyncio
        from core.ceo import ceo

        def _run_ceo() -> dict:
            ctx = ceo.handle(query)
            return {
                "response": ctx.final_response,
                "agents_used": [a.name for a in ctx.selected_agents],
                "risk_level": ctx.intent.risk_level.value,
                "model": ctx.model_used,
                "duration_ms": ctx.total_duration_ms,
                "cost_usd": ctx.total_cost_usd,
            }

        return await asyncio.to_thread(_run_ceo)

    logger.info("[mcp] Utility tools registered: zero_list_agents, zero_ask")
