"""
Google Calendar tool executors.

Provides:
  - read_calendar: Read upcoming Google Calendar events

Tries the direct API first, then falls back to Claude proxy.
"""

from __future__ import annotations

import logging
from typing import Any

from ._shared import (
    is_google_configured,
    is_auth_error,
    get_google_service,
    proxy_instruction,
)
from .proxy import call_claude_as_proxy

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool definitions (JSON schemas for Anthropic API)
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS: dict[str, dict] = {
    "read_calendar": {
        "name": "read_calendar",
        "description": (
            "Read upcoming Google Calendar events. Use for checking deadlines, "
            "meeting schedules, and timing context."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days_ahead": {
                    "type": "integer",
                    "description": "Number of days ahead to look (default: 7)",
                },
                "query": {
                    "type": "string",
                    "description": "Optional: filter events by text in title/description",
                },
            },
            "required": [],
        },
    },
}


# ---------------------------------------------------------------------------
# Executors
# ---------------------------------------------------------------------------

def exec_read_calendar(inputs: dict) -> dict:
    """Read upcoming Google Calendar events, or fallback to Claude proxy."""
    days = inputs.get("days_ahead", 7)
    query = inputs.get("query", "")

    proxy_schema = '{"events": [{"summary": "...", "start": "...", "end": "...", "description": "...", "attendees": ["..."]}], "total": N}'

    if not is_google_configured():
        return call_claude_as_proxy(
            proxy_instruction(
                f"Read upcoming Google Calendar events for the next {days} days",
                f"Filter: {query or 'all events'}. ",
                proxy_schema,
            )
        )

    try:
        from datetime import datetime, timedelta, timezone

        service = get_google_service(
            "calendar", "v3", ["https://www.googleapis.com/auth/calendar.readonly"],
        )

        now = datetime.now(timezone.utc)
        time_max = now + timedelta(days=days)

        events_result = service.events().list(
            calendarId="primary",
            timeMin=now.isoformat(),
            timeMax=time_max.isoformat(),
            maxResults=20,
            singleEvents=True,
            orderBy="startTime",
            q=query,
        ).execute()

        events = []
        for event in events_result.get("items", []):
            start = event["start"].get("dateTime", event["start"].get("date"))
            events.append({
                "summary": event.get("summary", ""),
                "start": start,
                "end": event["end"].get("dateTime", event["end"].get("date")),
                "description": event.get("description", "")[:200],
                "attendees": [a.get("email", "") for a in event.get("attendees", [])],
            })

        return {"events": events, "total": len(events)}

    except ImportError:
        return {"error": "google-api-python-client not installed. Run: pip install google-api-python-client google-auth"}
    except Exception as e:
        if is_auth_error(e):
            logger.warning("Calendar auth error, falling back to Claude proxy: %s", e)
            return call_claude_as_proxy(
                proxy_instruction(
                    f"Read upcoming Google Calendar events for the next {days} days",
                    f"Filter: {query or 'all events'}. ",
                    proxy_schema,
                )
            )
        return {"error": f"Calendar read failed: {e}"}


# ---------------------------------------------------------------------------
# Executor dispatch (tool_name -> function)
# ---------------------------------------------------------------------------

EXECUTORS: dict[str, Any] = {
    "read_calendar": exec_read_calendar,
}
