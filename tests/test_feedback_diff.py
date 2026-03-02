"""Tests for FeedbackDiff — domain model and structural fallback."""

import os
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-test-dummy-key-for-tests")

import pytest
from domain.feedback import FeedbackDiff
from orchestrator.feedback_diff import _structural_diff


# ---------------------------------------------------------------------------
# FeedbackDiff domain model tests
# ---------------------------------------------------------------------------

class TestFeedbackDiffModel:

    def test_is_material_with_new_observations(self):
        diff = FeedbackDiff(
            iteration=2,
            new_observations=["Regulador respondió"],
            changed_assessments=[],
        )
        assert diff.is_material is True

    def test_is_material_with_changed_assessments(self):
        diff = FeedbackDiff(
            iteration=2,
            new_observations=[],
            changed_assessments=["Riesgo legal subió de 6 a 8"],
        )
        assert diff.is_material is True

    def test_is_not_material_with_no_changes(self):
        diff = FeedbackDiff(
            iteration=2,
            new_observations=[],
            changed_assessments=[],
            unchanged_count=14,
        )
        assert diff.is_material is False

    def test_is_not_material_only_removed(self):
        """Removed items alone are not considered material."""
        diff = FeedbackDiff(
            iteration=2,
            new_observations=[],
            changed_assessments=[],
            removed_items=["Old item"],
        )
        assert diff.is_material is False

    def test_format_for_gate_with_changes(self):
        diff = FeedbackDiff(
            iteration=2,
            new_observations=["Regulador CMF respondió", "Stakeholder X opinó"],
            changed_assessments=["Riesgo legal subió de 6 a 8"],
            removed_items=[],
            unchanged_count=14,
            delta_summary="Feedback material: 2 nuevas observaciones, 1 cambio de evaluación.",
        )

        formatted = diff.format_for_gate()
        assert "iteración 2" in formatted
        assert "+ 2 observaciones nuevas" in formatted
        assert "~ 1 assessments cambiaron" in formatted
        assert "= 14 items sin cambios" in formatted
        assert "Regulador CMF" in formatted
        assert "Resumen:" in formatted

    def test_format_for_gate_no_changes(self):
        diff = FeedbackDiff(
            iteration=3,
            unchanged_count=20,
            delta_summary="Sin cambios materiales.",
        )
        formatted = diff.format_for_gate()
        assert "iteración 3" in formatted
        assert "= 20 items sin cambios" in formatted
        assert "observaciones nuevas" not in formatted

    def test_format_for_gate_caps_display_at_5(self):
        """Long lists are capped at 5 items in display."""
        diff = FeedbackDiff(
            iteration=2,
            new_observations=[f"Obs {i}" for i in range(10)],
        )
        formatted = diff.format_for_gate()
        # Should show at most 5 observations
        lines = [l for l in formatted.split("\n") if l.strip().startswith("- Obs")]
        assert len(lines) <= 5

    def test_format_for_event_serialization(self):
        diff = FeedbackDiff(
            iteration=2,
            new_observations=["New obs"],
            changed_assessments=["Changed"],
            removed_items=["Removed"],
            unchanged_count=10,
            delta_summary="Summary",
        )
        data = diff.format_for_event()
        assert data["iteration"] == 2
        assert data["new_observations"] == ["New obs"]
        assert data["changed_assessments"] == ["Changed"]
        assert data["removed_items"] == ["Removed"]
        assert data["unchanged_count"] == 10
        assert data["delta_summary"] == "Summary"
        assert data["is_material"] is True

    def test_format_for_event_not_material(self):
        diff = FeedbackDiff(iteration=1)
        data = diff.format_for_event()
        assert data["is_material"] is False


# ---------------------------------------------------------------------------
# Structural fallback tests
# ---------------------------------------------------------------------------

class TestStructuralDiff:

    def test_detects_added_lines(self):
        prev = "Line 1\nLine 2\nLine 3"
        new = "Line 1\nLine 2\nLine 3\nLine 4\nLine 5"

        diff = _structural_diff(prev, new, iteration=2)
        assert diff.iteration == 2
        assert len(diff.new_observations) == 2  # Line 4, Line 5
        assert diff.unchanged_count == 3

    def test_detects_removed_lines(self):
        prev = "Line 1\nLine 2\nLine 3"
        new = "Line 1"

        diff = _structural_diff(prev, new, iteration=2)
        assert len(diff.removed_items) == 2  # Line 2, Line 3
        assert diff.unchanged_count == 1

    def test_no_changes(self):
        text = "Line 1\nLine 2\nLine 3"
        diff = _structural_diff(text, text, iteration=1)

        assert diff.new_observations == []
        assert diff.removed_items == []
        assert diff.unchanged_count == 3
        assert diff.is_material is False

    def test_complete_replacement(self):
        prev = "Old line 1\nOld line 2"
        new = "New line 1\nNew line 2"

        diff = _structural_diff(prev, new, iteration=2)
        assert len(diff.new_observations) == 2
        assert len(diff.removed_items) == 2
        assert diff.unchanged_count == 0

    def test_delta_summary_format(self):
        prev = "A\nB\nC"
        new = "A\nD"

        diff = _structural_diff(prev, new, iteration=2)
        assert "Diff estructural" in diff.delta_summary
        assert "+" in diff.delta_summary
        assert "-" in diff.delta_summary

    def test_empty_inputs(self):
        diff = _structural_diff("", "", iteration=1)
        assert diff.unchanged_count >= 0
        assert not diff.is_material

    def test_large_diff_caps_at_10(self):
        """Structural diff caps new_observations and removed_items at 10."""
        prev = "\n".join(f"Old {i}" for i in range(20))
        new = "\n".join(f"New {i}" for i in range(20))

        diff = _structural_diff(prev, new, iteration=2)
        assert len(diff.new_observations) <= 10
        assert len(diff.removed_items) <= 10
