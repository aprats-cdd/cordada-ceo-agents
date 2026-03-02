"""
CONTEXT Middleware — intercept agent questions in interactive mode,
search internal sources (Drive, Gmail, Slack, Calendar), and suggest
answers scored by a domain-appropriate canonical referent.

Three-phase flow:

    1. **PLAN** — Claude reads the agent's output, extracts what
       information is needed, and designs targeted search queries
       per source (Drive/Gmail/Slack/Calendar).

    2. **EXECUTE** — Runs the planned queries via ``tools.execute_tool()``
       (direct API with proxy fallback).

    3. **SYNTHESIZE** — Claude interprets raw results, synthesises
       answers, and scores each 1–10 adopting the perspective of the
       canonical domain expert for the calling agent's role.
       Only suggestions scoring >= 5 are shown to the CEO.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field, asdict
from typing import Any

from domain.registry import AGENTS
from .context_cache import ContextCache

logger = logging.getLogger(__name__)

# Module-level cache instance (shared across all middleware calls in a session)
_cache = ContextCache(ttl_seconds=3600)

# Model used for CONTEXT calls (lightweight, fast)
_CONTEXT_MODEL = "claude-sonnet-4-20250514"

_DEFAULT_DOMAIN = (
    "un profesional senior del dominio relevante. "
    "Prioriza relevancia, recencia y autoridad de la fuente."
)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Suggestion:
    """A scored suggestion for one question."""
    question: str
    answer: str
    source_type: str     # "Drive", "Gmail", "Slack", "Calendar"
    source_name: str
    date: str
    score: int           # 1-10
    reasoning: str


@dataclass
class ContextResult:
    """Full result of a CONTEXT middleware pass."""
    suggestions: list[Suggestion] = field(default_factory=list)
    unanswered: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Shared Anthropic client (lazy singleton, same pattern as tools.py)
# ---------------------------------------------------------------------------

_context_client: Any = None
_context_client_lock = threading.Lock()


def _get_client() -> Any:
    global _context_client
    if _context_client is None:
        with _context_client_lock:
            if _context_client is None:
                import anthropic
                from .config import ANTHROPIC_API_KEY
                _context_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _context_client


def _call_claude(system: str, user_message: str) -> str:
    """Make a lightweight Claude call and return the text response."""
    client = _get_client()
    message = client.messages.create(
        model=_CONTEXT_MODEL,
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": user_message}],
    )
    blocks = [b.text for b in message.content if hasattr(b, "text")]
    return "\n".join(blocks) if blocks else ""


def _parse_json_response(text: str) -> dict:
    """Extract JSON from Claude's response, handling code fences."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        first_nl = cleaned.index("\n")
        cleaned = cleaned[first_nl + 1:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()
    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        logger.warning("Failed to parse CONTEXT JSON response: %s", cleaned[:200])
        return {}


# ---------------------------------------------------------------------------
# Phase 1: PLAN — Claude interprets questions + designs search strategy
# ---------------------------------------------------------------------------

_PLAN_SYSTEM = (
    "Eres CONTEXT, el middleware de recuperación de conocimiento interno de Cordada, "
    "un asset manager chileno de deuda privada LatAm. "
    "Tu trabajo es analizar el texto de un agente, extraer qué información necesita, "
    "y diseñar queries de búsqueda precisas para cada fuente interna."
)

_PLAN_USER_TEMPLATE = """\
AGENTE: {agent_name} — {agent_description}

TEXTO DEL AGENTE:
---
{assistant_text}
---

TAREA: Analiza el texto y extrae las preguntas o campos de información que el \
agente necesita del CEO. Para cada uno, diseña queries de búsqueda específicas.

Guía de queries por fuente:
- search_google_drive: documentos formales (reportes, actas, memos, presentaciones). \
  Usa términos como "AUM", "reporte mensual", "acta directorio", "due diligence".
- search_gmail: emails recientes (últimos 6 meses). Del CEO primero. \
  Usa "from:ceo@cordada.cl" o temas específicos.
- search_slack: conversaciones informales del equipo. \
  Canales típicos: inversiones, pipeline, deals, operaciones, nav, legal, directorio, compliance.
- read_calendar: solo si la pregunta involucra timing, deadlines o reuniones.

Para cada pregunta, incluye solo las fuentes que tengan sentido (no todas siempre).

Responde SOLO con JSON válido (sin explicaciones):
{{
  "questions": [
    {{
      "question": "texto de la pregunta",
      "category": "financiero|legal|operacional|estratégico|comunicación|gobernanza",
      "searches": [
        {{"tool": "search_google_drive", "params": {{"query": "...", "max_results": 5}}}},
        {{"tool": "search_gmail", "params": {{"query": "...", "max_results": 5}}}}
      ]
    }}
  ]
}}

Si el texto NO contiene preguntas que requieran información interna, responde:
{{"questions": []}}
"""


def _plan_searches(
    agent_name: str,
    agent_description: str,
    assistant_text: str,
) -> list[dict]:
    """Phase 1: Use Claude to interpret questions and design search queries."""
    user_msg = _PLAN_USER_TEMPLATE.format(
        agent_name=agent_name.upper(),
        agent_description=agent_description,
        assistant_text=assistant_text,
    )
    try:
        raw = _call_claude(_PLAN_SYSTEM, user_msg)
        data = _parse_json_response(raw)
        return data.get("questions", [])
    except Exception:
        logger.exception("CONTEXT PLAN phase failed")
        return []


# ---------------------------------------------------------------------------
# Phase 2: EXECUTE — Run planned searches via tools.py
# ---------------------------------------------------------------------------

def _execute_searches(planned_questions: list[dict]) -> dict[str, list[dict]]:
    """Phase 2: Execute all planned searches, grouped by question."""
    from .tools import execute_tool

    results: dict[str, list[dict]] = {}

    for pq in planned_questions:
        question = pq.get("question", "")
        question_results: list[dict] = []

        for search in pq.get("searches", []):
            tool_name = search.get("tool", "")
            params = search.get("params", {})

            try:
                raw = execute_tool(tool_name, params)
                data = json.loads(raw) if isinstance(raw, str) else raw
            except Exception as e:
                logger.warning("Search failed (%s): %s", tool_name, e)
                data = {"error": str(e)}

            question_results.append({
                "source": tool_name,
                "params": params,
                "result": data,
            })

        results[question] = question_results

    return results


# ---------------------------------------------------------------------------
# Phase 3: SYNTHESIZE — Claude interprets results + scores as domain expert
# ---------------------------------------------------------------------------

_SYNTH_SYSTEM = (
    "Eres CONTEXT, el middleware de evaluación de Cordada. "
    "Tu trabajo es interpretar resultados de búsqueda, sintetizar respuestas, "
    "y puntuar la calidad de cada sugerencia con rigor profesional."
)

_SYNTH_USER_TEMPLATE = """\
AGENTE: {agent_name} — {agent_description}

PREGUNTAS Y RESULTADOS DE BÚSQUEDA:
{search_results_json}

TAREA: Para cada pregunta, interpreta los resultados y genera una sugerencia.

CRITERIO DE EVALUACIÓN — Adopta la perspectiva de {domain_expert}

Puntúa cada sugerencia de 1 a 10:
- Relevancia: ¿responde directamente la pregunta?
- Frescura: ¿la fuente es reciente y vigente?
- Autoridad: ¿la fuente es confiable para este tipo de dato?
- Suficiencia: ¿la información es completa o parcial?

El puntaje final es el promedio redondeado de estos 4 criterios.
Solo incluye en "suggestions" las respuestas con puntaje >= 5.
Las de puntaje < 5 van a "unanswered" (con breve razón).

IMPORTANTE:
- Sintetiza la respuesta (no copies el snippet raw).
- Parafrasea emails, no los cites textualmente.
- Incluye la fecha de la fuente para evaluar vigencia.
- Si múltiples fuentes coinciden, menciona las más autoritativas.

Responde SOLO con JSON válido:
{{
  "suggestions": [
    {{
      "question": "...",
      "answer": "respuesta sintetizada",
      "source_type": "Drive|Gmail|Slack|Calendar",
      "source_name": "nombre del documento o mensaje",
      "date": "fecha de la fuente",
      "score": 8,
      "reasoning": "breve justificación del puntaje (1 línea)"
    }}
  ],
  "unanswered": [
    {{
      "question": "...",
      "reason": "por qué no se encontró respuesta suficiente"
    }}
  ]
}}
"""


def _synthesize(
    agent_name: str,
    agent_description: str,
    search_results: dict[str, list[dict]],
) -> ContextResult:
    """Phase 3: Claude interprets results and scores suggestions."""
    agent = AGENTS.get(agent_name)
    domain_expert = agent.canonical_referent if agent else _DEFAULT_DOMAIN

    # Build compact representation for Claude (skip errors, keep data)
    compact: list[dict] = []
    for question, results in search_results.items():
        sources: list[dict] = []
        for r in results:
            result_data = r.get("result", {})
            if "error" not in result_data:
                sources.append({
                    "tool": r["source"],
                    "data": result_data,
                })
        compact.append({"question": question, "sources": sources})

    user_msg = _SYNTH_USER_TEMPLATE.format(
        agent_name=agent_name.upper(),
        agent_description=agent_description,
        search_results_json=json.dumps(compact, ensure_ascii=False, indent=2),
        domain_expert=domain_expert,
    )

    try:
        raw = _call_claude(_SYNTH_SYSTEM, user_msg)
        data = _parse_json_response(raw)
    except Exception:
        logger.exception("CONTEXT SYNTHESIZE phase failed")
        return ContextResult()

    suggestions: list[Suggestion] = []
    for s in data.get("suggestions", []):
        score = s.get("score", 0)
        if score < 5:
            continue
        suggestions.append(Suggestion(
            question=s.get("question", ""),
            answer=s.get("answer", ""),
            source_type=s.get("source_type", ""),
            source_name=s.get("source_name", ""),
            date=s.get("date", ""),
            score=score,
            reasoning=s.get("reasoning", ""),
        ))

    unanswered: list[str] = []
    for u in data.get("unanswered", []):
        if isinstance(u, dict):
            q = u.get("question", "")
            reason = u.get("reason", "")
            unanswered.append(f"{q} ({reason})" if reason else q)
        else:
            unanswered.append(str(u))

    return ContextResult(suggestions=suggestions, unanswered=unanswered)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def suggest_answers(
    assistant_text: str,
    agent_name: str = "discover",
    run_id: str = "",
) -> ContextResult | None:
    """Run the full CONTEXT pipeline: PLAN -> EXECUTE -> SYNTHESIZE.

    Uses the TTL cache to avoid repeated API calls for the same question
    within the same pipeline run.

    Args:
        assistant_text: Raw text output from the agent.
        agent_name: Which agent is asking (affects search strategy and scoring).
        run_id: Pipeline run ID for cache scoping.

    Returns:
        ContextResult with scored suggestions, or None if no questions found.
    """
    start_time = time.time()

    # Check cache before doing any API calls
    cached = _cache.get(assistant_text, agent_name, run_id)
    if cached is not None:
        elapsed = time.time() - start_time
        logger.info("CONTEXT cache hit for %s (%.1fms)", agent_name, elapsed * 1000)
        result = _deserialize_result(cached)
        result._cached = True
        result._elapsed = elapsed
        result._api_calls = 0
        return result

    agent_def = AGENTS.get(agent_name)
    agent_description = agent_def.description if agent_def else "Agent"

    api_calls = 0

    # Phase 1: PLAN
    planned = _plan_searches(agent_name, agent_description, assistant_text)
    api_calls += 1
    if not planned:
        return None

    # Phase 2: EXECUTE
    raw_results = _execute_searches(planned)
    api_calls += sum(len(pq.get("searches", [])) for pq in planned)

    # Phase 3: SYNTHESIZE
    result = _synthesize(agent_name, agent_description, raw_results)
    api_calls += 1

    if not result.suggestions and not result.unanswered:
        return None

    elapsed = time.time() - start_time

    # Store in cache
    _cache.put(assistant_text, agent_name, run_id, _serialize_result(result))

    result._cached = False
    result._elapsed = elapsed
    result._api_calls = api_calls
    return result


def invalidate_context_cache(run_id: str = "") -> int:
    """Invalidate context cache for a run (called on gate/feedback/override).

    Returns the number of entries invalidated.
    """
    if run_id:
        return _cache.invalidate_run(run_id)
    _cache.clear()
    return 0


def get_context_cache() -> ContextCache:
    """Access the module-level cache instance (for testing/inspection)."""
    return _cache


def _serialize_result(result: ContextResult) -> dict:
    """Serialize a ContextResult to a dict for caching."""
    return {
        "suggestions": [asdict(s) for s in result.suggestions],
        "unanswered": result.unanswered,
    }


def _deserialize_result(data: dict) -> ContextResult:
    """Deserialize a cached dict back to ContextResult."""
    suggestions = [Suggestion(**s) for s in data.get("suggestions", [])]
    return ContextResult(
        suggestions=suggestions,
        unanswered=data.get("unanswered", []),
    )


def format_suggestions(result: ContextResult) -> str:
    """Format a ContextResult for the CEO."""
    lines: list[str] = []

    cached = getattr(result, "_cached", False)
    elapsed = getattr(result, "_elapsed", 0.0)
    api_calls = getattr(result, "_api_calls", 0)

    if cached:
        lines.append("\n  CONTEXT encontro respuestas sugeridas (cached):\n")
    else:
        lines.append("\n  CONTEXT encontro respuestas sugeridas:\n")

    for s in result.suggestions:
        timing = f"(cached, {elapsed:.1f}s)" if cached else f"({api_calls} API calls, {elapsed:.1f}s)"
        lines.append(f"  **{s.question}** [{s.score}/10] {timing}")
        lines.append(f"  -> Sugerencia: {s.answer}")
        lines.append(f"     Fuente: {s.source_type} - {s.source_name}")
        lines.append(f"     Fecha: {s.date}")
        lines.append(f"     Evaluacion: {s.reasoning}")
        lines.append("")

    if result.unanswered:
        lines.append("  No encontre respuesta suficiente para:")
        for q in result.unanswered:
            lines.append(f"  - {q}")
        lines.append("")

    lines.append("  Opciones:")
    lines.append("    1. Confirmar todas las sugerencias")
    lines.append("    2. Corregir una sugerencia")
    lines.append("    3. Responder manualmente")

    return "\n".join(lines)


def compile_confirmed_answers(result: ContextResult) -> str:
    """Turn confirmed suggestions into a plain-text reply for the agent."""
    parts: list[str] = []
    for s in result.suggestions:
        parts.append(f"{s.question}\n-> {s.answer}")
    return "\n\n".join(parts)
