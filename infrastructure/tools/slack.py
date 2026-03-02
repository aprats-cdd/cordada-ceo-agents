"""
Slack tool executors.

Provides:
  - search_slack: Search Slack messages
  - read_slack_thread: Read a Slack thread
  - send_slack_message: Send a Slack message (NEVER proxied — security boundary)

Each read executor tries the direct API first, then falls back to Claude proxy.
Write operations return manual_fallback when credentials are missing.
"""

from __future__ import annotations

import logging
from typing import Any

from ._shared import (
    is_slack_configured,
    is_auth_error,
    get_slack_client,
    proxy_instruction,
)
from .proxy import call_claude_as_proxy

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool definitions (JSON schemas for Anthropic API)
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS: dict[str, dict] = {
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
}


# ---------------------------------------------------------------------------
# Executors
# ---------------------------------------------------------------------------

def exec_search_slack(inputs: dict) -> dict:
    """Search Slack messages, or fallback to Claude proxy."""
    query = inputs["query"]
    max_results = inputs.get("max_results", 10)

    proxy_schema = '{"results": [{"text": "...", "user": "...", "channel": "...", "timestamp": "...", "permalink": "..."}], "total": N}'

    if not is_slack_configured():
        return call_claude_as_proxy(
            proxy_instruction(
                f"Search Slack for messages matching: {query}",
                f"Return top {max_results} results. ",
                proxy_schema,
            )
        )

    try:
        client = get_slack_client()

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
        if is_auth_error(e):
            logger.warning("Slack auth error, falling back to Claude proxy: %s", e)
            return call_claude_as_proxy(
                proxy_instruction(
                    f"Search Slack for messages matching: {query}",
                    f"Return top {max_results} results. ",
                    proxy_schema,
                )
            )
        return {"error": f"Slack search failed: {e}"}


def exec_read_slack_thread(inputs: dict) -> dict:
    """Read a Slack thread, or fallback to Claude proxy."""
    channel_id = inputs["channel_id"]
    thread_ts = inputs["thread_ts"]

    proxy_schema = '{"messages": [{"user": "...", "text": "...", "timestamp": "..."}], "total": N}'

    if not is_slack_configured():
        return call_claude_as_proxy(
            proxy_instruction(
                f"Read the Slack thread in channel {channel_id} with parent timestamp {thread_ts}",
                "", proxy_schema,
            )
        )

    try:
        client = get_slack_client()

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
        if is_auth_error(e):
            logger.warning("Slack auth error, falling back to Claude proxy: %s", e)
            return call_claude_as_proxy(
                proxy_instruction(
                    f"Read the Slack thread in channel {channel_id} with parent timestamp {thread_ts}",
                    "", proxy_schema,
                )
            )
        return {"error": f"Failed to read thread: {e}"}


def exec_send_slack_message(inputs: dict) -> dict:
    """
    Send a Slack message, or return content for manual action.

    Security: Write operations are NEVER proxied. Without direct credentials,
    the content is returned as manual_fallback for the CEO to send.
    """
    if not is_slack_configured():
        return {
            "source": "manual_fallback",
            "status": "message_not_sent",
            "note": "Sin acceso a Slack. El mensaje se muestra abajo para envio manual.",
            "channel": inputs["channel"],
            "text": inputs["text"],
            "thread_ts": inputs.get("thread_ts", ""),
        }

    try:
        client = get_slack_client()

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
        if is_auth_error(e):
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


# ---------------------------------------------------------------------------
# Executor dispatch (tool_name -> function)
# ---------------------------------------------------------------------------

EXECUTORS: dict[str, Any] = {
    "search_slack": exec_search_slack,
    "read_slack_thread": exec_read_slack_thread,
    "send_slack_message": exec_send_slack_message,
}
