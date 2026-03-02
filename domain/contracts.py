"""
Inter-Agent Contracts — structured output schemas for the pipeline.

Each agent in the pipeline has a typed output contract.  Contracts are
dataclasses with ``validate()`` (returns error list), ``to_json()``, and
``from_json()`` for serialization.

Zero external dependencies — only stdlib.  These are the term sheets
of the pipeline: without a term sheet, there is no deal.

Contracts covered:
    DiscoverOutput   — source catalog
    ExtractOutput    — extraction cards
    ValidateOutput   — validated claims
    CompileOutput    — structured document
    AuditOutput      — multi-expert review
    ReflectOutput    — stress-test scenarios
    DecideOutput     — decision options
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Any


# ---------------------------------------------------------------------------
# DISCOVER — source catalog
# ---------------------------------------------------------------------------

@dataclass
class SourceCard:
    """A single source identified by DISCOVER."""
    url: str
    title: str
    source_type: str          # "regulatory", "market_data", "internal", "news", "academic"
    relevance_score: float    # 0-1
    freshness: str            # "current", "recent", "dated"
    brief: str                # 1-2 sentences

    _VALID_TYPES = {"regulatory", "market_data", "internal", "news", "academic"}
    _VALID_FRESHNESS = {"current", "recent", "dated"}


@dataclass
class DiscoverOutput:
    """Output contract for the DISCOVER agent."""
    sources: list[SourceCard] = field(default_factory=list)
    search_queries_used: list[str] = field(default_factory=list)
    coverage_assessment: str = ""

    def validate(self) -> list[str]:
        """Return list of validation errors (empty = valid)."""
        errors: list[str] = []
        if len(self.sources) < 3:
            errors.append(f"At least 3 sources required, got {len(self.sources)}")
        for i, s in enumerate(self.sources):
            if not s.url:
                errors.append(f"Source [{i}]: url is empty")
            if not (0 <= s.relevance_score <= 1):
                errors.append(f"Source [{i}]: relevance_score {s.relevance_score} not in [0,1]")
            if s.freshness not in SourceCard._VALID_FRESHNESS:
                errors.append(f"Source [{i}]: invalid freshness '{s.freshness}'")
        if not self.coverage_assessment:
            errors.append("coverage_assessment is empty")
        return errors

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, raw: str) -> "DiscoverOutput":
        data = json.loads(raw)
        sources = [SourceCard(**s) for s in data.get("sources", [])]
        return cls(
            sources=sources,
            search_queries_used=data.get("search_queries_used", []),
            coverage_assessment=data.get("coverage_assessment", ""),
        )


# ---------------------------------------------------------------------------
# EXTRACT — extraction cards
# ---------------------------------------------------------------------------

@dataclass
class Extraction:
    """A single extraction from one source."""
    source_ref: str            # url or id of SourceCard
    claims: list[str] = field(default_factory=list)
    data_points: list[dict] = field(default_factory=list)  # {"label", "value", "unit"}
    quotes: list[str] = field(default_factory=list)
    confidence: float = 0.0    # 0-1


@dataclass
class ExtractOutput:
    """Output contract for the EXTRACT agent."""
    extractions: list[Extraction] = field(default_factory=list)
    gaps_identified: list[str] = field(default_factory=list)

    def validate(self, upstream_sources: list[str] | None = None) -> list[str]:
        """Validate extract output, optionally cross-referencing upstream sources."""
        errors: list[str] = []
        if not self.extractions:
            errors.append("No extractions produced")
        for i, ext in enumerate(self.extractions):
            if not ext.source_ref:
                errors.append(f"Extraction [{i}]: source_ref is empty")
            if not ext.claims and not ext.data_points:
                errors.append(f"Extraction [{i}]: no claims or data_points")
            if not (0 <= ext.confidence <= 1):
                errors.append(f"Extraction [{i}]: confidence {ext.confidence} not in [0,1]")
            if upstream_sources and ext.source_ref not in upstream_sources:
                errors.append(f"Extraction [{i}]: source_ref '{ext.source_ref}' not in upstream sources")
        return errors

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, raw: str) -> "ExtractOutput":
        data = json.loads(raw)
        extractions = [Extraction(**e) for e in data.get("extractions", [])]
        return cls(
            extractions=extractions,
            gaps_identified=data.get("gaps_identified", []),
        )


# ---------------------------------------------------------------------------
# VALIDATE — validated claims
# ---------------------------------------------------------------------------

@dataclass
class ValidatedClaim:
    """A single validated claim."""
    claim: str
    status: str               # "confirmed", "disputed", "unverifiable", "outdated"
    confidence: float         # 0-1
    issues: list[str] = field(default_factory=list)
    source_refs: list[str] = field(default_factory=list)

    _VALID_STATUS = {"confirmed", "disputed", "unverifiable", "outdated"}


@dataclass
class ValidateOutput:
    """Output contract for the VALIDATE agent."""
    validated_claims: list[ValidatedClaim] = field(default_factory=list)
    overall_reliability_score: float = 0.0
    bias_flags: list[str] = field(default_factory=list)

    def validate(self, upstream_claims: list[str] | None = None) -> list[str]:
        """Validate output, optionally checking claim coverage."""
        errors: list[str] = []
        if not self.validated_claims:
            errors.append("No validated claims")
        for i, vc in enumerate(self.validated_claims):
            if vc.status not in ValidatedClaim._VALID_STATUS:
                errors.append(f"Claim [{i}]: invalid status '{vc.status}'")
            if not (0 <= vc.confidence <= 1):
                errors.append(f"Claim [{i}]: confidence {vc.confidence} not in [0,1]")
        if not (0 <= self.overall_reliability_score <= 1):
            errors.append(f"overall_reliability_score {self.overall_reliability_score} not in [0,1]")
        # Cross-reference: at least 50% of upstream claims should be validated
        if upstream_claims:
            validated_texts = {vc.claim for vc in self.validated_claims}
            covered = sum(1 for c in upstream_claims if c in validated_texts)
            if covered < len(upstream_claims) * 0.5:
                errors.append(
                    f"Only {covered}/{len(upstream_claims)} upstream claims validated "
                    f"(minimum 50% required)"
                )
        return errors

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, raw: str) -> "ValidateOutput":
        data = json.loads(raw)
        claims = [ValidatedClaim(**c) for c in data.get("validated_claims", [])]
        return cls(
            validated_claims=claims,
            overall_reliability_score=data.get("overall_reliability_score", 0.0),
            bias_flags=data.get("bias_flags", []),
        )


# ---------------------------------------------------------------------------
# COMPILE — structured document
# ---------------------------------------------------------------------------

@dataclass
class Argument:
    """A single argument in the compiled document."""
    thesis: str
    supporting_evidence: list[str] = field(default_factory=list)  # refs to ValidatedClaims
    strength: str = "moderate"  # "strong", "moderate", "weak"

    _VALID_STRENGTH = {"strong", "moderate", "weak"}


@dataclass
class CompileOutput:
    """Output contract for the COMPILE agent."""
    main_thesis: str = ""
    arguments: list[Argument] = field(default_factory=list)
    traceability_map: dict = field(default_factory=dict)  # claim_id → source chain
    executive_summary: str = ""

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.main_thesis:
            errors.append("main_thesis is empty")
        if not self.arguments:
            errors.append("No arguments")
        for i, arg in enumerate(self.arguments):
            if not arg.supporting_evidence:
                errors.append(f"Argument [{i}]: no supporting_evidence")
            if arg.strength not in Argument._VALID_STRENGTH:
                errors.append(f"Argument [{i}]: invalid strength '{arg.strength}'")
        if not self.traceability_map:
            errors.append("traceability_map is empty")
        if not self.executive_summary:
            errors.append("executive_summary is empty")
        return errors

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, raw: str) -> "CompileOutput":
        data = json.loads(raw)
        arguments = [Argument(**a) for a in data.get("arguments", [])]
        return cls(
            main_thesis=data.get("main_thesis", ""),
            arguments=arguments,
            traceability_map=data.get("traceability_map", {}),
            executive_summary=data.get("executive_summary", ""),
        )


# ---------------------------------------------------------------------------
# AUDIT — multi-expert review
# ---------------------------------------------------------------------------

@dataclass
class AuditDimension:
    """A single dimension in the audit review."""
    dimension: str            # "legal", "financial", "regulatory", "operational", "reputational"
    score: float              # 1-10
    findings: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)


@dataclass
class AuditOutput:
    """Output contract for the AUDIT agent."""
    dimensions: list[AuditDimension] = field(default_factory=list)
    overall_verdict: str = ""
    blocking_issues: list[str] = field(default_factory=list)

    def validate(self) -> list[str]:
        errors: list[str] = []
        if len(self.dimensions) < 3:
            errors.append(f"At least 3 dimensions required, got {len(self.dimensions)}")
        for i, d in enumerate(self.dimensions):
            if not (1 <= d.score <= 10):
                errors.append(f"Dimension [{i}] '{d.dimension}': score {d.score} not in [1,10]")
        if not self.overall_verdict:
            errors.append("overall_verdict is empty")
        return errors

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, raw: str) -> "AuditOutput":
        data = json.loads(raw)
        dims = [AuditDimension(**d) for d in data.get("dimensions", [])]
        return cls(
            dimensions=dims,
            overall_verdict=data.get("overall_verdict", ""),
            blocking_issues=data.get("blocking_issues", []),
        )


# ---------------------------------------------------------------------------
# REFLECT — stress-test scenarios
# ---------------------------------------------------------------------------

@dataclass
class Scenario:
    """A single stress-test scenario."""
    name: str
    probability: str          # "high", "medium", "low"
    impact: str               # "severe", "moderate", "minor"
    assumptions_challenged: list[str] = field(default_factory=list)
    mitigation: str = ""

    _VALID_PROBABILITY = {"high", "medium", "low"}
    _VALID_IMPACT = {"severe", "moderate", "minor"}


@dataclass
class ReflectOutput:
    """Output contract for the REFLECT agent."""
    scenarios: list[Scenario] = field(default_factory=list)
    robustness_score: float = 0.0
    key_vulnerabilities: list[str] = field(default_factory=list)

    def validate(self) -> list[str]:
        errors: list[str] = []
        if len(self.scenarios) < 2:
            errors.append(f"At least 2 scenarios required, got {len(self.scenarios)}")
        for i, s in enumerate(self.scenarios):
            if s.probability not in Scenario._VALID_PROBABILITY:
                errors.append(f"Scenario [{i}] '{s.name}': invalid probability '{s.probability}'")
            if s.impact not in Scenario._VALID_IMPACT:
                errors.append(f"Scenario [{i}] '{s.name}': invalid impact '{s.impact}'")
        if not (0 <= self.robustness_score <= 1):
            errors.append(f"robustness_score {self.robustness_score} not in [0,1]")
        return errors

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, raw: str) -> "ReflectOutput":
        data = json.loads(raw)
        scenarios = [Scenario(**s) for s in data.get("scenarios", [])]
        return cls(
            scenarios=scenarios,
            robustness_score=data.get("robustness_score", 0.0),
            key_vulnerabilities=data.get("key_vulnerabilities", []),
        )


# ---------------------------------------------------------------------------
# DECIDE — decision options
# ---------------------------------------------------------------------------

@dataclass
class DecisionOption:
    """A single decision option presented to the CEO."""
    label: str
    description: str
    pros: list[str] = field(default_factory=list)
    cons: list[str] = field(default_factory=list)
    risk_profile: str = "moderate"   # "conservative", "moderate", "aggressive"
    estimated_impact: str = ""
    model_refs: list[str] = field(default_factory=list)  # refs to COMPILE arguments

    _VALID_RISK = {"conservative", "moderate", "aggressive"}


@dataclass
class DecideOutput:
    """Output contract for the DECIDE agent."""
    options: list[DecisionOption] = field(default_factory=list)  # 2-3 options
    recommendation: str = ""
    trade_off_summary: str = ""

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not (2 <= len(self.options) <= 4):
            errors.append(f"Expected 2-4 options, got {len(self.options)}")
        for i, opt in enumerate(self.options):
            if not opt.model_refs:
                errors.append(f"Option [{i}] '{opt.label}': no model_refs (must reference COMPILE arguments)")
            if opt.risk_profile not in DecisionOption._VALID_RISK:
                errors.append(f"Option [{i}] '{opt.label}': invalid risk_profile '{opt.risk_profile}'")
        if not self.recommendation:
            errors.append("recommendation is empty")
        return errors

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, raw: str) -> "DecideOutput":
        data = json.loads(raw)
        options = [DecisionOption(**o) for o in data.get("options", [])]
        return cls(
            options=options,
            recommendation=data.get("recommendation", ""),
            trade_off_summary=data.get("trade_off_summary", ""),
        )


# ---------------------------------------------------------------------------
# Contract registry — maps agent names to their output contract class
# ---------------------------------------------------------------------------

AGENT_CONTRACTS: dict[str, type] = {
    "discover": DiscoverOutput,
    "extract": ExtractOutput,
    "validate": ValidateOutput,
    "compile": CompileOutput,
    "audit": AuditOutput,
    "reflect": ReflectOutput,
    "decide": DecideOutput,
}
