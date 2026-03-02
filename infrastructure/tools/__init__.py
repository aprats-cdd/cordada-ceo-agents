"""
Infrastructure tools — unified facade.

Assembles tool definitions, per-agent registry, and executors from
service-specific modules (drive, gmail, slack, calendar, proxy).

Public API (backward compatible with orchestrator.tools):
  - get_tools_for_agent(agent_name) -> list[dict]
  - has_custom_tools(agent_name) -> bool
  - execute_tool(tool_name, tool_input) -> str
  - call_claude_as_proxy(instruction) -> dict

Internal names are also re-exported for test access.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from . import drive, gmail, slack, calendar
from .proxy import call_claude_as_proxy
from ._shared import (
    run_with_timeout,
    is_google_configured,
    is_slack_configured,
    is_auth_error,
    proxy_instruction,
)

logger = logging.getLogger(__name__)

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
# Aggregate tool definitions from all service modules
# ---------------------------------------------------------------------------

CUSTOM_TOOL_DEFINITIONS: dict[str, dict] = {}
CUSTOM_TOOL_DEFINITIONS.update(drive.TOOL_DEFINITIONS)
CUSTOM_TOOL_DEFINITIONS.update(gmail.TOOL_DEFINITIONS)
CUSTOM_TOOL_DEFINITIONS.update(slack.TOOL_DEFINITIONS)
CUSTOM_TOOL_DEFINITIONS.update(calendar.TOOL_DEFINITIONS)


# ---------------------------------------------------------------------------
# Aggregate executor dispatch table
# ---------------------------------------------------------------------------

_TOOL_EXECUTORS: dict[str, Any] = {}
_TOOL_EXECUTORS.update(drive.EXECUTORS)
_TOOL_EXECUTORS.update(gmail.EXECUTORS)
_TOOL_EXECUTORS.update(slack.EXECUTORS)
_TOOL_EXECUTORS.update(calendar.EXECUTORS)


# ---------------------------------------------------------------------------
# Per-agent tool registry
# ---------------------------------------------------------------------------

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
    """
    agent_config = AGENT_TOOLS.get(agent_name)
    if not agent_config:
        return []

    tools: list[dict] = []
    tools.extend(agent_config.get("server_tools", []))

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
    Enforces a timeout of _TOOL_TIMEOUT_SECONDS to prevent hangs.
    """
    executor = _TOOL_EXECUTORS.get(tool_name)
    if not executor:
        return json.dumps({
            "error": f"Unknown tool: {tool_name}",
            "available_tools": list(_TOOL_EXECUTORS.keys()),
        })

    try:
        result = run_with_timeout(executor, tool_input, timeout=_TOOL_TIMEOUT_SECONDS)
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
# Re-export internals for backward compatibility and testing
# ---------------------------------------------------------------------------

# Shared utilities (prefixed with _ for compat with old tests)
_is_google_configured = is_google_configured
_is_slack_configured = is_slack_configured
_is_auth_error = is_auth_error
_run_with_timeout = run_with_timeout
_proxy_instruction = proxy_instruction
_PROXY_MODEL = "claude-sonnet-4-20250514"

# Individual executors (prefixed with _ for compat with old tests)
_exec_search_google_drive = drive.exec_search_google_drive
_exec_read_google_drive_document = drive.exec_read_google_drive_document
_exec_search_gmail = gmail.exec_search_gmail
_exec_read_gmail_message = gmail.exec_read_gmail_message
_exec_draft_gmail = gmail.exec_draft_gmail
_exec_search_slack = slack.exec_search_slack
_exec_read_slack_thread = slack.exec_read_slack_thread
_exec_send_slack_message = slack.exec_send_slack_message
_exec_read_calendar = calendar.exec_read_calendar

# Drive helpers
_escape_drive_query = drive.escape_drive_query

# Proxy internal (re-exported for test patching compat)
from .proxy import _get_proxy_client  # noqa: F401
