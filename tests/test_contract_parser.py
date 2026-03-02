"""Tests for contract parsing — JSON extraction, schema validation, retry."""

import os
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-test-dummy-key-for-tests")

import json
import pytest

from orchestrator.contract_parser import (
    try_parse,
    get_schema_instruction,
    get_retry_prompt,
    _extract_json,
    ParseResult,
)


# ---------------------------------------------------------------------------
# JSON extraction from mixed content
# ---------------------------------------------------------------------------

class TestExtractJson:

    def test_pure_json(self):
        raw = '{"key": "value"}'
        assert _extract_json(raw) == raw

    def test_fenced_json(self):
        raw = 'Some text\n\n```json\n{"key": "value"}\n```\n\nMore text.'
        result = _extract_json(raw)
        assert result is not None
        assert json.loads(result) == {"key": "value"}

    def test_embedded_json(self):
        raw = 'Here is the analysis:\n\n{"sources": [{"url": "http://a.com"}]}'
        result = _extract_json(raw)
        assert result is not None
        parsed = json.loads(result)
        assert "sources" in parsed

    def test_no_json(self):
        raw = "Just some text with no JSON at all."
        assert _extract_json(raw) is None

    def test_invalid_json(self):
        raw = '{"key": invalid}'
        assert _extract_json(raw) is None

    def test_nested_json(self):
        raw = '{"outer": {"inner": [1, 2, 3]}}'
        result = _extract_json(raw)
        assert result is not None
        parsed = json.loads(result)
        assert parsed["outer"]["inner"] == [1, 2, 3]


# ---------------------------------------------------------------------------
# Contract parsing — successful parse
# ---------------------------------------------------------------------------

class TestTryParseSuccess:

    def test_discover_valid_json(self):
        output = json.dumps({
            "sources": [
                {"url": "http://a.com", "title": "A", "source_type": "news",
                 "relevance_score": 0.9, "freshness": "current", "brief": "A source"},
                {"url": "http://b.com", "title": "B", "source_type": "regulatory",
                 "relevance_score": 0.8, "freshness": "recent", "brief": "B source"},
                {"url": "http://c.com", "title": "C", "source_type": "market_data",
                 "relevance_score": 0.7, "freshness": "dated", "brief": "C source"},
            ],
            "search_queries_used": ["query1"],
            "coverage_assessment": "Good coverage.",
        })
        result = try_parse("discover", output)
        assert result.success is True
        assert result.structured is not None
        assert len(result.structured["sources"]) == 3

    def test_audit_valid_json(self):
        output = json.dumps({
            "dimensions": [
                {"dimension": "financial", "score": 8.0, "findings": ["f1"], "risks": ["r1"]},
                {"dimension": "regulatory", "score": 7.0, "findings": ["f2"], "risks": ["r2"]},
                {"dimension": "operational", "score": 6.0, "findings": ["f3"], "risks": ["r3"]},
            ],
            "overall_verdict": "Positive",
            "blocking_issues": [],
        })
        result = try_parse("audit", output)
        assert result.success is True
        assert result.structured["overall_verdict"] == "Positive"

    def test_agent_without_contract(self):
        """Agents without contracts (distribute, context) always succeed."""
        result = try_parse("distribute", "Some output text")
        assert result.success is True
        assert result.structured is None

    def test_json_in_markdown(self):
        """Parse JSON embedded in markdown response."""
        output = (
            "Aquí está mi análisis:\n\n"
            "```json\n"
            + json.dumps({
                "scenarios": [
                    {"name": "Base", "probability": "high", "impact": "moderate",
                     "assumptions_challenged": ["a"], "mitigation": "m"},
                    {"name": "Adverse", "probability": "low", "impact": "severe",
                     "assumptions_challenged": ["b"], "mitigation": "m2"},
                ],
                "robustness_score": 0.75,
                "key_vulnerabilities": ["v1"],
            })
            + "\n```"
        )
        result = try_parse("reflect", output)
        assert result.success is True
        assert len(result.structured["scenarios"]) == 2


# ---------------------------------------------------------------------------
# Contract parsing — failures
# ---------------------------------------------------------------------------

class TestTryParseFailure:

    def test_no_json_in_output(self):
        result = try_parse("discover", "Just text, no JSON")
        assert result.success is False
        assert any("no json" in e.lower() for e in result.errors)

    def test_invalid_json(self):
        result = try_parse("discover", '{"sources": invalid}')
        assert result.success is False

    def test_validation_errors(self):
        """Valid JSON but fails contract validation."""
        output = json.dumps({
            "sources": [
                {"url": "", "title": "A", "source_type": "news",
                 "relevance_score": 0.9, "freshness": "current", "brief": "A"},
            ],
            "search_queries_used": [],
            "coverage_assessment": "",
        })
        result = try_parse("discover", output)
        assert result.success is False
        assert any("at least 3" in e.lower() for e in result.errors)


# ---------------------------------------------------------------------------
# Schema instruction generation
# ---------------------------------------------------------------------------

class TestSchemaInstruction:

    def test_pipeline_agents_have_schema(self):
        for agent in ["discover", "extract", "validate", "compile", "audit", "reflect", "decide"]:
            instruction = get_schema_instruction(agent)
            assert instruction is not None, f"No schema for {agent}"
            assert "JSON" in instruction
            assert "schema" in instruction.lower()

    def test_non_contract_agents_return_none(self):
        assert get_schema_instruction("distribute") is None
        assert get_schema_instruction("context") is None

    def test_instruction_contains_example(self):
        instruction = get_schema_instruction("discover")
        assert "sources" in instruction
        assert "coverage_assessment" in instruction


# ---------------------------------------------------------------------------
# Retry prompt generation
# ---------------------------------------------------------------------------

class TestRetryPrompt:

    def test_retry_includes_errors(self):
        prompt = get_retry_prompt("discover", ["missing sources", "empty coverage"])
        assert "missing sources" in prompt
        assert "empty coverage" in prompt
        assert "schema" in prompt.lower()


# ---------------------------------------------------------------------------
# Event bus structured output
# ---------------------------------------------------------------------------

class TestEventBusStructuredOutput:

    def test_event_stores_structured_output(self):
        from domain.events import EventBus

        bus = EventBus(run_id="test-contracts")
        structured = {"sources": [{"url": "http://a.com"}]}

        event = bus.publish(
            "discover", "raw output",
            structured_output=structured,
        )
        assert event.agent_output_structured == structured

    def test_event_without_structured_output(self):
        from domain.events import EventBus

        bus = EventBus(run_id="test-contracts-2")
        event = bus.publish("discover", "raw output")
        assert event.agent_output_structured is None
