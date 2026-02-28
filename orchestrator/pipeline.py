"""
Pipeline Orchestrator — Chain agents into a full or partial pipeline.

Runs agents in sequence, passing the output of each as input to the next.
Supports starting from any stage and stopping at any stage.

With --project, each run creates a GitHub repo with full git traceability:
every agent output is committed individually, creating a complete audit trail.

Usage:
    # Standard pipeline (outputs to local files)
    python -m orchestrator.pipeline --topic "gobernanza para due diligence"

    # Project mode: creates GitHub repo with full traceability
    python -m orchestrator.pipeline --topic "gobernanza para due diligence" \
        --project "due-diligence-fondo-xyz"

    # Partial pipeline
    python -m orchestrator.pipeline --from compile --input-file ./validated.md
    python -m orchestrator.pipeline --from discover --to compile --topic "deuda privada"
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

from .config import AGENTS, OUTPUTS_DIR, get_model
from .agent_runner import run_agent


# Default pipeline sequence (Layer 1 → Layer 2, excluding DECIDE and Layer 3)
DEFAULT_PIPELINE = ["discover", "extract", "validate", "compile", "audit", "reflect"]

# Full pipeline including distribution
FULL_PIPELINE = [
    "discover",
    "extract",
    "validate",
    "compile",
    "audit",
    "reflect",
    "distribute",
]


def run_pipeline(
    topic: str | None = None,
    input_text: str | None = None,
    from_agent: str = "discover",
    to_agent: str = "reflect",
    interactive_at: set[str] | None = None,
    project_name: str | None = None,
    project_description: str | None = None,
) -> dict[str, str]:
    """
    Run a sequence of agents, passing outputs forward.

    Args:
        topic: The research topic (used as initial input for DISCOVER)
        input_text: Direct input text (used when starting mid-pipeline)
        from_agent: Which agent to start from
        to_agent: Which agent to stop at (inclusive)
        interactive_at: Set of agent names where interactive mode is enabled
        project_name: If provided, creates a GitHub repo for full traceability
        project_description: Optional description for the project repo

    Returns:
        Dict mapping agent names to their outputs
    """
    interactive_at = interactive_at or set()

    # Build the sequence
    all_agents = list(AGENTS.keys())
    order_map = {name: info["order"] for name, info in AGENTS.items()}

    start_order = order_map[from_agent]
    end_order = order_map[to_agent]

    sequence = [
        name
        for name in all_agents
        if start_order <= order_map[name] <= end_order
        and name in FULL_PIPELINE
    ]

    if not sequence:
        print(f"Error: No agents between {from_agent} and {to_agent}")
        sys.exit(1)

    # Prepare initial input
    current_input = input_text or topic
    if not current_input:
        print("Error: Provide --topic or --input-file")
        sys.exit(1)

    # Project mode: create GitHub repo for traceability
    project_dir = None
    if project_name:
        from .project import create_project, commit_agent_output, push_project

        project_dir = create_project(
            name=project_name,
            topic=topic or "Pipeline run",
            description=project_description,
            pipeline=sequence,
        )

    # Create local output directory (used in non-project mode or as backup)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = OUTPUTS_DIR / f"pipeline_{timestamp}"
    run_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'#'*60}")
    print(f"  PIPELINE RUN")
    print(f"  Sequence: {' → '.join(s.upper() for s in sequence)}")
    if project_dir:
        print(f"  Project: {project_dir}")
    print(f"  Output dir: {run_dir}")
    print(f"{'#'*60}")

    outputs = {}

    for i, agent_name in enumerate(sequence):
        step = i + 1
        total = len(sequence)
        model = get_model(agent_name)

        print(f"\n{'─'*60}")
        print(f"  Step {step}/{total}: {agent_name.upper()} ({model.split('-')[1]})")
        print(f"{'─'*60}")

        # For agents after the first, add context about pipeline
        if i > 0:
            prev_agent = sequence[i - 1]
            pipeline_context = (
                f"Este es el output del agente {prev_agent.upper()} del pipeline. "
                f"Procesa este input según tus instrucciones:\n\n"
                f"---\n\n{current_input}"
            )
        else:
            pipeline_context = current_input

        # Run agent
        is_interactive = agent_name in interactive_at
        output_path = run_dir / f"{step:02d}_{agent_name}.md"

        response = run_agent(
            agent_name=agent_name,
            user_input=pipeline_context,
            output_path=output_path,
            interactive=is_interactive,
        )

        outputs[agent_name] = response
        current_input = response  # Feed to next agent

        # Project mode: commit each agent output
        if project_dir:
            commit_agent_output(
                project_dir=project_dir,
                agent_name=agent_name,
                output=response,
                step=step,
                total_steps=total,
                model=model,
                topic=topic or "Pipeline run",
            )

    # Save pipeline summary
    summary_path = run_dir / "00_pipeline_summary.md"
    summary = _generate_summary(sequence, outputs, topic, timestamp)
    summary_path.write_text(summary, encoding="utf-8")

    # Project mode: push all commits to GitHub
    if project_dir:
        push_project(project_dir)

    print(f"\n{'#'*60}")
    print(f"  ✅ PIPELINE COMPLETE")
    print(f"  Outputs: {run_dir}")
    if project_dir:
        from .project import load_manifest
        manifest = load_manifest(project_dir)
        print(f"  GitHub: https://github.com/{manifest['repo']}")
    print(f"  Summary: {summary_path}")
    print(f"{'#'*60}\n")

    return outputs


def _generate_summary(
    sequence: list[str],
    outputs: dict[str, str],
    topic: str | None,
    timestamp: str,
) -> str:
    """Generate a markdown summary of the pipeline run."""
    lines = [
        f"# Pipeline Run — {timestamp}",
        f"",
        f"**Topic:** {topic or 'N/A'}",
        f"**Sequence:** {' → '.join(s.upper() for s in sequence)}",
        f"**Agents run:** {len(sequence)}",
        f"",
        f"## Outputs",
        f"",
    ]

    for i, agent_name in enumerate(sequence):
        output = outputs.get(agent_name, "No output")
        preview = output[:200].replace("\n", " ") + "..." if len(output) > 200 else output
        lines.append(f"### {i+1}. {agent_name.upper()}")
        lines.append(f"")
        lines.append(f"**File:** `{i+1:02d}_{agent_name}.md`")
        lines.append(f"**Preview:** {preview}")
        lines.append(f"")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Run the cordada-ceo-agents pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full pipeline from research to reflection
  python -m orchestrator.pipeline --topic "gobernanza para due diligence"

  # With GitHub traceability (creates a repo per project)
  python -m orchestrator.pipeline --topic "gobernanza para due diligence" \\
      --project "due-diligence-fondo-xyz"

  # Start from COMPILE with pre-existing data
  python -m orchestrator.pipeline --from compile --input-file ./validated.md

  # Only run Layer 1 (feed)
  python -m orchestrator.pipeline --topic "deuda privada" --to compile

  # Interactive mode at AUDIT and REFLECT
  python -m orchestrator.pipeline --topic "tema" --interactive-at audit reflect
        """,
    )

    parser.add_argument(
        "--topic",
        type=str,
        help="Research topic (initial input for DISCOVER)",
    )
    parser.add_argument(
        "--input-file",
        type=str,
        help="File to use as input (when starting mid-pipeline)",
    )
    parser.add_argument(
        "--from",
        dest="from_agent",
        type=str,
        default="discover",
        choices=list(AGENTS.keys()),
        help="Start pipeline from this agent (default: discover)",
    )
    parser.add_argument(
        "--to",
        dest="to_agent",
        type=str,
        default="reflect",
        choices=list(AGENTS.keys()),
        help="Stop pipeline at this agent (default: reflect)",
    )
    parser.add_argument(
        "--interactive-at",
        nargs="*",
        default=[],
        choices=list(AGENTS.keys()),
        help="Enable interactive mode at these agents",
    )
    parser.add_argument(
        "--project",
        type=str,
        help="Project name — creates a GitHub repo with full traceability",
    )
    parser.add_argument(
        "--project-description",
        type=str,
        help="Optional description for the project repo",
    )

    args = parser.parse_args()

    # Resolve input
    input_text = None
    if args.input_file:
        input_text = Path(args.input_file).read_text(encoding="utf-8")

    if not args.topic and not input_text:
        print("Error: Provide --topic or --input-file")
        sys.exit(1)

    # Run pipeline
    run_pipeline(
        topic=args.topic,
        input_text=input_text,
        from_agent=args.from_agent,
        to_agent=args.to_agent,
        interactive_at=set(args.interactive_at),
        project_name=args.project,
        project_description=args.project_description,
    )


if __name__ == "__main__":
    main()
