"""Tests for orchestrator.tools — tool registry, executors, proxy, and helpers."""

import json
import os
from unittest.mock import patch, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Import helpers — tools.py has heavy dependencies, so we patch at import
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _env_vars(monkeypatch):
    """Ensure consistent env for every test."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    # Clear Google/Slack so they default to "not configured"
    monkeypatch.delenv("GOOGLE_CREDENTIALS_PATH", raising=False)
    monkeypatch.delenv("GOOGLE_DELEGATE_EMAIL", raising=False)
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    # Reset LRU caches so env changes take effect
    from orchestrator.tools import _is_google_configured, _is_slack_configured
    _is_google_configured.cache_clear()
    _is_slack_configured.cache_clear()


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

class TestToolRegistry:
    def test_get_tools_for_known_agent(self):
        from orchestrator.tools import get_tools_for_agent
        tools = get_tools_for_agent("discover")
        names = [t.get("name", t.get("type")) for t in tools]
        assert "web_search" in names or "web_search_20250305" in [t.get("type") for t in tools]
        assert "search_google_drive" in names
        assert "search_slack" in names

    def test_get_tools_for_unknown_agent(self):
        from orchestrator.tools import get_tools_for_agent
        assert get_tools_for_agent("nonexistent") == []

    def test_has_custom_tools(self):
        from orchestrator.tools import has_custom_tools
        assert has_custom_tools("discover") is True
        assert has_custom_tools("compile") is False
        assert has_custom_tools("nonexistent") is False

    def test_all_agents_in_registry(self):
        from orchestrator.tools import AGENT_TOOLS
        from orchestrator.config import AGENTS
        for agent_name in AGENTS:
            assert agent_name in AGENT_TOOLS, f"Agent '{agent_name}' not in AGENT_TOOLS"

    def test_custom_tool_definitions_have_schemas(self):
        from orchestrator.tools import CUSTOM_TOOL_DEFINITIONS
        for name, defn in CUSTOM_TOOL_DEFINITIONS.items():
            assert "name" in defn, f"{name} missing 'name'"
            assert "description" in defn, f"{name} missing 'description'"
            assert "input_schema" in defn, f"{name} missing 'input_schema'"
            schema = defn["input_schema"]
            assert schema["type"] == "object"
            assert "properties" in schema


# ---------------------------------------------------------------------------
# Executor dispatch
# ---------------------------------------------------------------------------

class TestExecuteTool:
    def test_unknown_tool_returns_error(self):
        from orchestrator.tools import execute_tool
        result = json.loads(execute_tool("nonexistent_tool", {}))
        assert "error" in result
        assert "Unknown tool" in result["error"]

    def test_execute_tool_catches_exceptions(self):
        from orchestrator.tools import execute_tool, _TOOL_EXECUTORS
        # Temporarily inject a broken executor
        original = _TOOL_EXECUTORS.get("search_google_drive")
        _TOOL_EXECUTORS["__test_broken"] = lambda _: (_ for _ in ()).throw(ValueError("boom"))
        try:
            result = json.loads(execute_tool("__test_broken", {}))
            assert "error" in result
            assert "boom" in result["error"]
        finally:
            del _TOOL_EXECUTORS["__test_broken"]


# ---------------------------------------------------------------------------
# Service availability checks
# ---------------------------------------------------------------------------

class TestServiceChecks:
    def test_google_not_configured_default(self):
        from orchestrator.tools import _is_google_configured
        _is_google_configured.cache_clear()
        assert _is_google_configured() is False

    def test_google_configured_with_env(self, monkeypatch):
        from orchestrator.tools import _is_google_configured
        _is_google_configured.cache_clear()
        monkeypatch.setenv("GOOGLE_CREDENTIALS_PATH", "/tmp/creds.json")
        assert _is_google_configured() is True

    def test_slack_not_configured_default(self):
        from orchestrator.tools import _is_slack_configured
        _is_slack_configured.cache_clear()
        assert _is_slack_configured() is False

    def test_slack_configured_with_env(self, monkeypatch):
        from orchestrator.tools import _is_slack_configured
        _is_slack_configured.cache_clear()
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test-token")
        assert _is_slack_configured() is True


# ---------------------------------------------------------------------------
# Auth error detection
# ---------------------------------------------------------------------------

class TestIsAuthError:
    def test_string_based_detection(self):
        from orchestrator.tools import _is_auth_error
        assert _is_auth_error(Exception("invalid credentials")) is True
        assert _is_auth_error(Exception("401 Unauthorized")) is True
        assert _is_auth_error(Exception("403 Forbidden")) is False  # no "access denied" substring
        assert _is_auth_error(Exception("access denied")) is True
        assert _is_auth_error(Exception("token_revoked")) is True
        assert _is_auth_error(Exception("some random error")) is False

    def test_status_code_detection(self):
        from orchestrator.tools import _is_auth_error

        class FakeResp:
            status = 401
        exc = Exception("something")
        exc.resp = FakeResp()
        assert _is_auth_error(exc) is True

        exc2 = Exception("something")
        exc2.resp = type("R", (), {"status": 500})()
        assert _is_auth_error(exc2) is False


# ---------------------------------------------------------------------------
# Drive query escaping
# ---------------------------------------------------------------------------

class TestDriveQueryEscaping:
    def test_escape_single_quotes(self):
        from orchestrator.tools import _escape_drive_query
        assert _escape_drive_query("hello world") == "hello world"
        assert _escape_drive_query("it's a test") == "it\\'s a test"
        assert _escape_drive_query("a'b'c") == "a\\'b\\'c"

    def test_escape_backslashes(self):
        from orchestrator.tools import _escape_drive_query
        assert _escape_drive_query("path\\file") == "path\\\\file"


# ---------------------------------------------------------------------------
# Claude proxy
# ---------------------------------------------------------------------------

class TestCallClaudeAsProxy:
    @patch("orchestrator.tools._get_proxy_client")
    def test_proxy_returns_parsed_json(self, mock_get_client):
        from orchestrator.tools import call_claude_as_proxy

        mock_msg = MagicMock()
        text_block = MagicMock()
        text_block.text = '{"results": [{"id": "1"}], "total": 1}'
        mock_msg.content = [text_block]

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_msg
        mock_get_client.return_value = mock_client

        result = call_claude_as_proxy("test instruction")
        assert result == {"results": [{"id": "1"}], "total": 1}

    @patch("orchestrator.tools._get_proxy_client")
    def test_proxy_strips_markdown_fences(self, mock_get_client):
        from orchestrator.tools import call_claude_as_proxy

        mock_msg = MagicMock()
        text_block = MagicMock()
        text_block.text = '```json\n{"key": "value"}\n```'
        mock_msg.content = [text_block]

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_msg
        mock_get_client.return_value = mock_client

        result = call_claude_as_proxy("test")
        assert result == {"key": "value"}

    @patch("orchestrator.tools._get_proxy_client")
    def test_proxy_handles_non_json(self, mock_get_client):
        from orchestrator.tools import call_claude_as_proxy

        mock_msg = MagicMock()
        text_block = MagicMock()
        text_block.text = "Sorry, I could not find any results."
        mock_msg.content = [text_block]

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_msg
        mock_get_client.return_value = mock_client

        result = call_claude_as_proxy("test")
        assert result["source"] == "claude_proxy"
        assert "Sorry" in result["results"]

    @patch("orchestrator.tools._get_proxy_client", side_effect=Exception("network error"))
    def test_proxy_handles_exception(self, mock_get_client):
        from orchestrator.tools import call_claude_as_proxy
        result = call_claude_as_proxy("test")
        assert "error" in result


# ---------------------------------------------------------------------------
# Write tools: security boundary — never proxy without credentials
# ---------------------------------------------------------------------------

class TestWriteToolSecurity:
    def test_draft_gmail_returns_manual_fallback_without_creds(self):
        from orchestrator.tools import _exec_draft_gmail
        result = _exec_draft_gmail({
            "to": "test@example.com",
            "subject": "Test",
            "body": "Hello",
        })
        assert result["source"] == "manual_fallback"
        assert result["status"] == "draft_not_created"
        assert result["to"] == "test@example.com"

    def test_send_slack_returns_manual_fallback_without_creds(self):
        from orchestrator.tools import _exec_send_slack_message
        result = _exec_send_slack_message({
            "channel": "#general",
            "text": "Hello team",
        })
        assert result["source"] == "manual_fallback"
        assert result["status"] == "message_not_sent"
        assert result["channel"] == "#general"


# ---------------------------------------------------------------------------
# Read tools: proxy fallback without credentials
# ---------------------------------------------------------------------------

class TestReadToolFallback:
    @patch("orchestrator.tools.call_claude_as_proxy")
    def test_search_drive_falls_back_to_proxy(self, mock_proxy):
        from orchestrator.tools import _exec_search_google_drive
        mock_proxy.return_value = {"results": [], "total": 0}
        result = _exec_search_google_drive({"query": "test"})
        mock_proxy.assert_called_once()
        assert result["total"] == 0

    @patch("orchestrator.tools.call_claude_as_proxy")
    def test_search_gmail_falls_back_to_proxy(self, mock_proxy):
        from orchestrator.tools import _exec_search_gmail
        mock_proxy.return_value = {"results": [], "total": 0}
        result = _exec_search_gmail({"query": "test"})
        mock_proxy.assert_called_once()

    @patch("orchestrator.tools.call_claude_as_proxy")
    def test_search_slack_falls_back_to_proxy(self, mock_proxy):
        from orchestrator.tools import _exec_search_slack
        mock_proxy.return_value = {"results": [], "total": 0}
        result = _exec_search_slack({"query": "test"})
        mock_proxy.assert_called_once()


# ---------------------------------------------------------------------------
# Timeout wrapper
# ---------------------------------------------------------------------------

class TestTimeout:
    def test_timeout_raises_on_slow_function(self):
        import time
        from orchestrator.tools import _run_with_timeout

        def slow_func(inputs):
            time.sleep(10)
            return {"ok": True}

        with pytest.raises(TimeoutError):
            _run_with_timeout(slow_func, {}, timeout=1)

    def test_timeout_returns_fast_result(self):
        from orchestrator.tools import _run_with_timeout

        def fast_func(inputs):
            return {"ok": True}

        result = _run_with_timeout(fast_func, {}, timeout=5)
        assert result == {"ok": True}

    def test_timeout_propagates_exceptions(self):
        from orchestrator.tools import _run_with_timeout

        def error_func(inputs):
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            _run_with_timeout(error_func, {}, timeout=5)


# ---------------------------------------------------------------------------
# Proxy instruction builder
# ---------------------------------------------------------------------------

class TestProxyInstruction:
    def test_builds_correct_format(self):
        from orchestrator.tools import _proxy_instruction
        result = _proxy_instruction("Search Gmail", "Top 5. ", '{"results": []}')
        assert "Search Gmail" in result
        assert "Top 5." in result
        assert '{"results": []}' in result
