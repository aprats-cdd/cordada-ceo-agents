"""Tests for structured observability — spans, summaries, JSONL, stats."""

import json
import pytest

from infrastructure.observability import AgentSpan, PipelineObserver, compute_stats


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_span(
    agent_name: str = "discover",
    phase: str = "OBS",
    duration: float = 5.0,
    cost: float = 0.05,
    cumulative_cost: float = 0.05,
    heuristic_score: float = 7.5,
    structural_score: float = 1.0,
    run_id: str = "test_run",
    model: str = "claude-sonnet-4-20250514",
    input_tokens: int = 1000,
    output_tokens: int = 500,
) -> AgentSpan:
    return AgentSpan(
        run_id=run_id,
        agent_name=agent_name,
        phase=phase,
        model=model,
        start_time=100.0,
        end_time=100.0 + duration,
        duration_seconds=duration,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost,
        cumulative_cost_usd=cumulative_cost,
        structural_eval_score=structural_score,
        heuristic_eval_score=heuristic_score,
    )


# ---------------------------------------------------------------------------
# AgentSpan tests
# ---------------------------------------------------------------------------

class TestAgentSpan:

    def test_basic_fields(self):
        span = _make_span()
        assert span.agent_name == "discover"
        assert span.phase == "OBS"
        assert span.duration_seconds == 5.0
        assert span.cost_usd == 0.05

    def test_optional_fields(self):
        span = _make_span()
        assert span.gate_action is None
        assert span.error is None


# ---------------------------------------------------------------------------
# PipelineObserver tests
# ---------------------------------------------------------------------------

class TestPipelineObserver:

    def test_record_adds_span(self):
        obs = PipelineObserver(run_id="test_run")
        span = _make_span()
        obs.record(span)
        assert len(obs.spans) == 1

    def test_summary_empty(self):
        obs = PipelineObserver(run_id="test_run")
        summary = obs.summary()
        assert "test_run" in summary
        assert "No agents" in summary

    def test_summary_with_spans(self):
        obs = PipelineObserver(run_id="run_001")
        obs.record(_make_span("discover", "OBS", 3.0, 0.02, 0.02, 7.5))
        obs.record(_make_span("extract", "OBS", 5.0, 0.03, 0.05, 8.0))
        obs.record(_make_span("compile", "MOD", 8.0, 0.08, 0.13, 7.0))

        summary = obs.summary()
        assert "run_001" in summary
        assert "Costo total: $0.13" in summary
        assert "discover" in summary
        assert "extract" in summary
        assert "compile" in summary
        assert "TOTAL" in summary

    def test_summary_total_cost(self):
        obs = PipelineObserver(run_id="test")
        obs.record(_make_span(cost=0.10))
        obs.record(_make_span(cost=0.20))
        summary = obs.summary()
        assert "$0.30" in summary

    def test_summary_total_time(self):
        obs = PipelineObserver(run_id="test")
        obs.record(_make_span(duration=10.0))
        obs.record(_make_span(duration=20.0))
        summary = obs.summary()
        assert "30s" in summary

    def test_summary_avg_heuristic(self):
        obs = PipelineObserver(run_id="test")
        obs.record(_make_span(heuristic_score=8.0))
        obs.record(_make_span(heuristic_score=6.0))
        summary = obs.summary()
        assert "7.0/10" in summary

    def test_summary_excludes_unscored_from_avg(self):
        obs = PipelineObserver(run_id="test")
        obs.record(_make_span(heuristic_score=8.0))
        obs.record(_make_span(heuristic_score=0.0))  # unscored
        summary = obs.summary()
        assert "8.0/10" in summary  # only scored spans in avg

    def test_summary_no_scored_spans(self):
        obs = PipelineObserver(run_id="test")
        obs.record(_make_span(heuristic_score=0.0))
        summary = obs.summary()
        assert "0.0/10" in summary


# ---------------------------------------------------------------------------
# JSONL persistence tests
# ---------------------------------------------------------------------------

class TestJsonlPersistence:

    def test_to_jsonl_creates_file(self, tmp_path):
        obs = PipelineObserver(run_id="test", output_dir=str(tmp_path))
        obs.record(_make_span("discover"))
        obs.record(_make_span("extract"))

        path = obs.to_jsonl()
        assert "test_spans.jsonl" in path

        lines = open(path).read().strip().split("\n")
        assert len(lines) == 2

        data = json.loads(lines[0])
        assert data["agent_name"] == "discover"

    def test_to_jsonl_custom_path(self, tmp_path):
        obs = PipelineObserver(run_id="test")
        obs.record(_make_span())

        path = obs.to_jsonl(str(tmp_path / "custom_spans.jsonl"))
        assert "custom_spans" in path
        assert (tmp_path / "custom_spans.jsonl").exists()

    def test_roundtrip(self, tmp_path):
        obs = PipelineObserver(run_id="test", output_dir=str(tmp_path))
        obs.record(_make_span("discover", cost=0.05))
        obs.record(_make_span("audit", "DEC", cost=0.10, heuristic_score=8.5))

        path = obs.to_jsonl()
        loaded = PipelineObserver.from_jsonl(path)

        assert len(loaded) == 2
        assert loaded[0].agent_name == "discover"
        assert loaded[0].cost_usd == 0.05
        assert loaded[1].agent_name == "audit"
        assert loaded[1].heuristic_eval_score == 8.5

    def test_empty_observer(self, tmp_path):
        obs = PipelineObserver(run_id="empty", output_dir=str(tmp_path))
        path = obs.to_jsonl()
        loaded = PipelineObserver.from_jsonl(path)
        assert loaded == []


# ---------------------------------------------------------------------------
# compute_stats tests
# ---------------------------------------------------------------------------

class TestComputeStats:

    def _create_run(self, tmp_path, run_id: str, spans: list[AgentSpan]) -> str:
        obs = PipelineObserver(run_id=run_id, output_dir=str(tmp_path))
        for s in spans:
            obs.record(s)
        return obs.to_jsonl()

    def test_single_run(self, tmp_path):
        path = self._create_run(tmp_path, "run1", [
            _make_span("discover", cost=0.05, duration=3.0, heuristic_score=7.0),
            _make_span("audit", "DEC", cost=0.10, duration=8.0, heuristic_score=6.0),
        ])

        stats = compute_stats([path])
        assert stats["runs"] == 1
        assert stats["cost_avg"] == pytest.approx(0.15, abs=0.01)
        assert stats["slowest_agent"] == "audit"
        assert stats["worst_score_agent"] == "audit"

    def test_multiple_runs(self, tmp_path):
        path1 = self._create_run(tmp_path, "run1", [
            _make_span("discover", cost=0.05, run_id="run1"),
        ])
        path2 = self._create_run(tmp_path, "run2", [
            _make_span("discover", cost=0.15, run_id="run2"),
        ])

        stats = compute_stats([path1, path2])
        assert stats["runs"] == 2
        assert stats["cost_avg"] == pytest.approx(0.10, abs=0.01)

    def test_cost_trend_stable(self, tmp_path):
        paths = []
        for i in range(4):
            paths.append(self._create_run(tmp_path, f"run{i}", [
                _make_span(cost=0.10, run_id=f"run{i}"),
            ]))

        stats = compute_stats(paths)
        assert stats["cost_trend"] == "estable"

    def test_cost_trend_increasing(self, tmp_path):
        paths = []
        for i in range(4):
            paths.append(self._create_run(tmp_path, f"run{i}", [
                _make_span(cost=0.05 * (i + 1), run_id=f"run{i}"),
            ]))

        stats = compute_stats(paths)
        assert stats["cost_trend"] == "subiendo"

    def test_cost_trend_decreasing(self, tmp_path):
        paths = []
        costs = [0.20, 0.18, 0.05, 0.03]
        for i, cost in enumerate(costs):
            paths.append(self._create_run(tmp_path, f"run{i}", [
                _make_span(cost=cost, run_id=f"run{i}"),
            ]))

        stats = compute_stats(paths)
        assert stats["cost_trend"] == "bajando"

    def test_no_valid_files(self, tmp_path):
        stats = compute_stats([str(tmp_path / "nonexistent.jsonl")])
        assert "error" in stats

    def test_empty_file_list(self):
        stats = compute_stats([])
        assert "error" in stats
