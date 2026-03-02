"""Tests for CalibrationBank — add, correlation, drift_report."""

import json
import pytest
from domain.calibration import CalibrationBank, CalibrationExample, _pearson


def _make_example(agent: str, human: float, heuristic: float, i: int = 0) -> CalibrationExample:
    return CalibrationExample(
        agent_name=agent,
        input_summary=f"input_{i}",
        output_text=f"output_{i}",
        human_score=human,
        heuristic_score=heuristic,
        delta=human - heuristic,
        timestamp=f"2025-01-{i+1:02d}T00:00:00",
    )


class TestCalibrationBankAdd:

    def test_add_creates_file(self, tmp_path):
        bank = CalibrationBank(str(tmp_path))
        ex = _make_example("discover", 8.0, 7.5)
        bank.add(ex)

        file = tmp_path / "discover.jsonl"
        assert file.exists()
        data = json.loads(file.read_text().strip())
        assert data["agent_name"] == "discover"
        assert data["human_score"] == 8.0

    def test_add_appends(self, tmp_path):
        bank = CalibrationBank(str(tmp_path))
        bank.add(_make_example("discover", 8.0, 7.5, 0))
        bank.add(_make_example("discover", 6.0, 7.0, 1))

        file = tmp_path / "discover.jsonl"
        lines = file.read_text().strip().split("\n")
        assert len(lines) == 2

    def test_examples_returns_all(self, tmp_path):
        bank = CalibrationBank(str(tmp_path))
        for i in range(5):
            bank.add(_make_example("audit", 7.0 + i * 0.5, 6.5 + i * 0.3, i))

        exs = bank.examples("audit")
        assert len(exs) == 5
        assert exs[0].agent_name == "audit"

    def test_examples_empty(self, tmp_path):
        bank = CalibrationBank(str(tmp_path))
        assert bank.examples("nonexistent") == []


class TestCalibrationCorrelation:

    def test_returns_none_below_5(self, tmp_path):
        bank = CalibrationBank(str(tmp_path))
        for i in range(4):
            bank.add(_make_example("discover", 7.0 + i, 6.5 + i, i))
        assert bank.correlation("discover") is None

    def test_perfect_correlation(self, tmp_path):
        bank = CalibrationBank(str(tmp_path))
        for i in range(10):
            bank.add(_make_example("discover", 5.0 + i, 5.0 + i, i))  # identical scores
        corr = bank.correlation("discover")
        assert corr is not None
        assert corr == pytest.approx(1.0, abs=0.01)

    def test_strong_positive_correlation(self, tmp_path):
        bank = CalibrationBank(str(tmp_path))
        pairs = [(5, 4), (6, 5.5), (7, 6.8), (8, 7.5), (9, 8.2), (10, 9)]
        for i, (h, he) in enumerate(pairs):
            bank.add(_make_example("audit", h, he, i))
        corr = bank.correlation("audit")
        assert corr is not None
        assert corr > 0.95

    def test_negative_correlation(self, tmp_path):
        bank = CalibrationBank(str(tmp_path))
        pairs = [(10, 1), (9, 2), (8, 3), (7, 4), (6, 5)]
        for i, (h, he) in enumerate(pairs):
            bank.add(_make_example("reflect", h, he, i))
        corr = bank.correlation("reflect")
        assert corr is not None
        assert corr < -0.9


class TestCalibrationDriftReport:

    def test_drift_report_structure(self, tmp_path):
        bank = CalibrationBank(str(tmp_path))
        for i in range(6):
            bank.add(_make_example("discover", 6.0 + i * 0.5, 5.0 + i * 0.5, i))

        report = bank.drift_report()
        assert "discover" in report
        assert report["discover"]["mean_delta"] == 1.0
        assert report["discover"]["n"] == 6
        assert report["discover"]["correlation"] is not None

    def test_empty_report(self, tmp_path):
        bank = CalibrationBank(str(tmp_path))
        assert bank.drift_report() == {}

    def test_format_report(self, tmp_path):
        bank = CalibrationBank(str(tmp_path))
        for i in range(6):
            bank.add(_make_example("discover", 7.0, 6.5, i))

        formatted = bank.format_report()
        assert "discover" in formatted
        assert "Mean" in formatted

    def test_format_inline_no_data(self, tmp_path):
        bank = CalibrationBank(str(tmp_path))
        assert bank.format_inline("discover") == "(no calibrada)"

    def test_format_inline_with_data(self, tmp_path):
        bank = CalibrationBank(str(tmp_path))
        for i in range(6):
            bank.add(_make_example("discover", 7.0 + i * 0.5, 6.5 + i * 0.5, i))

        inline = bank.format_inline("discover")
        assert "r=" in inline
        assert "N=6" in inline
        assert "drift" in inline


class TestPearson:

    def test_empty_returns_none(self):
        assert _pearson([], []) is None

    def test_single_returns_none(self):
        assert _pearson([1.0], [1.0]) is None

    def test_constant_returns_none(self):
        assert _pearson([5, 5, 5], [1, 2, 3]) is None  # zero variance in x

    def test_perfect_correlation(self):
        assert _pearson([1, 2, 3, 4, 5], [1, 2, 3, 4, 5]) == pytest.approx(1.0)

    def test_perfect_negative(self):
        assert _pearson([1, 2, 3, 4, 5], [5, 4, 3, 2, 1]) == pytest.approx(-1.0)
