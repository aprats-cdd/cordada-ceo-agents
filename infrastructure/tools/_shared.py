"""
Shared infrastructure utilities for tool executors.

Contains:
  - Timeout wrapper (thread-based)
  - Auth error detection (multi-strategy)
  - Google API service factory (cached)
  - Slack client factory
  - Proxy instruction builder
  - Service availability checks
"""

from __future__ import annotations

import logging
import os
import threading
from functools import lru_cache
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Timeout wrapper
# ---------------------------------------------------------------------------

def run_with_timeout(func, inputs: dict, timeout: int) -> dict:
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
def is_google_configured() -> bool:
    """Check if Google API credentials are available."""
    return bool(os.getenv("GOOGLE_CREDENTIALS_PATH"))


@lru_cache(maxsize=1)
def is_slack_configured() -> bool:
    """Check if Slack API credentials are available."""
    return bool(os.getenv("SLACK_BOT_TOKEN"))


# ---------------------------------------------------------------------------
# Auth error detection
# ---------------------------------------------------------------------------

def is_auth_error(exc: Exception) -> bool:
    """
    Check if an exception is an authentication/authorization error.

    Uses a multi-strategy approach:
      1. Check HTTP status codes on response objects
      2. Fall back to string matching for unknown exception types
    """
    # Strategy 1: Check HTTP status codes if available
    status_code = None
    if hasattr(exc, "resp") and hasattr(exc.resp, "status"):
        status_code = exc.resp.status  # Google API errors
    elif hasattr(exc, "response") and hasattr(exc.response, "status_code"):
        status_code = exc.response.status_code  # Slack SDK errors

    if status_code in (401, 403):
        return True

    # Strategy 2: String matching as fallback
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
# Google service factory (cached)
# ---------------------------------------------------------------------------

_google_service_cache: dict[str, Any] = {}


def get_google_service(api: str, version: str, scopes: list[str]) -> Any:
    """
    Build and cache a Google API service client.

    Args:
        api: API name (e.g., "drive", "gmail", "calendar")
        version: API version (e.g., "v3", "v1")
        scopes: OAuth scopes needed

    Returns:
        Google API service resource object
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


# ---------------------------------------------------------------------------
# Slack client factory
# ---------------------------------------------------------------------------

def get_slack_client() -> Any:
    """Build a Slack WebClient. Raises ImportError if slack-sdk not installed."""
    from slack_sdk import WebClient
    return WebClient(token=os.getenv("SLACK_BOT_TOKEN"))


# ---------------------------------------------------------------------------
# Proxy instruction builder
# ---------------------------------------------------------------------------

def proxy_instruction(action: str, params: str, schema: str) -> str:
    """Build a structured proxy instruction with consistent format."""
    return (
        f"{action}. {params}"
        f"Return results as JSON with this exact structure: {schema}"
    )
