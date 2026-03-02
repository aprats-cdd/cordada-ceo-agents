"""
Google Drive tool executors.

Provides:
  - search_google_drive: Search Drive for documents
  - read_google_drive_document: Read document content by file ID

Each executor tries the direct API first, then falls back to Claude proxy.
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
    "search_google_drive": {
        "name": "search_google_drive",
        "description": (
            "Search Google Drive for documents matching a query. "
            "Returns file names, types, and snippets. Use for finding "
            "internal Cordada documents, reports, presentations, and memos."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (e.g., 'reporte AUM Q4', 'acta directorio')",
                },
                "file_type": {
                    "type": "string",
                    "enum": ["document", "spreadsheet", "presentation", "pdf", "any"],
                    "description": "Filter by file type (default: any)",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default: 10)",
                },
            },
            "required": ["query"],
        },
    },
    "read_google_drive_document": {
        "name": "read_google_drive_document",
        "description": (
            "Read the full text content of a specific Google Drive document by its file ID or URL. "
            "Use after search_google_drive to read a specific document."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_id": {
                    "type": "string",
                    "description": "Google Drive file ID or full URL",
                },
            },
            "required": ["file_id"],
        },
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def escape_drive_query(text: str) -> str:
    """Escape single quotes in a Drive API query value."""
    return text.replace("\\", "\\\\").replace("'", "\\'")


# ---------------------------------------------------------------------------
# Executors
# ---------------------------------------------------------------------------

def exec_search_google_drive(inputs: dict) -> dict:
    """Search Google Drive via the Drive API, or fallback to Claude proxy."""
    query = inputs["query"]
    file_type = inputs.get("file_type", "any")
    max_results = inputs.get("max_results", 10)

    proxy_schema = '{"results": [{"name": "...", "id": "...", "type": "...", "modified": "...", "url": "..."}], "total": N}'

    if not is_google_configured():
        return call_claude_as_proxy(
            proxy_instruction(
                f"Search Google Drive for documents matching: {query}",
                f"File type filter: {file_type}. Return top {max_results} results. ",
                proxy_schema,
            )
        )

    try:
        service = get_google_service(
            "drive", "v3", ["https://www.googleapis.com/auth/drive.readonly"],
        )

        # Build Drive API query (escape single quotes)
        escaped_query = escape_drive_query(query)
        q_parts = [f"fullText contains '{escaped_query}'"]
        mime_map = {
            "document": "application/vnd.google-apps.document",
            "spreadsheet": "application/vnd.google-apps.spreadsheet",
            "presentation": "application/vnd.google-apps.presentation",
            "pdf": "application/pdf",
        }
        if file_type != "any" and file_type in mime_map:
            q_parts.append(f"mimeType='{mime_map[file_type]}'")

        results = service.files().list(
            q=" and ".join(q_parts),
            pageSize=max_results,
            fields="files(id, name, mimeType, modifiedTime, webViewLink)",
            orderBy="modifiedTime desc",
        ).execute()

        files = results.get("files", [])
        return {
            "results": [
                {
                    "name": f["name"],
                    "id": f["id"],
                    "type": f["mimeType"],
                    "modified": f.get("modifiedTime", ""),
                    "url": f.get("webViewLink", ""),
                }
                for f in files
            ],
            "total": len(files),
        }

    except ImportError:
        return {"error": "google-api-python-client not installed. Run: pip install google-api-python-client google-auth"}
    except Exception as e:
        if is_auth_error(e):
            logger.warning("Google Drive auth error, falling back to Claude proxy: %s", e)
            return call_claude_as_proxy(
                proxy_instruction(
                    f"Search Google Drive for documents matching: {query}",
                    f"File type filter: {file_type}. Return top {max_results} results. ",
                    proxy_schema,
                )
            )
        return {"error": f"Google Drive search failed: {e}"}


def exec_read_google_drive_document(inputs: dict) -> dict:
    """Read a Google Drive document's content, or fallback to Claude proxy."""
    file_id = inputs["file_id"]

    proxy_schema = '{"file_id": "...", "content": "full text content here"}'

    if not is_google_configured():
        return call_claude_as_proxy(
            proxy_instruction(
                f"Read the content of the Google Drive document with ID or URL: {file_id}",
                "", proxy_schema,
            )
        )

    try:
        service = get_google_service(
            "drive", "v3", ["https://www.googleapis.com/auth/drive.readonly"],
        )

        # Extract ID from URL if full URL provided
        if "drive.google.com" in file_id:
            import re
            match = re.search(r"/d/([a-zA-Z0-9_-]+)", file_id)
            if match:
                file_id = match.group(1)

        content = service.files().export(
            fileId=file_id,
            mimeType="text/plain",
        ).execute()

        return {
            "file_id": file_id,
            "content": content.decode("utf-8") if isinstance(content, bytes) else str(content),
        }

    except ImportError:
        return {"error": "google-api-python-client not installed. Run: pip install google-api-python-client google-auth"}
    except Exception as e:
        if is_auth_error(e):
            logger.warning("Google Drive auth error, falling back to Claude proxy: %s", e)
            return call_claude_as_proxy(
                proxy_instruction(
                    f"Read the content of the Google Drive document with ID or URL: {file_id}",
                    "", proxy_schema,
                )
            )
        return {"error": f"Failed to read document: {e}"}


# ---------------------------------------------------------------------------
# Executor dispatch (tool_name -> function)
# ---------------------------------------------------------------------------

EXECUTORS: dict[str, Any] = {
    "search_google_drive": exec_search_google_drive,
    "read_google_drive_document": exec_read_google_drive_document,
}
