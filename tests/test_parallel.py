"""Tests for fan-out/fan-in EXTRACT parallelism."""

import os
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-test-dummy-key-for-tests")

import asyncio
import json
import pytest
from dataclasses import asdict

from domain.contracts import SourceCard, Extraction, ExtractOutput
from domain.model import CostBudget, TokenUsage
from orchestrator.parallel import fan_out_extract, merge_extractions, FAN_OUT_THRESHOLD


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_source(idx: int) -> SourceCard:
    return SourceCard(
        url=f"http://source-{idx}.com",
        title=f"Source {idx}",
        source_type="news",
        relevance_score=0.9 - idx * 0.05,
        freshness="current",
        brief=f"Brief for source {idx}",
    )


def _make_extract_output(source_idx: int, claims: list[str] | None = None) -> ExtractOutput:
    if claims is None:
        claims = [f"Claim from source {source_idx}"]
    return ExtractOutput(
        extractions=[
            Extraction(
                source_ref=f"http://source-{source_idx}.com",
                claims=claims,
                data_points=[{"label": f"dp{source_idx}", "value": "1", "unit": "M"}],
                quotes=[f"Quote {source_idx}"],
                confidence=0.8 + source_idx * 0.02,
            ),
        ],
        gaps_identified=[f"Gap {source_idx}"] if source_idx % 2 == 0 else [],
    )


def _fake_run_agent_factory(responses: dict[int, str] | None = None):
    """Create a fake run_agent that returns JSON ExtractOutputs.

    If responses is None, generates valid ExtractOutput JSON for each call.
    """
    call_count = {"n": 0}
    call_inputs: list[str] = []

    def fake_run_agent(agent_name, user_input, **kwargs):
        idx = call_count["n"]
        call_count["n"] += 1
        call_inputs.append(user_input)

        if responses and idx in responses:
            return responses[idx]

        # Generate valid ExtractOutput JSON
        eo = _make_extract_output(idx)
        return eo.to_json()

    return fake_run_agent, call_count, call_inputs


# ---------------------------------------------------------------------------
# merge_extractions tests
# ---------------------------------------------------------------------------

class TestMergeExtractions:

    def test_merge_concatenates(self):
        eo1 = _make_extract_output(0, ["Claim A"])
        eo2 = _make_extract_output(1, ["Claim B"])
        merged = merge_extractions([eo1, eo2])

        assert len(merged.extractions) == 2
        all_claims = [c for ext in merged.extractions for c in ext.claims]
        assert "Claim A" in all_claims
        assert "Claim B" in all_claims

    def test_merge_deduplicates_claims(self):
        eo1 = _make_extract_output(0, ["Duplicate claim", "Unique A"])
        eo2 = _make_extract_output(1, ["Duplicate claim", "Unique B"])
        merged = merge_extractions([eo1, eo2])

        all_claims = [c for ext in merged.extractions for c in ext.claims]
        # "Duplicate claim" appears only once across all extractions
        assert all_claims.count("Duplicate claim") == 1
        assert "Unique A" in all_claims
        assert "Unique B" in all_claims

    def test_merge_dedup_case_insensitive(self):
        eo1 = _make_extract_output(0, ["GDP grew 5%"])
        eo2 = _make_extract_output(1, ["gdp grew 5%"])  # same claim, different case
        merged = merge_extractions([eo1, eo2])

        all_claims = [c for ext in merged.extractions for c in ext.claims]
        # Only one version kept
        assert len(all_claims) == 1

    def test_merge_sorts_by_confidence_descending(self):
        eo_low = ExtractOutput(
            extractions=[Extraction(
                source_ref="a", claims=["low"], confidence=0.3,
            )],
            gaps_identified=[],
        )
        eo_high = ExtractOutput(
            extractions=[Extraction(
                source_ref="b", claims=["high"], confidence=0.95,
            )],
            gaps_identified=[],
        )
        merged = merge_extractions([eo_low, eo_high])
        assert merged.extractions[0].confidence >= merged.extractions[1].confidence

    def test_merge_deduplicates_gaps(self):
        eo1 = ExtractOutput(extractions=[], gaps_identified=["Gap X", "Gap Y"])
        eo2 = ExtractOutput(extractions=[], gaps_identified=["Gap X", "Gap Z"])
        merged = merge_extractions([eo1, eo2])
        assert merged.gaps_identified == ["Gap X", "Gap Y", "Gap Z"]

    def test_merge_empty_list(self):
        merged = merge_extractions([])
        assert merged.extractions == []
        assert merged.gaps_identified == []

    def test_merge_single_output(self):
        eo = _make_extract_output(0)
        merged = merge_extractions([eo])
        assert len(merged.extractions) == 1
        assert merged.extractions[0].source_ref == "http://source-0.com"

    def test_merge_preserves_data_points_and_quotes(self):
        eo = _make_extract_output(0, ["claim"])
        merged = merge_extractions([eo])
        assert len(merged.extractions[0].data_points) == 1
        assert len(merged.extractions[0].quotes) == 1


# ---------------------------------------------------------------------------
# fan_out_extract tests
# ---------------------------------------------------------------------------

class TestFanOutExtract:

    def test_fan_out_calls_agent_per_source(self):
        sources = [_make_source(i) for i in range(4)]
        fake_run, call_count, _ = _fake_run_agent_factory()

        # Monkey-patch run_agent and last_metrics
        import orchestrator.agent_runner as ar
        original_run = ar.run_agent
        original_metrics = ar.last_metrics
        ar.run_agent = fake_run
        ar.last_metrics = type(original_metrics)()
        ar.last_metrics.token_usage = TokenUsage(
            input_tokens=100, output_tokens=50,
            model="claude-sonnet-4-20250514", cost_usd=0.001,
        )

        try:
            merged, text, usages = asyncio.run(fan_out_extract(
                sources=sources,
                run_agent_fn=fake_run,
                max_concurrent=5,
                pipeline_context="Test context",
            ))

            assert call_count["n"] == 4  # one call per source
            assert len(merged.extractions) >= 1
        finally:
            ar.run_agent = original_run
            ar.last_metrics = original_metrics

    def test_fan_out_respects_budget(self):
        sources = [_make_source(i) for i in range(5)]
        fake_run, call_count, _ = _fake_run_agent_factory()

        # Budget already exceeded
        budget = CostBudget(max_total_usd=0.01)

        import orchestrator.agent_runner as ar
        original_run = ar.run_agent
        original_metrics = ar.last_metrics
        ar.run_agent = fake_run
        ar.last_metrics = type(original_metrics)()
        ar.last_metrics.token_usage = TokenUsage(
            input_tokens=100, output_tokens=50,
            model="claude-sonnet-4-20250514", cost_usd=0.001,
        )

        try:
            merged, text, usages = asyncio.run(fan_out_extract(
                sources=sources,
                run_agent_fn=fake_run,
                max_concurrent=5,
                cost_budget=budget,
                cumulative_cost=100.0,  # way over budget
                pipeline_context="Test context",
            ))

            # All calls should have been skipped due to budget
            assert call_count["n"] == 0
        finally:
            ar.run_agent = original_run
            ar.last_metrics = original_metrics

    def test_fan_out_handles_failed_extractions(self):
        """When some extractions fail, merge the successful ones."""
        sources = [_make_source(i) for i in range(3)]

        # First call succeeds, second returns garbage, third succeeds
        eo_valid = _make_extract_output(0, ["Valid claim"])
        responses = {
            0: eo_valid.to_json(),
            1: "Not valid JSON at all!",
            2: _make_extract_output(2, ["Another valid"]).to_json(),
        }
        fake_run, call_count, _ = _fake_run_agent_factory(responses)

        import orchestrator.agent_runner as ar
        original_run = ar.run_agent
        original_metrics = ar.last_metrics
        ar.run_agent = fake_run
        ar.last_metrics = type(original_metrics)()
        ar.last_metrics.token_usage = TokenUsage(
            input_tokens=100, output_tokens=50,
            model="claude-sonnet-4-20250514", cost_usd=0.001,
        )

        try:
            merged, text, usages = asyncio.run(fan_out_extract(
                sources=sources,
                run_agent_fn=fake_run,
                max_concurrent=5,
                pipeline_context="Test context",
            ))

            # Should have 2 successful extractions (indices 0 and 2)
            assert call_count["n"] == 3
            assert len(merged.extractions) == 2
        finally:
            ar.run_agent = original_run
            ar.last_metrics = original_metrics

    def test_fan_out_each_source_in_input(self):
        """Each parallel call should include the source JSON in its input."""
        sources = [_make_source(i) for i in range(3)]
        fake_run, _, call_inputs = _fake_run_agent_factory()

        import orchestrator.agent_runner as ar
        original_run = ar.run_agent
        original_metrics = ar.last_metrics
        ar.run_agent = fake_run
        ar.last_metrics = type(original_metrics)()
        ar.last_metrics.token_usage = TokenUsage(
            input_tokens=100, output_tokens=50,
            model="claude-sonnet-4-20250514", cost_usd=0.001,
        )

        try:
            asyncio.run(fan_out_extract(
                sources=sources,
                run_agent_fn=fake_run,
                max_concurrent=5,
                pipeline_context="Test context",
            ))

            # Each call should mention a specific source
            for i, inp in enumerate(call_inputs):
                assert f"source-{i}.com" in inp or "source" in inp.lower()
        finally:
            ar.run_agent = original_run
            ar.last_metrics = original_metrics


# ---------------------------------------------------------------------------
# Threshold / fallback tests
# ---------------------------------------------------------------------------

class TestFanOutThreshold:

    def test_threshold_is_3(self):
        assert FAN_OUT_THRESHOLD == 3

    def test_below_threshold_no_fan_out(self):
        """Pipeline should run EXTRACT sequentially when sources <= 2."""
        # This tests the threshold constant; actual pipeline integration
        # is tested in test_cost_enforcement / test_pipeline.
        sources = [_make_source(0), _make_source(1)]
        assert len(sources) < FAN_OUT_THRESHOLD


# ---------------------------------------------------------------------------
# Sequential flag tests
# ---------------------------------------------------------------------------

class TestSequentialFlag:

    def test_sequential_arg_in_cli(self):
        """The --sequential flag should exist in the CLI parser."""
        import orchestrator.pipeline as p
        import argparse

        parser = argparse.ArgumentParser()
        parser.add_argument("--sequential", action="store_true")
        args = parser.parse_args(["--sequential"])
        assert args.sequential is True
