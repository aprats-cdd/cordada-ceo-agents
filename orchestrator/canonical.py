"""
Backward-compatibility shim — re-exports from heuristic_eval.py.

All evaluation logic has moved to ``heuristic_eval.py`` (renamed from
"canonical evaluation" to "heuristic quality signal").  This file exists
solely so ``from orchestrator.canonical import evaluate_output`` continues
to work in existing code.
"""

from .heuristic_eval import (  # noqa: F401
    evaluate_output,
    AGENT_CANON,
    EpistemicPhase,
    AgentDefinition,
    AgentEvaluation,
    validate_epistemic_chain,
    VALID_UPSTREAM,
)
