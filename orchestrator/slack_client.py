"""
Slack API client — search messages in the workspace.

Uses a Bot Token (xoxb-…) which must have the ``search:read`` scope.
All functions return an empty list on error so the caller can
degrade gracefully.
"""

import logging

from .config import SLACK_BOT_TOKEN

logger = logging.getLogger(__name__)

# Relevant Cordada Slack channels (searched by default when no channels specified)
DEFAULT_CHANNELS = [
    "inversiones",
    "pipeline",
    "deals",
    "operaciones",
    "nav",
    "legal",
    "directorio",
    "compliance",
]


def is_slack_configured() -> bool:
    """Return True if the Slack bot token is present."""
    return bool(SLACK_BOT_TOKEN)


def search_slack(
    query: str,
    channels: list[str] | None = None,
    max_results: int = 5,
) -> list[dict]:
    """Search Slack messages matching *query*.

    Args:
        query: Search text (Slack search syntax supported).
        channels: Optional list of channel names to restrict the search.
                  Defaults to ``DEFAULT_CHANNELS``.
        max_results: Maximum number of results to return.

    Returns:
        List of dicts with keys: text, channel, user, date, permalink
    """
    if not is_slack_configured():
        return []
    try:
        from slack_sdk import WebClient

        client = WebClient(token=SLACK_BOT_TOKEN)

        # Build channel-scoped query if channels are specified
        search_channels = channels or DEFAULT_CHANNELS
        channel_filter = " ".join(f"in:{ch}" for ch in search_channels)
        full_query = f"{query} {channel_filter}"

        resp = client.search_messages(query=full_query, count=max_results, sort="timestamp")

        results = []
        for match in resp.get("messages", {}).get("matches", []):
            results.append({
                "text": (match.get("text") or "")[:300],
                "channel": match.get("channel", {}).get("name", ""),
                "user": match.get("username", ""),
                "date": match.get("ts", ""),
                "permalink": match.get("permalink", ""),
            })
        return results
    except Exception:
        logger.exception("Slack search failed for query: %s", query)
        return []
