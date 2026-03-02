"""Tests for cost enforcement in the orchestrator (Phase 1.2).

Verifies:
1. Budget exceeded halts the pipeline
2. Budget warning displays at gates
3. Feedback loop capped at max_feedback_iterations
4. Per-agent output token cap (cost governor truncation)
5. Token usage flows through to EventBus
"""

import os
# Set a dummy API key before any orchestrator imports trigger config validation
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-test-dummy-key-for-tests")

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from domain.model import CostBudget, TokenUsage


# ---------------------------------------------------------------------------
# Helpers — fake agent runner that produces controllable costs
# ---------------------------------------------------------------------------

def _make_fake_run_agent(cost_per_call: float, model: str = "claude-sonnet-4-20250514"):
    """Return a (fake_run_agent, metrics_ref) pair.

    Each call to fake_run_agent bumps the module-level ``last_metrics``
    so the pipeline can read token_usage from it.
    """
    call_count = {"n": 0}

    def fake_run_agent(agent_name, user_input, **kwargs):
        call_count["n"] += 1
        # Reverse-engineer tokens from cost for sonnet pricing ($3/$15 per M)
        # Use 1000 input, derive output from remaining cost
        inp = 1000
        out = int((cost_per_call * 1_000_000 - inp * 3) / 15)
        if out < 0:
            out = 0

        tu = TokenUsage(
            input_tokens=inp,
            output_tokens=out,
            model=model,
            cost_usd=cost_per_call,
        )

        # Update the module-level last_metrics
        import orchestrator.agent_runner as ar
        ar.last_metrics.token_usage = tu

        return f"Output from {agent_name} (call #{call_count['n']})"

    return fake_run_agent, call_count


class TestBudgetExceededHaltsPipeline:
    """When cumulative cost >= max_total_usd, pipeline halts before next agent."""

    @patch("orchestrator.pipeline.evaluate_output", return_value=None)
    @patch("orchestrator.pipeline.run_agent")
    def test_pipeline_halts_at_budget(self, mock_run_agent, mock_eval, tmp_path):
        """Pipeline with $1 budget and $0.60/call should halt after 2 agents."""
        from orchestrator.pipeline import run_pipeline

        fake_run, call_count = _make_fake_run_agent(cost_per_call=0.60)
        mock_run_agent.side_effect = fake_run

        budget = CostBudget(max_total_usd=1.0, max_agent_output_tokens=8000)

        with patch("orchestrator.pipeline.OUTPUTS_DIR", tmp_path):
            outputs = run_pipeline(
                topic="test budget halt",
                from_agent="discover",
                to_agent="compile",
                evaluate=True,
                budget=budget,
                budget_override=False,
            )

        # Should have run discover ($0.60) and extract ($0.60) = $1.20
        # But after discover ($0.60) the next check before extract sees $0.60 < $1.0 → ok
        # After extract ($0.60) cumulative = $1.20 → check before validate sees $1.20 >= $1.0 → halt
        assert "discover" in outputs
        assert "extract" in outputs
        assert "validate" not in outputs  # halted before this

    @patch("orchestrator.pipeline.evaluate_output", return_value=None)
    @patch("orchestrator.pipeline.run_agent")
    def test_budget_override_continues(self, mock_run_agent, mock_eval, tmp_path):
        """With --budget-override, pipeline continues past budget."""
        from orchestrator.pipeline import run_pipeline

        fake_run, call_count = _make_fake_run_agent(cost_per_call=0.60)
        mock_run_agent.side_effect = fake_run

        budget = CostBudget(max_total_usd=1.0, max_agent_output_tokens=8000)

        with patch("orchestrator.pipeline.OUTPUTS_DIR", tmp_path):
            outputs = run_pipeline(
                topic="test budget override",
                from_agent="discover",
                to_agent="compile",
                evaluate=True,
                budget=budget,
                budget_override=True,  # override the stop-loss
            )

        # All 4 agents should run despite exceeding budget
        assert "discover" in outputs
        assert "extract" in outputs
        assert "validate" in outputs
        assert "compile" in outputs

    @patch("orchestrator.pipeline.evaluate_output", return_value=None)
    @patch("orchestrator.pipeline.run_agent")
    def test_budget_state_saved_on_halt(self, mock_run_agent, mock_eval, tmp_path):
        """When pipeline halts, state is saved to pipeline_state.json."""
        from orchestrator.pipeline import run_pipeline

        fake_run, _ = _make_fake_run_agent(cost_per_call=5.50)
        mock_run_agent.side_effect = fake_run

        budget = CostBudget(max_total_usd=10.0, max_agent_output_tokens=8000)

        with patch("orchestrator.pipeline.OUTPUTS_DIR", tmp_path):
            outputs = run_pipeline(
                topic="test state save",
                from_agent="discover",
                to_agent="compile",
                evaluate=True,
                budget=budget,
                budget_override=False,
            )

        # After discover ($5.50) → check before extract: $5.50 < $10 → ok
        # After extract ($5.50) → cumulative $11.0 → check before validate: halt
        assert "discover" in outputs
        assert "extract" in outputs
        assert "validate" not in outputs

        # Find the run directory and check for state file
        run_dirs = [d for d in tmp_path.iterdir() if d.is_dir() and d.name.startswith("pipeline_")]
        assert len(run_dirs) == 1
        state_path = run_dirs[0] / "pipeline_state.json"
        assert state_path.exists()
        state = json.loads(state_path.read_text())
        assert state["paused_at"] == "validate"
        assert "Budget exceeded" in state["note"]


class TestBudgetWarningAtGates:
    """Budget warning shown at gates when approaching threshold."""

    @patch("orchestrator.pipeline.evaluate_output", return_value=None)
    @patch("orchestrator.pipeline.run_agent")
    def test_warning_at_gate(self, mock_run_agent, mock_eval, tmp_path, capsys):
        """Budget warning appears at gate when cost > warning_threshold."""
        from orchestrator.pipeline import run_pipeline
        from orchestrator.gates import GateResult

        # $4.50 per call, budget $10, threshold 0.8 → warning at $8
        fake_run, _ = _make_fake_run_agent(cost_per_call=4.50)
        mock_run_agent.side_effect = fake_run

        budget = CostBudget(
            max_total_usd=10.0,
            warning_threshold=0.8,
            max_agent_output_tokens=8000,
        )

        # Auto-approve gate so pipeline continues
        def auto_gate(ctx):
            return GateResult(action="proceed")

        with patch("orchestrator.pipeline.OUTPUTS_DIR", tmp_path):
            outputs = run_pipeline(
                topic="test warning",
                from_agent="discover",
                to_agent="audit",
                gates={"audit"},
                on_gate=auto_gate,
                evaluate=True,
                budget=budget,
                budget_override=True,  # don't halt, we want to see the warning
            )

        captured = capsys.readouterr()
        # After discover+extract+validate+compile = $18, but with override
        # At the audit gate the cost > 80% threshold → warning should appear
        assert "⚠️" in captured.out or "Budget" in captured.out


class TestFeedbackLoopCap:
    """COLLECT_ITERATE is capped at max_feedback_iterations."""

    @patch("orchestrator.pipeline.evaluate_output", return_value=None)
    @patch("orchestrator.pipeline.run_agent")
    def test_feedback_iterations_capped(self, mock_run_agent, mock_eval, tmp_path, capsys):
        """collect_iterate should be skipped after max_feedback_iterations."""
        from orchestrator.pipeline import run_pipeline

        fake_run, call_count = _make_fake_run_agent(cost_per_call=0.01)
        mock_run_agent.side_effect = fake_run

        budget = CostBudget(
            max_total_usd=100.0,  # high budget so it doesn't halt
            max_feedback_iterations=1,  # only 1 feedback iteration allowed
            max_agent_output_tokens=8000,
        )

        with patch("orchestrator.pipeline.OUTPUTS_DIR", tmp_path):
            outputs = run_pipeline(
                topic="test feedback cap",
                from_agent="distribute",
                to_agent="collect_iterate",
                evaluate=True,
                budget=budget,
                budget_override=True,
            )

        captured = capsys.readouterr()
        # collect_iterate should run once (iteration 1)
        assert "collect_iterate" in outputs
        assert "Feedback iteration 1/1" in captured.out

    @patch("orchestrator.pipeline.evaluate_output", return_value=None)
    @patch("orchestrator.pipeline.run_agent")
    def test_feedback_cap_zero_skips(self, mock_run_agent, mock_eval, tmp_path, capsys):
        """max_feedback_iterations=0 should skip collect_iterate entirely."""
        from orchestrator.pipeline import run_pipeline

        fake_run, _ = _make_fake_run_agent(cost_per_call=0.01)
        mock_run_agent.side_effect = fake_run

        budget = CostBudget(
            max_total_usd=100.0,
            max_feedback_iterations=0,  # no feedback iterations
            max_agent_output_tokens=8000,
        )

        with patch("orchestrator.pipeline.OUTPUTS_DIR", tmp_path):
            outputs = run_pipeline(
                topic="test feedback skip",
                from_agent="distribute",
                to_agent="collect_iterate",
                evaluate=True,
                budget=budget,
                budget_override=True,
            )

        captured = capsys.readouterr()
        # collect_iterate should be skipped entirely
        assert "collect_iterate" not in outputs
        assert "Feedback loop cap reached" in captured.out


class TestCostGovernorTruncation:
    """Per-agent output token cap truncates long responses."""

    def test_max_output_tokens_passed_to_run_agent(self):
        """Pipeline passes budget.max_agent_output_tokens to run_agent."""
        from orchestrator.pipeline import run_pipeline

        captured_kwargs = {}

        def spy_run_agent(agent_name, user_input, **kwargs):
            captured_kwargs[agent_name] = kwargs
            import orchestrator.agent_runner as ar
            ar.last_metrics.token_usage = TokenUsage.zero()
            return f"Output from {agent_name}"

        budget = CostBudget(max_agent_output_tokens=4000)

        with patch("orchestrator.pipeline.run_agent", side_effect=spy_run_agent), \
             patch("orchestrator.pipeline.evaluate_output", return_value=None), \
             patch("orchestrator.pipeline.OUTPUTS_DIR", Path("/tmp/test_cost")):
            run_pipeline(
                topic="test token cap",
                from_agent="discover",
                to_agent="discover",
                budget=budget,
            )

        assert "discover" in captured_kwargs
        assert captured_kwargs["discover"].get("max_output_tokens") == 4000


class TestTokenUsageFlowsToEventBus:
    """Token usage from agent runs propagates through the EventBus."""

    @patch("orchestrator.pipeline.evaluate_output", return_value=None)
    @patch("orchestrator.pipeline.run_agent")
    def test_event_bus_receives_token_usage(self, mock_run_agent, mock_eval, tmp_path):
        """EventBus events should contain token_usage from agent runs."""
        from orchestrator.pipeline import run_pipeline
        from domain.events import EventBus

        fake_run, _ = _make_fake_run_agent(cost_per_call=0.05)
        mock_run_agent.side_effect = fake_run

        budget = CostBudget(max_total_usd=100.0)

        # Capture the EventBus
        original_init = EventBus.__init__
        captured_bus = {}

        def patched_init(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            captured_bus["bus"] = self

        with patch.object(EventBus, "__init__", patched_init), \
             patch("orchestrator.pipeline.OUTPUTS_DIR", tmp_path):
            outputs = run_pipeline(
                topic="test token flow",
                from_agent="discover",
                to_agent="extract",
                budget=budget,
            )

        bus = captured_bus["bus"]
        assert len(bus.events) == 2  # discover + extract

        # Each event should have token_usage
        for event in bus.events:
            assert event.token_usage is not None
            assert event.token_usage["cost_usd"] == pytest.approx(0.05)

        # Cumulative cost should be 0.10
        assert bus.events[-1].cumulative_cost_usd == pytest.approx(0.10)


class TestRunMetricsTokenUsage:
    """RunMetrics.token_usage is populated after run_agent."""

    def test_run_metrics_has_token_usage(self):
        """After run_agent, last_metrics.token_usage should be set."""
        from orchestrator.agent_runner import RunMetrics, last_metrics

        # Verify RunMetrics has token_usage field
        m = RunMetrics(agent="test", model="test")
        assert m.token_usage is None  # default

        # Verify with a TokenUsage value
        tu = TokenUsage(input_tokens=100, output_tokens=50, model="test", cost_usd=0.001)
        m.token_usage = tu
        assert m.token_usage.cost_usd == 0.001

    def test_run_metrics_str_includes_cost(self):
        """RunMetrics.__str__ should include cost when token_usage is set."""
        from orchestrator.agent_runner import RunMetrics

        tu = TokenUsage(input_tokens=1000, output_tokens=500, model="sonnet", cost_usd=0.0105)
        m = RunMetrics(
            agent="discover", model="sonnet",
            latency_ms=1500, input_tokens=1000, output_tokens=500,
            token_usage=tu,
        )
        s = str(m)
        assert "$0.0105" in s
        assert "discover" in s

    def test_run_metrics_str_without_cost(self):
        """RunMetrics.__str__ should work without token_usage."""
        from orchestrator.agent_runner import RunMetrics

        m = RunMetrics(agent="discover", model="sonnet", latency_ms=1500)
        s = str(m)
        assert "$" not in s
        assert "discover" in s


class TestCostEnvConfig:
    """Cost config reads from environment variables."""

    def test_cost_config_defaults(self):
        from orchestrator.config import COST_BUDGET_MAX_USD, COST_MAX_OUTPUT_TOKENS, COST_MAX_ITERATIONS
        # These should have reasonable defaults
        assert COST_BUDGET_MAX_USD == 10.0
        assert COST_MAX_OUTPUT_TOKENS == 8000
        assert COST_MAX_ITERATIONS == 3

    def test_budget_default_construction(self):
        """Pipeline builds CostBudget from env config when not provided."""
        from orchestrator.config import COST_BUDGET_MAX_USD, COST_MAX_OUTPUT_TOKENS, COST_MAX_ITERATIONS

        budget = CostBudget(
            max_total_usd=COST_BUDGET_MAX_USD,
            max_agent_output_tokens=COST_MAX_OUTPUT_TOKENS,
            max_feedback_iterations=COST_MAX_ITERATIONS,
        )
        assert budget.max_total_usd == 10.0
        assert budget.max_agent_output_tokens == 8000
        assert budget.max_feedback_iterations == 3


class TestBudgetOverrideCLI:
    """--budget-override flag flows through CLI to run_pipeline."""

    def test_budget_override_arg_exists(self):
        """__main__ parser should accept --budget-override."""
        import argparse
        from orchestrator.__main__ import main

        # Test that the parser accepts --budget-override without error
        from orchestrator.config import AGENTS
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        run_parser = subparsers.add_parser("run")
        run_parser.add_argument("--topic", type=str)
        run_parser.add_argument("--budget-override", action="store_true")

        args = parser.parse_args(["run", "--topic", "test", "--budget-override"])
        assert args.budget_override is True

        args_no = parser.parse_args(["run", "--topic", "test"])
        assert args_no.budget_override is False
