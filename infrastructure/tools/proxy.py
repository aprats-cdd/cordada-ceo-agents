"""
Claude proxy — call Claude with MCP tools when local credentials are missing.

When local Google/Slack credentials are unavailable or auth fails, this module
sends structured instructions to Claude (which has MCP-connected Gmail, Drive,
Slack) to retrieve data. The calling agent never knows the difference.

Security boundary: write operations (draft_gmail, send_slack) are NEVER proxied.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)

# Model used for proxy calls (Claude with MCP tool access)
PROXY_MODEL = "claude-sonnet-4-20250514"

_PROXY_SYSTEM_PROMPT = (
    "You are a data retrieval proxy. "
    "Execute the requested operation using your available tools (Gmail, Slack, Google Drive). "
    "Return ONLY a JSON object with the results. No explanations."
)

# Shared Anthropic client for proxy calls (reuse TCP connection)
_proxy_client: Any = None
_proxy_client_lock = threading.Lock()


def _get_proxy_client() -> Any:
    """Get or create the shared Anthropic client for proxy calls."""
    global _proxy_client
    if _proxy_client is None:
        with _proxy_client_lock:
            if _proxy_client is None:  # double-check locking
                import anthropic
                from orchestrator.config import ANTHROPIC_API_KEY
                _proxy_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _proxy_client


def call_claude_as_proxy(tool_instruction: str) -> dict:
    """
    Call Claude as a data retrieval proxy.

    Sends a structured natural-language instruction to Claude via the
    Anthropic API. Claude uses its MCP-connected tools (Gmail, Slack,
    Google Drive) to execute the operation and returns a JSON result.

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
            model=PROXY_MODEL,
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
