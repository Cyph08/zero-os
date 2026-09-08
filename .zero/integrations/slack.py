"""
integrations/slack.py — Zero Slack Integration

Wraps the Slack Web API via httpx (no extra library needed — uses bearer token).
Token: SLACK_BOT_TOKEN in .env (xoxb-...)
Default channel: SLACK_DEFAULT_CHANNEL in .env (e.g. #Astra)

Functions:
  send_message(text, channel)    → post a message (risk=high — never auto-sends)
  list_channels()                → list public + private channels the bot is in
  get_channel_history(channel)   → recent messages from a channel
  get_channel_id(name)           → resolve channel name → ID
  upload_snippet(text, channel)  → post a code/text snippet
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

logger = logging.getLogger(__name__)

_BASE = "https://slack.com/api"
_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")
_DEFAULT_CHANNEL = os.getenv("SLACK_DEFAULT_CHANNEL", "#general").lstrip("#")

_HEADERS = {
    "Authorization": f"Bearer {_TOKEN}",
    "Content-Type": "application/json; charset=utf-8",
}


def _check(response: dict[str, Any], op: str) -> bool:
    """
    Check a Slack API response for errors.

    Args:
        response: Parsed JSON from Slack API.
        op: Operation name for logging.

    Returns:
        True if ok, False if error.
    """
    if not response.get("ok"):
        error = response.get("error", "unknown")
        logger.error(f"[slack] {op} failed: {error}")
        return False
    return True


# ---------------------------------------------------------------------------
# Channel utilities
# ---------------------------------------------------------------------------

def list_channels(types: str = "public_channel,private_channel") -> list[dict[str, Any]]:
    """
    List all channels the bot is a member of.

    Args:
        types: Comma-separated channel types to include.

    Returns:
        List of channel dicts with id, name, is_private, member_count.
    """
    try:
        r = httpx.get(
            f"{_BASE}/conversations.list",
            headers=_HEADERS,
            params={"types": types, "limit": 200},
            timeout=15,
        )
        data = r.json()
        if not _check(data, "list_channels"):
            return []
        return [
            {
                "id": ch["id"],
                "name": ch["name"],
                "is_private": ch.get("is_private", False),
                "member_count": ch.get("num_members", 0),
            }
            for ch in data.get("channels", [])
        ]
    except Exception as exc:
        logger.error(f"[slack] list_channels failed: {exc}")
        return []


def get_channel_id(name: str) -> str | None:
    """
    Resolve a channel name to its Slack ID.

    Args:
        name: Channel name (with or without #).

    Returns:
        Channel ID string, or None if not found.
    """
    name = name.lstrip("#")
    channels = list_channels()
    for ch in channels:
        if ch["name"] == name:
            return ch["id"]
    logger.warning(f"[slack] Channel #{name} not found — is the bot invited?")
    return None


def get_channel_history(
    channel: str = _DEFAULT_CHANNEL,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """
    Fetch recent messages from a channel.

    Args:
        channel: Channel name or ID.
        limit: Number of messages to return.

    Returns:
        List of message dicts with text, user, timestamp.
    """
    channel_id = channel if channel.startswith("C") else get_channel_id(channel)
    if not channel_id:
        return []

    try:
        r = httpx.get(
            f"{_BASE}/conversations.history",
            headers=_HEADERS,
            params={"channel": channel_id, "limit": limit},
            timeout=15,
        )
        data = r.json()
        if not _check(data, "get_channel_history"):
            return []
        return [
            {
                "text": msg.get("text", ""),
                "user": msg.get("user", "bot"),
                "ts": msg.get("ts", ""),
                "type": msg.get("type", "message"),
            }
            for msg in data.get("messages", [])
            if msg.get("type") == "message"
        ]
    except Exception as exc:
        logger.error(f"[slack] get_channel_history failed: {exc}")
        return []


# ---------------------------------------------------------------------------
# Send operations
# ---------------------------------------------------------------------------

def send_message(
    text: str,
    channel: str = _DEFAULT_CHANNEL,
    thread_ts: str | None = None,
) -> dict[str, Any]:
    """
    Send a message to a Slack channel.

    RISK: HIGH — never call this without explicit user confirmation.
    The comms/linkedin agents draft messages; this sends them.

    Args:
        text: Message text (supports Slack markdown).
        channel: Channel name or ID. Defaults to SLACK_DEFAULT_CHANNEL.
        thread_ts: Optional thread timestamp to reply in a thread.

    Returns:
        Dict with ts (message timestamp) and channel on success.
    """
    channel_id = channel if channel.startswith("C") else get_channel_id(channel)
    if not channel_id:
        return {"error": f"Channel #{channel} not found"}

    payload: dict[str, Any] = {"channel": channel_id, "text": text}
    if thread_ts:
        payload["thread_ts"] = thread_ts

    try:
        r = httpx.post(f"{_BASE}/chat.postMessage", headers=_HEADERS, json=payload, timeout=15)
        data = r.json()
        if not _check(data, "send_message"):
            return {"error": data.get("error", "unknown")}
        logger.info(f"[slack] Message sent to #{channel}")
        return {"ts": data.get("ts"), "channel": data.get("channel")}
    except Exception as exc:
        logger.error(f"[slack] send_message failed: {exc}")
        return {"error": str(exc)}


def upload_snippet(
    text: str,
    channel: str = _DEFAULT_CHANNEL,
    title: str = "Astra snippet",
    filetype: str = "text",
) -> dict[str, Any]:
    """
    Upload a text snippet / code block to Slack.

    Args:
        text: Content of the snippet.
        channel: Channel name or ID.
        title: Snippet title shown in Slack.
        filetype: e.g. "python", "text", "json".

    Returns:
        Dict with file url on success.
    """
    channel_id = channel if channel.startswith("C") else get_channel_id(channel)
    if not channel_id:
        return {"error": f"Channel #{channel} not found"}

    try:
        r = httpx.post(
            f"{_BASE}/files.upload",
            headers={"Authorization": f"Bearer {_TOKEN}"},
            data={
                "channels": channel_id,
                "content": text,
                "filename": f"{title}.txt",
                "title": title,
                "filetype": filetype,
            },
            timeout=20,
        )
        data = r.json()
        if not _check(data, "upload_snippet"):
            return {"error": data.get("error", "unknown")}
        return {"url": data.get("file", {}).get("permalink", "")}
    except Exception as exc:
        logger.error(f"[slack] upload_snippet failed: {exc}")
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== SLACK CHANNELS ===")
    channels = list_channels()
    if channels:
        for ch in channels:
            print(f"  {'🔒' if ch['is_private'] else '#'} {ch['name']} ({ch['member_count']} members)")
    else:
        print("  No channels found — check SLACK_BOT_TOKEN and bot invite status")

    print(f"\n=== RECENT MESSAGES IN #{_DEFAULT_CHANNEL} ===")
    msgs = get_channel_history(_DEFAULT_CHANNEL, limit=5)
    for m in msgs:
        print(f"  [{m['ts']}] {m['text'][:80]}")
