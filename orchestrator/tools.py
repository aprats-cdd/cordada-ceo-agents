"""
Tool system — backward-compatible facade.

The canonical implementation now lives in ``infrastructure.tools``,
split by service (drive, gmail, slack, calendar, proxy).

This module re-exports the full public API so existing imports
continue to work:

    from orchestrator.tools import get_tools_for_agent, execute_tool
    from orchestrator.tools import call_claude_as_proxy
"""

from infrastructure.tools import (  # noqa: F401
    # Public API
    get_tools_for_agent,
    has_custom_tools,
    execute_tool,
    call_claude_as_proxy,
    # Constants
    WEB_SEARCH_TOOL,
    CUSTOM_TOOL_DEFINITIONS,
    AGENT_TOOLS,
    _TOOL_EXECUTORS,
    _PROXY_MODEL,
    # Shared utilities (test compat)
    _is_google_configured,
    _is_slack_configured,
    _is_auth_error,
    _run_with_timeout,
    _proxy_instruction,
    # Individual executors (test compat)
    _exec_search_google_drive,
    _exec_read_google_drive_document,
    _exec_search_gmail,
    _exec_read_gmail_message,
    _exec_draft_gmail,
    _exec_search_slack,
    _exec_read_slack_thread,
    _exec_send_slack_message,
    _exec_read_calendar,
    # Helpers (test compat)
    _escape_drive_query,
    # Proxy internal (test compat)
    _get_proxy_client,
)

__all__ = [
    "get_tools_for_agent",
    "has_custom_tools",
    "execute_tool",
    "call_claude_as_proxy",
    "WEB_SEARCH_TOOL",
    "CUSTOM_TOOL_DEFINITIONS",
    "AGENT_TOOLS",
]
