"""Tests for inter-agent contracts — serialization, validation, cross-references."""

import json
import pytest

from domain.contracts import (
    SourceCard, DiscoverOutput,
    Extraction, ExtractOutput,
    ValidatedClaim, ValidateOutput,
    Argument, CompileOutput,
    AuditDimension, AuditOutput,
    Scenario, ReflectOutput,
    DecisionOption, DecideOutput,
    AGENT_CONTRACTS,
)


# ---------------------------------------------------------------------------
# Fixtures — valid instances for each contract
# ---------------------------------------------------------------------------

def _valid_discover():
    return DiscoverOutput(
        sources=[
            SourceCard("https://a.com", "Source A", "regulatory", 0.9, "current", "Relevant source"),
            SourceCard("https://b.com", "Source B", "market_data", 0.7, "recent", "Market data"),
            SourceCard("https://c.com", "Source C", "news", 0.5, "dated", "News article"),
        ],
        search_queries_used=["deuda privada LatAm", "regulatory framework"],
        coverage_assessment="Good coverage of regulatory and market sources, lacking academic.",
    )


def _valid_extract(source_refs=None):
    refs = source_refs or ["https://a.com", "https://b.com"]
    return ExtractOutput(
        extractions=[
            Extraction(refs[0], ["claim1", "claim2"], [{"label": "AUM", "value": "218", "unit": "M USD"}], [], 0.9),
            Extraction(refs[1], ["claim3"], [{"label": "Rate", "value": "8.5", "unit": "%"}], ["quote1"], 0.8),
        ],
        gaps_identified=["No data on operational risk"],
    )


def _valid_validate():
    return ValidateOutput(
        validated_claims=[
            ValidatedClaim("claim1", "confirmed", 0.95, [], ["https://a.com"]),
            ValidatedClaim("claim2", "disputed", 0.4, ["Contradicted by source B"], ["https://a.com", "https://b.com"]),
            ValidatedClaim("claim3", "confirmed", 0.85, [], ["https://b.com"]),
        ],
        overall_reliability_score=0.73,
        bias_flags=["Potential selection bias in source A"],
    )


def _valid_compile():
    return CompileOutput(
        main_thesis="La deuda privada LatAm ofrece oportunidad ajustada por riesgo superior.",
        arguments=[
            Argument("Rendimientos atractivos", ["claim1", "claim3"], "strong"),
            Argument("Marco regulatorio favorable", ["claim2"], "moderate"),
        ],
        traceability_map={"claim1": "a.com → extraction1 → validated", "claim3": "b.com → extraction2 → validated"},
        executive_summary="La tesis central es sólida con dos argumentos clave.",
    )


def _valid_audit():
    return AuditOutput(
        dimensions=[
            AuditDimension("financial", 8.0, ["Strong risk-adjusted returns"], ["Currency risk"]),
            AuditDimension("regulatory", 7.0, ["CMF compliant"], ["Pending regulation changes"]),
            AuditDimension("operational", 6.5, ["Standard processes"], ["Key person risk"]),
        ],
        overall_verdict="Favorable with caveats on regulatory timing.",
        blocking_issues=[],
    )


def _valid_reflect():
    return ReflectOutput(
        scenarios=[
            Scenario("Base case", "high", "moderate", ["Stable rates"], "Diversification"),
            Scenario("Rate spike", "medium", "severe", ["Rates stay low"], "Hedging strategy"),
            Scenario("Regulatory tightening", "low", "moderate", ["Current framework continues"], "Lobby effort"),
        ],
        robustness_score=0.72,
        key_vulnerabilities=["Concentrated in Chile", "FX exposure"],
    )


def _valid_decide():
    return DecideOutput(
        options=[
            DecisionOption("Proceed", "Launch fund", ["High returns"], ["Currency risk"],
                           "moderate", "Expected IRR 12%", ["arg1"]),
            DecisionOption("Delay", "Wait 6 months", ["More data"], ["Miss opportunity"],
                           "conservative", "Deferred", ["arg2"]),
            DecisionOption("Partial", "50% allocation", ["Balanced"], ["Lower returns"],
                           "moderate", "Expected IRR 8%", ["arg1", "arg2"]),
        ],
        recommendation="Proceed with full allocation based on strong fundamentals.",
        trade_off_summary="Higher returns vs currency risk; partial allocation hedges downside.",
    )


# ---------------------------------------------------------------------------
# Serialization roundtrip
# ---------------------------------------------------------------------------

class TestSerializationRoundtrip:
    """to_json → from_json roundtrip preserves data."""

    def test_discover_roundtrip(self):
        original = _valid_discover()
        restored = DiscoverOutput.from_json(original.to_json())
        assert len(restored.sources) == 3
        assert restored.sources[0].url == "https://a.com"
        assert restored.coverage_assessment == original.coverage_assessment

    def test_extract_roundtrip(self):
        original = _valid_extract()
        restored = ExtractOutput.from_json(original.to_json())
        assert len(restored.extractions) == 2
        assert restored.extractions[0].claims == ["claim1", "claim2"]
        assert restored.gaps_identified == original.gaps_identified

    def test_validate_roundtrip(self):
        original = _valid_validate()
        restored = ValidateOutput.from_json(original.to_json())
        assert len(restored.validated_claims) == 3
        assert restored.overall_reliability_score == pytest.approx(0.73)

    def test_compile_roundtrip(self):
        original = _valid_compile()
        restored = CompileOutput.from_json(original.to_json())
        assert restored.main_thesis == original.main_thesis
        assert len(restored.arguments) == 2

    def test_audit_roundtrip(self):
        original = _valid_audit()
        restored = AuditOutput.from_json(original.to_json())
        assert len(restored.dimensions) == 3
        assert restored.overall_verdict == original.overall_verdict

    def test_reflect_roundtrip(self):
        original = _valid_reflect()
        restored = ReflectOutput.from_json(original.to_json())
        assert len(restored.scenarios) == 3
        assert restored.robustness_score == pytest.approx(0.72)

    def test_decide_roundtrip(self):
        original = _valid_decide()
        restored = DecideOutput.from_json(original.to_json())
        assert len(restored.options) == 3
        assert restored.recommendation == original.recommendation

    def test_json_is_valid_json(self):
        """All to_json() produce valid JSON."""
        for contract_fn in [_valid_discover, _valid_extract, _valid_validate,
                            _valid_compile, _valid_audit, _valid_reflect, _valid_decide]:
            raw = contract_fn().to_json()
            parsed = json.loads(raw)
            assert isinstance(parsed, dict)


# ---------------------------------------------------------------------------
# Validation — happy path
# ---------------------------------------------------------------------------

class TestValidationHappyPath:
    """Valid instances pass validation with no errors."""

    def test_discover_valid(self):
        assert _valid_discover().validate() == []

    def test_extract_valid(self):
        assert _valid_extract().validate() == []

    def test_validate_valid(self):
        assert _valid_validate().validate() == []

    def test_compile_valid(self):
        assert _valid_compile().validate() == []

    def test_audit_valid(self):
        assert _valid_audit().validate() == []

    def test_reflect_valid(self):
        assert _valid_reflect().validate() == []

    def test_decide_valid(self):
        assert _valid_decide().validate() == []


# ---------------------------------------------------------------------------
# Validation — catches errors
# ---------------------------------------------------------------------------

class TestValidationCatchesErrors:

    def test_discover_too_few_sources(self):
        out = DiscoverOutput(sources=[SourceCard("u", "t", "news", 0.5, "current", "b")], coverage_assessment="ok")
        errors = out.validate()
        assert any("at least 3" in e.lower() for e in errors)

    def test_discover_empty_url(self):
        out = DiscoverOutput(
            sources=[
                SourceCard("", "t", "news", 0.5, "current", "b"),
                SourceCard("u2", "t", "news", 0.5, "current", "b"),
                SourceCard("u3", "t", "news", 0.5, "current", "b"),
            ],
            coverage_assessment="ok",
        )
        errors = out.validate()
        assert any("url is empty" in e for e in errors)

    def test_discover_invalid_relevance(self):
        out = DiscoverOutput(
            sources=[
                SourceCard("u1", "t", "news", 1.5, "current", "b"),
                SourceCard("u2", "t", "news", 0.5, "current", "b"),
                SourceCard("u3", "t", "news", 0.5, "current", "b"),
            ],
            coverage_assessment="ok",
        )
        errors = out.validate()
        assert any("relevance_score" in e for e in errors)

    def test_discover_empty_coverage(self):
        out = DiscoverOutput(
            sources=[
                SourceCard("u1", "t", "news", 0.5, "current", "b"),
                SourceCard("u2", "t", "news", 0.5, "current", "b"),
                SourceCard("u3", "t", "news", 0.5, "current", "b"),
            ],
            coverage_assessment="",
        )
        errors = out.validate()
        assert any("coverage_assessment" in e for e in errors)

    def test_extract_no_extractions(self):
        out = ExtractOutput()
        errors = out.validate()
        assert any("no extractions" in e.lower() for e in errors)

    def test_extract_empty_source_ref(self):
        out = ExtractOutput(extractions=[Extraction("", ["claim"], [], [], 0.5)])
        errors = out.validate()
        assert any("source_ref is empty" in e for e in errors)

    def test_extract_no_claims_or_data(self):
        out = ExtractOutput(extractions=[Extraction("ref", [], [], [], 0.5)])
        errors = out.validate()
        assert any("no claims or data_points" in e for e in errors)

    def test_extract_invalid_confidence(self):
        out = ExtractOutput(extractions=[Extraction("ref", ["c"], [], [], 1.5)])
        errors = out.validate()
        assert any("confidence" in e for e in errors)

    def test_validate_invalid_status(self):
        out = ValidateOutput(
            validated_claims=[ValidatedClaim("c", "invalid_status", 0.5)],
            overall_reliability_score=0.5,
        )
        errors = out.validate()
        assert any("invalid status" in e for e in errors)

    def test_validate_invalid_reliability(self):
        out = ValidateOutput(
            validated_claims=[ValidatedClaim("c", "confirmed", 0.5)],
            overall_reliability_score=1.5,
        )
        errors = out.validate()
        assert any("overall_reliability_score" in e for e in errors)

    def test_compile_empty_thesis(self):
        out = CompileOutput(arguments=[Argument("t", ["e"], "strong")], traceability_map={"a": "b"}, executive_summary="s")
        errors = out.validate()
        assert any("main_thesis" in e for e in errors)

    def test_compile_no_supporting_evidence(self):
        out = CompileOutput(
            main_thesis="t", arguments=[Argument("t", [], "strong")],
            traceability_map={"a": "b"}, executive_summary="s",
        )
        errors = out.validate()
        assert any("supporting_evidence" in e for e in errors)

    def test_audit_too_few_dimensions(self):
        out = AuditOutput(
            dimensions=[AuditDimension("legal", 7.0)],
            overall_verdict="ok",
        )
        errors = out.validate()
        assert any("at least 3" in e.lower() for e in errors)

    def test_audit_score_out_of_range(self):
        out = AuditOutput(
            dimensions=[
                AuditDimension("a", 11.0), AuditDimension("b", 5.0), AuditDimension("c", 5.0),
            ],
            overall_verdict="ok",
        )
        errors = out.validate()
        assert any("score" in e and "not in" in e for e in errors)

    def test_reflect_too_few_scenarios(self):
        out = ReflectOutput(scenarios=[Scenario("one", "high", "severe")], robustness_score=0.5)
        errors = out.validate()
        assert any("at least 2" in e.lower() for e in errors)

    def test_reflect_invalid_probability(self):
        out = ReflectOutput(
            scenarios=[Scenario("a", "very_high", "severe"), Scenario("b", "low", "moderate")],
            robustness_score=0.5,
        )
        errors = out.validate()
        assert any("probability" in e for e in errors)

    def test_decide_wrong_option_count(self):
        out = DecideOutput(options=[DecisionOption("one", "d", model_refs=["r"])], recommendation="r")
        errors = out.validate()
        assert any("2-4 options" in e for e in errors)

    def test_decide_no_model_refs(self):
        out = DecideOutput(
            options=[
                DecisionOption("a", "d", model_refs=[]),
                DecisionOption("b", "d", model_refs=["r"]),
            ],
            recommendation="r",
        )
        errors = out.validate()
        assert any("model_refs" in e for e in errors)

    def test_decide_no_recommendation(self):
        out = DecideOutput(
            options=[
                DecisionOption("a", "d", model_refs=["r"]),
                DecisionOption("b", "d", model_refs=["r"]),
            ],
            recommendation="",
        )
        errors = out.validate()
        assert any("recommendation" in e for e in errors)


# ---------------------------------------------------------------------------
# Cross-reference validation
# ---------------------------------------------------------------------------

class TestCrossReferenceValidation:

    def test_extract_validates_against_upstream_sources(self):
        out = ExtractOutput(
            extractions=[Extraction("unknown_ref", ["c"], [], [], 0.5)],
        )
        errors = out.validate(upstream_sources=["https://a.com", "https://b.com"])
        assert any("not in upstream" in e for e in errors)

    def test_extract_valid_upstream_refs(self):
        out = _valid_extract(source_refs=["https://a.com", "https://b.com"])
        errors = out.validate(upstream_sources=["https://a.com", "https://b.com", "https://c.com"])
        assert errors == []

    def test_validate_coverage_check(self):
        out = ValidateOutput(
            validated_claims=[ValidatedClaim("claim1", "confirmed", 0.9)],
            overall_reliability_score=0.5,
        )
        # 1 out of 4 upstream claims validated < 50%
        errors = out.validate(upstream_claims=["claim1", "claim2", "claim3", "claim4"])
        assert any("50%" in e for e in errors)

    def test_validate_sufficient_coverage(self):
        out = ValidateOutput(
            validated_claims=[
                ValidatedClaim("c1", "confirmed", 0.9),
                ValidatedClaim("c2", "disputed", 0.5),
                ValidatedClaim("c3", "confirmed", 0.8),
            ],
            overall_reliability_score=0.7,
        )
        # 3/4 = 75% > 50% → ok
        errors = out.validate(upstream_claims=["c1", "c2", "c3", "c4"])
        assert errors == []


# ---------------------------------------------------------------------------
# Contract registry
# ---------------------------------------------------------------------------

class TestContractRegistry:

    def test_all_pipeline_agents_have_contracts(self):
        pipeline = ["discover", "extract", "validate", "compile", "audit", "reflect", "decide"]
        for agent in pipeline:
            assert agent in AGENT_CONTRACTS, f"No contract for agent '{agent}'"

    def test_support_agents_not_in_registry(self):
        assert "context" not in AGENT_CONTRACTS
        assert "distribute" not in AGENT_CONTRACTS
        assert "collect_iterate" not in AGENT_CONTRACTS
