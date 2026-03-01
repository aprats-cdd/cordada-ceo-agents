"""Tests for orchestrator.agent_runner — RunMetrics, client singleton, text extraction."""

import pytest
from unittest.mock import MagicMock, patch

from orchestrator.agent_runner import (
    RunMetrics,
    _extract_text,
    _get_client,
    MAX_TOKENS,
)


class TestRunMetrics:
    def test_defaults(self):
        m = RunMetrics()
        assert m.agent == ""
        assert m.latency_ms == 0
        assert m.input_tokens == 0
        assert m.output_tokens == 0
        assert m.tool_calls == 0
        assert m.tool_rounds == 0
        assert m.proxy_calls == 0

    def test_str_format(self):
        m = RunMetrics(
            agent="discover",
            model="claude-sonnet-4-20250514",
            latency_ms=1500,
            input_tokens=1000,
            output_tokens=2000,
            tool_calls=3,
            tool_rounds=2,
        )
        s = str(m)
        assert "discover" in s
        assert "1500ms" in s
        assert "1000+2000 tokens" in s
        assert "3 tool calls" in s


class TestExtractText:
    def test_extracts_text_blocks(self):
        block1 = MagicMock()
        block1.text = "Hello"
        block2 = MagicMock()
        block2.text = "World"
        message = MagicMock()
        message.content = [block1, block2]
        assert _extract_text(message) == "Hello\n\nWorld"

    def test_skips_non_text_blocks(self):
        text_block = MagicMock()
        text_block.text = "Content"
        tool_block = MagicMock(spec=[])  # no .text attribute
        message = MagicMock()
        message.content = [tool_block, text_block]
        assert _extract_text(message) == "Content"

    def test_empty_content(self):
        message = MagicMock()
        message.content = []
        assert _extract_text(message) == ""


class TestGetClient:
    def test_returns_anthropic_client(self):
        # Reset the module-level client
        import orchestrator.agent_runner as ar
        ar._client = None
        client = _get_client()
        assert client is not None
        # Subsequent call returns same instance
        assert _get_client() is client


class TestMaxTokens:
    def test_max_tokens_reasonable(self):
        assert MAX_TOKENS >= 4096
        assert MAX_TOKENS <= 100_000
