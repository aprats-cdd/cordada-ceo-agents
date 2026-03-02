"""
Canonical Agent Registry — formal definitions, epistemic phases,
and evaluation criteria for every agent in the pipeline.

Core invariant (observation → model → decision):

    Every DECISION is sustained by explicit MODELS, and every MODEL
    by traceable OBSERVATIONS.  A decision never rests on another
    decision; a decision never rests directly on observations.
    The epistemic chain is always:

        OBSERVATION  →  MODEL  →  DECISION

    The pipeline enforces this structurally:

        Layer 1 FEED (obs)  →  COMPILE (model)  →  Layer 2 (model/decision)
        COLLECT_ITERATE (obs) ──────────────────→  AUDIT (model)  ↑ feedback

Usage:
    from orchestrator.canonical import AGENT_CANON, EpistemicPhase, evaluate_output
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

# Model used for canonical evaluation calls
_EVAL_MODEL = "claude-sonnet-4-20250514"


# ---------------------------------------------------------------------------
# Epistemic phases
# ---------------------------------------------------------------------------

class EpistemicPhase(str, Enum):
    """Which part of the observation→model→decision chain an agent occupies."""
    OBSERVATION = "observation"
    MODEL = "model"
    DECISION = "decision"


# Legal transitions for the invariant
VALID_UPSTREAM: dict[EpistemicPhase, set[EpistemicPhase]] = {
    EpistemicPhase.OBSERVATION: {EpistemicPhase.OBSERVATION, EpistemicPhase.DECISION},
    EpistemicPhase.MODEL: {EpistemicPhase.OBSERVATION, EpistemicPhase.MODEL},
    EpistemicPhase.DECISION: {EpistemicPhase.MODEL},
}


# ---------------------------------------------------------------------------
# Agent Canon dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AgentCanon:
    """Immutable canonical definition of an agent."""
    name: str
    canonical_name: str
    phase: EpistemicPhase
    description: str
    purpose: str
    output_artifact: str
    evaluation_criteria: tuple[str, ...]
    canonical_referent: str

    @property
    def criteria_prompt(self) -> str:
        """Format criteria as a numbered list for evaluation prompts."""
        return "\n".join(
            f"{i+1}. {c}" for i, c in enumerate(self.evaluation_criteria)
        )


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------

AGENT_CANON: dict[str, AgentCanon] = {
    "discover": AgentCanon(
        name="discover",
        canonical_name="DISCOVER — Investigación y Catálogo de Fuentes",
        phase=EpistemicPhase.OBSERVATION,
        description=(
            "Busca, filtra y prioriza fuentes de información relevantes "
            "al tema de investigación. Genera un catálogo de fuentes "
            "ordenado por relevancia y confiabilidad."
        ),
        purpose=(
            "Catálogo priorizado de fuentes con scoring de relevancia, "
            "tipo de fuente, y justificación de inclusión/exclusión."
        ),
        output_artifact="Catálogo de fuentes con fichas bibliográficas",
        evaluation_criteria=(
            "Cobertura: ¿cubrió fuentes primarias, secundarias y alternativas?",
            "Relevancia: ¿cada fuente está justificada para el tema específico?",
            "Diversidad: ¿hay fuentes de distintos tipos (académica, regulatoria, mercado)?",
            "Recencia: ¿priorizó fuentes actualizadas sobre obsoletas?",
            "Trazabilidad: ¿cada fuente tiene URL, autor, fecha verificables?",
        ),
        canonical_referent=(
            "Analista senior de research en asset management con 15+ años. "
            "Evalúa como si revisara el catálogo de fuentes de un analista junior."
        ),
    ),
    "extract": AgentCanon(
        name="extract",
        canonical_name="EXTRACT — Extracción de Datos Clave",
        phase=EpistemicPhase.OBSERVATION,
        description=(
            "Extrae datos, argumentos, frameworks y cifras clave de las "
            "fuentes catalogadas. Produce fichas estructuradas trazables "
            "a la fuente original."
        ),
        purpose=(
            "Fichas de extracción con dato, fuente, página/sección, "
            "y contexto del dato. Cada ficha es atómica y verificable."
        ),
        output_artifact="Fichas de extracción estructuradas",
        evaluation_criteria=(
            "Precisión: ¿los datos extraídos coinciden con la fuente original?",
            "Completitud: ¿se extrajeron todos los datos relevantes, no solo los obvios?",
            "Atomicidad: ¿cada ficha contiene un solo dato verificable?",
            "Trazabilidad: ¿cada dato apunta a fuente + ubicación exacta?",
            "Contexto: ¿se preservó el contexto necesario para interpretar el dato?",
        ),
        canonical_referent=(
            "Data analyst financiero especializado en due diligence. "
            "Evalúa como si revisara la extracción antes de un comité de inversión."
        ),
    ),
    "validate": AgentCanon(
        name="validate",
        canonical_name="VALIDATE — Verificación y Control de Calidad",
        phase=EpistemicPhase.OBSERVATION,
        description=(
            "Verifica precisión, consistencia, sesgo y vigencia de los datos "
            "extraídos. Cruza fuentes, identifica contradicciones y señala "
            "datos que no se pudieron confirmar."
        ),
        purpose=(
            "Reporte de validación con status por dato (confirmado/no confirmado/"
            "contradictorio), flags de riesgo, y gaps de información."
        ),
        output_artifact="Reporte de validación con scoring por dato",
        evaluation_criteria=(
            "Rigor: ¿cada dato fue contrastado con al menos una fuente independiente?",
            "Detección de sesgo: ¿identificó fuentes con conflicto de interés?",
            "Consistencia: ¿señaló contradicciones entre fuentes?",
            "Gaps: ¿identificó información faltante crítica para el propósito?",
            "Honestidad epistémica: ¿marcó correctamente lo que NO pudo verificar?",
        ),
        canonical_referent=(
            "Auditor / fact-checker independiente con experiencia en finanzas. "
            "Evalúa como si el reporte fuera a ser presentado a un regulador."
        ),
    ),
    "compile": AgentCanon(
        name="compile",
        canonical_name="COMPILE — Generador de Documentos Estructurados",
        phase=EpistemicPhase.MODEL,
        description=(
            "Transforma observaciones validadas en un documento estructurado "
            "que modela la realidad del tema. Usa Pirámide de Minto: "
            "conclusión primero, argumentos después, evidencia al final."
        ),
        purpose=(
            "Documento ejecutivo con tesis central, estructura argumentativa "
            "clara, y cada afirmación trazable a las observaciones validadas."
        ),
        output_artifact="Documento estructurado (Minto Pyramid)",
        evaluation_criteria=(
            "Estructura lógica: ¿la pirámide argumental es coherente (tesis→argumentos→evidencia)?",
            "Trazabilidad: ¿cada afirmación del modelo apunta a observaciones de VALIDATE?",
            "Completitud: ¿el modelo incorpora todas las observaciones relevantes?",
            "Claridad: ¿un lector externo puede seguir el argumento sin conocimiento previo?",
            "Fidelidad: ¿el modelo NO agrega interpretaciones sin sustento en observaciones?",
        ),
        canonical_referent=(
            "Consultor estratégico senior (McKinsey/BCG) con experiencia en "
            "documentos para directorio. Evalúa estructura y rigor argumentativo."
        ),
    ),
    "audit": AgentCanon(
        name="audit",
        canonical_name="AUDIT — Revisión Multi-Experto",
        phase=EpistemicPhase.MODEL,
        description=(
            "Panel de expertos virtuales (legal, financiero, persuasión, lógica) "
            "revisa el modelo generado por COMPILE. Cada experto evalúa desde "
            "su dominio. El panel produce un veredicto consolidado."
        ),
        purpose=(
            "Veredicto con scoring por dimensión (legal, lógica, persuasión, "
            "completitud), debilidades identificadas, y recomendaciones de mejora."
        ),
        output_artifact="Veredicto multi-experto con scoring dimensional",
        evaluation_criteria=(
            "Multi-dimensionalidad: ¿evaluó desde múltiples perspectivas relevantes?",
            "Profundidad: ¿cada dimensión fue evaluada con rigor, no superficialmente?",
            "Constructividad: ¿las críticas vienen con recomendaciones accionables?",
            "Sustento: ¿cada crítica referencia la parte específica del modelo que cuestiona?",
            "Equilibrio: ¿identifica fortalezas además de debilidades?",
        ),
        canonical_referent=(
            "Panel multi-experto: abogado CMF, CFA charterholder, director de "
            "comunicaciones corporativas. Evalúan como si el documento fuera a "
            "regulador, inversionista institucional, y directorio simultáneamente."
        ),
    ),
    "reflect": AgentCanon(
        name="reflect",
        canonical_name="REFLECT — Stress-Test Estratégico",
        phase=EpistemicPhase.MODEL,
        description=(
            "Stress-test del modelo auditado: busca supuestos no validados, "
            "escenarios adversos, riesgos de segundo orden, y puntos ciegos. "
            "Actúa como devil's advocate informado."
        ),
        purpose=(
            "Análisis de robustez con supuestos desafiados, escenarios adversos "
            "modelados, y evaluación de qué tan sensible es la conclusión a "
            "cambios en las premisas."
        ),
        output_artifact="Reporte de stress-test con análisis de sensibilidad",
        evaluation_criteria=(
            "Profundidad adversarial: ¿desafió los supuestos más cómodos, no solo los obvios?",
            "Escenarios: ¿modeló al menos 2-3 escenarios adversos realistas?",
            "Sensibilidad: ¿identificó qué premisas al cambiar destruyen la conclusión?",
            "Creatividad: ¿encontró riesgos que el modelo original no consideró?",
            "Realismo: ¿los escenarios adversos son plausibles, no fantasiosos?",
        ),
        canonical_referent=(
            "Devil's advocate estratégico con experiencia en risk management. "
            "Evalúa como si fuera a desafiar la tesis en un comité de riesgo."
        ),
    ),
    "decide": AgentCanon(
        name="decide",
        canonical_name="DECIDE — Opciones Estratégicas con Trade-offs",
        phase=EpistemicPhase.DECISION,
        description=(
            "Presenta 2-3 opciones estratégicas con trade-offs explícitos "
            "para que el CEO decida. Cada opción se sustenta en los modelos "
            "de AUDIT y REFLECT, nunca directamente en observaciones crudas."
        ),
        purpose=(
            "Menú de decisión con 2-3 opciones, trade-offs por stakeholder, "
            "tabla comparativa, y recomendación condicional."
        ),
        output_artifact="Menú de decisión con trade-offs y recomendación",
        evaluation_criteria=(
            "Sustento en modelos: ¿cada opción se deriva de los modelos de AUDIT/REFLECT, no de datos crudos?",
            "Diferenciación: ¿las opciones son genuinamente distintas, no variaciones cosméticas?",
            "Trade-offs: ¿cada opción tiene costos/riesgos explícitos, no solo beneficios?",
            "Accionabilidad: ¿el CEO puede ejecutar la opción elegida con la info provista?",
            "Reversibilidad: ¿se indica qué tan reversible es cada opción?",
        ),
        canonical_referent=(
            "Strategy advisor de C-suite con experiencia en asset management. "
            "Evalúa como si fuera a presentar las opciones al directorio de Cordada."
        ),
    ),
    "distribute": AgentCanon(
        name="distribute",
        canonical_name="DISTRIBUTE — Adaptación a Canal y Destinatario",
        phase=EpistemicPhase.DECISION,
        description=(
            "Adapta la decisión tomada al canal y destinatario apropiado. "
            "Genera versiones del mensaje para email, Slack, WhatsApp, etc. "
            "El contenido refleja la decisión, no reinterpreta los datos."
        ),
        purpose=(
            "Mensaje(s) adaptado(s) al canal con tono, extensión y formato "
            "apropiados para cada destinatario."
        ),
        output_artifact="Mensaje adaptado por canal (email, Slack, etc.)",
        evaluation_criteria=(
            "Fidelidad: ¿el mensaje refleja fielmente la decisión tomada, sin distorsión?",
            "Tono: ¿el tono es apropiado para el destinatario y canal?",
            "Completitud: ¿incluye la información necesaria para que el destinatario actúe?",
            "Concisión: ¿es lo más breve posible sin perder información crítica?",
            "Sensibilidad: ¿maneja información confidencial apropiadamente?",
        ),
        canonical_referent=(
            "Director de comunicaciones corporativas de un asset manager. "
            "Evalúa como si el mensaje fuera a salir en nombre del CEO."
        ),
    ),
    "collect_iterate": AgentCanon(
        name="collect_iterate",
        canonical_name="COLLECT+ITERATE — Recolección de Feedback",
        phase=EpistemicPhase.OBSERVATION,
        description=(
            "Recolecta feedback de stakeholders (vía email, Slack) y lo "
            "estructura como nuevas observaciones para re-inyectar en el "
            "ciclo. Alimenta AUDIT, no DISCOVER — se refina el modelo, "
            "no se re-investiga."
        ),
        purpose=(
            "Feedback estructurado: quién dijo qué, qué implica para el "
            "documento, qué requiere cambio vs qué es ruido."
        ),
        output_artifact="Reporte de feedback estructurado con scoring de señal/ruido",
        evaluation_criteria=(
            "Completitud: ¿capturó todo el feedback relevante de todos los canales?",
            "Señal vs ruido: ¿distinguió feedback accionable de comentarios irrelevantes?",
            "Atribución: ¿cada pieza de feedback está atribuida a su autor?",
            "Accionabilidad: ¿cada item accionable tiene una recomendación clara?",
            "Priorización: ¿ordenó el feedback por impacto y urgencia?",
        ),
        canonical_referent=(
            "Product manager senior con experiencia en procesos iterativos. "
            "Evalúa como si fuera a priorizar un backlog de cambios."
        ),
    ),
}


# ---------------------------------------------------------------------------
# Invariant validation
# ---------------------------------------------------------------------------

# Pipeline order for invariant checking
PIPELINE_ORDER: list[str] = [
    "discover", "extract", "validate", "compile",
    "audit", "reflect", "decide", "distribute",
    "collect_iterate",
]


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
        (valid, explanation) — True if the transition is legal.
    """
    canon = AGENT_CANON.get(agent_name)
    if not canon:
        return True, f"Agent '{agent_name}' has no canonical definition, skipping."

    if upstream_agent is None:
        return True, f"{agent_name}: first in chain, no upstream to validate."

    upstream_canon = AGENT_CANON.get(upstream_agent)
    if not upstream_canon:
        return True, f"Upstream '{upstream_agent}' has no canonical definition, skipping."

    current_phase = canon.phase
    upstream_phase = upstream_canon.phase

    valid_phases = VALID_UPSTREAM[current_phase]
    if upstream_phase in valid_phases:
        return True, (
            f"{upstream_agent}({upstream_phase.value}) → "
            f"{agent_name}({current_phase.value}): valid"
        )

    return False, (
        f"INVARIANT VIOLATION: {upstream_agent}({upstream_phase.value}) → "
        f"{agent_name}({current_phase.value}). "
        f"Phase '{current_phase.value}' requires upstream in {{{', '.join(p.value for p in valid_phases)}}}, "
        f"but got '{upstream_phase.value}'. "
        f"A {current_phase.value} must be sustained by "
        f"{' or '.join(p.value for p in valid_phases)}, never directly by {upstream_phase.value}."
    )


# ---------------------------------------------------------------------------
# Evaluation via Claude
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


@dataclass
class AgentEvaluation:
    """Result of evaluating an agent's output against its canonical criteria."""
    agent: str
    score: int
    criteria_scores: dict[str, int]
    reasoning: str
    canonical_referent: str
    epistemic_phase: str


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


def evaluate_output(
    agent_name: str,
    output: str,
    max_output_chars: int = 8000,
) -> AgentEvaluation | None:
    """Evaluate an agent's output against its canonical criteria.

    Makes a single Sonnet call. Returns None if evaluation fails.
    """
    canon = AGENT_CANON.get(agent_name)
    if not canon:
        logger.warning("No canonical definition for agent '%s', skipping eval.", agent_name)
        return None

    # Truncate output to stay within token limits
    eval_output = output[:max_output_chars]
    if len(output) > max_output_chars:
        eval_output += "\n[... truncado para evaluación]"

    user_msg = _EVAL_USER_TEMPLATE.format(
        canonical_name=canon.canonical_name,
        phase=canon.phase.value,
        description=canon.description,
        purpose=canon.purpose,
        canonical_referent=canon.canonical_referent,
        output=eval_output,
        criteria_prompt=canon.criteria_prompt,
        phase_rule=_PHASE_RULES[canon.phase],
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

        # Parse JSON (handle code fences)
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
            canonical_referent=canon.canonical_referent,
            epistemic_phase=canon.phase.value,
        )
    except Exception:
        logger.exception("Canonical evaluation failed for agent '%s'", agent_name)
        return None
