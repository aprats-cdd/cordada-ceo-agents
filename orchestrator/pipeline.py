"""
Pipeline Orchestrator — Chain agents with gate-based pause/resume.

Layer 1 (feed) runs automatically. Layer 2 (interpret/decide) pauses
at configurable gates for CEO review. Pipeline state is saved on stop,
enabling async resume (e.g., review overnight, resume next morning).

Usage:
    # Auto pipeline with gates at Layer 2
    results = run_pipeline(topic="gobernanza", gates={"audit", "reflect"})

    # Pipeline stops at gate → resume later
    results = resume_pipeline("due-diligence-xyz")

CLI:
    python -m orchestrator.pipeline --topic "gobernanza" --gates audit reflect
    python -m orchestrator.pipeline --resume "due-diligence-xyz"
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from .config import AGENTS, OUTPUTS_DIR, get_model
from .agent_runner import run_agent
from .gates import (
    GateContext,
    GateResult,
    GateHandler,
    terminal_gate,
    DEFAULT_GATES,
)


# Pipeline sequences
DEFAULT_PIPELINE = ["discover", "extract", "validate", "compile", "audit", "reflect"]

FULL_PIPELINE = [
    "discover", "extract", "validate", "compile",
    "audit", "reflect", "distribute",
]


def run_pipeline(
    topic: str | None = None,
    input_text: str | None = None,
    from_agent: str = "discover",
    to_agent: str = "reflect",
    interactive_at: set[str] | None = None,
    project_name: str | None = None,
    project_description: str | None = None,
    gates: set[str] | None = None,
    on_gate: GateHandler = terminal_gate,
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
        gates: Agent names where the pipeline pauses for human review.
               Default: None (no gates). Use DEFAULT_GATES for standard gates.
        on_gate: Callback function for gate handling (default: terminal_gate)

    Returns:
        Dict mapping agent names to their outputs
    """
    interactive_at = interactive_at or set()
    gates = gates or set()

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

    # Create local output directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = OUTPUTS_DIR / f"pipeline_{timestamp}"
    run_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'#'*60}")
    print(f"  PIPELINE RUN")
    print(f"  Sequence: {' → '.join(s.upper() for s in sequence)}")
    if gates:
        print(f"  Gates: {', '.join(g.upper() for g in gates if g in sequence)}")
    if project_dir:
        print(f"  Project: {project_dir}")
    print(f"  Output dir: {run_dir}")
    print(f"{'#'*60}")

    outputs = {}

    for i, agent_name in enumerate(sequence):
        step = i + 1
        total = len(sequence)
        model = get_model(agent_name)

        # Build input for this agent
        if i > 0:
            prev_agent = sequence[i - 1]
            pipeline_context = (
                f"Este es el output del agente {prev_agent.upper()} del pipeline. "
                f"Procesa este input según tus instrucciones:\n\n"
                f"---\n\n{current_input}"
            )
        else:
            pipeline_context = current_input

        # Gate check: pause for human review before running this agent
        if agent_name in gates:
            gate_ctx = GateContext(
                agent_name=agent_name,
                step=step,
                total_steps=total,
                outputs=dict(outputs),
                proposed_input=pipeline_context,
                topic=topic or "",
                project_name=project_name,
            )

            gate_result = on_gate(gate_ctx)

            if gate_result.action == "stop":
                # Save state and exit
                if project_dir:
                    from .project import save_pipeline_state, push_project

                    save_pipeline_state(
                        project_dir=project_dir,
                        paused_at=agent_name,
                        step=step,
                        total_steps=total,
                        pending_input=pipeline_context,
                        outputs=outputs,
                        note=gate_result.note,
                    )
                    push_project(project_dir)

                # Also save locally
                state = {
                    "paused_at": agent_name,
                    "step": step,
                    "total_steps": total,
                    "sequence": sequence,
                    "topic": topic,
                    "note": gate_result.note,
                    "timestamp": datetime.now().isoformat(),
                }
                state_path = run_dir / "pipeline_state.json"
                state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False))

                print(f"\n  Pipeline stopped at {agent_name.upper()} gate.")
                if project_name:
                    print(f"  Resume: investigate(\"{project_name}\", resume=True)")
                print(f"  State saved: {state_path}")
                return outputs

            elif gate_result.action == "modify" and gate_result.modified_input:
                pipeline_context = gate_result.modified_input
                if gate_result.note:
                    print(f"  Gate note: {gate_result.note[:80]}")

            # action == "proceed": continue as-is

        print(f"\n{'─'*60}")
        print(f"  Step {step}/{total}: {agent_name.upper()} ({model.split('-')[1]})")
        print(f"{'─'*60}")

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
        current_input = response

        # Project mode: commit each agent output
        if project_dir:
            from .project import commit_agent_output

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
        from .project import push_project

        push_project(project_dir)

    print(f"\n{'#'*60}")
    print(f"  PIPELINE COMPLETE")
    print(f"  Outputs: {run_dir}")
    if project_dir:
        from .project import load_manifest

        manifest = load_manifest(project_dir)
        print(f"  GitHub: https://github.com/{manifest['repo']}")
    print(f"  Summary: {summary_path}")
    print(f"{'#'*60}\n")

    return outputs


def resume_pipeline(
    project_name: str,
    gate_input: str | None = None,
    on_gate: GateHandler = terminal_gate,
    gates: set[str] | None = None,
) -> dict[str, str]:
    """
    Resume a pipeline that was stopped at a gate.

    Loads state from the project's manifest and continues from where
    it left off.

    Args:
        project_name: The project to resume
        gate_input: Optional human input to inject at the resume point
        on_gate: Gate handler for subsequent gates
        gates: Override gate set (default: keeps original gates)

    Returns:
        Dict mapping agent names to their outputs (includes prior outputs)
    """
    from .project import get_project_dir, load_manifest

    project_dir = get_project_dir(project_name)
    manifest = load_manifest(project_dir)

    pipeline_state = manifest.get("pipeline_state")
    if not pipeline_state:
        raise RuntimeError(f"Project '{project_name}' has no paused pipeline to resume")

    paused_at = pipeline_state["paused_at"]
    topic = manifest["topic"]
    sequence = manifest["pipeline"]
    prior_outputs = pipeline_state.get("outputs", {})

    # Determine input for the paused agent
    pending_input = pipeline_state.get("pending_input", "")
    if gate_input:
        pending_input = (
            f"{pending_input}\n\n"
            f"---\n\n"
            f"Contexto adicional del CEO:\n\n{gate_input}"
        )

    print(f"\n  Resuming pipeline for '{project_name}' at {paused_at.upper()}")

    # Continue from the paused agent
    return run_pipeline(
        topic=topic,
        input_text=pending_input,
        from_agent=paused_at,
        to_agent=sequence[-1],
        project_name=project_name,
        gates=gates if gates is not None else set(
            a for a in sequence[sequence.index(paused_at) + 1:]
            if a in DEFAULT_GATES
        ),
        on_gate=on_gate,
    )


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
  # Full pipeline with gates at Layer 2
  python -m orchestrator.pipeline --topic "gobernanza" --gates audit reflect

  # Full pipeline, no gates (runs straight through)
  python -m orchestrator.pipeline --topic "gobernanza"

  # With GitHub traceability
  python -m orchestrator.pipeline --topic "gobernanza" \\
      --project "due-diligence-xyz" --gates audit reflect

  # Resume a stopped pipeline
  python -m orchestrator.pipeline --resume "due-diligence-xyz"

  # Partial pipeline
  python -m orchestrator.pipeline --topic "deuda privada" --to compile

  # Interactive mode at specific agents
  python -m orchestrator.pipeline --topic "tema" --interactive-at audit reflect
        """,
    )

    parser.add_argument("--topic", type=str, help="Research topic")
    parser.add_argument("--input-file", type=str, help="File to use as input")
    parser.add_argument("--from", dest="from_agent", default="discover", choices=list(AGENTS.keys()))
    parser.add_argument("--to", dest="to_agent", default="reflect", choices=list(AGENTS.keys()))
    parser.add_argument("--interactive-at", nargs="*", default=[], choices=list(AGENTS.keys()))
    parser.add_argument("--project", type=str, help="Project name for GitHub traceability")
    parser.add_argument("--project-description", type=str)
    parser.add_argument(
        "--gates",
        nargs="*",
        choices=list(AGENTS.keys()),
        help="Agents where pipeline pauses for human review",
    )
    parser.add_argument(
        "--resume",
        type=str,
        metavar="PROJECT",
        help="Resume a stopped pipeline by project name",
    )
    parser.add_argument(
        "--gate-input",
        type=str,
        help="Human input to inject when resuming at a gate",
    )

    args = parser.parse_args()

    # Resume mode
    if args.resume:
        resume_pipeline(
            project_name=args.resume,
            gate_input=args.gate_input,
        )
        return

    # Standard run
    input_text = None
    if args.input_file:
        input_text = Path(args.input_file).read_text(encoding="utf-8")

    if not args.topic and not input_text:
        print("Error: Provide --topic, --input-file, or --resume")
        sys.exit(1)

    gate_set = set(args.gates) if args.gates else set()

    run_pipeline(
        topic=args.topic,
        input_text=input_text,
        from_agent=args.from_agent,
        to_agent=args.to_agent,
        interactive_at=set(args.interactive_at),
        project_name=args.project,
        project_description=args.project_description,
        gates=gate_set,
    )


if __name__ == "__main__":
    main()
