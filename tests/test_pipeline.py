"""Tests for orchestrator.pipeline — sequence building and context accumulation."""

import pytest

from orchestrator.pipeline import FULL_PIPELINE, _MAX_CONTEXT_CHARS


class TestFullPipeline:
    def test_pipeline_order(self):
        expected = [
            "discover", "extract", "validate", "compile",
            "audit", "reflect", "decide", "distribute",
            "collect_iterate",
        ]
        assert FULL_PIPELINE == expected

    def test_context_agent_not_in_pipeline(self):
        """Context is a support agent, not part of the standard pipeline."""
        assert "context" not in FULL_PIPELINE


class TestTokenBudget:
    def test_max_context_chars_reasonable(self):
        """Budget should allow substantial context but not exceed model limits."""
        assert _MAX_CONTEXT_CHARS > 100_000  # at least 100k chars
        assert _MAX_CONTEXT_CHARS <= 1_000_000  # not absurdly large


class TestSequenceBuilding:
    def test_partial_pipeline_discover_to_compile(self):
        from orchestrator.config import AGENTS
        from orchestrator.pipeline import FULL_PIPELINE

        order_map = {name: info["order"] for name, info in AGENTS.items()}
        start = order_map["discover"]
        end = order_map["compile"]

        sequence = [
            name for name in AGENTS
            if start <= order_map[name] <= end
            and name in FULL_PIPELINE
        ]
        assert sequence == ["discover", "extract", "validate", "compile"]

    def test_single_agent_pipeline(self):
        from orchestrator.config import AGENTS
        from orchestrator.pipeline import FULL_PIPELINE

        order_map = {name: info["order"] for name, info in AGENTS.items()}
        start = order_map["audit"]
        end = order_map["audit"]

        sequence = [
            name for name in AGENTS
            if start <= order_map[name] <= end
            and name in FULL_PIPELINE
        ]
        assert sequence == ["audit"]


class TestDefaultToAgent:
    def test_pipeline_default_matches_init(self):
        """run_pipeline default to_agent should match investigate() default."""
        import inspect
        from orchestrator.pipeline import run_pipeline
        from orchestrator import investigate

        pipeline_sig = inspect.signature(run_pipeline)
        investigate_sig = inspect.signature(investigate)

        assert pipeline_sig.parameters["to_agent"].default == "decide"
        assert investigate_sig.parameters["to_agent"].default == "decide"
