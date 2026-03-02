"""
Domain Layer — the core model of cordada-ceo-agents.

This package contains the pure domain logic with ZERO external dependencies
(no Anthropic SDK, no Google API, no Slack SDK, no file I/O beyond event
persistence).  All infrastructure concerns live in ``orchestrator/`` or
future ``infrastructure/`` packages.

Bounded contexts:
    model       — Value objects: AgentDefinition, EpistemicPhase, AgentEvaluation,
                    TokenUsage, CostBudget
    contracts   — Inter-agent output schemas: DiscoverOutput, ExtractOutput, etc.
    registry    — Single source of truth: AGENTS dict (unified config + canon)
    events      — Domain events: AgentEvent, EventBus, InvariantViolation
    invariant   — Epistemic chain validation (observation → model → decision)

DDD alignment (Evans, 2003):
    - AgentDefinition is the Aggregate Root for agent identity
    - AGENTS registry is a Repository
    - EventBus is a Domain Service
    - EpistemicPhase is a Value Object
    - validate_epistemic_chain() is a Domain Invariant
"""

from .model import AgentDefinition, EpistemicPhase, AgentEvaluation, TokenUsage, CostBudget
from .contracts import AGENT_CONTRACTS
from .registry import AGENTS, PIPELINE_ORDER, get_agent, get_model_for_agent
from .events import AgentEvent, EventBus, InvariantViolation
from .invariant import validate_epistemic_chain, VALID_UPSTREAM

__all__ = [
    # Model
    "AgentDefinition",
    "EpistemicPhase",
    "AgentEvaluation",
    "TokenUsage",
    "CostBudget",
    # Contracts
    "AGENT_CONTRACTS",
    # Registry
    "AGENTS",
    "PIPELINE_ORDER",
    "get_agent",
    "get_model_for_agent",
    # Events
    "AgentEvent",
    "EventBus",
    "InvariantViolation",
    # Invariant
    "validate_epistemic_chain",
    "VALID_UPSTREAM",
]
