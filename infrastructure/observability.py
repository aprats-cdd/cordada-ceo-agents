"""
Structured Observability — pipeline NAV (Net Asset Value).

Records structured spans for each agent run and produces a summary
that is the P&L of the pipeline. Without NAV, you don't know if you're
generating alpha or destroying value.

Zero heavy dependencies — only stdlib json + logging.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger("cordada.pipeline")


@dataclass
class AgentSpan:
    """Structured record for a single agent execution."""
    run_id: str
    agent_name: str
    phase: str                      # OBS, MOD, DEC
    model: str
    start_time: float
    end_time: float
    duration_seconds: float
    input_tokens: int
    output_tokens: int
    cost_usd: float
    cumulative_cost_usd: float
    structural_eval_score: float = 0.0
    heuristic_eval_score: float = 0.0
    gate_action: Optional[str] = None   # proceed, modify, stop, None
    error: Optional[str] = None


class PipelineObserver:
    """Collects AgentSpans and produces pipeline summaries."""

    def __init__(self, run_id: str, output_dir: str = "outputs/"):
        self.run_id = run_id
        self.output_dir = Path(output_dir)
        self.spans: list[AgentSpan] = []

    def record(self, span: AgentSpan) -> None:
        """Record a completed agent span."""
        self.spans.append(span)
        # Log structured JSON line for external tools
        logger.info(json.dumps(asdict(span), default=str))

    def summary(self) -> str:
        """Generate a CEO-friendly summary of the pipeline run.

        This is the P&L statement — cost, time, quality per agent.
        """
        if not self.spans:
            return f"═══ Pipeline Run: {self.run_id} ═══\n  No agents executed."

        total_cost = sum(s.cost_usd for s in self.spans)
        total_time = sum(s.duration_seconds for s in self.spans)
        scored_spans = [s for s in self.spans if s.heuristic_eval_score > 0]
        avg_heuristic = (
            sum(s.heuristic_eval_score for s in scored_spans) / len(scored_spans)
            if scored_spans else 0
        )

        lines = [
            f"═══ Pipeline Run: {self.run_id} ═══",
            f"Costo total: ${total_cost:.2f}",
            f"Duración total: {total_time:.0f}s",
            f"Señal heurística promedio: {avg_heuristic:.1f}/10",
            f"",
            f"{'Agente':<15} {'Fase':<5} {'Modelo':<12} {'Tiempo':>8} {'Costo':>8} {'Score':>6}",
            f"{'─'*15} {'─'*5} {'─'*12} {'─'*8} {'─'*8} {'─'*6}",
        ]
        for s in self.spans:
            score_str = f"{s.heuristic_eval_score:>5.1f}" if s.heuristic_eval_score > 0 else "  n/a"
            lines.append(
                f"{s.agent_name:<15} {s.phase:<5} "
                f"{s.model:<12} {s.duration_seconds:>7.1f}s "
                f"${s.cost_usd:>6.2f} {score_str}"
            )
        lines.append(f"{'─'*15} {'─'*5} {'─'*12} {'─'*8} {'─'*8} {'─'*6}")
        avg_str = f"{avg_heuristic:>5.1f}" if avg_heuristic > 0 else "  n/a"
        lines.append(
            f"{'TOTAL':<34} {total_time:>7.1f}s "
            f"${total_cost:>6.2f} {avg_str}"
        )

        return "\n".join(lines)

    def to_jsonl(self, path: str | None = None) -> str:
        """Export spans as JSON Lines for downstream analysis.

        Returns the file path written to.
        """
        if path is None:
            path = str(self.output_dir / f"{self.run_id}_spans.jsonl")

        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for span in self.spans:
                f.write(json.dumps(asdict(span), default=str) + "\n")

        return path

    @staticmethod
    def from_jsonl(path: str) -> list[AgentSpan]:
        """Load spans from a JSONL file."""
        spans: list[AgentSpan] = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    data = json.loads(line)
                    spans.append(AgentSpan(**data))
        return spans


def compute_stats(span_files: list[str]) -> dict:
    """Compute aggregate statistics across multiple pipeline runs.

    Args:
        span_files: List of paths to JSONL span files.

    Returns:
        Dict with cost_avg, slowest_agent, worst_score_agent, cost_trend.
    """
    all_runs: list[list[AgentSpan]] = []
    for path in span_files:
        try:
            spans = PipelineObserver.from_jsonl(path)
            if spans:
                all_runs.append(spans)
        except Exception:
            logger.warning("Failed to load spans from %s", path)

    if not all_runs:
        return {"error": "No valid span files found"}

    # Cost per run
    costs = [sum(s.cost_usd for s in run) for run in all_runs]
    cost_avg = sum(costs) / len(costs)

    # Agent performance aggregation
    agent_times: dict[str, list[float]] = {}
    agent_scores: dict[str, list[float]] = {}

    for run in all_runs:
        for span in run:
            agent_times.setdefault(span.agent_name, []).append(span.duration_seconds)
            if span.heuristic_eval_score > 0:
                agent_scores.setdefault(span.agent_name, []).append(span.heuristic_eval_score)

    # Slowest agent (by average duration)
    slowest_agent = max(
        agent_times.items(),
        key=lambda kv: sum(kv[1]) / len(kv[1]),
    )[0] if agent_times else "n/a"

    # Worst scoring agent
    worst_agent = "n/a"
    if agent_scores:
        worst_agent = min(
            agent_scores.items(),
            key=lambda kv: sum(kv[1]) / len(kv[1]),
        )[0]

    # Cost trend (simple: compare first half vs second half)
    trend = "estable"
    if len(costs) >= 4:
        mid = len(costs) // 2
        first_half = sum(costs[:mid]) / mid
        second_half = sum(costs[mid:]) / (len(costs) - mid)
        if second_half > first_half * 1.1:
            trend = "subiendo"
        elif second_half < first_half * 0.9:
            trend = "bajando"

    return {
        "runs": len(all_runs),
        "cost_avg": round(cost_avg, 4),
        "cost_total": round(sum(costs), 4),
        "slowest_agent": slowest_agent,
        "worst_score_agent": worst_agent,
        "cost_trend": trend,
    }
