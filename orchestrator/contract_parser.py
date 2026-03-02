"""
Contract Parser — parse and validate agent outputs against their schemas.

Integrates domain/contracts.py into the pipeline. Handles:
1. JSON extraction from mixed markdown/JSON agent responses
2. Schema validation via contract.validate()
3. Generation of schema instructions for agent prompts
4. Retry prompt generation when parsing fails

Think of contracts as term sheets: without a term sheet, there is no deal.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, asdict
from typing import Any

from domain.contracts import AGENT_CONTRACTS

logger = logging.getLogger(__name__)


@dataclass
class ParseResult:
    """Result of attempting to parse an agent's output to its contract."""
    agent_name: str
    success: bool
    structured: dict | None = None    # parsed and validated output as dict
    errors: list[str] | None = None   # validation errors if any
    raw_json: str | None = None       # the extracted JSON string


def _extract_json(text: str) -> str | None:
    """Extract the first JSON object from text that may contain markdown.

    Handles:
    - Pure JSON
    - JSON wrapped in ```json ... ``` fences
    - JSON embedded after text preamble
    """
    # Try pure JSON first
    stripped = text.strip()
    if stripped.startswith("{"):
        try:
            json.loads(stripped)
            return stripped
        except json.JSONDecodeError:
            pass

    # Try fenced code block
    fence_match = re.search(r"```(?:json)?\s*\n(\{.*?\})\s*\n```", text, re.DOTALL)
    if fence_match:
        candidate = fence_match.group(1).strip()
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            pass

    # Try to find the largest {...} block
    brace_start = text.find("{")
    if brace_start >= 0:
        # Find matching closing brace
        depth = 0
        for i in range(brace_start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[brace_start:i + 1]
                    try:
                        json.loads(candidate)
                        return candidate
                    except json.JSONDecodeError:
                        break

    return None


def try_parse(agent_name: str, raw_output: str) -> ParseResult:
    """Attempt to parse an agent's raw output into its contract schema.

    Returns ParseResult with success=True if parsing and validation succeed.
    """
    contract_cls = AGENT_CONTRACTS.get(agent_name)
    if not contract_cls:
        # Agent has no contract (e.g., distribute, collect_iterate)
        return ParseResult(agent_name=agent_name, success=True)

    raw_json = _extract_json(raw_output)
    if not raw_json:
        return ParseResult(
            agent_name=agent_name,
            success=False,
            errors=["No JSON object found in agent output"],
        )

    try:
        contract = contract_cls.from_json(raw_json)
    except (json.JSONDecodeError, TypeError, KeyError) as e:
        return ParseResult(
            agent_name=agent_name,
            success=False,
            errors=[f"JSON parse error: {e}"],
            raw_json=raw_json,
        )

    errors = contract.validate()
    if errors:
        return ParseResult(
            agent_name=agent_name,
            success=False,
            errors=errors,
            raw_json=raw_json,
        )

    return ParseResult(
        agent_name=agent_name,
        success=True,
        structured=asdict(contract),
        raw_json=raw_json,
    )


def get_schema_instruction(agent_name: str) -> str | None:
    """Generate a schema instruction to append to an agent's system prompt.

    Returns None if the agent has no contract.
    """
    contract_cls = AGENT_CONTRACTS.get(agent_name)
    if not contract_cls:
        return None

    # Build example JSON from the schema
    example = _build_example(agent_name)
    if not example:
        return None

    return (
        "\n\n---\n\n"
        "FORMATO DE OUTPUT: Responde EXCLUSIVAMENTE con un JSON válido "
        f"siguiendo este schema:\n\n```json\n{example}\n```\n\n"
        "No incluyas texto antes ni después del JSON. "
        "El JSON debe ser parseable directamente."
    )


def get_retry_prompt(agent_name: str, errors: list[str]) -> str:
    """Generate a retry prompt when contract parsing fails."""
    error_list = "\n".join(f"- {e}" for e in errors)
    schema_instruction = get_schema_instruction(agent_name) or ""

    return (
        "Tu output no cumple el schema requerido. Errores:\n"
        f"{error_list}\n\n"
        "Reformatea tu respuesta como JSON válido siguiendo este schema."
        f"{schema_instruction}"
    )


def _build_example(agent_name: str) -> str | None:
    """Build an example JSON for the given agent's contract."""
    examples = {
        "discover": {
            "sources": [
                {"url": "https://example.com/report", "title": "Annual Report 2024",
                 "source_type": "regulatory", "relevance_score": 0.9,
                 "freshness": "current", "brief": "Relevant regulatory report."},
                {"url": "https://example.com/data", "title": "Market Data Q4",
                 "source_type": "market_data", "relevance_score": 0.8,
                 "freshness": "recent", "brief": "Latest market data."},
                {"url": "https://example.com/news", "title": "Industry Analysis",
                 "source_type": "news", "relevance_score": 0.7,
                 "freshness": "current", "brief": "Industry overview."},
            ],
            "search_queries_used": ["deuda privada LatAm", "private debt regulation"],
            "coverage_assessment": "Good coverage of regulatory and market sources.",
        },
        "extract": {
            "extractions": [
                {"source_ref": "https://example.com/report",
                 "claims": ["AUM creció 15% en 2024"],
                 "data_points": [{"label": "AUM", "value": "218", "unit": "M USD"}],
                 "quotes": ["El mercado de deuda privada..."],
                 "confidence": 0.9},
            ],
            "gaps_identified": ["No data on operational risk"],
        },
        "validate": {
            "validated_claims": [
                {"claim": "AUM creció 15%", "status": "confirmed",
                 "confidence": 0.95, "issues": [],
                 "source_refs": ["https://example.com/report"]},
            ],
            "overall_reliability_score": 0.85,
            "bias_flags": [],
        },
        "compile": {
            "main_thesis": "La deuda privada LatAm ofrece oportunidad ajustada por riesgo.",
            "arguments": [
                {"thesis": "Rendimientos atractivos",
                 "supporting_evidence": ["claim_1", "claim_2"],
                 "strength": "strong"},
            ],
            "traceability_map": {"claim_1": "source_A → extraction → validated"},
            "executive_summary": "Summary text here.",
        },
        "audit": {
            "dimensions": [
                {"dimension": "financial", "score": 8.0,
                 "findings": ["Strong returns"], "risks": ["Currency exposure"]},
                {"dimension": "regulatory", "score": 7.0,
                 "findings": ["Compliant"], "risks": ["Pending changes"]},
                {"dimension": "operational", "score": 6.5,
                 "findings": ["Standard"], "risks": ["Key person"]},
            ],
            "overall_verdict": "Favorable with caveats.",
            "blocking_issues": [],
        },
        "reflect": {
            "scenarios": [
                {"name": "Base case", "probability": "high", "impact": "moderate",
                 "assumptions_challenged": ["Stable rates"], "mitigation": "Diversification"},
                {"name": "Rate spike", "probability": "medium", "impact": "severe",
                 "assumptions_challenged": ["Low rates"], "mitigation": "Hedging"},
            ],
            "robustness_score": 0.75,
            "key_vulnerabilities": ["FX exposure", "Concentration risk"],
        },
        "decide": {
            "options": [
                {"label": "Proceed", "description": "Full allocation",
                 "pros": ["High returns"], "cons": ["Currency risk"],
                 "risk_profile": "moderate", "estimated_impact": "IRR 12%",
                 "model_refs": ["arg_1"]},
                {"label": "Delay", "description": "Wait 6 months",
                 "pros": ["More data"], "cons": ["Miss opportunity"],
                 "risk_profile": "conservative", "estimated_impact": "Deferred",
                 "model_refs": ["arg_2"]},
            ],
            "recommendation": "Proceed based on strong fundamentals.",
            "trade_off_summary": "Higher returns vs currency risk.",
        },
    }

    example = examples.get(agent_name)
    if not example:
        return None
    return json.dumps(example, ensure_ascii=False, indent=2)
