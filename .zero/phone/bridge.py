"""
phone/bridge.py — Zero OS Mobile REST Bridge

Exposes a set of lightweight REST endpoints that a phone browser or PWA
can call over the ngrok HTTPS tunnel. Every endpoint (except /phone/status)
requires the X-Astra-Key header to match PHONE_API_KEY in .env.

─── HOW IT WORKS ────────────────────────────────────────────────────────────
Think of this as a "phone-sized window" into Zero:

  Phone → ngrok HTTPS → FastAPI → /phone/ask → CEO → agents → response
                                  /phone/voice → Whisper → CEO → response
                                  /phone/history → hot memory → last N turns
                                  /phone/tts → Edge TTS → audio bytes

─── ENDPOINTS ───────────────────────────────────────────────────────────────
  GET  /phone/status   — health check, no auth needed
  POST /phone/ask      — send a text command, get a text response
  POST /phone/voice    — send a base64 audio clip, get transcription + response
  GET  /phone/history  — last N conversation turns from hot memory
  POST /phone/tts      — convert text to speech, returns base64 MP3 audio

─── SETUP ───────────────────────────────────────────────────────────────────
1. Add to .env:
       PHONE_API_KEY=choose-a-long-random-secret
2. Include this router in api/main.py (already done if you followed the guide)
3. On your phone, open the ngrok URL and set the header X-Astra-Key to your secret
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import base64
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Router — all endpoints live under /phone/
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/phone", tags=["phone"])


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

def _require_auth(x_zero_key: str = Header(default="")) -> str:
    """
    Dependency: validate X-Astra-Key header against PHONE_API_KEY in .env.

    Thinks of this like a bouncer at a door — if you don't know the secret
    passphrase, you don't get in. The key never leaves your .env file.

    Args:
        x_zero_key: Value of the X-Astra-Key HTTP header.

    Returns:
        The validated key string.

    Raises:
        HTTPException 401: If the key is missing or wrong.
    """
    expected = os.getenv("PHONE_API_KEY", "")
    if not expected:
        # No key configured — warn but allow (dev mode only)
        logger.warning(
            "[bridge] PHONE_API_KEY not set in .env — running unauthenticated (dev mode)"
        )
        return x_zero_key

    if x_zero_key != expected:
        logger.warning(f"[bridge] Rejected request — wrong API key")
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing X-Astra-Key header. Set PHONE_API_KEY in .env.",
        )
    return x_zero_key


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class AskRequest(BaseModel):
    """Body for POST /phone/ask."""
    input: str                      # the text command from the phone


class VoiceRequest(BaseModel):
    """
    Body for POST /phone/voice.
    Audio must be base64-encoded WAV or MP3 (max ~5MB raw, so ~7MB base64).
    """
    audio_b64: str                  # base64-encoded audio bytes
    format: str = "wav"            # "wav" or "mp3"
    return_audio: bool = False     # if True, also TTS the response back as audio


class TTSRequest(BaseModel):
    """Body for POST /phone/tts."""
    text: str
    voice: str = "en-GB-SoniaNeural"   # default: British female, same as tts.py


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/status")
async def phone_status() -> dict[str, Any]:
    """
    Health check — no auth required.

    Returns Zero's online status and active agent count.
    Great for the phone PWA to show a connection indicator.
    """
    from core.registry import registry
    agents = registry.all_names()
    return {
        "status": "online",
        "agents_active": len(agents),
        "agent_names": agents,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


@router.post("/ask")
async def phone_ask(
    body: AskRequest,
    _key: str = Depends(_require_auth),
) -> dict[str, Any]:
    """
    Send a text command to Zero's CEO agent and get a response.

    This is the main endpoint the phone PWA uses for text input.
    The CEO routes the request to the right department agent automatically.

    Body example:
        {"input": "what are the latest papers on motor imagery BCI?"}

    Returns:
        response: Zero's answer
        agents_used: which department agents ran
        risk_level: read / write / high
        duration_ms: how long it took
    """
    user_input = body.input.strip()
    if not user_input:
        raise HTTPException(status_code=400, detail="input cannot be empty")

    logger.info(f"[bridge] /phone/ask — input: {user_input!r}")

    try:
        import asyncio
        from core.ceo import ceo

        def _run() -> dict:
            ctx = ceo.handle(user_input)
            return {
                "response": ctx.final_response,
                "agents_used": [a.name for a in ctx.selected_agents],
                "risk_level": ctx.intent.risk_level.value,
                "model": ctx.model_used,
                "duration_ms": ctx.total_duration_ms,
                "cost_usd": ctx.total_cost_usd,
            }

        return await asyncio.to_thread(_run)
    except Exception as exc:
        logger.error(f"[bridge] /phone/ask error: {exc}")
        raise HTTPException(status_code=500, detail=f"Astra error: {exc}")


@router.post("/voice")
async def phone_voice(
    body: VoiceRequest,
    _key: str = Depends(_require_auth),
) -> dict[str, Any]:
    """
    Send a voice recording to Zero. Whisper transcribes it, CEO handles it.

    Think of this as the microphone button on your phone UI:
    1. Phone records audio → encodes to base64 → sends here
    2. Zero decodes audio → saves to temp file → Whisper transcribes
    3. Transcript goes to CEO → agents run → response text comes back
    4. Optionally: response is converted to speech → base64 audio returned

    Body example:
        {"audio_b64": "<base64 wav bytes>", "format": "wav", "return_audio": true}

    Returns:
        transcript: what Whisper heard
        response: Zero's answer
        audio_b64: base64 MP3 of spoken response (only if return_audio=True)
    """
    logger.info(f"[bridge] /phone/voice — format={body.format} return_audio={body.return_audio}")

    # 1. Decode audio from base64
    try:
        audio_bytes = base64.b64decode(body.audio_b64)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid base64 audio: {exc}")

    if len(audio_bytes) < 100:
        raise HTTPException(status_code=400, detail="Audio too short — recording may be empty")

    # 2. Save to temp file so Whisper can read it
    suffix = f".{body.format.lower()}"
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = Path(tmp.name)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Could not save audio: {exc}")

    # 3. Transcribe with Whisper — use PHONE_MODEL (base) for low latency on CPU
    transcript = ""
    try:
        from voice.stt import transcribe_file, PHONE_MODEL
        transcript = transcribe_file(tmp_path, model_name=PHONE_MODEL)
        logger.info(f"[bridge] Whisper transcript: {transcript!r}")
    except Exception as exc:
        logger.error(f"[bridge] Whisper transcription failed: {exc}")
        raise HTTPException(status_code=500, detail=f"Transcription failed: {exc}")
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass

    if not transcript or not transcript.strip():
        raise HTTPException(status_code=422, detail="Could not transcribe audio — try speaking more clearly")

    # 4. Send transcript to CEO (in thread — ceo.handle() is synchronous)
    try:
        import asyncio
        from core.ceo import ceo
        ctx = await asyncio.to_thread(ceo.handle, transcript)
    except Exception as exc:
        logger.error(f"[bridge] CEO error after transcription: {exc}")
        raise HTTPException(status_code=500, detail=f"Astra error: {exc}")

    result: dict[str, Any] = {
        "transcript": transcript,
        "response": ctx.final_response,
        "agents_used": [a.name for a in ctx.selected_agents],
        "risk_level": ctx.intent.risk_level.value,
        "duration_ms": ctx.total_duration_ms,
    }

    # 5. Optionally synthesise speech and return it
    if body.return_audio:
        try:
            from voice.tts import speak_to_bytes
            audio_out = speak_to_bytes(ctx.final_response, voice=body.voice)
            result["audio_b64"] = base64.b64encode(audio_out).decode()
            result["audio_format"] = "mp3"
        except Exception as exc:
            logger.warning(f"[bridge] TTS failed (non-fatal): {exc}")
            result["audio_b64"] = None
            result["tts_error"] = str(exc)

    return result


@router.get("/history")
async def phone_history(
    n: int = 10,
    _key: str = Depends(_require_auth),
) -> dict[str, Any]:
    """
    Return the last N conversation turns from session memory.

    This lets the phone PWA show a conversation history view —
    like a chat log of everything you've said to Zero this session.

    Query param:
        n (int): How many recent turns to return. Default 10, max 50.
    """
    n = min(max(1, n), 50)
    try:
        from memory.hot import hot_memory
        turns = hot_memory.recent(n)
        return {
            "turns": [
                {
                    "role": t.role,
                    "content": t.content,
                    "agent": t.agent,
                    "timestamp": t.timestamp,
                }
                for t in turns
            ],
            "count": len(turns),
        }
    except Exception as exc:
        logger.error(f"[bridge] /phone/history error: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/tts")
async def phone_tts(
    body: TTSRequest,
    _key: str = Depends(_require_auth),
) -> dict[str, Any]:
    """
    Convert text to speech and return base64 audio.

    Useful for the phone PWA to speak any text — e.g. reading back
    a research summary or calendar agenda out loud.

    Body example:
        {"text": "Your next meeting is at 3pm.", "voice": "en-GB-SoniaNeural"}

    Returns:
        audio_b64: base64 MP3 audio of spoken text
        audio_format: always "mp3"
        char_count: number of characters synthesised
    """
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="text cannot be empty")
    if len(text) > 5000:
        raise HTTPException(status_code=400, detail="text too long — max 5000 characters")

    try:
        from voice.tts import speak_to_bytes
        audio_bytes = speak_to_bytes(text, voice=body.voice)
        return {
            "audio_b64": base64.b64encode(audio_bytes).decode(),
            "audio_format": "mp3",
            "char_count": len(text),
        }
    except Exception as exc:
        logger.error(f"[bridge] /phone/tts error: {exc}")
        raise HTTPException(status_code=500, detail=f"TTS error: {exc}")


# ---------------------------------------------------------------------------
# Mobile UI — served at /phone/ui
# Open this URL on your phone to get a full chat interface
# ---------------------------------------------------------------------------

_MOBILE_UI = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Zero">
<meta name="theme-color" content="#0a0a0f">
<title>Zero OS</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: #0a0a0f;
    color: #e0e0e0;
    height: 100dvh;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  /* ── Lock screen ── */
  #lock-screen {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100dvh;
    gap: 20px;
    padding: 32px;
  }
  #lock-screen h1 { font-size: 2rem; color: #7df9ff; letter-spacing: 4px; }
  #lock-screen p  { color: #666; font-size: 0.85rem; text-align: center; }
  #key-input {
    width: 100%;
    padding: 14px 16px;
    background: #111;
    border: 1px solid #333;
    border-radius: 12px;
    color: #e0e0e0;
    font-size: 1rem;
    outline: none;
  }
  #key-input:focus { border-color: #7df9ff; }
  #connect-btn {
    width: 100%;
    padding: 14px;
    background: #7df9ff22;
    border: 1px solid #7df9ff55;
    border-radius: 12px;
    color: #7df9ff;
    font-size: 1rem;
    cursor: pointer;
    letter-spacing: 2px;
  }
  #connect-btn:active { background: #7df9ff44; }
  #lock-error { color: #ff5555; font-size: 0.85rem; display: none; }

  /* ── Chat screen ── */
  #chat-screen { display: none; flex-direction: column; height: 100dvh; }

  header {
    padding: 16px 20px 12px;
    background: #0a0a0f;
    border-bottom: 1px solid #1a1a2e;
    display: flex;
    align-items: center;
    gap: 12px;
  }
  .status-dot {
    width: 8px; height: 8px;
    border-radius: 50%;
    background: #00ff88;
    box-shadow: 0 0 6px #00ff88;
    flex-shrink: 0;
  }
  header h2 { font-size: 1rem; color: #7df9ff; letter-spacing: 2px; flex: 1; }
  #agent-count { font-size: 0.75rem; color: #555; }

  /* Alert badge — glows when there are unread proactive alerts */
  #alert-badge {
    display: none;
    width: 8px; height: 8px;
    border-radius: 50%;
    background: #ff9900;
    box-shadow: 0 0 6px #ff9900;
    animation: alertPulse 1.5s infinite;
    flex-shrink: 0;
  }
  #alert-badge.visible { display: block; }
  @keyframes alertPulse {
    0%, 100% { opacity: 1; box-shadow: 0 0 6px #ff9900; }
    50% { opacity: 0.4; box-shadow: 0 0 12px #ff9900; }
  }

  /* Alert message — distinct from regular zero messages */
  .msg.alert {
    align-self: flex-start;
    background: #1a1200;
    border: 1px solid #ff990044;
    color: #ffe0a0;
    max-width: 95%;
  }
  .msg.alert .alert-title {
    font-size: 0.75rem;
    color: #ff9900;
    letter-spacing: 1px;
    margin-bottom: 6px;
    text-transform: uppercase;
  }

  #messages {
    flex: 1;
    overflow-y: auto;
    padding: 16px;
    display: flex;
    flex-direction: column;
    gap: 12px;
    scroll-behavior: smooth;
  }

  .msg {
    max-width: 85%;
    padding: 10px 14px;
    border-radius: 16px;
    font-size: 0.9rem;
    line-height: 1.45;
    word-break: break-word;
    animation: fadeIn 0.2s ease;
  }
  @keyframes fadeIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; } }

  .msg.user {
    align-self: flex-end;
    background: #1a1a3e;
    border: 1px solid #333366;
    color: #c0c0ff;
  }
  .msg.zero {
    align-self: flex-start;
    background: #0f1f1f;
    border: 1px solid #1a3333;
    color: #e0ffe0;
  }
  .msg.system {
    align-self: center;
    background: transparent;
    color: #444;
    font-size: 0.75rem;
    border: none;
    padding: 4px;
  }
  .msg-meta {
    font-size: 0.7rem;
    color: #555;
    margin-top: 4px;
  }

  .typing-indicator {
    align-self: flex-start;
    display: flex;
    gap: 4px;
    padding: 12px 16px;
    background: #0f1f1f;
    border: 1px solid #1a3333;
    border-radius: 16px;
  }
  .typing-indicator span {
    width: 6px; height: 6px;
    background: #7df9ff;
    border-radius: 50%;
    animation: bounce 1.2s infinite;
  }
  .typing-indicator span:nth-child(2) { animation-delay: 0.2s; }
  .typing-indicator span:nth-child(3) { animation-delay: 0.4s; }
  @keyframes bounce {
    0%, 80%, 100% { transform: translateY(0); }
    40% { transform: translateY(-6px); }
  }

  #input-area {
    padding: 12px 16px;
    padding-bottom: max(12px, env(safe-area-inset-bottom));
    background: #0a0a0f;
    border-top: 1px solid #1a1a2e;
    display: flex;
    gap: 8px;
    align-items: flex-end;
  }

  #text-input {
    flex: 1;
    background: #111;
    border: 1px solid #333;
    border-radius: 20px;
    padding: 10px 16px;
    color: #e0e0e0;
    font-size: 0.95rem;
    outline: none;
    resize: none;
    max-height: 100px;
    line-height: 1.4;
  }
  #text-input:focus { border-color: #7df9ff55; }

  .icon-btn {
    width: 42px; height: 42px;
    border-radius: 50%;
    border: none;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    font-size: 1.1rem;
    transition: all 0.15s;
  }
  #send-btn {
    background: #7df9ff22;
    border: 1px solid #7df9ff55;
    color: #7df9ff;
  }
  #send-btn:active { background: #7df9ff44; transform: scale(0.95); }

  #mic-btn {
    background: #ff007722;
    border: 1px solid #ff007755;
    color: #ff6699;
  }
  #mic-btn.recording {
    background: #ff007755;
    border-color: #ff0077;
    animation: pulse 1s infinite;
  }
  @keyframes pulse {
    0%, 100% { box-shadow: 0 0 0 0 #ff007744; }
    50% { box-shadow: 0 0 0 8px transparent; }
  }

  #play-btn {
    background: #00ff8822;
    border: 1px solid #00ff8855;
    color: #00ff88;
    display: none;
  }
  #play-btn.visible { display: flex; }

  ::-webkit-scrollbar { width: 4px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: #333; border-radius: 2px; }
</style>
</head>
<body>

<!-- ── Lock screen ── -->
<div id="lock-screen">
  <h1>ZERO</h1>
  <p>Enter your Zero key to connect</p>
  <input id="key-input" type="password" placeholder="Paste PHONE_API_KEY here" autocomplete="off">
  <button id="connect-btn">CONNECT</button>
  <span id="lock-error">Wrong key — check PHONE_API_KEY in .env</span>
</div>

<!-- ── Chat screen ── -->
<div id="chat-screen">
  <header>
    <div class="status-dot"></div>
    <h2>ZERO OS</h2>
    <span id="agent-count">loading...</span>
    <div id="alert-badge" title="New alert from Astra"></div>
  </header>

  <div id="messages">
    <div class="msg system">Astra is online. Ask anything.</div>
  </div>

  <div id="input-area">
    <button class="icon-btn" id="mic-btn" title="Voice input">🎙</button>
    <textarea id="text-input" placeholder="Ask Zero..." rows="1"></textarea>
    <button class="icon-btn" id="send-btn" title="Send">➤</button>
    <button class="icon-btn" id="play-btn" title="Play response">🔊</button>
  </div>
</div>

<script>
// ── State ──────────────────────────────────────────────────────────────────
let API_KEY = sessionStorage.getItem('zero_key') || '';
let lastAudioB64 = null;
let mediaRecorder = null;
let audioChunks = [];
let isRecording = false;
const BASE_URL = window.location.origin;

// ── Lock screen ────────────────────────────────────────────────────────────
async function tryConnect(key) {
  try {
    const r = await fetch(`${BASE_URL}/phone/history?n=1`, {
      headers: { 'X-Astra-Key': key }
    });
    return r.ok;
  } catch { return false; }
}

document.getElementById('connect-btn').onclick = async () => {
  const key = document.getElementById('key-input').value.trim();
  if (!key) return;
  document.getElementById('connect-btn').textContent = 'CONNECTING...';
  const ok = await tryConnect(key);
  if (ok) {
    API_KEY = key;
    sessionStorage.setItem('zero_key', key);
    showChat();
  } else {
    document.getElementById('lock-error').style.display = 'block';
    document.getElementById('connect-btn').textContent = 'CONNECT';
  }
};

document.getElementById('key-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') document.getElementById('connect-btn').click();
});

async function showChat() {
  document.getElementById('lock-screen').style.display = 'none';
  document.getElementById('chat-screen').style.display = 'flex';
  // Fetch agent count
  try {
    const r = await fetch(`${BASE_URL}/phone/status`);
    const d = await r.json();
    document.getElementById('agent-count').textContent =
      `${d.agents_active} agents`;
  } catch {}
}

// Auto-connect if key already in session
if (API_KEY) tryConnect(API_KEY).then(ok => ok ? showChat() : null);

// ── Messaging ──────────────────────────────────────────────────────────────
const messagesEl = document.getElementById('messages');

function addMessage(role, content, meta = '') {
  const div = document.createElement('div');
  div.className = `msg ${role}`;
  div.textContent = content;
  if (meta) {
    const m = document.createElement('div');
    m.className = 'msg-meta';
    m.textContent = meta;
    div.appendChild(m);
  }
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return div;
}

function showTyping() {
  const el = document.createElement('div');
  el.className = 'typing-indicator';
  el.id = 'typing';
  el.innerHTML = '<span></span><span></span><span></span>';
  messagesEl.appendChild(el);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function removeTyping() {
  document.getElementById('typing')?.remove();
}

async function sendText(text) {
  if (!text.trim()) return;
  addMessage('user', text);
  showTyping();

  try {
    const r = await fetch(`${BASE_URL}/phone/ask`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Astra-Key': API_KEY,
      },
      body: JSON.stringify({ input: text }),
    });
    const d = await r.json();
    removeTyping();

    if (!r.ok) {
      addMessage('system', `Error: ${d.detail || 'unknown error'}`);
      return;
    }

    const meta = `${d.agents_used?.join(', ') || '—'} · ${d.duration_ms}ms`;
    addMessage('zero', d.response, meta);
    lastAudioB64 = null;
    document.getElementById('play-btn').classList.remove('visible');
  } catch (err) {
    removeTyping();
    addMessage('system', `Connection error: ${err.message}`);
  }
}

// Send button
document.getElementById('send-btn').onclick = () => {
  const input = document.getElementById('text-input');
  const text = input.value.trim();
  input.value = '';
  input.style.height = 'auto';
  sendText(text);
};

// Enter to send (shift+enter for newline)
document.getElementById('text-input').addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    document.getElementById('send-btn').click();
  }
});

// Auto-resize textarea
document.getElementById('text-input').addEventListener('input', function() {
  this.style.height = 'auto';
  this.style.height = Math.min(this.scrollHeight, 100) + 'px';
});

// ── Voice recording ────────────────────────────────────────────────────────
const micBtn = document.getElementById('mic-btn');

micBtn.onclick = async () => {
  if (isRecording) {
    stopRecording();
  } else {
    await startRecording();
  }
};

async function startRecording() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    audioChunks = [];
    mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });
    mediaRecorder.ondataavailable = e => audioChunks.push(e.data);
    mediaRecorder.onstop = async () => {
      stream.getTracks().forEach(t => t.stop());
      await sendVoice();
    };
    mediaRecorder.start();
    isRecording = true;
    micBtn.classList.add('recording');
    micBtn.title = 'Tap to stop';
  } catch (err) {
    addMessage('system', `Mic error: ${err.message}`);
  }
}

function stopRecording() {
  if (mediaRecorder && isRecording) {
    mediaRecorder.stop();
    isRecording = false;
    micBtn.classList.remove('recording');
    micBtn.title = 'Voice input';
  }
}

async function sendVoice() {
  const blob = new Blob(audioChunks, { type: 'audio/webm' });
  if (blob.size < 500) {
    addMessage('system', 'Recording too short — try again');
    return;
  }

  addMessage('user', '🎙 Voice message');
  showTyping();

  const reader = new FileReader();
  reader.onloadend = async () => {
    const b64 = reader.result.split(',')[1];
    try {
      const r = await fetch(`${BASE_URL}/phone/voice`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Astra-Key': API_KEY,
        },
        body: JSON.stringify({
          audio_b64: b64,
          format: 'webm',
          return_audio: true,
        }),
      });
      const d = await r.json();
      removeTyping();

      if (!r.ok) {
        addMessage('system', `Error: ${d.detail || 'unknown error'}`);
        return;
      }

      // Show transcript as user message (replace the placeholder)
      const msgs = messagesEl.querySelectorAll('.msg.user');
      const lastUser = msgs[msgs.length - 1];
      if (lastUser) lastUser.textContent = `🎙 "${d.transcript}"`;

      const meta = `${d.agents_used?.join(', ') || '—'} · ${d.duration_ms}ms`;
      addMessage('zero', d.response, meta);

      // Store audio for playback
      if (d.audio_b64) {
        lastAudioB64 = d.audio_b64;
        document.getElementById('play-btn').classList.add('visible');
      }
    } catch (err) {
      removeTyping();
      addMessage('system', `Error: ${err.message}`);
    }
  };
  reader.readAsDataURL(blob);
}

// ── Audio playback ─────────────────────────────────────────────────────────
document.getElementById('play-btn').onclick = () => {
  if (!lastAudioB64) return;
  const binary = atob(lastAudioB64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  const blob = new Blob([bytes], { type: 'audio/mp3' });
  const url = URL.createObjectURL(blob);
  const audio = new Audio(url);
  audio.play();
  audio.onended = () => URL.revokeObjectURL(url);
};

// ── Proactive alerts (poll every 30s) ─────────────────────────────────────
function addAlertMessage(alert) {
  const div = document.createElement('div');
  div.className = 'msg alert';

  const title = document.createElement('div');
  title.className = 'alert-title';
  title.textContent = alert.title;
  div.appendChild(title);

  const body = document.createElement('div');
  // Preserve newlines in alert body
  body.style.whiteSpace = 'pre-wrap';
  body.textContent = alert.body;
  div.appendChild(body);

  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

async function pollAlerts() {
  if (!API_KEY) return;
  try {
    const r = await fetch(`${BASE_URL}/alerts?mark_delivered=true`, {
      headers: { 'X-Astra-Key': API_KEY },
    });
    if (!r.ok) return;
    const d = await r.json();
    if (d.alerts && d.alerts.length > 0) {
      d.alerts.forEach(addAlertMessage);
      // Hide badge once displayed
      document.getElementById('alert-badge').classList.remove('visible');
    }
  } catch (_) {
    // Silently ignore poll failures — network may be flaky
  }
}

// Check for alerts immediately on connect, then every 30s
function startAlertPolling() {
  pollAlerts();
  setInterval(pollAlerts, 30_000);
}

// Start polling when chat screen appears
const _origShowChat = showChat;
async function showChat() {
  await _origShowChat();
  startAlertPolling();
}
</script>
</body>
</html>"""


@router.get("/ui", response_class=HTMLResponse)
async def phone_ui() -> HTMLResponse:
    """
    Serve the mobile chat UI. No auth needed to load the page itself —
    the page asks for the key on screen before making any API calls.

    Open this URL on your phone:
        https://<your-ngrok-url>/phone/ui
    """
    return HTMLResponse(content=_MOBILE_UI)
