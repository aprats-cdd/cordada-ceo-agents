"""Tests for Tier 1 structural evaluation — deterministic, no LLM calls."""

import pytest
from domain.evaluation import evaluate_structural, StructuralCheck, StructuralEvaluation


# ---------------------------------------------------------------------------
# Helpers — minimal valid outputs for each agent
# ---------------------------------------------------------------------------

def _valid_discover():
    return {
        "sources": [
            {"url": "http://a.com", "title": "A", "source_type": "news",
             "relevance_score": 0.9, "freshness": "current", "brief": "A"},
            {"url": "http://b.com", "title": "B", "source_type": "regulatory",
             "relevance_score": 0.8, "freshness": "recent", "brief": "B"},
            {"url": "http://c.com", "title": "C", "source_type": "market_data",
             "relevance_score": 0.7, "freshness": "dated", "brief": "C"},
        ],
        "search_queries_used": ["query"],
        "coverage_assessment": "Good coverage.",
    }


def _valid_extract():
    return {
        "extractions": [
            {"source_ref": "http://a.com", "claims": ["c1"], "data_points": [], "quotes": [], "confidence": 0.9},
            {"source_ref": "http://b.com", "claims": ["c2"], "data_points": [{"label": "x", "value": "1", "unit": "m"}], "quotes": [], "confidence": 0.8},
        ],
        "gaps_identified": [],
    }


def _valid_validate():
    return {
        "validated_claims": [
            {"claim": "c1", "status": "confirmed", "confidence": 0.9, "issues": [], "source_refs": ["a"]},
        ],
        "overall_reliability_score": 0.85,
        "bias_flags": [],
    }


def _valid_compile():
    return {
        "main_thesis": "Thesis",
        "arguments": [
            {"thesis": "arg1", "supporting_evidence": ["ev1"], "strength": "strong"},
        ],
        "traceability_map": {"ev1": "source chain"},
        "executive_summary": "Summary.",
    }


def _valid_audit():
    return {
        "dimensions": [
            {"dimension": "financial", "score": 8.0, "findings": ["f"], "risks": ["r"]},
            {"dimension": "regulatory", "score": 7.0, "findings": ["f"], "risks": ["r"]},
            {"dimension": "operational", "score": 6.0, "findings": ["f"], "risks": ["r"]},
        ],
        "overall_verdict": "Positive.",
        "blocking_issues": [],
    }


def _valid_reflect():
    return {
        "scenarios": [
            {"name": "Base", "probability": "high", "impact": "moderate",
             "assumptions_challenged": ["a"], "mitigation": "m"},
            {"name": "Adverse", "probability": "low", "impact": "severe",
             "assumptions_challenged": ["b"], "mitigation": "m2"},
        ],
        "robustness_score": 0.75,
        "key_vulnerabilities": ["v1"],
    }


def _valid_decide():
    return {
        "options": [
            {"label": "A", "description": "d", "pros": ["p"], "cons": ["c"],
             "risk_profile": "moderate", "estimated_impact": "e", "model_refs": ["m1"]},
            {"label": "B", "description": "d", "pros": ["p"], "cons": ["c"],
             "risk_profile": "conservative", "estimated_impact": "e", "model_refs": ["m2"]},
        ],
        "recommendation": "Go with A.",
        "trade_off_summary": "A vs B.",
    }


# ---------------------------------------------------------------------------
# Valid outputs → all checks pass
# ---------------------------------------------------------------------------

class TestStructuralEvalValid:

    def test_discover_passes(self):
        result = evaluate_structural("discover", _valid_discover())
        assert result.passed
        assert result.score == 1.0
        assert all(c.passed for c in result.checks)

    def test_extract_passes(self):
        result = evaluate_structural("extract", _valid_extract())
        assert result.passed
        assert result.score == 1.0

    def test_validate_passes(self):
        result = evaluate_structural("validate", _valid_validate())
        assert result.passed

    def test_compile_passes(self):
        result = evaluate_structural("compile", _valid_compile())
        assert result.passed
        assert result.score == 1.0

    def test_audit_passes(self):
        result = evaluate_structural("audit", _valid_audit())
        assert result.passed

    def test_reflect_passes(self):
        result = evaluate_structural("reflect", _valid_reflect())
        assert result.passed

    def test_decide_passes(self):
        result = evaluate_structural("decide", _valid_decide())
        assert result.passed


# ---------------------------------------------------------------------------
# Invalid outputs → checks fail appropriately
# ---------------------------------------------------------------------------

class TestStructuralEvalFails:

    def test_discover_too_few_sources(self):
        data = _valid_discover()
        data["sources"] = data["sources"][:1]
        result = evaluate_structural("discover", data)
        # 1/4 check fails (min_sources), 3/4 pass = 75% ≥ 70% threshold
        assert result.passed  # still passes threshold but has failure
        failed = [c for c in result.checks if not c.passed]
        assert any("min_sources" in c.name for c in failed)

    def test_discover_empty_url(self):
        data = _valid_discover()
        data["sources"][0]["url"] = ""
        result = evaluate_structural("discover", data)
        failed = [c for c in result.checks if not c.passed]
        assert any("url" in c.name for c in failed)

    def test_discover_bad_relevance(self):
        data = _valid_discover()
        data["sources"][0]["relevance_score"] = 1.5
        result = evaluate_structural("discover", data)
        failed = [c for c in result.checks if not c.passed]
        assert any("relevance" in c.name for c in failed)

    def test_extract_no_extractions(self):
        result = evaluate_structural("extract", {"extractions": [], "gaps_identified": []})
        assert not result.passed  # 0/4 checks pass = 0% (vacuous truth fixed)

    def test_extract_missing_source_ref(self):
        data = _valid_extract()
        data["extractions"][0]["source_ref"] = ""
        result = evaluate_structural("extract", data)
        failed = [c for c in result.checks if not c.passed]
        assert any("source_ref" in c.name for c in failed)

    def test_validate_bad_status(self):
        data = _valid_validate()
        data["validated_claims"][0]["status"] = "maybe"
        result = evaluate_structural("validate", data)
        failed = [c for c in result.checks if not c.passed]
        assert any("status" in c.name for c in failed)

    def test_compile_no_thesis(self):
        data = _valid_compile()
        data["main_thesis"] = ""
        result = evaluate_structural("compile", data)
        failed = [c for c in result.checks if not c.passed]
        assert any("thesis" in c.name for c in failed)

    def test_audit_too_few_dimensions(self):
        data = _valid_audit()
        data["dimensions"] = data["dimensions"][:2]
        result = evaluate_structural("audit", data)
        failed = [c for c in result.checks if not c.passed]
        assert any("dimension" in c.name for c in failed)

    def test_audit_score_out_of_range(self):
        data = _valid_audit()
        data["dimensions"][0]["score"] = 11
        result = evaluate_structural("audit", data)
        failed = [c for c in result.checks if not c.passed]
        assert any("score" in c.name for c in failed)

    def test_reflect_one_scenario(self):
        data = _valid_reflect()
        data["scenarios"] = data["scenarios"][:1]
        result = evaluate_structural("reflect", data)
        assert not result.passed

    def test_decide_one_option(self):
        data = _valid_decide()
        data["options"] = data["options"][:1]
        result = evaluate_structural("decide", data)
        assert not result.passed

    def test_decide_no_model_refs(self):
        data = _valid_decide()
        data["options"][0]["model_refs"] = []
        result = evaluate_structural("decide", data)
        failed = [c for c in result.checks if not c.passed]
        assert any("model_refs" in c.name for c in failed)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestStructuralEvalEdgeCases:

    def test_none_structured_output(self):
        """None structured output → single failing check."""
        result = evaluate_structural("discover", None)
        assert not result.passed
        assert result.score == 0.0
        assert len(result.checks) == 1
        assert not result.checks[0].passed

    def test_unknown_agent_passes(self):
        """Agents without checkers pass by default."""
        result = evaluate_structural("context", {"whatever": "data"})
        assert result.passed
        assert result.score == 1.0

    def test_summary_format(self):
        """Summary includes check counts and failure details."""
        data = _valid_discover()
        data["coverage_assessment"] = ""
        result = evaluate_structural("discover", data)
        summary = result.summary()
        assert "3/4" in summary
        assert "FAIL" in summary
        assert "coverage" in summary.lower()

    def test_passed_threshold(self):
        """70% is the minimum to pass."""
        # 3 out of 4 checks = 75% → passes
        data = _valid_discover()
        data["coverage_assessment"] = ""
        result = evaluate_structural("discover", data)
        assert result.score == 0.75
        assert result.passed  # 75% >= 70%

    def test_exactly_70_percent(self):
        """Exactly 70% passes."""
        eval_ = StructuralEvaluation(agent_name="test", score=0.7)
        assert eval_.passed

    def test_below_70_percent(self):
        """Below 70% fails."""
        eval_ = StructuralEvaluation(agent_name="test", score=0.69)
        assert not eval_.passed
