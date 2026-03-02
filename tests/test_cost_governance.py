"""Tests for cost governance domain objects — TokenUsage, CostBudget, and EventBus cost tracking."""

import pytest
from dataclasses import asdict


class TestTokenUsage:
    """TokenUsage value object — pricing, factory, serialization."""

    def test_from_api_response_with_dict(self):
        from domain.model import TokenUsage
        response = {"usage": {"input_tokens": 1000, "output_tokens": 500}}
        tu = TokenUsage.from_api_response(response, "claude-sonnet-4-20250514")
        assert tu.input_tokens == 1000
        assert tu.output_tokens == 500
        assert tu.model == "claude-sonnet-4-20250514"
        # Sonnet: (1000 * 3 + 500 * 15) / 1_000_000 = 0.0105
        assert tu.cost_usd == pytest.approx(0.0105, abs=1e-6)

    def test_from_api_response_with_object(self):
        from domain.model import TokenUsage

        class FakeUsage:
            input_tokens = 2000
            output_tokens = 1000

        class FakeResponse:
            usage = FakeUsage()

        tu = TokenUsage.from_api_response(FakeResponse(), "claude-opus-4-6")
        assert tu.input_tokens == 2000
        assert tu.output_tokens == 1000
        # Opus: (2000 * 15 + 1000 * 75) / 1_000_000 = 0.105
        assert tu.cost_usd == pytest.approx(0.105, abs=1e-6)

    def test_from_api_response_unknown_model_uses_default(self):
        from domain.model import TokenUsage
        response = {"usage": {"input_tokens": 1000, "output_tokens": 500}}
        tu = TokenUsage.from_api_response(response, "claude-future-model")
        # Default pricing same as sonnet
        assert tu.cost_usd == pytest.approx(0.0105, abs=1e-6)

    def test_from_api_response_no_usage(self):
        from domain.model import TokenUsage
        tu = TokenUsage.from_api_response({}, "claude-sonnet-4-20250514")
        assert tu.input_tokens == 0
        assert tu.output_tokens == 0
        assert tu.cost_usd == 0.0

    def test_zero(self):
        from domain.model import TokenUsage
        tu = TokenUsage.zero()
        assert tu.input_tokens == 0
        assert tu.output_tokens == 0
        assert tu.cost_usd == 0.0
        assert tu.model == "none"

    def test_frozen(self):
        from domain.model import TokenUsage
        tu = TokenUsage.zero()
        with pytest.raises(AttributeError):
            tu.cost_usd = 999.0

    def test_opus_pricing_correct(self):
        from domain.model import TokenUsage
        # 1M input + 1M output on Opus = $15 + $75 = $90
        response = {"usage": {"input_tokens": 1_000_000, "output_tokens": 1_000_000}}
        tu = TokenUsage.from_api_response(response, "claude-opus-4-6")
        assert tu.cost_usd == pytest.approx(90.0, abs=0.01)

    def test_sonnet_pricing_correct(self):
        from domain.model import TokenUsage
        # 1M input + 1M output on Sonnet = $3 + $15 = $18
        response = {"usage": {"input_tokens": 1_000_000, "output_tokens": 1_000_000}}
        tu = TokenUsage.from_api_response(response, "claude-sonnet-4-20250514")
        assert tu.cost_usd == pytest.approx(18.0, abs=0.01)

    def test_serialization_roundtrip(self):
        from domain.model import TokenUsage
        tu = TokenUsage(input_tokens=100, output_tokens=200, model="test", cost_usd=0.01)
        d = asdict(tu)
        assert d == {
            "input_tokens": 100,
            "output_tokens": 200,
            "model": "test",
            "cost_usd": 0.01,
        }


class TestCostBudget:
    """CostBudget — stop-loss rules for the pipeline."""

    def test_check_ok(self):
        from domain.model import CostBudget
        budget = CostBudget(max_total_usd=10.0)
        assert budget.check(0.0) == "ok"
        assert budget.check(5.0) == "ok"
        assert budget.check(7.9) == "ok"

    def test_check_warning(self):
        from domain.model import CostBudget
        budget = CostBudget(max_total_usd=10.0, warning_threshold=0.8)
        assert budget.check(8.0) == "warning"
        assert budget.check(9.5) == "warning"
        assert budget.check(9.99) == "warning"

    def test_check_exceeded(self):
        from domain.model import CostBudget
        budget = CostBudget(max_total_usd=10.0)
        assert budget.check(10.0) == "exceeded"
        assert budget.check(15.0) == "exceeded"

    def test_check_custom_threshold(self):
        from domain.model import CostBudget
        budget = CostBudget(max_total_usd=5.0, warning_threshold=0.5)
        assert budget.check(2.4) == "ok"
        assert budget.check(2.5) == "warning"
        assert budget.check(5.0) == "exceeded"

    def test_format_status_ok(self):
        from domain.model import CostBudget
        budget = CostBudget(max_total_usd=10.0)
        msg = budget.format_status(3.50)
        assert "$3.50" in msg
        assert "$10.00" in msg
        assert "35%" in msg

    def test_format_status_warning(self):
        from domain.model import CostBudget
        budget = CostBudget(max_total_usd=10.0)
        msg = budget.format_status(8.50)
        assert "⚠️" in msg
        assert "85%" in msg

    def test_format_status_exceeded(self):
        from domain.model import CostBudget
        budget = CostBudget(max_total_usd=10.0)
        msg = budget.format_status(12.00)
        assert "🛑" in msg
        assert "--budget-override" in msg

    def test_defaults(self):
        from domain.model import CostBudget
        budget = CostBudget()
        assert budget.max_total_usd == 10.0
        assert budget.max_agent_output_tokens == 8000
        assert budget.max_feedback_iterations == 3
        assert budget.warning_threshold == 0.8

    def test_frozen(self):
        from domain.model import CostBudget
        budget = CostBudget()
        with pytest.raises(AttributeError):
            budget.max_total_usd = 999.0

    def test_zero_budget_exceeded_immediately(self):
        from domain.model import CostBudget
        budget = CostBudget(max_total_usd=0.0)
        assert budget.check(0.0) == "exceeded"


class TestEventBusCostTracking:
    """EventBus integration — cost flows through events."""

    def test_publish_with_token_usage(self):
        from domain.events import EventBus
        from domain.model import TokenUsage

        bus = EventBus(run_id="test-cost-001")
        tu = TokenUsage(input_tokens=1000, output_tokens=500, model="sonnet", cost_usd=0.01)

        event = bus.publish("discover", "output text", token_usage=tu)
        assert event.token_usage is not None
        assert event.token_usage["input_tokens"] == 1000
        assert event.cumulative_cost_usd == pytest.approx(0.01)

    def test_cumulative_cost_across_events(self):
        from domain.events import EventBus
        from domain.model import TokenUsage

        bus = EventBus(run_id="test-cost-002")

        tu1 = TokenUsage(input_tokens=1000, output_tokens=500, model="sonnet", cost_usd=0.01)
        tu2 = TokenUsage(input_tokens=2000, output_tokens=1000, model="sonnet", cost_usd=0.02)
        tu3 = TokenUsage(input_tokens=500, output_tokens=200, model="sonnet", cost_usd=0.005)

        e1 = bus.publish("discover", "out1", token_usage=tu1)
        e2 = bus.publish("extract", "out2", token_usage=tu2)
        e3 = bus.publish("validate", "out3", token_usage=tu3)

        assert e1.cumulative_cost_usd == pytest.approx(0.01)
        assert e2.cumulative_cost_usd == pytest.approx(0.03)
        assert e3.cumulative_cost_usd == pytest.approx(0.035)

    def test_publish_without_token_usage(self):
        from domain.events import EventBus

        bus = EventBus(run_id="test-cost-003")
        event = bus.publish("discover", "output text")
        assert event.token_usage is None
        assert event.cumulative_cost_usd == 0.0

    def test_cost_summary(self):
        from domain.events import EventBus
        from domain.model import TokenUsage

        bus = EventBus(run_id="test-cost-004")
        tu = TokenUsage(input_tokens=1000, output_tokens=500, model="sonnet", cost_usd=0.0105)
        bus.publish("discover", "out", token_usage=tu)

        summary = bus.get_cost_summary()
        assert "DISCOVER" in summary
        assert "1000" in summary
        assert "500" in summary
        assert "0.0105" in summary
        assert "Total pipeline cost" in summary
