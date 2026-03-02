"""
Tier 1 Structural Evaluation — automated checks, no LLM calls.

Validates agent outputs against their contract schemas using deterministic
checks. Runs BEFORE the Tier 2 heuristic evaluation (Claude API call)
to save cost when structural requirements aren't met.

Zero external dependencies — pure Python.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .contracts import (
    AGENT_CONTRACTS,
    DiscoverOutput,
    ExtractOutput,
    ValidateOutput,
    CompileOutput,
    AuditOutput,
    ReflectOutput,
    DecideOutput,
)


@dataclass
class StructuralCheck:
    """A single structural check result."""
    name: str
    passed: bool
    detail: str


@dataclass
class StructuralEvaluation:
    """Result of Tier 1 structural evaluation for an agent's output."""
    agent_name: str
    checks: list[StructuralCheck] = field(default_factory=list)
    score: float = 0.0  # 0-1, proportion of checks passed

    @property
    def passed(self) -> bool:
        """70% minimum to proceed to Tier 2."""
        return self.score >= 0.7

    def summary(self) -> str:
        """Human-readable summary."""
        passed = sum(1 for c in self.checks if c.passed)
        total = len(self.checks)
        failed = [c for c in self.checks if not c.passed]
        lines = [f"Tier 1: {passed}/{total} checks passed ({self.score:.0%})"]
        for c in failed:
            lines.append(f"  FAIL: {c.name} — {c.detail}")
        return "\n".join(lines)


def evaluate_structural(agent_name: str, structured_output: dict | None) -> StructuralEvaluation:
    """Run Tier 1 structural checks on an agent's parsed output.

    If structured_output is None (parse failed), returns a single failing check.
    """
    if structured_output is None:
        return StructuralEvaluation(
            agent_name=agent_name,
            checks=[StructuralCheck("contract_parsed", False, "Output could not be parsed to contract schema")],
            score=0.0,
        )

    checker = _CHECKERS.get(agent_name)
    if not checker:
        # Agent has no structural checks — pass by default
        return StructuralEvaluation(agent_name=agent_name, score=1.0)

    checks = checker(structured_output)
    passed = sum(1 for c in checks if c.passed)
    score = passed / len(checks) if checks else 1.0

    return StructuralEvaluation(
        agent_name=agent_name,
        checks=checks,
        score=round(score, 3),
    )


# ---------------------------------------------------------------------------
# Per-agent structural checks
# ---------------------------------------------------------------------------

def _check_discover(data: dict) -> list[StructuralCheck]:
    checks: list[StructuralCheck] = []
    sources = data.get("sources", [])

    checks.append(StructuralCheck(
        "min_sources",
        len(sources) >= 3,
        f"Got {len(sources)} sources (minimum 3)",
    ))

    all_have_url = all(s.get("url") for s in sources)
    checks.append(StructuralCheck(
        "sources_have_url",
        all_have_url,
        "All sources have non-empty url" if all_have_url else "Some sources missing url",
    ))

    scores_valid = all(0 <= s.get("relevance_score", -1) <= 1 for s in sources)
    checks.append(StructuralCheck(
        "relevance_scores_valid",
        scores_valid,
        "All relevance_scores in [0,1]" if scores_valid else "Some scores out of range",
    ))

    coverage = data.get("coverage_assessment", "")
    checks.append(StructuralCheck(
        "coverage_assessment_present",
        bool(coverage),
        "coverage_assessment is present" if coverage else "coverage_assessment is empty",
    ))

    return checks


def _check_extract(data: dict) -> list[StructuralCheck]:
    checks: list[StructuralCheck] = []
    extractions = data.get("extractions", [])
    has_data = len(extractions) > 0

    checks.append(StructuralCheck(
        "has_extractions",
        has_data,
        f"Got {len(extractions)} extractions" if has_data else "No extractions",
    ))

    all_have_ref = has_data and all(e.get("source_ref") for e in extractions)
    checks.append(StructuralCheck(
        "extractions_have_source_ref",
        all_have_ref,
        "All extractions have source_ref" if all_have_ref else "Some missing source_ref",
    ))

    all_have_content = has_data and all(
        e.get("claims") or e.get("data_points")
        for e in extractions
    )
    checks.append(StructuralCheck(
        "extractions_have_content",
        all_have_content,
        "All extractions have claims or data_points" if all_have_content else "Some extractions empty",
    ))

    confidence_valid = has_data and all(0 <= e.get("confidence", -1) <= 1 for e in extractions)
    checks.append(StructuralCheck(
        "confidence_scores_valid",
        confidence_valid,
        "All confidence scores in [0,1]" if confidence_valid else "Some confidence out of range",
    ))

    return checks


def _check_validate(data: dict) -> list[StructuralCheck]:
    checks: list[StructuralCheck] = []
    claims = data.get("validated_claims", [])

    checks.append(StructuralCheck(
        "has_validated_claims",
        len(claims) > 0,
        f"Got {len(claims)} validated claims" if claims else "No validated claims",
    ))

    valid_statuses = {"confirmed", "disputed", "unverifiable", "outdated"}
    all_valid_status = all(c.get("status") in valid_statuses for c in claims)
    checks.append(StructuralCheck(
        "valid_status_values",
        all_valid_status,
        "All statuses valid" if all_valid_status else "Some invalid status values",
    ))

    reliability = data.get("overall_reliability_score", -1)
    checks.append(StructuralCheck(
        "reliability_score_valid",
        0 <= reliability <= 1,
        f"reliability_score={reliability}" + (" (valid)" if 0 <= reliability <= 1 else " (out of range)"),
    ))

    return checks


def _check_compile(data: dict) -> list[StructuralCheck]:
    checks: list[StructuralCheck] = []

    thesis = data.get("main_thesis", "")
    checks.append(StructuralCheck(
        "main_thesis_present",
        bool(thesis),
        "main_thesis is present" if thesis else "main_thesis is empty",
    ))

    arguments = data.get("arguments", [])
    checks.append(StructuralCheck(
        "has_arguments",
        len(arguments) > 0,
        f"Got {len(arguments)} arguments" if arguments else "No arguments",
    ))

    all_have_evidence = all(a.get("supporting_evidence") for a in arguments)
    checks.append(StructuralCheck(
        "arguments_have_evidence",
        all_have_evidence,
        "All arguments have evidence" if all_have_evidence else "Some arguments lack evidence",
    ))

    traceability = data.get("traceability_map", {})
    checks.append(StructuralCheck(
        "traceability_map_present",
        bool(traceability),
        "traceability_map is present" if traceability else "traceability_map is empty",
    ))

    summary = data.get("executive_summary", "")
    checks.append(StructuralCheck(
        "executive_summary_present",
        bool(summary),
        "executive_summary is present" if summary else "executive_summary is empty",
    ))

    return checks


def _check_audit(data: dict) -> list[StructuralCheck]:
    checks: list[StructuralCheck] = []
    dims = data.get("dimensions", [])

    checks.append(StructuralCheck(
        "min_dimensions",
        len(dims) >= 3,
        f"Got {len(dims)} dimensions (minimum 3)",
    ))

    scores_valid = all(1 <= d.get("score", 0) <= 10 for d in dims)
    checks.append(StructuralCheck(
        "dimension_scores_valid",
        scores_valid,
        "All scores in [1,10]" if scores_valid else "Some scores out of range",
    ))

    verdict = data.get("overall_verdict", "")
    checks.append(StructuralCheck(
        "overall_verdict_present",
        bool(verdict),
        "overall_verdict present" if verdict else "overall_verdict empty",
    ))

    return checks


def _check_reflect(data: dict) -> list[StructuralCheck]:
    checks: list[StructuralCheck] = []
    scenarios = data.get("scenarios", [])

    checks.append(StructuralCheck(
        "min_scenarios",
        len(scenarios) >= 2,
        f"Got {len(scenarios)} scenarios (minimum 2)",
    ))

    valid_prob = {"high", "medium", "low"}
    valid_impact = {"severe", "moderate", "minor"}
    all_valid = all(
        s.get("probability") in valid_prob and s.get("impact") in valid_impact
        for s in scenarios
    )
    checks.append(StructuralCheck(
        "scenario_enums_valid",
        all_valid,
        "All probability/impact values valid" if all_valid else "Some invalid enum values",
    ))

    robustness = data.get("robustness_score", -1)
    checks.append(StructuralCheck(
        "robustness_score_valid",
        0 <= robustness <= 1,
        f"robustness_score={robustness}" + (" (valid)" if 0 <= robustness <= 1 else " (out of range)"),
    ))

    return checks


def _check_decide(data: dict) -> list[StructuralCheck]:
    checks: list[StructuralCheck] = []
    options = data.get("options", [])
    count_ok = 2 <= len(options) <= 4

    checks.append(StructuralCheck(
        "option_count",
        count_ok,
        f"Got {len(options)} options (expected 2-4)",
    ))

    all_have_refs = count_ok and all(o.get("model_refs") for o in options)
    checks.append(StructuralCheck(
        "options_have_model_refs",
        all_have_refs,
        "All options reference models" if all_have_refs else "Some options lack model_refs",
    ))

    valid_risk = {"conservative", "moderate", "aggressive"}
    all_valid_risk = count_ok and all(o.get("risk_profile") in valid_risk for o in options)
    checks.append(StructuralCheck(
        "risk_profiles_valid",
        all_valid_risk,
        "All risk_profiles valid" if all_valid_risk else "Some invalid risk_profiles",
    ))

    rec = data.get("recommendation", "")
    checks.append(StructuralCheck(
        "recommendation_present",
        bool(rec),
        "recommendation present" if rec else "recommendation empty",
    ))

    return checks


# Registry of per-agent checker functions
_CHECKERS: dict[str, Any] = {
    "discover": _check_discover,
    "extract": _check_extract,
    "validate": _check_validate,
    "compile": _check_compile,
    "audit": _check_audit,
    "reflect": _check_reflect,
    "decide": _check_decide,
}
