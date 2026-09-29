"""
api/main.py — Zero OS FastAPI Entry Point

Starts the FastAPI application, mounts the MCP server,
and wires up the plugin registry file watcher.

Run with:
    uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

Add to Cowork:
    Settings → Connectors → Add custom connector → http://localhost:8000/mcp
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")  # load keys from .env on startup
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse

from api.mcp_server import create_mcp_app, get_mcp
from core.registry import registry
from core.scheduler import scheduler
from phone.bridge import router as phone_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan: start/stop background services
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Start registry watcher and FastMCP session manager on startup.

    FastMCP's StreamableHTTPSessionManager must be used as an async context
    manager to initialise its internal task group before it can handle requests.
    Without this, every MCP request crashes with 'Task group is not initialized'.
    """
    import asyncio

    logger.info("[main] Zero OS starting up…")
    registry.start_watcher()
    logger.info(f"[main] Registry loaded — {len(registry.all_agents())} agents active")

    # Switch CEO to API mode so high-risk actions don't block on stdin
    from core.ceo import ceo as _ceo
    _ceo.use_api_mode()

    # Pre-warm Whisper base model in a thread so phone voice is fast on first use.
    # asyncio.to_thread runs it in the thread pool without blocking the event loop.
    async def _prewarm_whisper() -> None:
        def _load() -> None:
            try:
                from voice.stt import load_model, PHONE_MODEL
                logger.info(f"[main] Pre-warming Whisper {PHONE_MODEL}…")
                load_model(PHONE_MODEL)
                logger.info(f"[main] Whisper {PHONE_MODEL} ready")
            except Exception as exc:
                logger.warning(f"[main] Whisper pre-warm failed (non-fatal): {exc}")
        await asyncio.to_thread(_load)

    asyncio.create_task(_prewarm_whisper())

    # Sync Obsidian vault notes INTO cold memory in the background so anything
    # Cyph wrote/edited by hand in K:\Zero\Zero Memory becomes recallable.
    async def _sync_vault() -> None:
        def _sync() -> None:
            try:
                from memory.cold import cold_memory
                n = cold_memory.sync_vault()
                if n:
                    logger.info(f"[main] Vault sync: {n} note(s) ingested into cold memory")
            except Exception as exc:
                logger.warning(f"[main] Vault sync failed (non-fatal): {exc}")
        await asyncio.to_thread(_sync)

    asyncio.create_task(_sync_vault())

    # Pre-warm the local model when the hybrid fast tier is on, so the first
    # request doesn't pay a ~34s cold load from disk.
    async def _prewarm_local() -> None:
        def _warm() -> None:
            try:
                from core.llm import _local_fast_enabled, prewarm_local
                if _local_fast_enabled():
                    prewarm_local()
            except Exception as exc:
                logger.warning(f"[main] Local pre-warm failed (non-fatal): {exc}")
        await asyncio.to_thread(_warm)

    asyncio.create_task(_prewarm_local())

    # Telegram bot — Zero's primary interface. Starts only when
    # TELEGRAM_BOT_TOKEN is set; refuses to start unlocked (see telegram_bot.py).
    telegram_bot = None
    try:
        from phone.telegram_bot import build_from_env
        telegram_bot = build_from_env()
        if telegram_bot is not None:
            asyncio.create_task(telegram_bot.run_polling())
            logger.info("[main] Telegram bot starting…")
        else:
            logger.info("[main] Telegram bot not configured (no TELEGRAM_BOT_TOKEN) — skipping")
    except RuntimeError as exc:
        # Misconfigured on purpose-fail: a token with no allowed user id.
        logger.error(f"[main] Telegram bot NOT started — {exc}")
    except Exception as exc:
        logger.warning(f"[main] Telegram bot failed to start (non-fatal): {exc}")

    # Start proactive scheduler + register default jobs
    try:
        scheduler.start()
        from core.jobs import register_default_jobs
        register_default_jobs()
        logger.info("[main] Scheduler started and jobs registered")
    except Exception as exc:
        logger.warning(f"[main] Scheduler failed to start (non-fatal): {exc}")

    mcp = get_mcp()
    async with mcp.session_manager.run():
        logger.info("[main] MCP session manager initialised")
        yield

    logger.info("[main] Zero OS shutting down…")
    if telegram_bot is not None:
        telegram_bot.stop()
    registry.stop_watcher()
    scheduler.stop()


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Zero OS",
    description="Multi-agent AI operating system — MCP + REST API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],        # wildcard — do NOT use allow_credentials=True with this
    allow_credentials=False,    # must be False when allow_origins=["*"] (browser spec)
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# REST routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=JSONResponse)
async def root() -> dict:
    """Health check + agent list."""
    agents = [a.to_dict() for a in registry.all_agents()]
    return {
        "status": "online",
        "version": "0.1.0",
        "agents": len(agents),
        "agent_names": registry.all_names(),
    }


@app.get("/agents", response_class=JSONResponse)
async def list_agents() -> dict:
    """Return all registered agent manifests."""
    return {
        "agents": [a.to_dict() for a in registry.all_agents()]
    }


@app.get("/agents/{name}", response_class=JSONResponse)
async def get_agent(name: str) -> JSONResponse:
    """Return a single agent manifest by name."""
    manifest = registry.get(name)
    if manifest is None:
        return JSONResponse(status_code=404, content={"error": f"Agent '{name}' not found"})
    return JSONResponse(content=manifest.to_dict())


# ---------------------------------------------------------------------------
# OAuth 2.0 — minimal local implementation so Cowork can authenticate
# This is a dummy handshake: no real auth, just satisfies Cowork's requirement
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# OAuth 2.0 — minimal local implementation so Cowork can authenticate
# Endpoints match exactly what Cowork (MCP spec 2025-11-25) requests
# ---------------------------------------------------------------------------

@app.get("/.well-known/oauth-protected-resource")
@app.get("/.well-known/oauth-protected-resource/{path:path}")
async def oauth_protected_resource(request: Request) -> JSONResponse:
    """RFC 9728 protected resource metadata — tells Cowork which auth server to use."""
    base = str(request.base_url).rstrip("/")
    return JSONResponse({
        "resource": f"{base}/mcp",
        "authorization_servers": [base],
        "scopes_supported": ["read"],
        "bearer_methods_supported": ["header"],
    })


@app.get("/.well-known/oauth-authorization-server")
async def oauth_metadata(request: Request) -> JSONResponse:
    """Authorization server metadata — tells Cowork where to register and get tokens."""
    base = str(request.base_url).rstrip("/")
    return JSONResponse({
        "issuer": base,
        "authorization_endpoint": f"{base}/authorize",
        "token_endpoint": f"{base}/token",
        "registration_endpoint": f"{base}/register",
        "scopes_supported": ["read"],
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "code_challenge_methods_supported": ["S256"],
    })


@app.post("/register")
async def oauth_register(request: Request) -> JSONResponse:
    """Dynamic client registration (Cowork hits /register, not /oauth/register)."""
    body = await request.json()
    return JSONResponse({
        "client_id": "zero-local-client",
        "client_secret": "zero-local-secret",
        "redirect_uris": body.get("redirect_uris", []),
        "grant_types": ["authorization_code"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "client_secret_post",
    })


@app.get("/authorize")
async def oauth_authorize(request: Request) -> RedirectResponse:
    """Authorization endpoint — immediately issues a code, no login needed locally."""
    params = dict(request.query_params)
    redirect_uri = params.get("redirect_uri", "")
    state = params.get("state", "")
    return RedirectResponse(f"{redirect_uri}?code=zero-auth-code&state={state}")


@app.post("/token")
async def oauth_token() -> JSONResponse:
    """Token endpoint — issues a permanent local bearer token."""
    return JSONResponse({
        "access_token": "zero-local-token",
        "token_type": "bearer",
        "expires_in": 86400,
        "scope": "read",
    })


app.include_router(phone_router)


# ---------------------------------------------------------------------------
# Scheduler REST API
# ---------------------------------------------------------------------------

@app.get("/scheduler/jobs", response_class=JSONResponse)
async def list_scheduler_jobs() -> dict:
    """List all registered scheduled jobs."""
    return {"jobs": scheduler.list_jobs(), "count": len(scheduler.list_jobs())}


@app.post("/scheduler/jobs/{job_id}/pause", response_class=JSONResponse)
async def pause_scheduler_job(job_id: str) -> dict:
    """Pause a scheduled job."""
    ok = scheduler.pause_job(job_id)
    return {"success": ok, "job_id": job_id}


@app.post("/scheduler/jobs/{job_id}/resume", response_class=JSONResponse)
async def resume_scheduler_job(job_id: str) -> dict:
    """Resume a paused scheduled job."""
    ok = scheduler.resume_job(job_id)
    return {"success": ok, "job_id": job_id}


@app.delete("/scheduler/jobs/{job_id}", response_class=JSONResponse)
async def delete_scheduler_job(job_id: str) -> dict:
    """Remove a scheduled job permanently."""
    ok = scheduler.remove_job(job_id)
    return {"success": ok, "job_id": job_id}


@app.post("/scheduler/jobs/{job_id}/run-now", response_class=JSONResponse)
async def run_job_now(job_id: str) -> dict:
    """
    Trigger a scheduled job immediately (for testing / on-demand briefings).
    Runs in background — returns immediately.
    """
    import asyncio
    from core.jobs import (
        morning_briefing_job,
        world_news_digest_job,
        research_digest_job,
    )

    job_map = {
        "morning_briefing": morning_briefing_job,
        "world_news_digest": world_news_digest_job,
        "research_digest": research_digest_job,
    }

    if job_id not in job_map:
        return JSONResponse(
            status_code=404,
            content={"error": f"Unknown job: {job_id}. Known: {list(job_map.keys())}"},
        )

    asyncio.create_task(job_map[job_id]())
    return {"success": True, "job_id": job_id, "message": "Job triggered — check /alerts"}


# ---------------------------------------------------------------------------
# Alert REST API — phone polls this for proactive messages
# ---------------------------------------------------------------------------

@app.get("/alerts", response_class=JSONResponse)
async def get_alerts(mark_delivered: bool = True) -> dict:
    """
    Return pending proactive alerts (news briefings, digests, reminders).

    The phone UI polls this every 30s. Set mark_delivered=true to
    automatically clear the queue after reading.

    Query params:
        mark_delivered: If true (default), marks returned alerts as delivered.
    """
    from core.alerts import alert_queue
    pending = alert_queue.get_undelivered()
    if mark_delivered and pending:
        alert_queue.mark_all_delivered()
    return {
        "alerts": [a.to_dict() for a in pending],
        "count": len(pending),
        "total_in_queue": len(alert_queue),
    }


@app.get("/alerts/all", response_class=JSONResponse)
async def get_all_alerts() -> dict:
    """Return full alert history (delivered + pending), newest first."""
    from core.alerts import alert_queue
    return {
        "alerts": [a.to_dict() for a in alert_queue.all_alerts()],
        "pending": alert_queue.pending_count,
        "total": len(alert_queue),
    }


@app.post("/tts")
async def tts_endpoint(body: dict):
    """
    Desktop TTS endpoint — no auth required (localhost only).
    Body: {"text": "...", "persona": "zero"|"v" (optional)}
    Returns: MP3 audio bytes (audio/mpeg). Markdown stripped automatically.
    """
    from fastapi.responses import Response as FastAPIResponse
    from voice.tts import speak_to_bytes
    text: str = body.get("text", "").strip()
    persona: str = body.get("persona", "zero")
    if not text:
        return JSONResponse(status_code=400, content={"error": "text is required"})
    try:
        audio_bytes = await asyncio.to_thread(speak_to_bytes, text, persona=persona)
        return FastAPIResponse(content=audio_bytes, media_type="audio/mpeg")
    except Exception as exc:
        logger.error(f"[tts] Error: {exc}")
        return JSONResponse(status_code=500, content={"error": str(exc)})


# ---------------------------------------------------------------------------
# Persona API
# ---------------------------------------------------------------------------

@app.get("/persona/current", response_class=JSONResponse)
async def get_current_persona() -> dict:
    """Return the currently active persona (zero or v)."""
    from core.personas import persona_state
    return persona_state.to_dict()


@app.post("/persona/switch/{name}", response_class=JSONResponse)
async def switch_persona(name: str) -> JSONResponse:
    """
    Switch the active persona.
    name: 'zero' or 'v' (case-insensitive)
    """
    from core.personas import persona_state
    try:
        persona = persona_state.switch(name)
        logger.info(f"[persona] Switched to {persona.name} via API")
        return JSONResponse(content={
            "success": True,
            "persona": persona_state.to_dict(),
            "greeting": persona.greeting,
        })
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


# ---------------------------------------------------------------------------
# Info Stored API
# ---------------------------------------------------------------------------

@app.get("/info", response_class=JSONResponse)
async def get_all_info() -> dict:
    """Return all stored info items across all agents."""
    from core.info_store import info_store
    items = info_store.get_all()
    return {"items": items, "count": len(items), "agents": info_store.agents_with_data()}


@app.get("/info/{agent}", response_class=JSONResponse)
async def get_agent_info(agent: str) -> dict:
    """Return stored info items for a specific agent."""
    from core.info_store import info_store
    items = info_store.get_all(agent)
    return {"agent": agent, "items": items, "count": len(items)}


@app.post("/info/{agent}", response_class=JSONResponse)
async def save_info(agent: str, body: dict) -> JSONResponse:
    """
    Save an info item for an agent.
    Body: {"key": "label", "value": "content"}
    """
    from core.info_store import info_store
    key: str = body.get("key", "").strip()
    value: str = body.get("value", "").strip()
    if not key or not value:
        return JSONResponse(status_code=400, content={"error": "key and value are required"})
    item = info_store.save(agent, key, value)
    return JSONResponse(content={"success": True, "item": item})


@app.delete("/info/{agent}/{key}", response_class=JSONResponse)
async def delete_info(agent: str, key: str) -> dict:
    """Delete a specific stored info item."""
    from core.info_store import info_store
    deleted = info_store.delete(agent, key)
    return {"success": deleted, "agent": agent, "key": key}


@app.get("/health", response_class=JSONResponse)
async def health() -> dict:
    """Simple health check — always returns 200."""
    return {"status": "ok"}


@app.post("/ask", response_class=JSONResponse)
async def ask(body: dict) -> JSONResponse:
    """
    Send a command to the Zero CEO agent.
    Body: {"input": "..."} or {"query": "..."} — both accepted.
    """
    from core.ceo import ceo
    # Accept both field names for compatibility
    user_input: str = (body.get("input") or body.get("query") or "").strip()
    if not user_input:
        return JSONResponse(status_code=400, content={"error": "input is required"})

    try:
        # Run synchronous ceo.handle() in a thread so the event loop stays free
        ctx = await asyncio.to_thread(ceo.handle, user_input)
        from core.personas import persona_state
        payload: dict = {
            "response": ctx.final_response,
            "agents_used": [a.name for a in ctx.selected_agents],
            "risk_level": ctx.intent.risk_level.value,
            "model": ctx.model_used,
            "duration_ms": ctx.total_duration_ms,
            "cost_usd": ctx.total_cost_usd,
            "persona": persona_state.to_dict(),  # always include active persona
        }
        # Signal persona switch so UI can react immediately
        if ctx.model_used == "persona_switch":
            payload["persona_switched"] = True
        return JSONResponse(content=payload)
    except Exception as exc:
        logger.exception(f"[ask] Unhandled error: {exc}")
        return JSONResponse(
            status_code=500,
            content={"error": str(exc), "response": f"Zero encountered an error: {exc}"}
        )


# ---------------------------------------------------------------------------
# MCP mount — MUST be last so explicit routes above take priority
# FastMCP serves at /mcp internally; mounting at / maps that to /mcp correctly
# ---------------------------------------------------------------------------

mcp_app = create_mcp_app()
app.mount("/", mcp_app)
