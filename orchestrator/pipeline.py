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
import signal
import sys
from datetime import datetime
from pathlib import Path

from domain.registry import AGENTS, get_model_for_agent as get_model
from domain.model import CostBudget
from domain.events import EventBus
from domain.evaluation import evaluate_structural

from .config import OUTPUTS_DIR, COST_BUDGET_MAX_USD, COST_MAX_OUTPUT_TOKENS, COST_MAX_ITERATIONS
from .agent_runner import run_agent, last_metrics
from .canonical import evaluate_output
from .contract_parser import try_parse, get_schema_instruction, get_retry_prompt
from .gates import (
    GateContext,
    GateResult,
    GateHandler,
    terminal_gate,
    DEFAULT_GATES,
)


# Pipeline sequences — all agents that can participate in a pipeline run.
# DECIDE and COLLECT_ITERATE have mandatory gates (require CEO intervention).
FULL_PIPELINE = [
    "discover", "extract", "validate", "compile",
    "audit", "reflect", "decide", "distribute",
    "collect_iterate",
]

# Token budget for context accumulation.
# Approx 4 chars per token. We leave room for the agent's system prompt
# (~2k tokens) and response (max_tokens). 180k input budget is safe for
# both Sonnet (200k context) and Opus (200k context).
_MAX_CONTEXT_TOKENS = 180_000
_CHARS_PER_TOKEN = 4  # conservative estimate
_MAX_CONTEXT_CHARS = _MAX_CONTEXT_TOKENS * _CHARS_PER_TOKEN


def run_pipeline(
    topic: str | None = None,
    input_text: str | None = None,
    from_agent: str = "discover",
    to_agent: str = "decide",
    interactive_at: set[str] | None = None,
    project_name: str | None = None,
    project_description: str | None = None,
    gates: set[str] | None = None,
    on_gate: GateHandler = terminal_gate,
    prior_outputs: dict[str, str] | None = None,
    no_context: bool = False,
    evaluate: bool = True,
    budget: CostBudget | None = None,
    budget_override: bool = False,
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
        prior_outputs: Outputs from previous agents (used when resuming).
                       Merged into the returned dict so callers get the full picture.
        no_context: If True, disable CONTEXT middleware in interactive agents.
        evaluate: If True, run canonical evaluation after each agent (default: True).
        budget: Cost budget (stop-loss) for the pipeline run. Default: from env vars.
        budget_override: If True, ignore budget exceeded and continue running.

    Returns:
        Dict mapping agent names to their outputs
    """
    interactive_at = interactive_at or set()
    gates = gates or set()

    # Cost governor: build budget from env defaults if not provided
    if budget is None:
        budget = CostBudget(
            max_total_usd=COST_BUDGET_MAX_USD,
            max_agent_output_tokens=COST_MAX_OUTPUT_TOKENS,
            max_feedback_iterations=COST_MAX_ITERATIONS,
        )

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
        raise ValueError(f"No agents between {from_agent} and {to_agent}")

    # Prepare initial input
    current_input = input_text or topic
    if not current_input:
        raise ValueError("Provide topic or input_text")

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
    print(f"  Stop-loss: ${budget.max_total_usd:.2f} "
          f"(warn at {budget.warning_threshold*100:.0f}%, "
          f"max {budget.max_feedback_iterations} feedback loops)")
    if budget_override:
        print(f"  ⚠️ Budget override active — stop-loss disabled")
    print(f"{'#'*60}")

    outputs = dict(prior_outputs) if prior_outputs else {}

    # Event bus for epistemic traceability
    bus = EventBus(
        run_id=f"pipeline_{timestamp}",
        persist_dir=run_dir,
    )

    # Graceful shutdown: save state on Ctrl+C instead of losing work (Fix #12)
    _shutdown_requested = False
    _original_sigint = signal.getsignal(signal.SIGINT)

    def _handle_shutdown(signum, frame):
        nonlocal _shutdown_requested
        if _shutdown_requested:
            # Second Ctrl+C: force exit
            print("\n  Forced exit.")
            sys.exit(1)
        _shutdown_requested = True
        print("\n  Shutdown requested. Finishing current agent, then saving state...")

    signal.signal(signal.SIGINT, _handle_shutdown)

    try:
        _run_pipeline_loop(
            sequence, outputs, topic, current_input, gates, on_gate,
            interactive_at, project_dir, project_name, run_dir,
            lambda: _shutdown_requested,
            no_context=no_context,
            bus=bus,
            evaluate=evaluate,
            budget=budget,
            budget_override=budget_override,
        )
    finally:
        signal.signal(signal.SIGINT, _original_sigint)

    # Save pipeline summary
    summary_path = run_dir / "00_pipeline_summary.md"
    summary = _generate_summary(sequence, outputs, topic, timestamp)
    summary_path.write_text(summary, encoding="utf-8")

    # Project mode: push all commits to GitHub
    if project_dir:
        from .project import push_project

        push_project(project_dir)

    completed_agents = [a for a in sequence if a in outputs]

    # Print epistemic chain, evaluation, and cost summary
    if bus.events:
        print(f"\n{'─'*60}")
        print(f"  EPISTEMIC CHAIN")
        print(bus.get_chain_summary())
        print(f"\n{bus.get_scores_summary()}")
        print(f"\n{bus.get_cost_summary()}")
        print(f"{'─'*60}")

    if len(completed_agents) == len(sequence):
        print(f"\n{'#'*60}")
        print(f"  PIPELINE COMPLETE")
        print(f"  Outputs: {run_dir}")
        if project_dir:
            from .project import load_manifest

            manifest = load_manifest(project_dir)
            print(f"  GitHub: https://github.com/{manifest['repo']}")
        print(f"  Summary: {summary_path}")
        print(f"{'#'*60}\n")
    else:
        print(f"\n  Pipeline stopped after {len(completed_agents)}/{len(sequence)} agents.")
        print(f"  Outputs saved: {run_dir}")

    return outputs


def _run_pipeline_loop(
    sequence: list[str],
    outputs: dict[str, str],
    topic: str | None,
    initial_input: str,
    gates: set[str],
    on_gate: GateHandler,
    interactive_at: set[str],
    project_dir: Path | None,
    project_name: str | None,
    run_dir: Path,
    is_shutdown_requested,
    no_context: bool = False,
    bus: EventBus | None = None,
    evaluate: bool = True,
    budget: CostBudget | None = None,
    budget_override: bool = False,
) -> None:
    """Inner pipeline loop, extracted so the caller can wrap with signal handling."""
    current_input = initial_input
    feedback_iteration = 0  # track COLLECT_ITERATE → AUDIT loop count

    for i, agent_name in enumerate(sequence):
        # Check for graceful shutdown before starting next agent
        if is_shutdown_requested():
            if project_dir:
                from .project import save_pipeline_state, push_project

                save_pipeline_state(
                    project_dir=project_dir,
                    paused_at=agent_name,
                    step=i + 1,
                    total_steps=len(sequence),
                    pending_input="",
                    outputs=outputs,
                    note="Graceful shutdown (Ctrl+C)",
                )
                push_project(project_dir)
            print(f"\n  Pipeline saved at {agent_name.upper()} (graceful shutdown).")
            return
        step = i + 1
        total = len(sequence)
        model = get_model(agent_name)

        # Cost governor: check budget before each agent
        if budget and bus and bus.events:
            cumulative = bus.events[-1].cumulative_cost_usd
            status = budget.check(cumulative)
            if status == "exceeded" and not budget_override:
                # Halt pipeline — stop-loss triggered
                print(f"\n  {budget.format_status(cumulative)}")

                # Save state
                state = {
                    "paused_at": agent_name,
                    "step": step,
                    "total_steps": total,
                    "sequence": sequence,
                    "topic": topic,
                    "note": f"Budget exceeded: ${cumulative:.2f} / ${budget.max_total_usd:.2f}",
                    "timestamp": datetime.now().isoformat(),
                }
                state_path = run_dir / "pipeline_state.json"
                state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False))
                return

        # Feedback loop cap: track COLLECT_ITERATE → AUDIT iterations
        if agent_name == "collect_iterate":
            feedback_iteration += 1
            if budget and feedback_iteration > budget.max_feedback_iterations:
                print(f"\n  🛑 Feedback loop cap reached ({budget.max_feedback_iterations} iterations).")
                print(f"  Pipeline continuing without further feedback loops.")
                continue  # skip this agent

            print(f"  Feedback iteration {feedback_iteration}/{budget.max_feedback_iterations if budget else '∞'}")

        # Build input for this agent — carry forward accumulated context
        if i > 0:
            prev_agent = sequence[i - 1]

            # Dynamic token budget: allocate chars among prior summaries
            # so the total context stays within _MAX_CONTEXT_CHARS.
            # Reserve space for the full previous output + header.
            prev_full_output = outputs.get(prev_agent, "")
            header_overhead = 500  # chars for [MODO PIPELINE] header, topic, etc.
            budget_for_summaries = max(
                0,
                _MAX_CONTEXT_CHARS - len(prev_full_output) - header_overhead,
            )

            # Build context summary from prior outputs (dynamically truncated)
            prior_agents = [n for n in outputs if n != prev_agent]
            chars_per_summary = (
                budget_for_summaries // len(prior_agents)
                if prior_agents else 0
            )

            prior_summaries = []
            for prev_name in prior_agents:
                prev_output = outputs[prev_name]
                truncated = prev_output[:chars_per_summary]
                if len(prev_output) > chars_per_summary:
                    truncated += "\n[... truncado]"
                prior_summaries.append(f"### {prev_name.upper()}\n{truncated}")

            context_header = (
                f"[MODO PIPELINE — Procesa directamente, no hagas preguntas]\n\n"
                f"**Topic original:** {topic or 'N/A'}\n\n"
            )

            if prior_summaries:
                context_header += (
                    f"**Contexto acumulado del pipeline:**\n\n"
                    + "\n\n---\n\n".join(prior_summaries)
                    + "\n\n---\n\n"
                )

            pipeline_context = (
                f"{context_header}"
                f"**Output completo del agente {prev_agent.upper()}:**\n\n"
                f"{current_input}"
            )
        else:
            pipeline_context = (
                f"[MODO PIPELINE — Procesa directamente, no hagas preguntas]\n\n"
                f"**Topic:** {topic or 'N/A'}\n\n"
                f"{current_input}"
            )

        # Gate check: pause for human review before running this agent
        if agent_name in gates:
            # Show budget warning at gate if approaching limit
            if budget and bus and bus.events:
                cumulative = bus.events[-1].cumulative_cost_usd
                status = budget.check(cumulative)
                if status == "warning":
                    print(f"\n  {budget.format_status(cumulative)}")

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
                return

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

        # Inject schema instruction into pipeline context for contract agents
        schema_instruction = get_schema_instruction(agent_name)
        agent_input = pipeline_context
        if schema_instruction and not is_interactive:
            agent_input = pipeline_context + schema_instruction
        output_path = run_dir / f"{step:02d}_{agent_name}.md"

        response = run_agent(
            agent_name=agent_name,
            user_input=agent_input,
            output_path=output_path,
            interactive=is_interactive,
            no_context=no_context,
            max_output_tokens=budget.max_agent_output_tokens if budget else None,
        )

        # Contract parsing: try to parse output to structured schema
        structured_output = None
        parse_result = try_parse(agent_name, response)

        if not parse_result.success and parse_result.errors:
            # Retry once with error feedback
            print(f"  Contract parse failed for {agent_name.upper()}: {parse_result.errors}")
            print(f"  Retrying with schema correction prompt...")

            retry_prompt = get_retry_prompt(agent_name, parse_result.errors)
            retry_input = f"{response}\n\n---\n\n{retry_prompt}"

            response = run_agent(
                agent_name=agent_name,
                user_input=retry_input,
                output_path=output_path,
                interactive=False,
                save=False,
                verbose=False,
                max_output_tokens=budget.max_agent_output_tokens if budget else None,
            )

            parse_result = try_parse(agent_name, response)
            if parse_result.success:
                print(f"  Contract retry succeeded for {agent_name.upper()}")
            else:
                print(f"  Contract retry failed for {agent_name.upper()}: {parse_result.errors}")
                print(f"  Continuing with raw output.")

        if parse_result.success and parse_result.structured:
            structured_output = parse_result.structured

        outputs[agent_name] = response
        current_input = response

        # Retrieve token_usage from the agent run (via last_metrics)
        agent_token_usage = last_metrics.token_usage if last_metrics else None

        # Tier 1 structural evaluation (no LLM call) + Tier 2 heuristic
        if bus:
            eval_result = None

            # Tier 1: structural checks (free, deterministic)
            structural = evaluate_structural(agent_name, structured_output)
            if structural.checks:
                print(f"  {structural.summary()}")

            if evaluate:
                canon = AGENTS.get(agent_name)
                if canon:
                    if structural.passed:
                        # Tier 2: heuristic evaluation (Sonnet API call)
                        print(f"  Evaluating {agent_name.upper()} "
                              f"[{canon.phase.value}] as {canon.canonical_referent[:50]}...")
                        eval_result = evaluate_output(agent_name, response)
                        if eval_result:
                            print(f"  Score: {eval_result.score}/10 — {eval_result.reasoning}")
                    else:
                        print(f"  Tier 1 failed ({structural.score:.0%}) — skipping Tier 2 (saves API call)")

            bus.publish(
                agent_name=agent_name,
                output=response,
                evaluation=eval_result,
                input_text=pipeline_context,
                token_usage=agent_token_usage,
                structured_output=structured_output,
            )

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

    # Continue from the paused agent, carrying forward prior outputs
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
        prior_outputs=prior_outputs,
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
    parser.add_argument("--to", dest="to_agent", default="decide", choices=list(AGENTS.keys()))
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
    parser.add_argument(
        "--no-context",
        action="store_true",
        help="Disable CONTEXT middleware (skip Drive/Gmail/Slack suggestions in interactive mode)",
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
        no_context=args.no_context,
    )


if __name__ == "__main__":
    main()
