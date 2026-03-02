"""
Agent Registry — single source of truth for all agent definitions.

Unifies what was previously split between ``config.AGENTS`` (pipeline
config) and ``canonical.AGENT_CANON`` (epistemic definitions).  One
``AgentDefinition`` per agent, one dict, one language.

    from domain.registry import AGENTS
    agent = AGENTS["discover"]
    agent.phase              # EpistemicPhase.OBSERVATION
    agent.canonical_referent # "Analista senior de research..."
    agent["file"]            # "01_discover.md"  (legacy dict access)
"""

from __future__ import annotations

from .model import AgentDefinition, EpistemicPhase

# ---------------------------------------------------------------------------
# Model defaults
# ---------------------------------------------------------------------------

MODEL_DEFAULT = "claude-sonnet-4-20250514"
MODEL_PREMIUM = "claude-opus-4-6"
PREMIUM_AGENTS = {"audit", "reflect", "decide"}

# ---------------------------------------------------------------------------
# The Registry — one definition per agent, one source of truth
# ---------------------------------------------------------------------------

AGENTS: dict[str, AgentDefinition] = {
    "discover": AgentDefinition(
        name="discover",
        canonical_name="DISCOVER — Investigación y Catálogo de Fuentes",
        order=1,
        layer="feed",
        next_agent="extract",
        prompt_file="01_discover.md",
        phase=EpistemicPhase.OBSERVATION,
        description="Research and rank sources",
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
    "extract": AgentDefinition(
        name="extract",
        canonical_name="EXTRACT — Extracción de Datos Clave",
        order=2,
        layer="feed",
        next_agent="validate",
        prompt_file="02_extract.md",
        phase=EpistemicPhase.OBSERVATION,
        description="Pull key data from sources",
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
    "validate": AgentDefinition(
        name="validate",
        canonical_name="VALIDATE — Verificación y Control de Calidad",
        order=3,
        layer="feed",
        next_agent="compile",
        prompt_file="03_validate.md",
        phase=EpistemicPhase.OBSERVATION,
        description="Verify accuracy and consistency",
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
    "compile": AgentDefinition(
        name="compile",
        canonical_name="COMPILE — Generador de Documentos Estructurados",
        order=4,
        layer="feed",
        next_agent="audit",
        prompt_file="04_compile.md",
        phase=EpistemicPhase.MODEL,
        description="Generate structured document",
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
    "audit": AgentDefinition(
        name="audit",
        canonical_name="AUDIT — Revisión Multi-Experto",
        order=5,
        layer="interpret",
        next_agent="reflect",
        prompt_file="05_audit.md",
        phase=EpistemicPhase.MODEL,
        description="Multi-expert panel review",
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
    "reflect": AgentDefinition(
        name="reflect",
        canonical_name="REFLECT — Stress-Test Estratégico",
        order=6,
        layer="decide",
        next_agent="decide",
        prompt_file="06_reflect.md",
        phase=EpistemicPhase.MODEL,
        description="Strategic stress-test",
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
    "decide": AgentDefinition(
        name="decide",
        canonical_name="DECIDE — Opciones Estratégicas con Trade-offs",
        order=7,
        layer="decide",
        next_agent="distribute",
        prompt_file="07_decide.md",
        phase=EpistemicPhase.DECISION,
        description="Present options with trade-offs",
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
    "distribute": AgentDefinition(
        name="distribute",
        canonical_name="DISTRIBUTE — Adaptación a Canal y Destinatario",
        order=8,
        layer="distribute",
        next_agent="collect_iterate",
        prompt_file="08_distribute.md",
        phase=EpistemicPhase.DECISION,
        description="Adapt deliverable to channel",
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
    "collect_iterate": AgentDefinition(
        name="collect_iterate",
        canonical_name="COLLECT+ITERATE — Recolección de Feedback",
        order=9,
        layer="feedback",
        next_agent="audit",
        prompt_file="09_collect_iterate.md",
        phase=EpistemicPhase.OBSERVATION,
        description="Parse feedback and re-inject",
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
    "context": AgentDefinition(
        name="context",
        canonical_name="CONTEXT — Middleware de Contexto Interno",
        order=10,
        layer="support",
        next_agent=None,
        prompt_file="10_context.md",
        phase=EpistemicPhase.OBSERVATION,
        description="Search internal sources to suggest answers",
        purpose=(
            "Sugerencias de respuesta con fuente, puntaje 1-10, y razonamiento. "
            "Evaluación contextual según el agente que pregunta."
        ),
        output_artifact="Sugerencias puntuadas con fuente y razonamiento",
        evaluation_criteria=(
            "Relevancia: ¿las sugerencias responden directamente la pregunta?",
            "Frescura: ¿las fuentes son recientes y vigentes?",
            "Autoridad: ¿las fuentes son confiables para el tipo de dato?",
            "Suficiencia: ¿la información es completa o parcial?",
            "Calibración: ¿los puntajes reflejan correctamente la calidad?",
        ),
        canonical_referent=(
            "El referente canónico del agente que está preguntando. "
            "CONTEXT adopta la perspectiva del agente llamante."
        ),
    ),
}


# Pipeline order (excludes CONTEXT, which is support)
PIPELINE_ORDER: list[str] = [
    name for name, agent in sorted(AGENTS.items(), key=lambda x: x[1].order)
    if agent.layer != "support"
]


# ---------------------------------------------------------------------------
# Accessor helpers
# ---------------------------------------------------------------------------

def get_agent(name: str) -> AgentDefinition:
    """Get agent definition by name, raising ValueError if unknown."""
    if name not in AGENTS:
        available = ", ".join(sorted(AGENTS.keys()))
        raise ValueError(f"Unknown agent: '{name}'. Available: {available}")
    return AGENTS[name]


def get_model_for_agent(name: str) -> str:
    """Return the appropriate model for an agent."""
    if name in PREMIUM_AGENTS:
        return MODEL_PREMIUM
    return MODEL_DEFAULT
