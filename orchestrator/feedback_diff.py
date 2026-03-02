"""
Feedback Diff Service — compute semantic diffs between feedback iterations.

Uses a short Sonnet call to compare two states and identify what changed.
The diff enables incremental AUDIT (only re-evaluating changes) and
informs the CEO whether the feedback was material.

Application service layer — depends on Anthropic API.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any

from domain.feedback import FeedbackDiff

logger = logging.getLogger(__name__)

_DIFF_MODEL = "claude-sonnet-4-20250514"

# ---------------------------------------------------------------------------
# Anthropic client (lazy singleton)
# ---------------------------------------------------------------------------

_diff_client: Any = None
_diff_client_lock = threading.Lock()


def _get_client() -> Any:
    global _diff_client
    if _diff_client is None:
        with _diff_client_lock:
            if _diff_client is None:
                import anthropic
                from .config import ANTHROPIC_API_KEY
                _diff_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _diff_client


# ---------------------------------------------------------------------------
# Diff computation
# ---------------------------------------------------------------------------

_DIFF_SYSTEM = (
    "Eres un analista que compara dos versiones de un documento de auditoría. "
    "Identificas cambios con precisión quirúrgica. Responde solo con JSON."
)

_DIFF_USER_TEMPLATE = """\
VERSIÓN ANTERIOR (iteración {prev_iteration}):
---
{prev_output}
---

VERSIÓN NUEVA (iteración {new_iteration}, después de feedback):
---
{new_output}
---

TAREA: Compara los dos estados y genera un diff semántico.

Responde SOLO con JSON válido:
{{
  "new_observations": ["descripción breve de cada observación nueva"],
  "changed_assessments": ["qué cambió y cómo (ej: 'riesgo legal subió de 6 a 8')"],
  "removed_items": ["items que estaban en la versión anterior pero ya no"],
  "unchanged_count": 0,
  "delta_summary": "Resumen en 1-2 oraciones de los cambios materiales."
}}
"""


def compute_diff(
    prev_output: str,
    new_output: str,
    iteration: int,
    max_chars: int = 4000,
) -> FeedbackDiff:
    """Compute semantic diff between two feedback iterations.

    Uses a short Sonnet call (~500 output tokens) to compare states.
    Falls back to a structural diff on API failure.

    Args:
        prev_output: Output from the previous iteration.
        new_output: Output from the current iteration (after feedback).
        iteration: Current iteration number (1-indexed).
        max_chars: Max chars per output sent to the API.

    Returns:
        FeedbackDiff with changes identified.
    """
    # Truncate for API efficiency
    prev_truncated = prev_output[:max_chars]
    if len(prev_output) > max_chars:
        prev_truncated += "\n[... truncado]"
    new_truncated = new_output[:max_chars]
    if len(new_output) > max_chars:
        new_truncated += "\n[... truncado]"

    user_msg = _DIFF_USER_TEMPLATE.format(
        prev_iteration=iteration - 1,
        new_iteration=iteration,
        prev_output=prev_truncated,
        new_output=new_truncated,
    )

    try:
        client = _get_client()
        message = client.messages.create(
            model=_DIFF_MODEL,
            max_tokens=512,
            system=_DIFF_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = "\n".join(b.text for b in message.content if hasattr(b, "text"))

        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned[cleaned.index("\n") + 1:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]

        data = json.loads(cleaned.strip())

        return FeedbackDiff(
            iteration=iteration,
            new_observations=data.get("new_observations", []),
            changed_assessments=data.get("changed_assessments", []),
            removed_items=data.get("removed_items", []),
            unchanged_count=data.get("unchanged_count", 0),
            delta_summary=data.get("delta_summary", ""),
        )

    except Exception:
        logger.exception("Feedback diff computation failed, using structural fallback")
        return _structural_diff(prev_output, new_output, iteration)


def _structural_diff(
    prev_output: str,
    new_output: str,
    iteration: int,
) -> FeedbackDiff:
    """Structural fallback: line-level diff without LLM.

    Used when the Sonnet call fails. Provides basic change detection.
    """
    prev_lines = set(prev_output.strip().split("\n"))
    new_lines = set(new_output.strip().split("\n"))

    added = new_lines - prev_lines
    removed = prev_lines - new_lines
    unchanged = prev_lines & new_lines

    return FeedbackDiff(
        iteration=iteration,
        new_observations=[line[:100] for line in sorted(added)[:10]],
        changed_assessments=[],
        removed_items=[line[:100] for line in sorted(removed)[:10]],
        unchanged_count=len(unchanged),
        delta_summary=f"Diff estructural: +{len(added)} líneas, -{len(removed)} líneas, ={len(unchanged)} sin cambios.",
    )
