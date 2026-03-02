"""
Calibration Bank — track record for heuristic evaluation scores.

Stores CEO-scored examples alongside Claude's heuristic scores to measure
correlation and drift over time. Without calibration, heuristic scores are
backtests without live performance.

Zero external dependencies — pure Python + json.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class CalibrationExample:
    """A single calibration data point: human vs heuristic score."""
    agent_name: str
    input_summary: str
    output_text: str
    human_score: float        # score given by CEO (1-10)
    heuristic_score: float    # score given by Claude (1-10)
    delta: float              # human - heuristic
    timestamp: str


class CalibrationBank:
    """Persistent store for calibration examples.

    Examples are stored as JSONL (one JSON object per line) in
    ``{path}/{agent_name}.jsonl``.

    Think of this as the track record of the evaluation model.
    Without it, the heuristic scores are backtests without live performance.
    """

    def __init__(self, path: str = "calibration/"):
        self._dir = Path(path)
        self._dir.mkdir(parents=True, exist_ok=True)

    def add(self, example: CalibrationExample) -> None:
        """Persist a calibration example."""
        file_path = self._dir / f"{example.agent_name}.jsonl"
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(example), ensure_ascii=False) + "\n")

    def examples(self, agent_name: str) -> list[CalibrationExample]:
        """Load all examples for an agent."""
        file_path = self._dir / f"{agent_name}.jsonl"
        if not file_path.exists():
            return []
        results: list[CalibrationExample] = []
        for line in file_path.read_text(encoding="utf-8").strip().split("\n"):
            if line.strip():
                data = json.loads(line)
                results.append(CalibrationExample(**data))
        return results

    def correlation(self, agent_name: str) -> Optional[float]:
        """Pearson correlation between human and heuristic scores.

        Returns None if fewer than 5 examples (not statistically meaningful).
        """
        exs = self.examples(agent_name)
        if len(exs) < 5:
            return None

        human = [e.human_score for e in exs]
        heuristic = [e.heuristic_score for e in exs]

        return _pearson(human, heuristic)

    def drift_report(self) -> dict[str, dict]:
        """Per-agent drift report: mean delta, stddev, correlation, N examples.

        Returns dict[agent_name → {"mean_delta", "stddev", "correlation", "n"}].
        """
        report: dict[str, dict] = {}

        for f in sorted(self._dir.glob("*.jsonl")):
            agent_name = f.stem
            exs = self.examples(agent_name)
            if not exs:
                continue

            deltas = [e.delta for e in exs]
            mean_delta = sum(deltas) / len(deltas)
            variance = sum((d - mean_delta) ** 2 for d in deltas) / len(deltas)
            stddev = math.sqrt(variance)

            report[agent_name] = {
                "mean_delta": round(mean_delta, 2),
                "stddev": round(stddev, 2),
                "correlation": self.correlation(agent_name),
                "n": len(exs),
            }

        return report

    def format_report(self) -> str:
        """Human-readable drift report."""
        report = self.drift_report()
        if not report:
            return "No calibration data available."

        lines = [
            f"{'Agent':<20} {'N':>4} {'Mean Δ':>8} {'StdDev':>8} {'Corr':>8}",
            f"{'─'*20} {'─'*4} {'─'*8} {'─'*8} {'─'*8}",
        ]

        for agent, data in report.items():
            corr_str = f"{data['correlation']:.2f}" if data["correlation"] is not None else "n/a"
            lines.append(
                f"{agent:<20} {data['n']:>4} "
                f"{data['mean_delta']:>+7.2f} {data['stddev']:>7.2f} {corr_str:>8}"
            )

        return "\n".join(lines)

    def format_inline(self, agent_name: str) -> str:
        """Inline calibration note for pipeline output.

        Returns string like "(calibración: r=0.83, N=12, drift medio=+0.4)"
        or "(no calibrada)" if insufficient data.
        """
        corr = self.correlation(agent_name)
        exs = self.examples(agent_name)

        if corr is None:
            return "(no calibrada)"

        deltas = [e.delta for e in exs]
        mean_delta = sum(deltas) / len(deltas)

        return f"(calibración: r={corr:.2f}, N={len(exs)}, drift medio={mean_delta:+.1f})"


def _pearson(x: list[float], y: list[float]) -> Optional[float]:
    """Pearson correlation coefficient. Returns None if undefined."""
    n = len(x)
    if n < 2:
        return None

    mean_x = sum(x) / n
    mean_y = sum(y) / n

    num = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
    den_x = math.sqrt(sum((xi - mean_x) ** 2 for xi in x))
    den_y = math.sqrt(sum((yi - mean_y) ** 2 for yi in y))

    if den_x == 0 or den_y == 0:
        return None

    return round(num / (den_x * den_y), 4)
