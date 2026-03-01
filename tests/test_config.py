"""Tests for orchestrator.config — agent registry, model selection, prompts."""

import pytest

from orchestrator.config import (
    AGENTS,
    PREMIUM_AGENTS,
    get_model,
    get_agent_prompt,
    MODEL_DEFAULT,
    MODEL_PREMIUM,
)


class TestAgentRegistry:
    def test_all_agents_have_required_keys(self):
        required_keys = {"file", "order", "layer", "description", "next"}
        for name, info in AGENTS.items():
            for key in required_keys:
                assert key in info, f"Agent '{name}' missing key '{key}'"

    def test_order_values_unique(self):
        orders = [info["order"] for info in AGENTS.values()]
        assert len(orders) == len(set(orders)), "Duplicate order values in AGENTS"

    def test_next_chain_valid(self):
        """Every agent's 'next' should point to a valid agent or be None."""
        for name, info in AGENTS.items():
            nxt = info["next"]
            if nxt is not None:
                assert nxt in AGENTS, f"Agent '{name}' points to unknown next: '{nxt}'"

    def test_layers_valid(self):
        valid_layers = {"feed", "interpret", "decide", "distribute", "feedback", "support"}
        for name, info in AGENTS.items():
            assert info["layer"] in valid_layers, (
                f"Agent '{name}' has invalid layer: '{info['layer']}'"
            )

    def test_at_least_9_pipeline_agents(self):
        """The standard pipeline has 9 agents + context support."""
        assert len(AGENTS) >= 10


class TestModelSelection:
    def test_premium_agents_get_opus(self):
        for agent_name in PREMIUM_AGENTS:
            assert get_model(agent_name) == MODEL_PREMIUM

    def test_standard_agents_get_sonnet(self):
        for agent_name in AGENTS:
            if agent_name not in PREMIUM_AGENTS:
                assert get_model(agent_name) == MODEL_DEFAULT


class TestAgentPrompts:
    def test_load_prompt_for_all_agents(self):
        """Every agent should have a readable prompt file."""
        for agent_name in AGENTS:
            prompt = get_agent_prompt(agent_name)
            assert len(prompt) > 50, f"Agent '{agent_name}' prompt too short"

    def test_unknown_agent_raises(self):
        with pytest.raises(ValueError, match="Unknown agent"):
            get_agent_prompt("nonexistent_agent")
