"""
Gmail tool executors.

Provides:
  - search_gmail: Search Gmail messages
  - read_gmail_message: Read a full email message
  - draft_gmail: Create a Gmail draft (NEVER proxied — security boundary)

Each read executor tries the direct API first, then falls back to Claude proxy.
Write operations return manual_fallback when credentials are missing.
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
    "search_gmail": {
        "name": "search_gmail",
        "description": (
            "Search Gmail for emails matching a query. Returns subject, sender, date, "
            "and snippet. Use for finding communications about specific topics."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Gmail search query (supports Gmail search syntax: from:, to:, subject:, after:, before:)",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results (default: 10)",
                },
            },
            "required": ["query"],
        },
    },
    "read_gmail_message": {
        "name": "read_gmail_message",
        "description": "Read the full content of a specific Gmail message by ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message_id": {
                    "type": "string",
                    "description": "Gmail message ID",
                },
            },
            "required": ["message_id"],
        },
    },
    "draft_gmail": {
        "name": "draft_gmail",
        "description": (
            "Create a Gmail draft (does NOT send). The CEO reviews and sends manually. "
            "Use for preparing email communications."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Recipient email address",
                },
                "subject": {
                    "type": "string",
                    "description": "Email subject line",
                },
                "body": {
                    "type": "string",
                    "description": "Email body (plain text)",
                },
                "cc": {
                    "type": "string",
                    "description": "CC recipients (comma-separated)",
                },
            },
            "required": ["to", "subject", "body"],
        },
    },
}


# ---------------------------------------------------------------------------
# Executors
# ---------------------------------------------------------------------------

def exec_search_gmail(inputs: dict) -> dict:
    """Search Gmail messages, or fallback to Claude proxy."""
    query = inputs["query"]
    max_results = inputs.get("max_results", 10)

    proxy_schema = '{"results": [{"id": "...", "subject": "...", "from": "...", "date": "...", "snippet": "..."}], "total": N}'

    if not is_google_configured():
        return call_claude_as_proxy(
            proxy_instruction(
                f"Search Gmail for: {query}",
                f"Return top {max_results} results. ",
                proxy_schema,
            )
        )

    try:
        service = get_google_service(
            "gmail", "v1", ["https://www.googleapis.com/auth/gmail.readonly"],
        )

        # Batch-compatible approach — request list with message IDs,
        # then use a single batch request to fetch metadata for all.
        list_result = service.users().messages().list(
            userId="me",
            q=query,
            maxResults=max_results,
        ).execute()

        msg_stubs = list_result.get("messages", [])
        if not msg_stubs:
            return {"results": [], "total": 0}

        # Batch fetch all message metadata in one round-trip
        batch_results: dict[str, Any] = {}

        def _on_batch_response(request_id, response, exception):
            if exception:
                logger.warning("Batch Gmail get failed for %s: %s", request_id, exception)
            else:
                batch_results[request_id] = response

        batch = service.new_batch_http_request(callback=_on_batch_response)
        for stub in msg_stubs:
            batch.add(
                service.users().messages().get(
                    userId="me",
                    id=stub["id"],
                    format="metadata",
                    metadataHeaders=["Subject", "From", "Date"],
                ),
                request_id=stub["id"],
            )
        batch.execute()

        messages = []
        for stub in msg_stubs:
            msg = batch_results.get(stub["id"])
            if not msg:
                continue
            headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
            messages.append({
                "id": msg["id"],
                "subject": headers.get("Subject", ""),
                "from": headers.get("From", ""),
                "date": headers.get("Date", ""),
                "snippet": msg.get("snippet", ""),
            })

        return {"results": messages, "total": len(messages)}

    except ImportError:
        return {"error": "google-api-python-client not installed. Run: pip install google-api-python-client google-auth"}
    except Exception as e:
        if is_auth_error(e):
            logger.warning("Gmail auth error, falling back to Claude proxy: %s", e)
            return call_claude_as_proxy(
                proxy_instruction(
                    f"Search Gmail for: {query}",
                    f"Return top {max_results} results. ",
                    proxy_schema,
                )
            )
        return {"error": f"Gmail search failed: {e}"}


def exec_read_gmail_message(inputs: dict) -> dict:
    """Read a full Gmail message, or fallback to Claude proxy."""
    message_id = inputs["message_id"]

    proxy_schema = '{"id": "...", "subject": "...", "from": "...", "to": "...", "date": "...", "body": "full email body"}'

    if not is_google_configured():
        return call_claude_as_proxy(
            proxy_instruction(
                f"Read the full Gmail message with ID: {message_id}",
                "", proxy_schema,
            )
        )

    try:
        import base64

        service = get_google_service(
            "gmail", "v1", ["https://www.googleapis.com/auth/gmail.readonly"],
        )

        msg = service.users().messages().get(
            userId="me",
            id=message_id,
            format="full",
        ).execute()

        headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}

        # Extract body
        body = ""
        payload = msg.get("payload", {})
        if "body" in payload and payload["body"].get("data"):
            body = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8")
        elif "parts" in payload:
            for part in payload["parts"]:
                if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
                    body = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8")
                    break

        return {
            "id": msg["id"],
            "subject": headers.get("Subject", ""),
            "from": headers.get("From", ""),
            "to": headers.get("To", ""),
            "date": headers.get("Date", ""),
            "body": body,
        }

    except ImportError:
        return {"error": "google-api-python-client not installed. Run: pip install google-api-python-client google-auth"}
    except Exception as e:
        if is_auth_error(e):
            logger.warning("Gmail auth error, falling back to Claude proxy: %s", e)
            return call_claude_as_proxy(
                proxy_instruction(
                    f"Read the full Gmail message with ID: {message_id}",
                    "", proxy_schema,
                )
            )
        return {"error": f"Failed to read message: {e}"}


def exec_draft_gmail(inputs: dict) -> dict:
    """
    Create a Gmail draft, or return content for manual action.

    Security: Write operations are NEVER proxied. Without direct credentials,
    the content is returned as manual_fallback for the CEO to send.
    """
    if not is_google_configured():
        return {
            "source": "manual_fallback",
            "status": "draft_not_created",
            "note": "Sin acceso a Gmail. El borrador se muestra abajo para envio manual.",
            "to": inputs["to"],
            "subject": inputs["subject"],
            "body": inputs["body"],
            "cc": inputs.get("cc", ""),
        }

    try:
        import base64
        from email.mime.text import MIMEText

        service = get_google_service(
            "gmail", "v1", ["https://www.googleapis.com/auth/gmail.compose"],
        )

        message = MIMEText(inputs["body"])
        message["to"] = inputs["to"]
        message["subject"] = inputs["subject"]
        if inputs.get("cc"):
            message["cc"] = inputs["cc"]

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        draft = service.users().drafts().create(
            userId="me",
            body={"message": {"raw": raw}},
        ).execute()

        return {
            "status": "draft_created",
            "draft_id": draft["id"],
            "to": inputs["to"],
            "subject": inputs["subject"],
        }

    except ImportError:
        return {"error": "google-api-python-client not installed. Run: pip install google-api-python-client google-auth"}
    except Exception as e:
        if is_auth_error(e):
            logger.warning("Gmail auth error on draft — returning manual fallback: %s", e)
            return {
                "source": "manual_fallback",
                "status": "draft_not_created",
                "note": "Auth error. El borrador se muestra abajo para envio manual.",
                "to": inputs["to"],
                "subject": inputs["subject"],
                "body": inputs["body"],
                "cc": inputs.get("cc", ""),
            }
        return {"error": f"Failed to create draft: {e}"}


# ---------------------------------------------------------------------------
# Executor dispatch (tool_name -> function)
# ---------------------------------------------------------------------------

EXECUTORS: dict[str, Any] = {
    "search_gmail": exec_search_gmail,
    "read_gmail_message": exec_read_gmail_message,
    "draft_gmail": exec_draft_gmail,
}
