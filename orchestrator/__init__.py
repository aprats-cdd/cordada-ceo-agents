"""
cordada-ceo-agents — Programmatic API for CEO-level agent pipeline.

Usage:

    from orchestrator import investigate, agent, decide

    # Full pipeline with gates (pauses at Layer 2 for CEO review)
    results = investigate(
        "due-diligence-fondo-xyz",
        topic="Análisis de gobernanza para due diligence institucional",
        gates={"audit", "reflect"},
    )

    # Pipeline stopped at a gate? Resume later:
    results = investigate(
        "due-diligence-fondo-xyz",
        resume=True,
        gate_input="Aprobado. Usar panel: legal CMF + persuasión + lógica.",
    )

    # Run a single agent (returns string, no files)
    output = agent("discover", "deuda privada LatAm")

    # Present decision options
    options = decide("Resolver gobernanza Cordada antes de due diligence")

    # Full pipeline without GitHub (local only)
    results = investigate(topic="análisis regulatorio CMF")
"""

from .agent_runner import run_agent as _run_agent
from .pipeline import run_pipeline as _run_pipeline, resume_pipeline as _resume_pipeline
from .gates import DEFAULT_GATES, GateHandler, terminal_gate, auto_gate
from .tools import call_claude_as_proxy
from .config import AGENTS


def agent(name: str, user_input: str, *, verbose: bool = False) -> str:
    """
    Run a single agent and return its output.

    Args:
        name: Agent name (discover, extract, validate, compile,
              audit, reflect, decide, distribute, collect_iterate, context)
        user_input: The text input for the agent
        verbose: Print progress banners (default: False)

    Returns:
        Agent's response as a string

    Example:
        output = agent("discover", "deuda privada LatAm gobernanza")
        output = agent("compile", extracted_data)
    """
    return _run_agent(
        agent_name=name,
        user_input=user_input,
        save=False,
        verbose=verbose,
    )


def investigate(
    project: str | None = None,
    *,
    topic: str | None = None,
    description: str | None = None,
    from_agent: str = "discover",
    to_agent: str = "decide",
    gates: set[str] | None = None,
    on_gate: GateHandler = terminal_gate,
    resume: bool = False,
    gate_input: str | None = None,
    interactive_at: set[str] | None = None,
    verbose: bool = True,
) -> dict[str, str]:
    """
    Run the agent pipeline end-to-end.

    Layer 1 (DISCOVER → COMPILE) runs automatically.
    Layer 2 (AUDIT, REFLECT, DECIDE) pauses at gates for CEO review.
    Layer 3 (DISTRIBUTE, COLLECT_ITERATE) requires mandatory gates.

    Args:
        project: Project slug for GitHub traceability (optional).
                 Creates github.com/{org}/cordada-proyecto-{project}
        topic: Research topic or decision context
        description: Optional longer description for the project
        from_agent: Start from this agent (default: discover)
        to_agent: Stop at this agent (default: decide)
        gates: Agents where pipeline pauses for CEO review.
               Use DEFAULT_GATES for standard gates.
        on_gate: Gate handler callback (default: terminal_gate).
                 Use auto_gate for fully automated runs.
        resume: If True, resume a previously stopped pipeline
        gate_input: Human input to inject when resuming at a gate
        interactive_at: Agents where interactive mode is enabled
        verbose: Print progress (default: True)

    Returns:
        Dict mapping agent names to their output strings.

    Examples:
        # Full pipeline with gates
        results = investigate(
            "due-diligence-fondo-xyz",
            topic="Análisis de gobernanza para due diligence",
            gates={"audit", "reflect"},
        )

        # Resume a stopped pipeline
        results = investigate(
            "due-diligence-fondo-xyz",
            resume=True,
            gate_input="Proceder con panel: legal + persuasión + lógica",
        )

        # Fully automated (no gates)
        results = investigate(topic="regulación CMF", on_gate=auto_gate)

        # Access outputs
        results["discover"]   # What was observed
        results["compile"]    # What was drafted
        results["reflect"]    # Strategic assessment
    """
    # Resume mode
    if resume:
        if not project:
            raise ValueError("resume=True requires a project name")
        return _resume_pipeline(
            project_name=project,
            gate_input=gate_input,
            on_gate=on_gate,
            gates=gates,
        )

    # Normal run
    if not topic:
        raise ValueError("topic is required (unless resuming)")

    return _run_pipeline(
        topic=topic,
        from_agent=from_agent,
        to_agent=to_agent,
        interactive_at=interactive_at,
        project_name=project,
        project_description=description,
        gates=gates or set(),
        on_gate=on_gate,
    )


def decide(context: str, *, verbose: bool = False) -> str:
    """
    Run the DECIDE agent to present 2-3 strategic options with trade-offs.

    Args:
        context: The decision context — what needs to be decided and why
        verbose: Print progress (default: False)

    Returns:
        Structured options with trade-offs, comparison table,
        and conditional recommendations.

    Example:
        options = decide(
            "Resolver la gobernanza de Cordada antes del due diligence. "
            "El directorio actual no pasa filtro institucional. "
            "Opciones: reorganizar directorio, vender participación, o negociar waiver."
        )
    """
    return agent("decide", user_input=context, verbose=verbose)


def list_agents() -> dict[str, dict]:
    """Return the agent registry with metadata."""
    return {
        name: {
            "order": info["order"],
            "layer": info["layer"],
            "description": info["description"],
        }
        for name, info in sorted(AGENTS.items(), key=lambda x: x[1]["order"])
    }


__all__ = [
    "agent",
    "investigate",
    "decide",
    "list_agents",
    "call_claude_as_proxy",
    "DEFAULT_GATES",
    "auto_gate",
    "terminal_gate",
]
