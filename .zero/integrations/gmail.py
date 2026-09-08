"""
integrations/gmail.py — Zero OS Gmail Integration

Reads, searches, and drafts Gmail emails using the Google Gmail API.
Uses OAuth 2.0 — first run opens a browser to authenticate, then
saves a token locally so you never have to log in again.

─── SETUP (one time only) ────────────────────────────────────────────
1. Go to https://console.cloud.google.com
2. Create a new project (or use an existing one)
3. Enable the Gmail API:
   APIs & Services → Enable APIs → search "Gmail API" → Enable
4. Create OAuth credentials:
   APIs & Services → Credentials → Create Credentials → OAuth Client ID
   Application type: Desktop app → Download JSON
5. Save the downloaded file as:
   K:\\Astra\\.zero\\integrations\\google_credentials.json
6. Run this file once to authenticate:
   python integrations/gmail.py
   A browser will open → log in → token saved automatically.
──────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# File paths
_CREDS_FILE  = Path(__file__).parent / "google_credentials.json"
_TOKEN_FILE  = Path(__file__).parent / "google_token.json"

# Scopes — what Zero is allowed to do with Gmail
_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",   # read emails
    "https://www.googleapis.com/auth/gmail.compose",    # draft/send emails
    "https://www.googleapis.com/auth/gmail.modify",     # label, archive
]


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def _get_service() -> Any:
    """
    Authenticate with Google and return a Gmail API service object.

    On first run: opens browser for OAuth consent.
    On subsequent runs: loads saved token from disk.

    Returns:
        Gmail API service object.

    Raises:
        FileNotFoundError: If google_credentials.json is missing.
        RuntimeError: If google-api packages are not installed.
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
            f"Google credentials file not found at {_CREDS_FILE}\n"
            "Follow the setup instructions at the top of integrations/gmail.py"
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
        logger.info(f"[gmail] Token saved to {_TOKEN_FILE}")

    return build("gmail", "v1", credentials=creds)


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def list_unread(max_results: int = 10) -> list[dict[str, Any]]:
    """
    Return a list of unread emails from the inbox.

    Args:
        max_results: Maximum number of emails to return.

    Returns:
        List of dicts with keys: id, subject, from, snippet, date.
    """
    try:
        service = _get_service()
        result = service.users().messages().list(
            userId="me",
            q="is:unread in:inbox",
            maxResults=max_results,
        ).execute()

        messages = result.get("messages", [])
        emails = []
        for msg in messages:
            full = service.users().messages().get(
                userId="me", id=msg["id"], format="metadata",
                metadataHeaders=["Subject", "From", "Date"],
            ).execute()
            headers = {h["name"]: h["value"] for h in full["payload"]["headers"]}
            emails.append({
                "id": msg["id"],
                "subject": headers.get("Subject", "(no subject)"),
                "from": headers.get("From", ""),
                "date": headers.get("Date", ""),
                "snippet": full.get("snippet", ""),
            })
        logger.info(f"[gmail] Fetched {len(emails)} unread emails")
        return emails
    except Exception as exc:
        logger.error(f"[gmail] list_unread failed: {exc}")
        return []


def search_emails(query: str, max_results: int = 10) -> list[dict[str, Any]]:
    """
    Search Gmail with a query string (same syntax as Gmail search bar).

    Args:
        query: Gmail search query, e.g. "from:boss@work.com subject:urgent"
        max_results: Maximum results to return.

    Returns:
        List of email dicts with subject, from, date, snippet.
    """
    try:
        service = _get_service()
        result = service.users().messages().list(
            userId="me", q=query, maxResults=max_results,
        ).execute()
        messages = result.get("messages", [])
        emails = []
        for msg in messages:
            full = service.users().messages().get(
                userId="me", id=msg["id"], format="metadata",
                metadataHeaders=["Subject", "From", "Date"],
            ).execute()
            headers = {h["name"]: h["value"] for h in full["payload"]["headers"]}
            emails.append({
                "id": msg["id"],
                "subject": headers.get("Subject", "(no subject)"),
                "from": headers.get("From", ""),
                "date": headers.get("Date", ""),
                "snippet": full.get("snippet", ""),
            })
        return emails
    except Exception as exc:
        logger.error(f"[gmail] search_emails({query!r}) failed: {exc}")
        return []


def get_email_body(message_id: str) -> str:
    """
    Get the full plain-text body of an email.

    Args:
        message_id: Gmail message ID from list_unread() or search_emails().

    Returns:
        Plain text body of the email.
    """
    import base64
    try:
        service = _get_service()
        msg = service.users().messages().get(
            userId="me", id=message_id, format="full",
        ).execute()

        def _extract_text(payload: dict) -> str:
            """Recursively extract plain text from MIME parts."""
            if payload.get("mimeType") == "text/plain":
                data = payload.get("body", {}).get("data", "")
                return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
            for part in payload.get("parts", []):
                text = _extract_text(part)
                if text:
                    return text
            return ""

        return _extract_text(msg["payload"])
    except Exception as exc:
        logger.error(f"[gmail] get_email_body({message_id}) failed: {exc}")
        return ""


# ---------------------------------------------------------------------------
# Draft / Send (HIGH risk — always preview before sending)
# ---------------------------------------------------------------------------

def create_draft(to: str, subject: str, body: str) -> dict[str, Any]:
    """
    Create a Gmail draft. Does NOT send — Zero always previews first.

    Args:
        to: Recipient email address.
        subject: Email subject line.
        body: Plain text email body.

    Returns:
        Dict with draft id and preview summary.
    """
    import base64
    from email.mime.text import MIMEText
    try:
        service = _get_service()
        message = MIMEText(body)
        message["to"] = to
        message["subject"] = subject
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        draft = service.users().drafts().create(
            userId="me", body={"message": {"raw": raw}},
        ).execute()
        logger.info(f"[gmail] Draft created: {draft['id']} → {to}")
        return {
            "draft_id": draft["id"],
            "to": to,
            "subject": subject,
            "preview": body[:300],
        }
    except Exception as exc:
        logger.error(f"[gmail] create_draft failed: {exc}")
        return {"error": str(exc)}


def send_draft(draft_id: str) -> bool:
    """
    Send an existing draft. ONLY call this after explicit user confirmation.

    Args:
        draft_id: The draft ID from create_draft().

    Returns:
        True if sent successfully.
    """
    try:
        service = _get_service()
        service.users().drafts().send(
            userId="me", body={"id": draft_id},
        ).execute()
        logger.info(f"[gmail] Draft {draft_id} sent")
        return True
    except Exception as exc:
        logger.error(f"[gmail] send_draft({draft_id}) failed: {exc}")
        return False


# ---------------------------------------------------------------------------
# Status check
# ---------------------------------------------------------------------------

def is_connected() -> bool:
    """Return True if Gmail credentials exist and token is valid."""
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
    print("Setting up Gmail integration...")
    if not _CREDS_FILE.exists():
        print(f"\n❌ Missing: {_CREDS_FILE}")
        print("Download your OAuth credentials from Google Cloud Console first.")
        print("See the setup instructions at the top of this file.")
    else:
        try:
            _get_service()
            print("✅ Gmail connected successfully!")
            emails = list_unread(max_results=3)
            print(f"\nYou have unread emails. First {len(emails)}:")
            for e in emails:
                print(f"  From: {e['from']}")
                print(f"  Subject: {e['subject']}")
                print(f"  Preview: {e['snippet'][:80]}\n")
        except Exception as exc:
            print(f"❌ Error: {exc}")
