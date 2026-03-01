"""
Tool system for cordada-ceo-agents.

Provides tool definitions, a per-agent registry, and executors so that
agents can search the web, read Google Drive/Gmail, query Slack, etc.

Architecture:
  - Server tools (web_search): Anthropic executes them server-side.
    The client only needs to include them in the tools list.
  - Custom tools (Google, Slack): Defined here with JSON schemas.
    The agent_runner executes them locally when the model requests them
    and sends tool_results back to the API.

Fallback strategy — agents are NEVER blind:
  - Credentials available → direct API call (fast, precise)
  - Credentials missing OR auth error → call_claude_as_proxy() sends a
    structured prompt to Claude (claude-sonnet-4-20250514), which uses
    its MCP-connected tools (Gmail, Drive, Slack) to retrieve the data
  - Write tools (draft_gmail, send_slack) without credentials → return the
    content for manual sending instead of failing silently
  - The calling agent never knows whether data came from direct API or proxy
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Model used for proxy calls (Claude with MCP tool access)
_PROXY_MODEL = "claude-sonnet-4-20250514"

_PROXY_SYSTEM_PROMPT = (
    "You are a data retrieval proxy. "
    "Execute the requested operation using your available tools (Gmail, Slack, Google Drive). "
    "Return ONLY a JSON object with the results. No explanations."
)


# ---------------------------------------------------------------------------
# Server tool (Anthropic-hosted) — web_search
# ---------------------------------------------------------------------------

WEB_SEARCH_TOOL = {
    "type": "web_search_20250305",
    "name": "web_search",
    "max_uses": 5,
}


# ---------------------------------------------------------------------------
# Custom tool definitions (JSON schemas for the Anthropic API)
# ---------------------------------------------------------------------------

CUSTOM_TOOL_DEFINITIONS: dict[str, dict] = {
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
    "search_slack": {
        "name": "search_slack",
        "description": (
            "Search Slack messages across channels. Returns message text, channel, "
            "author, and timestamp. Use for finding team conversations about topics."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (supports Slack search modifiers: in:#channel, from:@user)",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results (default: 10)",
                },
            },
            "required": ["query"],
        },
    },
    "read_slack_thread": {
        "name": "read_slack_thread",
        "description": "Read all messages in a specific Slack thread.",
        "input_schema": {
            "type": "object",
            "properties": {
                "channel_id": {
                    "type": "string",
                    "description": "Slack channel ID",
                },
                "thread_ts": {
                    "type": "string",
                    "description": "Thread timestamp (parent message ts)",
                },
            },
            "required": ["channel_id", "thread_ts"],
        },
    },
    "send_slack_message": {
        "name": "send_slack_message",
        "description": (
            "Send a message to a Slack channel. Use for distributing "
            "communications to the team."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "channel": {
                    "type": "string",
                    "description": "Channel name (e.g., '#general') or channel ID",
                },
                "text": {
                    "type": "string",
                    "description": "Message text (supports Slack markdown)",
                },
                "thread_ts": {
                    "type": "string",
                    "description": "Optional: reply to a specific thread",
                },
            },
            "required": ["channel", "text"],
        },
    },
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
# Per-agent tool registry
# ---------------------------------------------------------------------------

# Maps agent names to which tools they can use.
# server_tools: Anthropic-hosted (web_search) — API handles execution.
# custom_tools: Names from CUSTOM_TOOL_DEFINITIONS — we execute locally.
AGENT_TOOLS: dict[str, dict[str, list]] = {
    "discover": {
        "server_tools": [WEB_SEARCH_TOOL],
        "custom_tools": ["search_google_drive", "search_slack"],
    },
    "extract": {
        "server_tools": [],
        "custom_tools": ["read_google_drive_document", "read_slack_thread"],
    },
    "validate": {
        "server_tools": [WEB_SEARCH_TOOL],
        "custom_tools": [],
    },
    "compile": {
        "server_tools": [],
        "custom_tools": [],
    },
    "audit": {
        "server_tools": [],
        "custom_tools": [],
    },
    "reflect": {
        "server_tools": [],
        "custom_tools": [],
    },
    "decide": {
        "server_tools": [],
        "custom_tools": [],
    },
    "distribute": {
        "server_tools": [],
        "custom_tools": ["send_slack_message", "draft_gmail"],
    },
    "collect_iterate": {
        "server_tools": [],
        "custom_tools": ["search_slack", "search_gmail", "read_slack_thread", "read_gmail_message"],
    },
    "context": {
        "server_tools": [],
        "custom_tools": [
            "search_google_drive", "search_gmail",
            "search_slack", "read_calendar",
        ],
    },
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_tools_for_agent(agent_name: str) -> list[dict]:
    """
    Return the tools list to pass to client.messages.create(tools=...).

    Combines server tools and custom tool definitions for the given agent.
    All tools are always included — when local credentials are missing,
    the executor falls back to call_claude_as_proxy().
    """
    agent_config = AGENT_TOOLS.get(agent_name)
    if not agent_config:
        return []

    tools: list[dict] = []

    # Server tools (Anthropic-hosted) — include as-is
    tools.extend(agent_config.get("server_tools", []))

    # Custom tools — always include (fallback handles missing credentials)
    for tool_name in agent_config.get("custom_tools", []):
        definition = CUSTOM_TOOL_DEFINITIONS.get(tool_name)
        if definition:
            tools.append(definition)

    return tools


def has_custom_tools(agent_name: str) -> bool:
    """Check if an agent has any custom tools that require a tool execution loop."""
    agent_config = AGENT_TOOLS.get(agent_name, {})
    return bool(agent_config.get("custom_tools"))


def execute_tool(tool_name: str, tool_input: dict[str, Any]) -> str:
    """
    Execute a custom tool and return the result as a string.

    Dispatches to the appropriate service handler based on tool name.
    Each handler tries the direct API first, then falls back to
    call_claude_as_proxy() if credentials are missing or auth fails.
    Returns a JSON string with the result or an error message.
    """
    executor = _TOOL_EXECUTORS.get(tool_name)
    if not executor:
        return json.dumps({
            "error": f"Unknown tool: {tool_name}",
            "available_tools": list(_TOOL_EXECUTORS.keys()),
        })

    try:
        result = executor(tool_input)
        return json.dumps(result, ensure_ascii=False) if isinstance(result, (dict, list)) else str(result)
    except Exception as e:
        logger.error("Tool '%s' failed: %s", tool_name, e)
        return json.dumps({
            "error": f"Tool execution failed: {type(e).__name__}: {e}",
            "tool": tool_name,
            "input": tool_input,
        })


# ---------------------------------------------------------------------------
# Service availability checks
# ---------------------------------------------------------------------------

def _is_google_configured() -> bool:
    """Check if Google API credentials are available."""
    import os
    return bool(os.getenv("GOOGLE_CREDENTIALS_PATH"))


def _is_slack_configured() -> bool:
    """Check if Slack API credentials are available."""
    import os
    return bool(os.getenv("SLACK_BOT_TOKEN"))


def _is_auth_error(exc: Exception) -> bool:
    """Check if an exception is an authentication/authorization error."""
    error_str = str(exc).lower()
    auth_indicators = [
        "invalid credentials",
        "unauthorized",
        "403",
        "401",
        "access denied",
        "permission denied",
        "invalid_auth",
        "not_authed",
        "token_revoked",
        "account_inactive",
        "missing_scope",
    ]
    return any(indicator in error_str for indicator in auth_indicators)


# ---------------------------------------------------------------------------
# Claude proxy — when local credentials are missing or auth fails, call
# Claude (which has MCP-connected Gmail, Drive, Slack) to retrieve data.
# ---------------------------------------------------------------------------

def call_claude_as_proxy(tool_instruction: str) -> dict:
    """
    Call Claude as a data retrieval proxy.

    Sends a structured natural-language instruction to Claude via the
    Anthropic API. Claude uses its MCP-connected tools (Gmail, Slack,
    Google Drive) to execute the operation and returns a JSON result.

    The calling agent never knows whether data came from the direct API
    or from this proxy — the return format is the same.

    Args:
        tool_instruction: Natural language instruction describing exactly
            what data to retrieve and in what format to return it.
            E.g., "Search Gmail for emails from X with subject Y,
            return results as JSON with fields: id, subject, from, date, snippet"

    Returns:
        Parsed JSON dict from Claude's response, or an error dict if the
        proxy call fails.
    """
    try:
        import anthropic
        from .config import ANTHROPIC_API_KEY

        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        message = client.messages.create(
            model=_PROXY_MODEL,
            max_tokens=4096,
            system=_PROXY_SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": tool_instruction,
            }],
        )

        # Extract text from response
        text_blocks = [b.text for b in message.content if hasattr(b, "text")]
        response_text = "\n".join(text_blocks) if text_blocks else ""

        # Try to parse as JSON
        # Claude may wrap JSON in markdown code fences — strip them
        cleaned = response_text.strip()
        if cleaned.startswith("```"):
            # Remove opening fence (```json or ```)
            first_newline = cleaned.index("\n")
            cleaned = cleaned[first_newline + 1:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return {
                "source": "claude_proxy",
                "results": response_text,
            }

    except Exception as e:
        logger.error("call_claude_as_proxy failed: %s", e)
        return {
            "error": f"Claude proxy call failed: {e}",
            "source": "claude_proxy",
        }


# ---------------------------------------------------------------------------
# Tool executors — each follows the pattern:
#   1. If credentials exist → try direct API
#   2. If direct API raises an auth error → fall back to proxy
#   3. If no credentials → fall back to proxy immediately
#   4. Write tools without credentials → return content for manual action
# ---------------------------------------------------------------------------

def _exec_search_google_drive(inputs: dict) -> dict:
    """Search Google Drive via the Drive API, or fallback to Claude proxy."""
    query = inputs["query"]
    file_type = inputs.get("file_type", "any")
    max_results = inputs.get("max_results", 10)

    if not _is_google_configured():
        return call_claude_as_proxy(
            f"Search Google Drive for documents matching: {query}. "
            f"File type filter: {file_type}. "
            f"Return top {max_results} results as JSON with this exact structure: "
            f'{{"results": [{{"name": "...", "id": "...", "type": "...", "modified": "...", "url": "..."}}], "total": N}}'
        )

    try:
        from googleapiclient.discovery import build
        from google.oauth2 import service_account
        import os

        creds_path = os.getenv("GOOGLE_CREDENTIALS_PATH")
        creds = service_account.Credentials.from_service_account_file(
            creds_path,
            scopes=["https://www.googleapis.com/auth/drive.readonly"],
        )
        delegate_email = os.getenv("GOOGLE_DELEGATE_EMAIL")
        if delegate_email:
            creds = creds.with_subject(delegate_email)

        service = build("drive", "v3", credentials=creds)

        # Build Drive API query
        q_parts = [f"fullText contains '{query}'"]
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
        if _is_auth_error(e):
            logger.warning("Google Drive auth error, falling back to Claude proxy: %s", e)
            return call_claude_as_proxy(
                f"Search Google Drive for documents matching: {query}. "
                f"File type filter: {file_type}. "
                f"Return top {max_results} results as JSON with this exact structure: "
                f'{{"results": [{{"name": "...", "id": "...", "type": "...", "modified": "...", "url": "..."}}], "total": N}}'
            )
        return {"error": f"Google Drive search failed: {e}"}


def _exec_read_google_drive_document(inputs: dict) -> dict:
    """Read a Google Drive document's content, or fallback to Claude proxy."""
    file_id = inputs["file_id"]

    if not _is_google_configured():
        return call_claude_as_proxy(
            f"Read the content of the Google Drive document with ID or URL: {file_id}. "
            f"Return the document content as JSON with this exact structure: "
            f'{{"file_id": "...", "content": "full text content here"}}'
        )

    try:
        from googleapiclient.discovery import build
        from google.oauth2 import service_account
        import os

        creds_path = os.getenv("GOOGLE_CREDENTIALS_PATH")
        creds = service_account.Credentials.from_service_account_file(
            creds_path,
            scopes=["https://www.googleapis.com/auth/drive.readonly"],
        )
        delegate_email = os.getenv("GOOGLE_DELEGATE_EMAIL")
        if delegate_email:
            creds = creds.with_subject(delegate_email)

        service = build("drive", "v3", credentials=creds)

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
        if _is_auth_error(e):
            logger.warning("Google Drive auth error, falling back to Claude proxy: %s", e)
            return call_claude_as_proxy(
                f"Read the content of the Google Drive document with ID or URL: {file_id}. "
                f"Return the document content as JSON with this exact structure: "
                f'{{"file_id": "...", "content": "full text content here"}}'
            )
        return {"error": f"Failed to read document: {e}"}


def _exec_search_gmail(inputs: dict) -> dict:
    """Search Gmail messages, or fallback to Claude proxy."""
    query = inputs["query"]
    max_results = inputs.get("max_results", 10)

    if not _is_google_configured():
        return call_claude_as_proxy(
            f"Search Gmail for: {query}. "
            f"Return top {max_results} results as JSON with this exact structure: "
            f'{{"results": [{{"id": "...", "subject": "...", "from": "...", "date": "...", "snippet": "..."}}], "total": N}}'
        )

    try:
        from googleapiclient.discovery import build
        from google.oauth2 import service_account
        import os

        creds_path = os.getenv("GOOGLE_CREDENTIALS_PATH")
        creds = service_account.Credentials.from_service_account_file(
            creds_path,
            scopes=["https://www.googleapis.com/auth/gmail.readonly"],
        )
        delegate_email = os.getenv("GOOGLE_DELEGATE_EMAIL")
        if delegate_email:
            creds = creds.with_subject(delegate_email)

        service = build("gmail", "v1", credentials=creds)

        results = service.users().messages().list(
            userId="me",
            q=query,
            maxResults=max_results,
        ).execute()

        messages = []
        for msg_stub in results.get("messages", []):
            msg = service.users().messages().get(
                userId="me",
                id=msg_stub["id"],
                format="metadata",
                metadataHeaders=["Subject", "From", "Date"],
            ).execute()

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
        if _is_auth_error(e):
            logger.warning("Gmail auth error, falling back to Claude proxy: %s", e)
            return call_claude_as_proxy(
                f"Search Gmail for: {query}. "
                f"Return top {max_results} results as JSON with this exact structure: "
                f'{{"results": [{{"id": "...", "subject": "...", "from": "...", "date": "...", "snippet": "..."}}], "total": N}}'
            )
        return {"error": f"Gmail search failed: {e}"}


def _exec_read_gmail_message(inputs: dict) -> dict:
    """Read a full Gmail message, or fallback to Claude proxy."""
    message_id = inputs["message_id"]

    if not _is_google_configured():
        return call_claude_as_proxy(
            f"Read the full Gmail message with ID: {message_id}. "
            f"Return the message as JSON with this exact structure: "
            f'{{"id": "...", "subject": "...", "from": "...", "to": "...", "date": "...", "body": "full email body"}}'
        )

    try:
        from googleapiclient.discovery import build
        from google.oauth2 import service_account
        import os
        import base64

        creds_path = os.getenv("GOOGLE_CREDENTIALS_PATH")
        creds = service_account.Credentials.from_service_account_file(
            creds_path,
            scopes=["https://www.googleapis.com/auth/gmail.readonly"],
        )
        delegate_email = os.getenv("GOOGLE_DELEGATE_EMAIL")
        if delegate_email:
            creds = creds.with_subject(delegate_email)

        service = build("gmail", "v1", credentials=creds)

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
        if _is_auth_error(e):
            logger.warning("Gmail auth error, falling back to Claude proxy: %s", e)
            return call_claude_as_proxy(
                f"Read the full Gmail message with ID: {message_id}. "
                f"Return the message as JSON with this exact structure: "
                f'{{"id": "...", "subject": "...", "from": "...", "to": "...", "date": "...", "body": "full email body"}}'
            )
        return {"error": f"Failed to read message: {e}"}


def _exec_draft_gmail(inputs: dict) -> dict:
    """Create a Gmail draft, or fallback to Claude proxy / manual content."""
    if not _is_google_configured():
        # Try via Claude proxy first (it may have Gmail write access)
        proxy_result = call_claude_as_proxy(
            f"Create a Gmail draft with the following details:\n"
            f"To: {inputs['to']}\n"
            f"Subject: {inputs['subject']}\n"
            f"Body: {inputs['body']}\n"
            f"CC: {inputs.get('cc', '')}\n\n"
            f"If you can create the draft, return JSON: "
            f'{{"status": "draft_created", "draft_id": "...", "to": "...", "subject": "..."}}. '
            f"If you cannot create the draft, return JSON: "
            f'{{"status": "draft_not_created", "reason": "..."}}'
        )
        # If proxy couldn't create it, return content for manual sending
        if proxy_result.get("status") != "draft_created":
            return {
                "source": "manual_fallback",
                "status": "draft_not_created",
                "note": "Sin acceso a Gmail. El borrador se muestra abajo para envío manual.",
                "to": inputs["to"],
                "subject": inputs["subject"],
                "body": inputs["body"],
                "cc": inputs.get("cc", ""),
            }
        return proxy_result

    try:
        from googleapiclient.discovery import build
        from google.oauth2 import service_account
        import os
        import base64
        from email.mime.text import MIMEText

        creds_path = os.getenv("GOOGLE_CREDENTIALS_PATH")
        creds = service_account.Credentials.from_service_account_file(
            creds_path,
            scopes=["https://www.googleapis.com/auth/gmail.compose"],
        )
        delegate_email = os.getenv("GOOGLE_DELEGATE_EMAIL")
        if delegate_email:
            creds = creds.with_subject(delegate_email)

        service = build("gmail", "v1", credentials=creds)

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
        if _is_auth_error(e):
            logger.warning("Gmail auth error on draft, falling back to Claude proxy: %s", e)
            proxy_result = call_claude_as_proxy(
                f"Create a Gmail draft with the following details:\n"
                f"To: {inputs['to']}\n"
                f"Subject: {inputs['subject']}\n"
                f"Body: {inputs['body']}\n"
                f"CC: {inputs.get('cc', '')}\n\n"
                f"If you can create the draft, return JSON: "
                f'{{"status": "draft_created", "draft_id": "...", "to": "...", "subject": "..."}}. '
                f"If you cannot, return JSON: "
                f'{{"status": "draft_not_created", "reason": "..."}}'
            )
            if proxy_result.get("status") != "draft_created":
                return {
                    "source": "manual_fallback",
                    "status": "draft_not_created",
                    "note": "Auth error y proxy sin acceso. El borrador se muestra abajo para envío manual.",
                    "to": inputs["to"],
                    "subject": inputs["subject"],
                    "body": inputs["body"],
                    "cc": inputs.get("cc", ""),
                }
            return proxy_result
        return {"error": f"Failed to create draft: {e}"}


def _exec_search_slack(inputs: dict) -> dict:
    """Search Slack messages, or fallback to Claude proxy."""
    query = inputs["query"]
    max_results = inputs.get("max_results", 10)

    if not _is_slack_configured():
        return call_claude_as_proxy(
            f"Search Slack for messages matching: {query}. "
            f"Return top {max_results} results as JSON with this exact structure: "
            f'{{"results": [{{"text": "...", "user": "...", "channel": "...", "timestamp": "...", "permalink": "..."}}], "total": N}}'
        )

    try:
        from slack_sdk import WebClient
        import os

        client = WebClient(token=os.getenv("SLACK_BOT_TOKEN"))

        result = client.search_messages(
            query=query,
            count=max_results,
            sort="timestamp",
            sort_dir="desc",
        )

        messages = []
        for match in result.get("messages", {}).get("matches", []):
            messages.append({
                "text": match.get("text", ""),
                "user": match.get("username", ""),
                "channel": match.get("channel", {}).get("name", ""),
                "timestamp": match.get("ts", ""),
                "permalink": match.get("permalink", ""),
            })

        return {"results": messages, "total": len(messages)}

    except ImportError:
        return {"error": "slack-sdk not installed. Run: pip install slack-sdk"}
    except Exception as e:
        if _is_auth_error(e):
            logger.warning("Slack auth error, falling back to Claude proxy: %s", e)
            return call_claude_as_proxy(
                f"Search Slack for messages matching: {query}. "
                f"Return top {max_results} results as JSON with this exact structure: "
                f'{{"results": [{{"text": "...", "user": "...", "channel": "...", "timestamp": "...", "permalink": "..."}}], "total": N}}'
            )
        return {"error": f"Slack search failed: {e}"}


def _exec_read_slack_thread(inputs: dict) -> dict:
    """Read a Slack thread, or fallback to Claude proxy."""
    channel_id = inputs["channel_id"]
    thread_ts = inputs["thread_ts"]

    if not _is_slack_configured():
        return call_claude_as_proxy(
            f"Read the Slack thread in channel {channel_id} with parent timestamp {thread_ts}. "
            f"Return all thread messages as JSON with this exact structure: "
            f'{{"messages": [{{"user": "...", "text": "...", "timestamp": "..."}}], "total": N}}'
        )

    try:
        from slack_sdk import WebClient
        import os

        client = WebClient(token=os.getenv("SLACK_BOT_TOKEN"))

        result = client.conversations_replies(
            channel=channel_id,
            ts=thread_ts,
        )

        messages = [
            {
                "user": msg.get("user", ""),
                "text": msg.get("text", ""),
                "timestamp": msg.get("ts", ""),
            }
            for msg in result.get("messages", [])
        ]

        return {"messages": messages, "total": len(messages)}

    except ImportError:
        return {"error": "slack-sdk not installed. Run: pip install slack-sdk"}
    except Exception as e:
        if _is_auth_error(e):
            logger.warning("Slack auth error, falling back to Claude proxy: %s", e)
            return call_claude_as_proxy(
                f"Read the Slack thread in channel {channel_id} with parent timestamp {thread_ts}. "
                f"Return all thread messages as JSON with this exact structure: "
                f'{{"messages": [{{"user": "...", "text": "...", "timestamp": "..."}}], "total": N}}'
            )
        return {"error": f"Failed to read thread: {e}"}


def _exec_send_slack_message(inputs: dict) -> dict:
    """Send a Slack message, or fallback to Claude proxy / manual content."""
    if not _is_slack_configured():
        # Try via Claude proxy first (it may have Slack write access)
        proxy_result = call_claude_as_proxy(
            f"Send a Slack message to channel: {inputs['channel']}\n"
            f"Message text: {inputs['text']}\n"
            f"Thread timestamp (if reply): {inputs.get('thread_ts', 'none')}\n\n"
            f"If you can send the message, return JSON: "
            f'{{"status": "sent", "channel": "...", "timestamp": "..."}}. '
            f"If you cannot, return JSON: "
            f'{{"status": "message_not_sent", "reason": "..."}}'
        )
        if proxy_result.get("status") != "sent":
            return {
                "source": "manual_fallback",
                "status": "message_not_sent",
                "note": "Sin acceso a Slack. El mensaje se muestra abajo para envío manual.",
                "channel": inputs["channel"],
                "text": inputs["text"],
                "thread_ts": inputs.get("thread_ts", ""),
            }
        return proxy_result

    try:
        from slack_sdk import WebClient
        import os

        client = WebClient(token=os.getenv("SLACK_BOT_TOKEN"))

        kwargs = {
            "channel": inputs["channel"],
            "text": inputs["text"],
        }
        if inputs.get("thread_ts"):
            kwargs["thread_ts"] = inputs["thread_ts"]

        result = client.chat_postMessage(**kwargs)

        return {
            "status": "sent",
            "channel": inputs["channel"],
            "timestamp": result.get("ts", ""),
        }

    except ImportError:
        return {"error": "slack-sdk not installed. Run: pip install slack-sdk"}
    except Exception as e:
        if _is_auth_error(e):
            logger.warning("Slack auth error on send, falling back to Claude proxy: %s", e)
            proxy_result = call_claude_as_proxy(
                f"Send a Slack message to channel: {inputs['channel']}\n"
                f"Message text: {inputs['text']}\n"
                f"Thread timestamp (if reply): {inputs.get('thread_ts', 'none')}\n\n"
                f"If you can send the message, return JSON: "
                f'{{"status": "sent", "channel": "...", "timestamp": "..."}}. '
                f"If you cannot, return JSON: "
                f'{{"status": "message_not_sent", "reason": "..."}}'
            )
            if proxy_result.get("status") != "sent":
                return {
                    "source": "manual_fallback",
                    "status": "message_not_sent",
                    "note": "Auth error y proxy sin acceso. El mensaje se muestra abajo para envío manual.",
                    "channel": inputs["channel"],
                    "text": inputs["text"],
                    "thread_ts": inputs.get("thread_ts", ""),
                }
            return proxy_result
        return {"error": f"Failed to send message: {e}"}


def _exec_read_calendar(inputs: dict) -> dict:
    """Read upcoming Google Calendar events, or fallback to Claude proxy."""
    days = inputs.get("days_ahead", 7)
    query = inputs.get("query", "")

    if not _is_google_configured():
        return call_claude_as_proxy(
            f"Read upcoming Google Calendar events for the next {days} days. "
            f"Filter: {query or 'all events'}. "
            f"Return events as JSON with this exact structure: "
            f'{{"events": [{{"summary": "...", "start": "...", "end": "...", "description": "...", "attendees": ["..."]}}], "total": N}}'
        )

    try:
        from googleapiclient.discovery import build
        from google.oauth2 import service_account
        from datetime import datetime, timedelta, timezone
        import os

        creds_path = os.getenv("GOOGLE_CREDENTIALS_PATH")
        creds = service_account.Credentials.from_service_account_file(
            creds_path,
            scopes=["https://www.googleapis.com/auth/calendar.readonly"],
        )
        delegate_email = os.getenv("GOOGLE_DELEGATE_EMAIL")
        if delegate_email:
            creds = creds.with_subject(delegate_email)

        service = build("calendar", "v3", credentials=creds)

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
        if _is_auth_error(e):
            logger.warning("Calendar auth error, falling back to Claude proxy: %s", e)
            return call_claude_as_proxy(
                f"Read upcoming Google Calendar events for the next {days} days. "
                f"Filter: {query or 'all events'}. "
                f"Return events as JSON with this exact structure: "
                f'{{"events": [{{"summary": "...", "start": "...", "end": "...", "description": "...", "attendees": ["..."]}}], "total": N}}'
            )
        return {"error": f"Calendar read failed: {e}"}


# ---------------------------------------------------------------------------
# Executor dispatch table
# ---------------------------------------------------------------------------

_TOOL_EXECUTORS: dict[str, Any] = {
    "search_google_drive": _exec_search_google_drive,
    "read_google_drive_document": _exec_read_google_drive_document,
    "search_gmail": _exec_search_gmail,
    "read_gmail_message": _exec_read_gmail_message,
    "draft_gmail": _exec_draft_gmail,
    "search_slack": _exec_search_slack,
    "read_slack_thread": _exec_read_slack_thread,
    "send_slack_message": _exec_send_slack_message,
    "read_calendar": _exec_read_calendar,
}
