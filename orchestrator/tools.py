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
  - Credentials available -> direct API call (fast, precise)
  - Credentials missing OR auth error -> call_claude_as_proxy() sends a
    structured prompt to Claude (claude-sonnet-4-20250514), which uses
    its MCP-connected tools (Gmail, Drive, Slack) to retrieve the data
  - Write tools (draft_gmail, send_slack) without credentials -> return the
    content for manual sending (NEVER proxied — security boundary)
  - The calling agent never knows whether data came from direct API or proxy
"""

from __future__ import annotations

import json
import logging
import os
import threading
from functools import lru_cache
from typing import Any

logger = logging.getLogger(__name__)

# Model used for proxy calls (Claude with MCP tool access)
_PROXY_MODEL = "claude-sonnet-4-20250514"

_PROXY_SYSTEM_PROMPT = (
    "You are a data retrieval proxy. "
    "Execute the requested operation using your available tools (Gmail, Slack, Google Drive). "
    "Return ONLY a JSON object with the results. No explanations."
)

# Timeout for tool execution (seconds)
_TOOL_TIMEOUT_SECONDS = 30


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

    Enforces a timeout of _TOOL_TIMEOUT_SECONDS to prevent hangs.
    """
    executor = _TOOL_EXECUTORS.get(tool_name)
    if not executor:
        return json.dumps({
            "error": f"Unknown tool: {tool_name}",
            "available_tools": list(_TOOL_EXECUTORS.keys()),
        })

    try:
        result = _run_with_timeout(executor, tool_input, timeout=_TOOL_TIMEOUT_SECONDS)
        return json.dumps(result, ensure_ascii=False) if isinstance(result, (dict, list)) else str(result)
    except TimeoutError:
        logger.error("Tool '%s' timed out after %ds", tool_name, _TOOL_TIMEOUT_SECONDS)
        return json.dumps({
            "error": f"Tool execution timed out after {_TOOL_TIMEOUT_SECONDS}s",
            "tool": tool_name,
        })
    except Exception as e:
        logger.error("Tool '%s' failed: %s", tool_name, e)
        return json.dumps({
            "error": f"Tool execution failed: {type(e).__name__}: {e}",
            "tool": tool_name,
            "input": tool_input,
        })


# ---------------------------------------------------------------------------
# Timeout wrapper (Fix #8)
# ---------------------------------------------------------------------------

def _run_with_timeout(func, inputs: dict, timeout: int) -> dict:
    """Run a tool executor with a timeout. Raises TimeoutError if exceeded."""
    result_holder: list = []
    error_holder: list = []

    def target():
        try:
            result_holder.append(func(inputs))
        except Exception as e:
            error_holder.append(e)

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(timeout=timeout)

    if thread.is_alive():
        raise TimeoutError(f"Tool execution exceeded {timeout}s")
    if error_holder:
        raise error_holder[0]
    if result_holder:
        return result_holder[0]
    raise RuntimeError("Tool returned no result")


# ---------------------------------------------------------------------------
# Service availability checks (cached at first call)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _is_google_configured() -> bool:
    """Check if Google API credentials are available."""
    return bool(os.getenv("GOOGLE_CREDENTIALS_PATH"))


@lru_cache(maxsize=1)
def _is_slack_configured() -> bool:
    """Check if Slack API credentials are available."""
    return bool(os.getenv("SLACK_BOT_TOKEN"))


def _is_auth_error(exc: Exception) -> bool:
    """
    Check if an exception is an authentication/authorization error.

    Uses a multi-strategy approach:
      1. Check known exception types from Google/Slack SDKs
      2. Check HTTP status codes on response objects
      3. Fall back to string matching for unknown exception types
    """
    # Strategy 1: Check known exception types
    exc_type_name = type(exc).__name__
    auth_exception_types = {
        "RefreshError",          # google.auth.exceptions.RefreshError
        "TransportError",        # google.auth.transport — often auth
        "SlackApiError",         # May carry auth-related response
    }

    # Strategy 2: Check HTTP status codes if available
    status_code = None
    if hasattr(exc, "resp") and hasattr(exc.resp, "status"):
        status_code = exc.resp.status  # Google API errors
    elif hasattr(exc, "response") and hasattr(exc.response, "status_code"):
        status_code = exc.response.status_code  # Slack SDK errors

    if status_code in (401, 403):
        return True

    # Strategy 3: String matching as fallback
    error_str = str(exc).lower()
    auth_indicators = [
        "invalid credentials",
        "unauthorized",
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
# Google service factory (Fix #2 — DRY: one place for credential loading)
# ---------------------------------------------------------------------------

_google_service_cache: dict[str, Any] = {}


def _get_google_service(api: str, version: str, scopes: list[str]) -> Any:
    """
    Build and cache a Google API service client.

    Args:
        api: API name (e.g., "drive", "gmail", "calendar")
        version: API version (e.g., "v3", "v1")
        scopes: OAuth scopes needed

    Returns:
        Google API service resource object

    Raises:
        ImportError: If google-api-python-client is not installed
        RuntimeError: If credentials are not configured
    """
    cache_key = f"{api}:{version}:{','.join(sorted(scopes))}"
    if cache_key in _google_service_cache:
        return _google_service_cache[cache_key]

    from googleapiclient.discovery import build
    from google.oauth2 import service_account

    creds_path = os.getenv("GOOGLE_CREDENTIALS_PATH")
    if not creds_path:
        raise RuntimeError("GOOGLE_CREDENTIALS_PATH not set")

    creds = service_account.Credentials.from_service_account_file(
        creds_path, scopes=scopes,
    )
    delegate_email = os.getenv("GOOGLE_DELEGATE_EMAIL")
    if delegate_email:
        creds = creds.with_subject(delegate_email)

    service = build(api, version, credentials=creds)
    _google_service_cache[cache_key] = service
    return service


def _get_slack_client() -> Any:
    """Build a Slack WebClient. Raises ImportError if slack-sdk not installed."""
    from slack_sdk import WebClient
    return WebClient(token=os.getenv("SLACK_BOT_TOKEN"))


# ---------------------------------------------------------------------------
# Proxy instruction builder (DRY for JSON schema instructions)
# ---------------------------------------------------------------------------

def _proxy_instruction(action: str, params: str, schema: str) -> str:
    """Build a structured proxy instruction with consistent format."""
    return (
        f"{action}. {params}"
        f"Return results as JSON with this exact structure: {schema}"
    )


# ---------------------------------------------------------------------------
# Claude proxy — when local credentials are missing or auth fails, call
# Claude (which has MCP-connected Gmail, Drive, Slack) to retrieve data.
# ---------------------------------------------------------------------------

# Shared Anthropic client for proxy calls (Fix #5 — reuse TCP connection)
_proxy_client: Any = None
_proxy_client_lock = threading.Lock()


def _get_proxy_client() -> Any:
    """Get or create the shared Anthropic client for proxy calls."""
    global _proxy_client
    if _proxy_client is None:
        with _proxy_client_lock:
            if _proxy_client is None:  # double-check locking
                import anthropic
                from .config import ANTHROPIC_API_KEY
                _proxy_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _proxy_client


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

    Returns:
        Parsed JSON dict from Claude's response, or an error dict if the
        proxy call fails.
    """
    try:
        client = _get_proxy_client()

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
#   1. If credentials exist -> try direct API
#   2. If direct API raises an auth error -> fall back to proxy
#   3. If no credentials -> fall back to proxy immediately
#   4. Write tools without credentials -> return content for manual action
#      (NEVER proxied — write operations are a security boundary)
# ---------------------------------------------------------------------------

def _escape_drive_query(text: str) -> str:
    """Escape single quotes in a Drive API query value (Fix #3)."""
    return text.replace("\\", "\\\\").replace("'", "\\'")


def _exec_search_google_drive(inputs: dict) -> dict:
    """Search Google Drive via the Drive API, or fallback to Claude proxy."""
    query = inputs["query"]
    file_type = inputs.get("file_type", "any")
    max_results = inputs.get("max_results", 10)

    proxy_schema = '{"results": [{"name": "...", "id": "...", "type": "...", "modified": "...", "url": "..."}], "total": N}'

    if not _is_google_configured():
        return call_claude_as_proxy(
            _proxy_instruction(
                f"Search Google Drive for documents matching: {query}",
                f"File type filter: {file_type}. Return top {max_results} results. ",
                proxy_schema,
            )
        )

    try:
        service = _get_google_service(
            "drive", "v3", ["https://www.googleapis.com/auth/drive.readonly"],
        )

        # Build Drive API query (Fix #3: escape single quotes)
        escaped_query = _escape_drive_query(query)
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
        if _is_auth_error(e):
            logger.warning("Google Drive auth error, falling back to Claude proxy: %s", e)
            return call_claude_as_proxy(
                _proxy_instruction(
                    f"Search Google Drive for documents matching: {query}",
                    f"File type filter: {file_type}. Return top {max_results} results. ",
                    proxy_schema,
                )
            )
        return {"error": f"Google Drive search failed: {e}"}


def _exec_read_google_drive_document(inputs: dict) -> dict:
    """Read a Google Drive document's content, or fallback to Claude proxy."""
    file_id = inputs["file_id"]

    proxy_schema = '{"file_id": "...", "content": "full text content here"}'

    if not _is_google_configured():
        return call_claude_as_proxy(
            _proxy_instruction(
                f"Read the content of the Google Drive document with ID or URL: {file_id}",
                "", proxy_schema,
            )
        )

    try:
        service = _get_google_service(
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
        if _is_auth_error(e):
            logger.warning("Google Drive auth error, falling back to Claude proxy: %s", e)
            return call_claude_as_proxy(
                _proxy_instruction(
                    f"Read the content of the Google Drive document with ID or URL: {file_id}",
                    "", proxy_schema,
                )
            )
        return {"error": f"Failed to read document: {e}"}


def _exec_search_gmail(inputs: dict) -> dict:
    """Search Gmail messages, or fallback to Claude proxy."""
    query = inputs["query"]
    max_results = inputs.get("max_results", 10)

    proxy_schema = '{"results": [{"id": "...", "subject": "...", "from": "...", "date": "...", "snippet": "..."}], "total": N}'

    if not _is_google_configured():
        return call_claude_as_proxy(
            _proxy_instruction(
                f"Search Gmail for: {query}",
                f"Return top {max_results} results. ",
                proxy_schema,
            )
        )

    try:
        service = _get_google_service(
            "gmail", "v1", ["https://www.googleapis.com/auth/gmail.readonly"],
        )

        # Fix #14: Use batch-compatible approach — request list with message
        # IDs, then use a single batch request to fetch metadata for all.
        list_result = service.users().messages().list(
            userId="me",
            q=query,
            maxResults=max_results,
        ).execute()

        msg_stubs = list_result.get("messages", [])
        if not msg_stubs:
            return {"results": [], "total": 0}

        # Batch fetch all message metadata in one round-trip
        messages = []
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
        if _is_auth_error(e):
            logger.warning("Gmail auth error, falling back to Claude proxy: %s", e)
            return call_claude_as_proxy(
                _proxy_instruction(
                    f"Search Gmail for: {query}",
                    f"Return top {max_results} results. ",
                    proxy_schema,
                )
            )
        return {"error": f"Gmail search failed: {e}"}


def _exec_read_gmail_message(inputs: dict) -> dict:
    """Read a full Gmail message, or fallback to Claude proxy."""
    message_id = inputs["message_id"]

    proxy_schema = '{"id": "...", "subject": "...", "from": "...", "to": "...", "date": "...", "body": "full email body"}'

    if not _is_google_configured():
        return call_claude_as_proxy(
            _proxy_instruction(
                f"Read the full Gmail message with ID: {message_id}",
                "", proxy_schema,
            )
        )

    try:
        import base64

        service = _get_google_service(
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
        if _is_auth_error(e):
            logger.warning("Gmail auth error, falling back to Claude proxy: %s", e)
            return call_claude_as_proxy(
                _proxy_instruction(
                    f"Read the full Gmail message with ID: {message_id}",
                    "", proxy_schema,
                )
            )
        return {"error": f"Failed to read message: {e}"}


def _exec_draft_gmail(inputs: dict) -> dict:
    """
    Create a Gmail draft, or return content for manual action.

    Security: Write operations are NEVER proxied. Without direct credentials,
    the content is returned as manual_fallback for the CEO to send.
    """
    # Fix #6: Write operations without credentials -> always manual fallback
    if not _is_google_configured():
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

        service = _get_google_service(
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
        if _is_auth_error(e):
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


def _exec_search_slack(inputs: dict) -> dict:
    """Search Slack messages, or fallback to Claude proxy."""
    query = inputs["query"]
    max_results = inputs.get("max_results", 10)

    proxy_schema = '{"results": [{"text": "...", "user": "...", "channel": "...", "timestamp": "...", "permalink": "..."}], "total": N}'

    if not _is_slack_configured():
        return call_claude_as_proxy(
            _proxy_instruction(
                f"Search Slack for messages matching: {query}",
                f"Return top {max_results} results. ",
                proxy_schema,
            )
        )

    try:
        client = _get_slack_client()

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
                _proxy_instruction(
                    f"Search Slack for messages matching: {query}",
                    f"Return top {max_results} results. ",
                    proxy_schema,
                )
            )
        return {"error": f"Slack search failed: {e}"}


def _exec_read_slack_thread(inputs: dict) -> dict:
    """Read a Slack thread, or fallback to Claude proxy."""
    channel_id = inputs["channel_id"]
    thread_ts = inputs["thread_ts"]

    proxy_schema = '{"messages": [{"user": "...", "text": "...", "timestamp": "..."}], "total": N}'

    if not _is_slack_configured():
        return call_claude_as_proxy(
            _proxy_instruction(
                f"Read the Slack thread in channel {channel_id} with parent timestamp {thread_ts}",
                "", proxy_schema,
            )
        )

    try:
        client = _get_slack_client()

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
                _proxy_instruction(
                    f"Read the Slack thread in channel {channel_id} with parent timestamp {thread_ts}",
                    "", proxy_schema,
                )
            )
        return {"error": f"Failed to read thread: {e}"}


def _exec_send_slack_message(inputs: dict) -> dict:
    """
    Send a Slack message, or return content for manual action.

    Security: Write operations are NEVER proxied. Without direct credentials,
    the content is returned as manual_fallback for the CEO to send.
    """
    # Fix #6: Write operations without credentials -> always manual fallback
    if not _is_slack_configured():
        return {
            "source": "manual_fallback",
            "status": "message_not_sent",
            "note": "Sin acceso a Slack. El mensaje se muestra abajo para envio manual.",
            "channel": inputs["channel"],
            "text": inputs["text"],
            "thread_ts": inputs.get("thread_ts", ""),
        }

    try:
        client = _get_slack_client()

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
            logger.warning("Slack auth error on send — returning manual fallback: %s", e)
            return {
                "source": "manual_fallback",
                "status": "message_not_sent",
                "note": "Auth error. El mensaje se muestra abajo para envio manual.",
                "channel": inputs["channel"],
                "text": inputs["text"],
                "thread_ts": inputs.get("thread_ts", ""),
            }
        return {"error": f"Failed to send message: {e}"}


def _exec_read_calendar(inputs: dict) -> dict:
    """Read upcoming Google Calendar events, or fallback to Claude proxy."""
    days = inputs.get("days_ahead", 7)
    query = inputs.get("query", "")

    proxy_schema = '{"events": [{"summary": "...", "start": "...", "end": "...", "description": "...", "attendees": ["..."]}], "total": N}'

    if not _is_google_configured():
        return call_claude_as_proxy(
            _proxy_instruction(
                f"Read upcoming Google Calendar events for the next {days} days",
                f"Filter: {query or 'all events'}. ",
                proxy_schema,
            )
        )

    try:
        from datetime import datetime, timedelta, timezone

        service = _get_google_service(
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
        if _is_auth_error(e):
            logger.warning("Calendar auth error, falling back to Claude proxy: %s", e)
            return call_claude_as_proxy(
                _proxy_instruction(
                    f"Read upcoming Google Calendar events for the next {days} days",
                    f"Filter: {query or 'all events'}. ",
                    proxy_schema,
                )
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
