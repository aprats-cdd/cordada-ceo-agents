"""
cordada-ceo-agents — Programmatic API for CEO-level agent pipeline.

Usage:

    from orchestrator import investigate, agent, decide

    # Run full pipeline with GitHub traceability (1 line)
    results = investigate(
        "due-diligence-fondo-xyz",
        topic="Análisis de gobernanza para due diligence institucional",
    )
    print(results["discover"])   # What was observed
    print(results["compile"])    # What was drafted
    print(results["reflect"])    # Strategic assessment

    # Run a single agent (returns string, no files)
    output = agent("discover", "deuda privada LatAm")

    # Present decision options
    options = decide("Resolver gobernanza Cordada antes de due diligence")

    # Full pipeline without GitHub (local only)
    results = investigate(topic="análisis regulatorio CMF")
"""

from .agent_runner import run_agent as _run_agent
from .pipeline import run_pipeline as _run_pipeline
from .config import AGENTS


def agent(name: str, input: str, *, verbose: bool = False) -> str:
    """
    Run a single agent and return its output.

    Args:
        name: Agent name (discover, extract, validate, compile,
              audit, reflect, decide, distribute, collect_iterate)
        input: The text input for the agent
        verbose: Print progress banners (default: False)

    Returns:
        Agent's response as a string

    Example:
        output = agent("discover", "deuda privada LatAm gobernanza")
        output = agent("compile", extracted_data)
    """
    return _run_agent(
        agent_name=name,
        user_input=input,
        save=False,
        verbose=verbose,
    )


def investigate(
    project: str | None = None,
    *,
    topic: str,
    description: str | None = None,
    from_agent: str = "discover",
    to_agent: str = "reflect",
    interactive_at: set[str] | None = None,
    verbose: bool = True,
) -> dict[str, str]:
    """
    Run the agent pipeline end-to-end.

    With a project name: creates a GitHub repo with full traceability.
    Without: runs locally, returns results in memory.

    Args:
        project: Project slug for GitHub traceability (optional).
                 Creates github.com/{org}/cordada-proyecto-{project}
        topic: Research topic or decision context
        description: Optional longer description for the project
        from_agent: Start from this agent (default: discover)
        to_agent: Stop at this agent (default: reflect)
        interactive_at: Agents where interactive mode is enabled
        verbose: Print progress (default: True)

    Returns:
        Dict mapping agent names to their output strings.

    Examples:
        # Full pipeline with GitHub repo
        results = investigate(
            "due-diligence-fondo-xyz",
            topic="Análisis de gobernanza para due diligence",
        )

        # Local only, partial pipeline
        results = investigate(
            topic="regulación CMF para fondos de deuda",
            to_agent="compile",
        )

        # Access outputs programmatically
        results["discover"]   # What was observed
        results["extract"]    # What was extracted
        results["validate"]   # What was verified
        results["compile"]    # What was drafted
        results["audit"]      # What experts said
        results["reflect"]    # Strategic assessment
    """
    return _run_pipeline(
        topic=topic,
        from_agent=from_agent,
        to_agent=to_agent,
        interactive_at=interactive_at,
        project_name=project,
        project_description=description,
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
    return agent("decide", context, verbose=verbose)


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


__all__ = ["agent", "investigate", "decide", "list_agents"]
