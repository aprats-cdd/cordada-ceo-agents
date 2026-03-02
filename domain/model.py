"""
Domain Value Objects — pure data, no I/O, no external dependencies.

These are the building blocks of the ubiquitous language:

    EpistemicPhase   — Where an agent sits in the observation→model→decision chain
    AgentDefinition  — Complete, immutable identity of an agent (single source of truth)
    AgentEvaluation  — Result of scoring an agent's output against its canonical criteria
    TokenUsage       — Token consumption and cost for a single API call
    CostBudget       — Budget ceiling and stop-loss rules for a pipeline run
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EpistemicPhase(str, Enum):
    """Where an agent sits in the epistemic chain.

    The invariant: OBSERVATION → MODEL → DECISION.
    A decision is always sustained by models, a model by observations.
    """
    OBSERVATION = "observation"
    MODEL = "model"
    DECISION = "decision"


@dataclass(frozen=True)
class AgentDefinition:
    """Complete, immutable definition of an agent.

    This is the **single source of truth** — replaces both the legacy
    ``config.AGENTS`` dict and ``canonical.AGENT_CANON`` dict.  One object
    per agent, one registry, one language.

    Supports legacy dict-style access (``agent["file"]``) via
    ``__getitem__`` for backward compatibility with existing pipeline code.
    """
    # --- Identity ---
    name: str
    canonical_name: str
    order: int

    # --- Pipeline position ---
    layer: str                  # feed, interpret, decide, distribute, feedback, support
    next_agent: str | None      # next in pipeline, None for terminal/support
    prompt_file: str            # filename in agents/ dir (e.g., "01_discover.md")

    # --- Epistemic phase ---
    phase: EpistemicPhase

    # --- Purpose ---
    description: str            # short (for tables, CLI)
    purpose: str                # full expected output description
    output_artifact: str        # concrete deliverable name

    # --- Evaluation ---
    evaluation_criteria: tuple[str, ...]    # 5 criteria scored 1-10
    canonical_referent: str                 # domain expert persona

    # --- Legacy dict-style access (anti-corruption layer) ---
    def __getitem__(self, key: str) -> Any:
        """Support ``agent["file"]`` access for backward compatibility."""
        _mapping = {
            "file": self.prompt_file,
            "order": self.order,
            "layer": self.layer,
            "description": self.description,
            "next": self.next_agent,
        }
        if key not in _mapping:
            raise KeyError(f"AgentDefinition has no legacy key '{key}'")
        return _mapping[key]

    def get(self, key: str, default: Any = None) -> Any:
        """Dict-like .get() for backward compatibility."""
        try:
            return self[key]
        except KeyError:
            return default

    @property
    def criteria_prompt(self) -> str:
        """Format evaluation criteria as numbered list for prompts."""
        return "\n".join(
            f"{i+1}. {c}" for i, c in enumerate(self.evaluation_criteria)
        )


@dataclass
class AgentEvaluation:
    """Result of evaluating an agent's output against its canonical criteria."""
    agent: str
    score: int                          # 1-10
    criteria_scores: dict[str, int]
    reasoning: str
    canonical_referent: str
    epistemic_phase: str


# ---------------------------------------------------------------------------
# Cost governance — the stop-loss of the pipeline
# ---------------------------------------------------------------------------

# Pricing per million tokens (USD) — Anthropic published rates
_PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4-6":          {"input": 15.0,  "output": 75.0},
    "claude-sonnet-4-20250514": {"input": 3.0,   "output": 15.0},
}

# Fallback for unknown models: use sonnet pricing as conservative estimate
_DEFAULT_PRICING = {"input": 3.0, "output": 15.0}


@dataclass(frozen=True)
class TokenUsage:
    """Token consumption and cost for a single API call.

    Immutable value object. Created from API responses via ``from_api_response``
    or directly for testing.  No external dependencies — pricing is a pure lookup.
    """
    input_tokens: int
    output_tokens: int
    model: str
    cost_usd: float

    @staticmethod
    def from_api_response(response: Any, model: str) -> "TokenUsage":
        """Extract token counts from an Anthropic API response and compute cost.

        Works with both the ``anthropic.types.Message`` object and raw dicts
        (for testing). The response must have a ``usage`` attribute or key
        containing ``input_tokens`` and ``output_tokens``.
        """
        if hasattr(response, "usage"):
            usage = response.usage
            inp = getattr(usage, "input_tokens", 0)
            out = getattr(usage, "output_tokens", 0)
        elif isinstance(response, dict) and "usage" in response:
            usage = response["usage"]
            inp = usage.get("input_tokens", 0)
            out = usage.get("output_tokens", 0)
        else:
            inp, out = 0, 0

        pricing = _PRICING.get(model, _DEFAULT_PRICING)
        cost = (inp * pricing["input"] + out * pricing["output"]) / 1_000_000

        return TokenUsage(
            input_tokens=inp,
            output_tokens=out,
            model=model,
            cost_usd=round(cost, 6),
        )

    @staticmethod
    def zero() -> "TokenUsage":
        """A zero-cost usage for agents that don't make API calls."""
        return TokenUsage(input_tokens=0, output_tokens=0, model="none", cost_usd=0.0)


@dataclass(frozen=True)
class CostBudget:
    """Budget ceiling and stop-loss rules for a pipeline run.

    Think of this as the stop-loss on the pipeline position:
    - ``max_total_usd``: hard ceiling per run
    - ``max_agent_output_tokens``: per-agent output cap (prevents runaway generation)
    - ``max_feedback_iterations``: cap on COLLECT_ITERATE → AUDIT loop
    - ``warning_threshold``: fraction of budget that triggers a warning at the next gate

    Defaults are calibrated for a full 9-agent pipeline with Opus on Layer 2:
    ~$10 total, which covers worst-case with margin.
    """
    max_total_usd: float = 10.0
    max_agent_output_tokens: int = 8000
    max_feedback_iterations: int = 3
    warning_threshold: float = 0.8

    def check(self, cumulative_usd: float) -> str:
        """Check budget status. Returns 'ok', 'warning', or 'exceeded'."""
        if cumulative_usd >= self.max_total_usd:
            return "exceeded"
        if cumulative_usd >= self.max_total_usd * self.warning_threshold:
            return "warning"
        return "ok"

    def format_status(self, cumulative_usd: float) -> str:
        """Human-readable budget status for gate display."""
        status = self.check(cumulative_usd)
        pct = (cumulative_usd / self.max_total_usd * 100) if self.max_total_usd > 0 else 0
        if status == "exceeded":
            return (
                f"🛑 Budget excedido: ${cumulative_usd:.2f} / ${self.max_total_usd:.2f} "
                f"({pct:.0f}%). Pipeline pausado. "
                f"Resume con --budget-override para continuar."
            )
        if status == "warning":
            return (
                f"⚠️ Budget al {pct:.0f}%: ${cumulative_usd:.2f} / ${self.max_total_usd:.2f}"
            )
        return f"Budget: ${cumulative_usd:.2f} / ${self.max_total_usd:.2f} ({pct:.0f}%)"
