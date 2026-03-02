"""
Epistemic Invariant — pure validation logic, no I/O.

Core rule:

    OBSERVATION → MODEL → DECISION

    - A MODEL must have upstream OBSERVATION or MODEL (never DECISION)
    - A DECISION must have upstream MODEL (never OBSERVATION or DECISION)
    - An OBSERVATION can start the chain or follow DECISION (feedback loop)

This module contains ONLY the invariant logic.  It has no knowledge of
the Anthropic API, file I/O, or any infrastructure.
"""

from __future__ import annotations

from .model import EpistemicPhase
from .registry import AGENTS, PIPELINE_ORDER


# Legal upstream phases for each phase
VALID_UPSTREAM: dict[EpistemicPhase, set[EpistemicPhase]] = {
    EpistemicPhase.OBSERVATION: {EpistemicPhase.OBSERVATION, EpistemicPhase.DECISION},
    EpistemicPhase.MODEL: {EpistemicPhase.OBSERVATION, EpistemicPhase.MODEL},
    EpistemicPhase.DECISION: {EpistemicPhase.MODEL},
}


def get_upstream_agent(agent_name: str) -> str | None:
    """Return the previous agent in the pipeline, or None for the first."""
    try:
        idx = PIPELINE_ORDER.index(agent_name)
        if idx == 0:
            return None
        return PIPELINE_ORDER[idx - 1]
    except ValueError:
        return None


def validate_epistemic_chain(
    agent_name: str,
    upstream_agent: str | None,
) -> tuple[bool, str]:
    """Check whether the epistemic invariant holds for this transition.

    Returns:
        (valid, explanation)
    """
    agent = AGENTS.get(agent_name)
    if not agent:
        return True, f"Agent '{agent_name}' not in registry, skipping."

    if upstream_agent is None:
        return True, f"{agent_name}: first in chain, no upstream to validate."

    upstream = AGENTS.get(upstream_agent)
    if not upstream:
        return True, f"Upstream '{upstream_agent}' not in registry, skipping."

    current_phase = agent.phase
    upstream_phase = upstream.phase

    valid_phases = VALID_UPSTREAM[current_phase]
    if upstream_phase in valid_phases:
        return True, (
            f"{upstream_agent}({upstream_phase.value}) → "
            f"{agent_name}({current_phase.value}): valid"
        )

    return False, (
        f"INVARIANT VIOLATION: {upstream_agent}({upstream_phase.value}) → "
        f"{agent_name}({current_phase.value}). "
        f"Phase '{current_phase.value}' requires upstream in "
        f"{{{', '.join(p.value for p in valid_phases)}}}, "
        f"but got '{upstream_phase.value}'."
    )
