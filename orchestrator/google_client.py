"""
Google Workspace API client — Drive, Gmail, Calendar search.

Uses a service account with domain-wide delegation so everything
runs headless in the terminal (no OAuth browser flow).

All functions return an empty list on error so the caller can
degrade gracefully.
"""

import logging
from datetime import datetime, timedelta, timezone

from .config import GOOGLE_CREDENTIALS_PATH, GOOGLE_DELEGATE_EMAIL

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy service builder
# ---------------------------------------------------------------------------

_services: dict = {}


def _build_service(api: str, version: str):
    """Build a Google API service with delegated credentials (cached)."""
    key = f"{api}:{version}"
    if key in _services:
        return _services[key]

    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    scopes = {
        "drive": ["https://www.googleapis.com/auth/drive.readonly"],
        "gmail": ["https://www.googleapis.com/auth/gmail.readonly"],
        "calendar": ["https://www.googleapis.com/auth/calendar.readonly"],
    }

    creds = service_account.Credentials.from_service_account_file(
        GOOGLE_CREDENTIALS_PATH,
        scopes=scopes.get(api, []),
    )
    if GOOGLE_DELEGATE_EMAIL:
        creds = creds.with_subject(GOOGLE_DELEGATE_EMAIL)

    svc = build(api, version, credentials=creds, cache_discovery=False)
    _services[key] = svc
    return svc


def is_google_configured() -> bool:
    """Return True if Google credentials are present."""
    return bool(GOOGLE_CREDENTIALS_PATH and GOOGLE_DELEGATE_EMAIL)


# ---------------------------------------------------------------------------
# Google Drive
# ---------------------------------------------------------------------------

def search_drive(query: str, max_results: int = 5) -> list[dict]:
    """Search Google Drive for documents matching *query*.

    Returns:
        List of dicts with keys: title, url, snippet, date, mime_type
    """
    if not is_google_configured():
        return []
    try:
        svc = _build_service("drive", "v3")
        resp = (
            svc.files()
            .list(
                q=f"fullText contains '{query}'",
                pageSize=max_results,
                fields="files(id, name, mimeType, modifiedTime, webViewLink)",
                orderBy="modifiedTime desc",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        results = []
        for f in resp.get("files", []):
            results.append({
                "title": f.get("name", ""),
                "url": f.get("webViewLink", ""),
                "snippet": "",  # Drive list API does not return snippets
                "date": f.get("modifiedTime", "")[:10],
                "mime_type": f.get("mimeType", ""),
            })
        return results
    except Exception:
        logger.exception("Google Drive search failed for query: %s", query)
        return []


# ---------------------------------------------------------------------------
# Gmail
# ---------------------------------------------------------------------------

def search_gmail(query: str, max_results: int = 5) -> list[dict]:
    """Search Gmail for emails matching *query*.

    Returns:
        List of dicts with keys: subject, from, date, snippet
    """
    if not is_google_configured():
        return []
    try:
        svc = _build_service("gmail", "v1")
        resp = (
            svc.users()
            .messages()
            .list(userId="me", q=query, maxResults=max_results)
            .execute()
        )
        results = []
        for msg_meta in resp.get("messages", []):
            msg = (
                svc.users()
                .messages()
                .get(userId="me", id=msg_meta["id"], format="metadata",
                     metadataHeaders=["Subject", "From", "Date"])
                .execute()
            )
            headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
            results.append({
                "subject": headers.get("Subject", "(sin asunto)"),
                "from": headers.get("From", ""),
                "date": headers.get("Date", ""),
                "snippet": msg.get("snippet", ""),
            })
        return results
    except Exception:
        logger.exception("Gmail search failed for query: %s", query)
        return []


# ---------------------------------------------------------------------------
# Google Calendar
# ---------------------------------------------------------------------------

def search_calendar(query: str, days_ahead: int = 14) -> list[dict]:
    """Search Google Calendar for upcoming events.

    Returns:
        List of dicts with keys: title, date, attendees, description
    """
    if not is_google_configured():
        return []
    try:
        svc = _build_service("calendar", "v3")
        now = datetime.now(timezone.utc)
        time_max = now + timedelta(days=days_ahead)

        resp = (
            svc.events()
            .list(
                calendarId="primary",
                q=query,
                timeMin=now.isoformat(),
                timeMax=time_max.isoformat(),
                maxResults=10,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        results = []
        for ev in resp.get("items", []):
            start = ev.get("start", {}).get("dateTime", ev.get("start", {}).get("date", ""))
            attendees = [a.get("email", "") for a in ev.get("attendees", [])]
            results.append({
                "title": ev.get("summary", ""),
                "date": start[:10] if start else "",
                "attendees": attendees,
                "description": (ev.get("description") or "")[:200],
            })
        return results
    except Exception:
        logger.exception("Calendar search failed for query: %s", query)
        return []
