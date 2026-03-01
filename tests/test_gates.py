"""Tests for orchestrator.gates — gate handlers and data structures."""

import pytest

from orchestrator.gates import (
    GateContext,
    GateResult,
    auto_gate,
    DEFAULT_GATES,
)


class TestGateContext:
    def test_required_fields(self):
        ctx = GateContext(
            agent_name="audit",
            step=5,
            total_steps=9,
            outputs={"compile": "some output"},
            proposed_input="input text",
            topic="gobernanza",
        )
        assert ctx.agent_name == "audit"
        assert ctx.step == 5
        assert ctx.total_steps == 9
        assert ctx.project_name is None  # optional

    def test_with_project_name(self):
        ctx = GateContext(
            agent_name="reflect",
            step=6,
            total_steps=9,
            outputs={},
            proposed_input="text",
            topic="topic",
            project_name="my-project",
        )
        assert ctx.project_name == "my-project"


class TestGateResult:
    def test_proceed(self):
        r = GateResult(action="proceed")
        assert r.action == "proceed"
        assert r.modified_input is None
        assert r.note == ""

    def test_modify(self):
        r = GateResult(action="modify", modified_input="new input", note="CEO added context")
        assert r.action == "modify"
        assert r.modified_input == "new input"

    def test_stop(self):
        r = GateResult(action="stop", note="Waiting for board meeting")
        assert r.action == "stop"


class TestAutoGate:
    def test_always_proceeds(self):
        ctx = GateContext(
            agent_name="audit",
            step=1,
            total_steps=3,
            outputs={},
            proposed_input="text",
            topic="topic",
        )
        result = auto_gate(ctx)
        assert result.action == "proceed"


class TestDefaultGates:
    def test_contains_expected_agents(self):
        assert "audit" in DEFAULT_GATES
        assert "reflect" in DEFAULT_GATES
        assert "decide" in DEFAULT_GATES
        assert "distribute" in DEFAULT_GATES
        assert "collect_iterate" in DEFAULT_GATES

    def test_does_not_contain_feed_agents(self):
        assert "discover" not in DEFAULT_GATES
        assert "extract" not in DEFAULT_GATES
        assert "validate" not in DEFAULT_GATES
        assert "compile" not in DEFAULT_GATES
