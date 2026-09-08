"""
integrations/google_calendar.py — Zero OS Google Calendar Integration

Lists events, creates events, and checks availability using Google Calendar API.
Shares the same OAuth credentials file as Gmail (google_credentials.json).

─── SETUP (one time only) ────────────────────────────────────────────
Same as Gmail setup. If you already ran gmail.py setup, you only need to
re-authenticate because Calendar needs an additional scope:

1. Make sure K:\\Astra\\.zero\\integrations\\google_credentials.json exists
   (same file used for Gmail)
2. Delete google_token.json (if it exists) to force re-auth with new scopes
3. Run: python integrations/google_calendar.py
   Browser opens → approve Calendar access → token saved.
──────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CREDS_FILE = Path(__file__).parent / "google_credentials.json"
_TOKEN_FILE  = Path(__file__).parent / "google_token.json"

# Combined scopes — includes Gmail + Calendar so one token covers both
_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
]


# ---------------------------------------------------------------------------
# Auth (shared logic with gmail.py)
# ---------------------------------------------------------------------------

def _get_service() -> Any:
    """
    Authenticate and return a Google Calendar API service object.

    Returns:
        Calendar API service object.
    """
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError:
        raise RuntimeError(
            "Google API packages not installed. Run:\n"
            "uv pip install google-api-python-client google-auth-oauthlib google-auth-httplib2"
        )

    if not _CREDS_FILE.exists():
        raise FileNotFoundError(
            f"Missing: {_CREDS_FILE}\n"
            "See setup instructions at the top of integrations/google_calendar.py"
        )

    creds = None
    if _TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(_TOKEN_FILE), _SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(_CREDS_FILE), _SCOPES)
            creds = flow.run_local_server(port=0)
        _TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")

    return build("calendar", "v3", credentials=creds)


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def list_upcoming(days: int = 7, max_results: int = 20) -> list[dict[str, Any]]:
    """
    List upcoming calendar events.

    Args:
        days: How many days ahead to look.
        max_results: Maximum events to return.

    Returns:
        List of event dicts with: id, title, start, end, location, description.
    """
    try:
        service = _get_service()
        now = datetime.now(timezone.utc)
        end = now + timedelta(days=days)
        result = service.events().list(
            calendarId="primary",
            timeMin=now.isoformat(),
            timeMax=end.isoformat(),
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        events = []
        for item in result.get("items", []):
            start = item["start"].get("dateTime", item["start"].get("date", ""))
            end_dt = item["end"].get("dateTime", item["end"].get("date", ""))
            events.append({
                "id": item["id"],
                "title": item.get("summary", "(no title)"),
                "start": start,
                "end": end_dt,
                "location": item.get("location", ""),
                "description": item.get("description", ""),
                "all_day": "dateTime" not in item["start"],
            })
        logger.info(f"[calendar] Fetched {len(events)} upcoming events")
        return events
    except Exception as exc:
        logger.error(f"[calendar] list_upcoming failed: {exc}")
        return []


def get_today() -> list[dict[str, Any]]:
    """
    Return today's events only.

    Returns:
        List of today's event dicts.
    """
    return list_upcoming(days=1)


def search_events(query: str, days: int = 30) -> list[dict[str, Any]]:
    """
    Search calendar events by text.

    Args:
        query: Search string to match against event titles/descriptions.
        days: How many days ahead to search.

    Returns:
        Matching event dicts.
    """
    try:
        service = _get_service()
        now = datetime.now(timezone.utc)
        end = now + timedelta(days=days)
        result = service.events().list(
            calendarId="primary",
            timeMin=now.isoformat(),
            timeMax=end.isoformat(),
            q=query,
            singleEvents=True,
            orderBy="startTime",
        ).execute()
        events = []
        for item in result.get("items", []):
            start = item["start"].get("dateTime", item["start"].get("date", ""))
            events.append({
                "id": item["id"],
                "title": item.get("summary", "(no title)"),
                "start": start,
                "location": item.get("location", ""),
            })
        return events
    except Exception as exc:
        logger.error(f"[calendar] search_events({query!r}) failed: {exc}")
        return []


# ---------------------------------------------------------------------------
# Write (risk level: write — informs Cyph before creating)
# ---------------------------------------------------------------------------

def create_event(
    title: str,
    start: str,
    end: str,
    description: str = "",
    location: str = "",
) -> dict[str, Any]:
    """
    Create a new calendar event.

    Args:
        title: Event title.
        start: ISO 8601 datetime string, e.g. "2025-06-20T14:00:00"
        end: ISO 8601 datetime string.
        description: Optional event notes.
        location: Optional location string.

    Returns:
        Dict with event id, link, and summary.
    """
    try:
        service = _get_service()
        if "Z" not in start and "+" not in start:
            start += "+00:00"
        if "Z" not in end and "+" not in end:
            end += "+00:00"

        event_body = {
            "summary": title,
            "description": description,
            "location": location,
            "start": {"dateTime": start},
            "end": {"dateTime": end},
        }
        created = service.events().insert(
            calendarId="primary", body=event_body,
        ).execute()
        logger.info(f"[calendar] Created event: {title} at {start}")
        return {
            "id": created["id"],
            "title": title,
            "start": start,
            "end": end,
            "link": created.get("htmlLink", ""),
        }
    except Exception as exc:
        logger.error(f"[calendar] create_event({title!r}) failed: {exc}")
        return {"error": str(exc)}


def delete_event(event_id: str) -> bool:
    """
    Delete a calendar event. ONLY call after explicit user confirmation.

    Args:
        event_id: The event ID from list_upcoming() or create_event().

    Returns:
        True if deleted successfully.
    """
    try:
        service = _get_service()
        service.events().delete(calendarId="primary", eventId=event_id).execute()
        logger.info(f"[calendar] Deleted event {event_id}")
        return True
    except Exception as exc:
        logger.error(f"[calendar] delete_event({event_id}) failed: {exc}")
        return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def format_events_for_llm(events: list[dict[str, Any]]) -> str:
    """
    Format an event list into a readable string for LLM context.

    Args:
        events: List of event dicts from list_upcoming() etc.

    Returns:
        Human-readable multi-line string.
    """
    if not events:
        return "No events found."
    lines = []
    for e in events:
        line = f"• {e['title']} — {e['start']}"
        if e.get("location"):
            line += f" @ {e['location']}"
        lines.append(line)
    return "\n".join(lines)


def is_connected() -> bool:
    """Return True if Calendar credentials are valid."""
    if not _CREDS_FILE.exists():
        return False
    try:
        _get_service()
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# CLI setup helper
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
    print("Setting up Google Calendar integration...")
    if not _CREDS_FILE.exists():
        print(f"\n❌ Missing: {_CREDS_FILE}")
        print("See setup instructions at the top of this file.")
    else:
        try:
            events = list_upcoming(days=7)
            print(f"✅ Calendar connected! Upcoming events ({len(events)}):")
            for e in events:
                print(f"  {e['start'][:16]} — {e['title']}")
        except Exception as exc:
            print(f"❌ Error: {exc}")
