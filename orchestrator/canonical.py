"""
Canonical Evaluation Service — scores agent outputs via Claude.

Domain model and invariant logic live in ``domain/``.  This module
is the **application service** that calls the Anthropic API to evaluate
agent outputs against their canonical criteria.

Re-exports domain types for backward compatibility:
    from orchestrator.canonical import AGENT_CANON, EpistemicPhase, evaluate_output
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any

# Re-export domain types for backward compat
from domain.model import AgentDefinition, EpistemicPhase, AgentEvaluation  # noqa: F401
from domain.registry import AGENTS as AGENT_CANON  # noqa: F401
from domain.invariant import validate_epistemic_chain, VALID_UPSTREAM  # noqa: F401

logger = logging.getLogger(__name__)

# Model used for canonical evaluation calls
_EVAL_MODEL = "claude-sonnet-4-20250514"

# ---------------------------------------------------------------------------
# Anthropic client (lazy singleton)
# ---------------------------------------------------------------------------

_eval_client: Any = None
_eval_client_lock = threading.Lock()


def _get_eval_client() -> Any:
    global _eval_client
    if _eval_client is None:
        with _eval_client_lock:
            if _eval_client is None:
                import anthropic
                from .config import ANTHROPIC_API_KEY
                _eval_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _eval_client


# ---------------------------------------------------------------------------
# Evaluation prompts
# ---------------------------------------------------------------------------

_EVAL_SYSTEM = (
    "Eres un evaluador canónico de calidad para agentes de IA en un pipeline "
    "de toma de decisiones para el CEO de Cordada, un asset manager chileno. "
    "Evalúas con rigor profesional. Nunca inflas puntajes."
)

_EVAL_USER_TEMPLATE = """\
AGENTE: {canonical_name}
FASE EPISTÉMICA: {phase}

DESCRIPCIÓN DEL AGENTE:
{description}

PROPÓSITO ESPERADO:
{purpose}

TU ROL COMO EVALUADOR — Adopta la perspectiva de:
{canonical_referent}

OUTPUT DEL AGENTE A EVALUAR:
---
{output}
---

CRITERIOS DE EVALUACIÓN (puntúa cada uno de 1 a 10):
{criteria_prompt}

INVARIANTE EPISTÉMICA:
El output debe ser una {phase} válida. {phase_rule}

Responde SOLO con JSON válido:
{{
  "criteria_scores": {{
    "criterio_1": 7,
    "criterio_2": 8
  }},
  "overall_score": 7,
  "reasoning": "Justificación concisa del puntaje general (2-3 oraciones).",
  "epistemic_compliance": "¿El output respeta su fase epistémica? Sí/No + breve razón."
}}
"""

_PHASE_RULES: dict[EpistemicPhase, str] = {
    EpistemicPhase.OBSERVATION: (
        "Una OBSERVACIÓN registra hechos trazables a fuentes. "
        "No debe contener interpretaciones no sustentadas ni recomendaciones de acción."
    ),
    EpistemicPhase.MODEL: (
        "Un MODELO estructura observaciones en un argumento o análisis. "
        "Cada afirmación del modelo debe ser trazable a observaciones. "
        "No debe saltar directamente a decisiones."
    ),
    EpistemicPhase.DECISION: (
        "Una DECISIÓN presenta opciones sustentadas en modelos explícitos. "
        "Nunca se sustenta directamente en observaciones crudas ni en otras decisiones."
    ),
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def evaluate_output(
    agent_name: str,
    output: str,
    max_output_chars: int = 8000,
) -> AgentEvaluation | None:
    """Evaluate an agent's output against its canonical criteria.

    Makes a single Sonnet call. Returns None if evaluation fails.
    """
    from domain.registry import AGENTS

    agent = AGENTS.get(agent_name)
    if not agent:
        logger.warning("No definition for agent '%s', skipping eval.", agent_name)
        return None

    eval_output = output[:max_output_chars]
    if len(output) > max_output_chars:
        eval_output += "\n[... truncado para evaluación]"

    user_msg = _EVAL_USER_TEMPLATE.format(
        canonical_name=agent.canonical_name,
        phase=agent.phase.value,
        description=agent.description,
        purpose=agent.purpose,
        canonical_referent=agent.canonical_referent,
        output=eval_output,
        criteria_prompt=agent.criteria_prompt,
        phase_rule=_PHASE_RULES[agent.phase],
    )

    try:
        client = _get_eval_client()
        message = client.messages.create(
            model=_EVAL_MODEL,
            max_tokens=2048,
            system=_EVAL_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = "\n".join(b.text for b in message.content if hasattr(b, "text"))

        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned[cleaned.index("\n") + 1:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        data = json.loads(cleaned.strip())

        return AgentEvaluation(
            agent=agent_name,
            score=data.get("overall_score", 0),
            criteria_scores=data.get("criteria_scores", {}),
            reasoning=data.get("reasoning", ""),
            canonical_referent=agent.canonical_referent,
            epistemic_phase=agent.phase.value,
        )
    except Exception:
        logger.exception("Canonical evaluation failed for agent '%s'", agent_name)
        return None
