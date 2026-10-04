"""
phone/telegram_bot.py — Zero OS Telegram interface

Zero's primary front door. Everything the desktop UI did, from a phone:
text, voice notes, built files delivered into the chat, proactive briefings,
and laptop control with confirmation.

Deliberately dependency-free: talks to the Telegram Bot API directly over
httpx (already a requirement) using long polling. No python-telegram-bot —
that ships its own asyncio loop which fights FastAPI's.

SECURITY — read before changing anything here:
    Zero can delete files and run shell commands (agents/system, "Helm").
    Telegram is internet-facing. The bot therefore answers EXACTLY ONE
    Telegram user id (TELEGRAM_ALLOWED_USER_ID) and refuses to start without
    it. Every other sender is ignored and logged. Do not add a "public mode".

Destructive actions (deletes, moves, overwrites, shell commands, and anything
the intent classifier rates HIGH) show a preview with Yes/Cancel buttons
before they run.

Env:
    TELEGRAM_BOT_TOKEN        from @BotFather
    TELEGRAM_ALLOWED_USER_ID  your numeric Telegram user id
    TELEGRAM_VOICE_REPLIES    '1' to also send a spoken reply (default off)
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import secrets
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

TELEGRAM_MAX_CHARS = 4096
_POLL_TIMEOUT_S = 25          # Telegram long-poll window
_HTTP_TIMEOUT_S = 60          # must exceed the poll window
_ALERT_POLL_S = 30            # how often to drain the proactive alert queue
_CONFIRM_TTL_S = 300          # pending confirmations expire after 5 minutes
_MAX_UPLOAD_BYTES = 50 * 1024 * 1024

# Files Zero produces that are worth delivering into the chat.
_SENDABLE_SUFFIXES = {
    ".html", ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".txt", ".md",
    ".csv", ".json", ".py", ".zip", ".mp3", ".wav",
}

# A Windows path in the reply text — how we notice Forge/Helm wrote a file
# without coupling this module to either agent's dataclass fields.
_PATH_RE = re.compile(r"[A-Za-z]:\\[^\s\"'<>|?*\n]+\.[A-Za-z0-9]{1,5}")

# Destructive file/shell intent. Helm's ops only classify as WRITE, so the
# intent gate alone won't catch "delete that file" — this does.
_DESTRUCTIVE_VERB = re.compile(
    r"\b(delete|remove|erase|trash|wipe|destroy|move|rename|overwrite|replace|uninstall)\b",
    re.IGNORECASE,
)
_FILE_TARGET = re.compile(
    r"(\bfiles?\b|\bfolders?\b|\bdirectory\b|\bdirectories\b|\.[A-Za-z0-9]{1,5}\b"
    r"|[A-Za-z]:\\|\b(?:desktop|documents|downloads|pictures|videos)\b)",
    re.IGNORECASE,
)
_RUN_CMD = re.compile(
    r"\b(run|execute)\b.*\b(command|script|shell|powershell|cmd|terminal|bat|exe)\b",
    re.IGNORECASE,
)

_HELP = """Zero — what I can do

Just talk to me. Ask anything, or tell me to do something.

  research      "latest papers on motor imagery BCI"
  build         "make me a snake game"  (I'll send you the file)
  laptop        "find my dissertation notes", "what's in my downloads"
  schedule      "remind me to submit the report on Friday"
  brief         "give me a briefing"

Voice notes work — send one and I'll transcribe and answer it.

Commands
  /agents     list every agent and what it does
  /health     backend + model status
  /status     today's usage
  /persona    switch between Zero and V
  /help       this message

Anything destructive (delete, move, run a command) asks first."""


# ---------------------------------------------------------------------------
# Pure helpers — unit-checked in __main__, no network needed
# ---------------------------------------------------------------------------

def split_message(text: str, limit: int = TELEGRAM_MAX_CHARS) -> list[str]:
    """
    Split a reply into Telegram-sized chunks, preferring clean break points.

    Tries paragraph breaks, then line breaks, then a hard cut, so answers don't
    get chopped mid-sentence.

    Args:
        text:  The full reply.
        limit: Max characters per message.

    Returns:
        List of chunks, each <= limit. Never empty for non-empty input.
    """
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        window = remaining[:limit]
        cut = window.rfind("\n\n")
        if cut < limit // 2:
            cut = window.rfind("\n")
        if cut < limit // 2:
            cut = window.rfind(" ")
        if cut <= 0:
            cut = limit
        chunks.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
    if remaining:
        chunks.append(remaining)
    return [c for c in chunks if c]


def needs_confirmation(text: str) -> tuple[bool, str]:
    """
    Decide whether a request must be confirmed before it runs.

    Two independent triggers:
      1. The intent classifier rates it HIGH (send email, buy, deploy, wipe...).
      2. It looks like a destructive file op or a shell command — Helm's ops
         only rate WRITE, so the classifier alone would let them straight
         through.

    Args:
        text: The user's message.

    Returns:
        (needs_confirmation, human reason). Reason is "" when not needed.
    """
    # "how do I delete a file in python" asks ABOUT an action, it doesn't request
    # one. intent.py already owns this distinction — reuse it rather than keep a
    # second copy of the prefix list here.
    try:
        from core.intent import _is_informational_question
        if _is_informational_question(text.lower()):
            return False, ""
    except Exception as exc:
        logger.debug(f"[tg] informational check skipped: {exc}")

    if _RUN_CMD.search(text):
        return True, "runs a shell command on your laptop"
    if _DESTRUCTIVE_VERB.search(text) and _FILE_TARGET.search(text):
        return True, "changes or deletes files on your laptop"
    try:
        from core.intent import RiskLevel, classifier
        result = classifier.classify(text)
        if result.risk_level == RiskLevel.HIGH:
            signals = ", ".join(result.matched_signals[:3]) or "high-risk action"
            return True, f"is a high-risk action ({signals})"
    except Exception as exc:          # classifier must never block the bot
        logger.debug(f"[tg] classify skipped: {exc}")
    return False, ""


def find_sendable_file(text: str) -> Path | None:
    """
    Pull a deliverable file path out of a reply, if one exists on disk.

    Forge says "saved it to C:\\...\\game.html" and Helm reports paths, so a
    path scan covers both without either agent needing to know about Telegram.

    Args:
        text: Zero's reply text.

    Returns:
        The file to send, or None.
    """
    for raw in _PATH_RE.findall(text or ""):
        candidate = Path(raw.rstrip(".,;:)]"))
        try:
            if (
                candidate.is_file()
                and candidate.suffix.lower() in _SENDABLE_SUFFIXES
                and candidate.stat().st_size <= _MAX_UPLOAD_BYTES
            ):
                return candidate
        except OSError:
            continue
    return None


# ---------------------------------------------------------------------------
# Bot
# ---------------------------------------------------------------------------

class ZeroTelegramBot:
    """
    Long-polling Telegram front end for Zero's CEO orchestrator.

    Args:
        token:           Bot token from @BotFather.
        allowed_user_id: The single Telegram user id allowed to use this bot.
    """

    def __init__(self, token: str, allowed_user_id: int) -> None:
        self._token = token
        self._allowed = int(allowed_user_id)
        self._api = f"https://api.telegram.org/bot{token}"
        self._file_api = f"https://api.telegram.org/file/bot{token}"
        self._offset = 0
        self._running = False
        self._pending: dict[str, tuple[str, float]] = {}
        self._client: httpx.AsyncClient | None = None

    # -- transport ---------------------------------------------------------

    async def _call(self, method: str, **payload: Any) -> dict[str, Any]:
        """
        Call one Telegram Bot API method.

        Args:
            method:  API method name, e.g. 'sendMessage'.
            payload: JSON body fields.

        Returns:
            The 'result' object, or {} on failure (never raises).
        """
        if self._client is None:
            return {}
        try:
            resp = await self._client.post(f"{self._api}/{method}", json=payload)
            data = resp.json()
            if not data.get("ok"):
                logger.warning(f"[tg] {method} failed: {data.get('description')}")
                return {}
            return data.get("result") or {}
        except Exception as exc:
            logger.warning(f"[tg] {method} error: {exc}")
            return {}

    async def _send(self, chat_id: int, text: str, **extra: Any) -> None:
        """Send text, split across messages if needed. parse_mode is left off
        deliberately so stray characters can't trigger Telegram parse errors."""
        parts = split_message(text)
        for i, part in enumerate(parts):
            payload = dict(chat_id=chat_id, text=part)
            if extra and i == len(parts) - 1:
                payload.update(extra)
            await self._call("sendMessage", **payload)

    async def _typing(self, chat_id: int, action: str = "typing") -> None:
        """Show a typing/recording indicator — Telegram clears it after ~5s."""
        await self._call("sendChatAction", chat_id=chat_id, action=action)

    async def _keep_typing(self, chat_id: int, stop: asyncio.Event) -> None:
        """Re-send the typing indicator until told to stop (agents take a while)."""
        while not stop.is_set():
            await self._typing(chat_id)
            try:
                await asyncio.wait_for(stop.wait(), timeout=4.0)
            except asyncio.TimeoutError:
                continue

    # -- CEO bridge --------------------------------------------------------

    async def _ask_zero(self, chat_id: int, text: str, confirmed: bool = False) -> None:
        """
        Run a request through the CEO and deliver the answer.

        Mirrors phone/bridge.py's /ask: ceo.handle() is synchronous, so it runs
        in a worker thread while the event loop keeps the typing indicator alive.

        Args:
            chat_id:   Where to reply.
            text:      The request.
            confirmed: True if Cyph already approved this via the Yes button.
        """
        from core.ceo import ceo

        stop = asyncio.Event()
        typer = asyncio.create_task(self._keep_typing(chat_id, stop))
        images: list[str] = []
        memory_id = ""
        try:
            ctx = await asyncio.to_thread(ceo.handle, text, confirmed)
            reply = (ctx.final_response or "").strip() or "No response produced."
            memory_id = ctx.memory_id
            agents = ", ".join(a.name for a in ctx.selected_agents) or "direct"
            # Iris publishes image URLs from its Tavily search — show them.
            if ctx.bus is not None:
                found = ctx.bus.get_from("research", "images", []) or []
                images = [u for u in found if isinstance(u, str)][:3]
            logger.info(
                f"[tg] answered in {ctx.total_duration_ms}ms via [{agents}] "
                f"cost=${ctx.total_cost_usd:.6f}"
            )
        except Exception as exc:
            logger.error(f"[tg] CEO error: {exc}")
            from core.errlog import log_error
            log_error("telegram", "ask_zero", exc, context=text)
            reply = f"Something broke handling that: {exc}"
        finally:
            stop.set()
            typer.cancel()

        rate: dict[str, Any] = {}
        if memory_id:
            rate["reply_markup"] = {"inline_keyboard": [[
                {"text": "👍", "callback_data": f"fb:+:{memory_id}"},
                {"text": "👎", "callback_data": f"fb:-:{memory_id}"},
            ]]}
        await self._send(chat_id, reply, **rate)

        # Images Iris found (Telegram fetches these by URL — no upload needed).
        for url in images:
            await self._call("sendPhoto", chat_id=chat_id, photo=url)

        # Deliver any file Zero just produced (Forge builds, Helm reads).
        f = find_sendable_file(reply)
        if f is not None:
            await self._send_file(chat_id, f)

        if os.getenv("TELEGRAM_VOICE_REPLIES", "0").strip() in ("1", "true", "True"):
            await self._send_voice_reply(chat_id, reply)

    async def _send_file(self, chat_id: int, path: Path) -> None:
        """Upload a file into the chat as a document."""
        if self._client is None:
            return
        await self._typing(chat_id, "upload_document")
        try:
            data = path.read_bytes()
            resp = await self._client.post(
                f"{self._api}/sendDocument",
                data={"chat_id": str(chat_id), "caption": path.name},
                files={"document": (path.name, data)},
            )
            if not resp.json().get("ok"):
                logger.warning(f"[tg] sendDocument failed for {path}")
        except Exception as exc:
            logger.warning(f"[tg] Could not send {path}: {exc}")

    async def _send_voice_reply(self, chat_id: int, text: str) -> None:
        """Synthesise the reply and send it as a Telegram voice note."""
        if self._client is None:
            return
        try:
            from voice.tts import speak_to_bytes
            audio = await asyncio.to_thread(speak_to_bytes, text[:1500])
            if not audio:
                return
            await self._typing(chat_id, "upload_voice")
            await self._client.post(
                f"{self._api}/sendAudio",
                data={"chat_id": str(chat_id)},
                files={"audio": ("zero.mp3", audio)},
            )
        except Exception as exc:
            logger.warning(f"[tg] Voice reply failed (non-fatal): {exc}")

    # -- handlers ----------------------------------------------------------

    async def _handle_text(self, chat_id: int, text: str) -> None:
        """Route a text message: command, confirmation-gated action, or question."""
        cmd = text.strip().lower()

        if cmd in ("/start", "/help"):
            await self._send(chat_id, _HELP)
            return
        if cmd == "/agents":
            await self._send(chat_id, await asyncio.to_thread(self._agents_text))
            return
        if cmd == "/health":
            await self._send(chat_id, await asyncio.to_thread(self._health_text))
            return
        if cmd == "/status":
            await self._send(chat_id, await asyncio.to_thread(self._status_text))
            return
        if cmd.startswith("/persona"):
            await self._send(chat_id, await asyncio.to_thread(self._persona_text, text))
            return

        gated, reason = needs_confirmation(text)
        if gated:
            token = secrets.token_urlsafe(8)
            self._pending[token] = (text, time.time() + _CONFIRM_TTL_S)
            self._expire_pending()
            await self._send(
                chat_id,
                f"This {reason}:\n\n  {text}\n\nRun it?",
                reply_markup={
                    "inline_keyboard": [[
                        {"text": "Yes, do it", "callback_data": f"ok:{token}"},
                        {"text": "Cancel", "callback_data": f"no:{token}"},
                    ]]
                },
            )
            return

        await self._ask_zero(chat_id, text)

    async def _handle_voice(self, chat_id: int, file_id: str) -> None:
        """Transcribe a voice note with Whisper, then treat it as a text request."""
        await self._typing(chat_id)
        info = await self._call("getFile", file_id=file_id)
        remote = info.get("file_path")
        if not remote or self._client is None:
            await self._send(chat_id, "I couldn't download that voice note.")
            return

        suffix = Path(remote).suffix or ".oga"
        tmp_path: Path | None = None
        try:
            audio = (await self._client.get(f"{self._file_api}/{remote}")).content
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(audio)
                tmp_path = Path(tmp.name)

            from voice.stt import PHONE_MODEL, transcribe_file
            transcript = (await asyncio.to_thread(transcribe_file, tmp_path, PHONE_MODEL) or "").strip()
        except Exception as exc:
            logger.error(f"[tg] Transcription failed: {exc}")
            hint = ""
            if "ffmpeg" in str(exc).lower() or "winerror 2" in str(exc).lower():
                # Whisper shells out to ffmpeg to decode Telegram's .oga/opus.
                hint = ("\n\nVoice notes need ffmpeg on PATH. Install it with:\n"
                        "  winget install Gyan.FFmpeg\nthen restart the backend.")
            await self._send(chat_id, f"I couldn't transcribe that.{hint}")
            return
        finally:
            if tmp_path is not None:
                try:
                    tmp_path.unlink(missing_ok=True)
                except OSError:
                    pass

        if not transcript:
            await self._send(chat_id, "I couldn't make out any words — try again?")
            return

        await self._send(chat_id, f'You said: "{transcript}"')
        await self._handle_text(chat_id, transcript)

    async def _handle_callback(self, cb: dict[str, Any]) -> None:
        """Handle a tap: 👍/👎 on an answer, or Yes/Cancel on a confirmation."""
        data = cb.get("data") or ""
        msg = cb.get("message") or {}
        chat_id = msg.get("chat", {}).get("id")

        if data.startswith("fb:"):                       # 👍 / 👎 on an answer
            _, sign, memory_id = data.split(":", 2)
            from core.feedback import record
            note = await asyncio.to_thread(record, memory_id, 1 if sign == "+" else -1)
            await self._call("answerCallbackQuery", callback_query_id=cb.get("id", ""),
                             text=note)
            if chat_id is not None and msg.get("message_id"):
                await self._call("editMessageReplyMarkup", chat_id=chat_id,
                                 message_id=msg["message_id"],
                                 reply_markup={"inline_keyboard": []})
            return

        await self._call("answerCallbackQuery", callback_query_id=cb.get("id", ""))
        if chat_id is None:
            return

        action, _, token = data.partition(":")
        entry = self._pending.pop(token, None)
        if entry is None:
            await self._send(chat_id, "That confirmation expired — send the request again.")
            return
        text, expiry = entry
        if time.time() > expiry:
            await self._send(chat_id, "That confirmation expired — send the request again.")
            return

        if action == "ok":
            logger.info(f"[tg] Cyph confirmed: {text!r}")
            await self._ask_zero(chat_id, text, confirmed=True)
        else:
            await self._send(chat_id, "Cancelled — nothing was changed.")

    def _expire_pending(self) -> None:
        """Drop confirmation tokens that have timed out."""
        now = time.time()
        for token in [t for t, (_, exp) in self._pending.items() if now > exp]:
            self._pending.pop(token, None)

    # -- command bodies (sync; called via to_thread) ------------------------

    @staticmethod
    def _agents_text() -> str:
        """Build the /agents roster from the live registry."""
        try:
            from core.registry import registry
            lines = ["Zero's agents:", ""]
            for m in sorted(registry.all_agents(), key=lambda a: a.name):
                display = ""
                try:
                    import json
                    display = json.loads(
                        m.manifest_path.read_text(encoding="utf-8")
                    ).get("display_name", "")
                except Exception:
                    pass
                label = f"{display} ({m.name})" if display else m.name
                lines.append(f"  {label} — {m.description}")
            return "\n".join(lines)
        except Exception as exc:
            return f"Couldn't read the registry: {exc}"

    @staticmethod
    def _health_text() -> str:
        """Backend, model and memory status for /health."""
        try:
            from core.llm import _local_fast_enabled, _provider_chain, detect_provider
            from core.personas import persona_state
            from core.registry import registry
            chain = " → ".join(p.value for p in _provider_chain())
            lines = [
                "Zero is up.",
                "",
                f"  persona    {persona_state.active.name}",
                f"  agents     {len(registry.all_agents())}",
                f"  provider   {detect_provider().value}",
                f"  chain      {chain}",
                f"  local fast {'on' if _local_fast_enabled() else 'off'}",
            ]
            try:
                from memory.cold import cold_memory
                lines.append(f"  memory     {'connected' if cold_memory._client else 'offline'}")
            except Exception:
                lines.append("  memory     unknown")
            return "\n".join(lines)
        except Exception as exc:
            return f"Health check failed: {exc}"

    @staticmethod
    def _status_text() -> str:
        """Today's request count and cost from the CEO action log."""
        try:
            import json
            log = Path(__file__).parent.parent / "logs" / "ceo_actions.jsonl"
            if not log.exists():
                return "No activity logged yet."
            today = time.strftime("%Y-%m-%d")
            count, cost, agents = 0, 0.0, {}
            for line in log.read_text(encoding="utf-8").splitlines():
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not str(rec.get("timestamp", "")).startswith(today):
                    continue
                count += 1
                cost += float(rec.get("cost_usd") or 0)
                for a in rec.get("agents_used") or []:
                    agents[a] = agents.get(a, 0) + 1
            top = ", ".join(f"{a} ({n})" for a, n in
                            sorted(agents.items(), key=lambda kv: -kv[1])[:5]) or "none"
            return (f"Today\n\n  requests  {count}\n  cost      ${cost:.4f}\n  busiest   {top}")
        except Exception as exc:
            return f"Couldn't read the log: {exc}"

    @staticmethod
    def _persona_text(text: str) -> str:
        """Switch persona for '/persona v', or report the current one."""
        from core.personas import PERSONAS, persona_state
        parts = text.split()
        if len(parts) < 2:
            return (f"Currently {persona_state.active.name}. "
                    f"Switch with /persona {' or /persona '.join(PERSONAS)}")
        try:
            p = persona_state.switch(parts[1])
            return f"{p.name} here. {p.greeting}"
        except ValueError as exc:
            return str(exc)

    # -- proactive alerts --------------------------------------------------

    async def _alert_pump(self, chat_id: int) -> None:
        """
        Forward scheduled briefings from the alert queue into Telegram.

        The cron jobs (08:00 briefing, 18:00 news, Sunday digest) already push
        into core.alerts; this drains the same queue the phone UI polls, so the
        proactive side needs no new plumbing.
        """
        from core.alerts import alert_queue
        while self._running:
            try:
                pending = await asyncio.to_thread(alert_queue.get_undelivered)
                for alert in pending:
                    await self._send(chat_id, f"{alert.title}\n\n{alert.body}")
                if pending:
                    await asyncio.to_thread(
                        alert_queue.mark_delivered, [a.alert_id for a in pending]
                    )
                    logger.info(f"[tg] Pushed {len(pending)} proactive alert(s)")
            except Exception as exc:
                logger.warning(f"[tg] Alert pump error: {exc}")
            await asyncio.sleep(_ALERT_POLL_S)

    # -- main loop ---------------------------------------------------------

    async def _dispatch(self, update: dict[str, Any]) -> None:
        """Authorise an update, then route it to the right handler."""
        if "callback_query" in update:
            cb = update["callback_query"]
            if (cb.get("from") or {}).get("id") != self._allowed:
                logger.warning(f"[tg] Rejected callback from {(cb.get('from') or {}).get('id')}")
                return
            await self._handle_callback(cb)
            return

        msg = update.get("message") or update.get("edited_message")
        if not msg:
            return

        sender = (msg.get("from") or {}).get("id")
        chat_id = (msg.get("chat") or {}).get("id")
        if sender != self._allowed:
            logger.warning(f"[tg] IGNORED message from unauthorised user id={sender}")
            return

        if "text" in msg:
            await self._handle_text(chat_id, msg["text"])
        elif "voice" in msg or "audio" in msg:
            media = msg.get("voice") or msg.get("audio")
            await self._handle_voice(chat_id, media["file_id"])
        elif "document" in msg:
            await self._send(chat_id, "I can't read documents yet — tell me what you need instead.")
        else:
            await self._send(chat_id, "I only handle text and voice notes right now.")

    async def run_polling(self) -> None:
        """
        Long-poll Telegram until stopped. Safe to run as a background task.

        Never raises — network errors back off and retry, so a dropped
        connection can't take the FastAPI app down with it.
        """
        self._running = True
        self._client = httpx.AsyncClient(timeout=_HTTP_TIMEOUT_S)
        me = await self._call("getMe")
        logger.info(
            f"[tg] Bot online as @{me.get('username', '?')} — "
            f"locked to user id {self._allowed}"
        )

        asyncio.create_task(self._alert_pump(self._allowed))
        backoff = 1.0
        try:
            while self._running:
                try:
                    updates = await self._call(
                        "getUpdates", offset=self._offset, timeout=_POLL_TIMEOUT_S
                    )
                    backoff = 1.0
                    for update in updates if isinstance(updates, list) else []:
                        self._offset = update["update_id"] + 1
                        try:
                            await self._dispatch(update)
                        except Exception as exc:
                            logger.error(f"[tg] Handler error: {exc}")
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning(f"[tg] Poll error ({exc}) — retrying in {backoff:.0f}s")
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 60.0)
        except asyncio.CancelledError:
            logger.info("[tg] Polling cancelled")
        finally:
            self._running = False
            await self._client.aclose()
            self._client = None

    def stop(self) -> None:
        """Ask the polling loop to finish."""
        self._running = False


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def build_from_env() -> ZeroTelegramBot | None:
    """
    Construct the bot from environment variables.

    Returns:
        A configured bot, or None when Telegram isn't set up (missing token) —
        the backend then simply runs without it.

    Raises:
        RuntimeError: If a token is present but TELEGRAM_ALLOWED_USER_ID is
            missing or not numeric. Refusing to start is deliberate: an
            unlocked bot would expose shell access to anyone who finds it.
    """
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token or "your_" in token:
        return None
    raw_id = (os.getenv("TELEGRAM_ALLOWED_USER_ID") or "").strip()
    if not raw_id.isdigit():
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is set but TELEGRAM_ALLOWED_USER_ID is missing or "
            "not a number. Zero can delete files and run commands — it will not "
            "start an unlocked bot. Message @userinfobot to get your numeric id."
        )
    return ZeroTelegramBot(token=token, allowed_user_id=int(raw_id))


# ---------------------------------------------------------------------------
# Self-check — no network, no token. Run: python -m phone.telegram_bot
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # split_message
    assert split_message("") == []
    assert split_message("hi") == ["hi"]
    long_paras = ("A" * 2000 + "\n\n" + "B" * 2000 + "\n\n" + "C" * 2000)
    parts = split_message(long_paras)
    assert all(len(p) <= TELEGRAM_MAX_CHARS for p in parts), [len(p) for p in parts]
    assert len(parts) >= 2
    assert "".join(p.replace("\n", "") for p in parts).count("A") == 2000
    solid = split_message("X" * 9000)
    assert all(len(p) <= TELEGRAM_MAX_CHARS for p in solid) and len(solid) == 3

    # needs_confirmation — destructive
    for risky in (
        "delete helm_test.txt from my desktop",
        "move the snake game to my documents folder",
        "run the command echo hello",
        "overwrite my notes.md file",
    ):
        ok, why = needs_confirmation(risky)
        assert ok, f"should gate: {risky!r}"
        assert why

    # needs_confirmation — safe
    for safe in (
        "what are the latest papers on motor imagery",
        "make me a snake game",
        "remove the bug from my training loop",
        "what's in my downloads folder",
        "how do I delete a file in python",
    ):
        ok, _ = needs_confirmation(safe)
        assert not ok, f"should NOT gate: {safe!r}"

    # find_sendable_file
    assert find_sendable_file("no paths here") is None
    with tempfile.TemporaryDirectory() as td:
        real = Path(td) / "game.html"
        real.write_text("<html></html>", encoding="utf-8")
        assert find_sendable_file(f"Saved it to {real}.") == real
        assert find_sendable_file(f"Saved it to {Path(td) / 'nope.html'}") is None

    # auth gate: a bot must refuse to exist unlocked
    import os as _os
    _prev = _os.environ.get("TELEGRAM_ALLOWED_USER_ID")
    _os.environ["TELEGRAM_BOT_TOKEN"] = "123:abc"
    _os.environ.pop("TELEGRAM_ALLOWED_USER_ID", None)
    try:
        build_from_env()
        raise AssertionError("must refuse to build without an allowed user id")
    except RuntimeError:
        pass
    finally:
        if _prev is not None:
            _os.environ["TELEGRAM_ALLOWED_USER_ID"] = _prev

    _os.environ["TELEGRAM_ALLOWED_USER_ID"] = "42"
    bot = build_from_env()
    assert bot is not None and bot._allowed == 42
    _os.environ.pop("TELEGRAM_BOT_TOKEN", None)
    assert build_from_env() is None, "no token → no bot, not an error"

    print("Telegram bot self-check passed.")
