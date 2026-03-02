"""
Domain Value Objects — pure data, no I/O, no external dependencies.

These are the building blocks of the ubiquitous language:

    EpistemicPhase   — Where an agent sits in the observation→model→decision chain
    AgentDefinition  — Complete, immutable identity of an agent (single source of truth)
    AgentEvaluation  — Result of scoring an agent's output against its canonical criteria
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
