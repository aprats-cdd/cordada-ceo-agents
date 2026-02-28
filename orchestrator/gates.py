"""
Gate Handlers — Pause-and-resume logic for the agent pipeline.

Gates are checkpoints where the pipeline pauses for human review.
Layer 1 (feed) runs automatically; Layer 2 (interpret/decide) pauses.

A gate handler receives context about what's been produced so far
and returns an action: proceed, modify (add human input), or stop.

Built-in handlers:
    terminal_gate  — Interactive terminal (stdin/stdout)
    auto_gate      — Auto-approve everything (for batch/CI)

Custom handlers:
    Any callable matching the GateHandler signature.

Usage:
    from orchestrator.gates import terminal_gate

    results = run_pipeline(
        topic="gobernanza",
        gates={"audit", "reflect"},
        on_gate=terminal_gate,
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .config import AGENTS


@dataclass
class GateContext:
    """Information passed to a gate handler."""

    agent_name: str
    """The agent about to run (e.g., 'audit')."""

    step: int
    """Current step number in the pipeline."""

    total_steps: int
    """Total steps in the pipeline."""

    outputs: dict[str, str]
    """All agent outputs produced so far (agent_name → output text)."""

    proposed_input: str
    """The input the agent would receive if approved as-is."""

    topic: str
    """The pipeline's research topic."""

    project_name: str | None = None
    """Project name, if running in project mode."""


@dataclass
class GateResult:
    """Decision returned by a gate handler."""

    action: str
    """One of: 'proceed', 'modify', 'stop'."""

    modified_input: str | None = None
    """If action='modify', the new input for the agent.
    If None with 'proceed', uses proposed_input as-is."""

    note: str = ""
    """Optional note from the human (logged in manifest)."""


# Type alias for gate handler functions
GateHandler = Callable[[GateContext], GateResult]


def terminal_gate(ctx: GateContext) -> GateResult:
    """
    Interactive terminal gate — pauses for human review via stdin.

    Shows the last agent's output preview, asks the CEO to:
    - [Enter] Proceed as-is
    - [m] Add context/instructions before the agent runs
    - [s] Stop the pipeline (saves state for later resumption)
    """
    agent_info = AGENTS.get(ctx.agent_name, {})
    layer = agent_info.get("layer", "?")
    desc = agent_info.get("description", "?")

    # Find the last completed agent
    last_agent = list(ctx.outputs.keys())[-1] if ctx.outputs else None
    last_output = ctx.outputs.get(last_agent, "") if last_agent else ""

    print(f"\n{'='*60}")
    print(f"  GATE: {ctx.agent_name.upper()}")
    print(f"  Step {ctx.step}/{ctx.total_steps} — {desc}")
    print(f"  Layer: {layer}")
    print(f"{'='*60}")

    if last_agent:
        # Show preview of what was produced
        preview_lines = last_output[:800].split("\n")
        print(f"\n  Last output ({last_agent.upper()}, {len(last_output)} chars):\n")
        for line in preview_lines[:15]:
            print(f"    {line}")
        if len(last_output) > 800 or len(preview_lines) > 15:
            print(f"    ...")

    print(f"\n  Options:")
    print(f"    [enter]  Proceed — run {ctx.agent_name.upper()} with this input")
    print(f"    [m]      Modify — add context or instructions before running")
    print(f"    [s]      Stop — pause pipeline, save state for later")

    choice = input("\n  > ").strip().lower()

    if choice == "m":
        print(f"\n  Add context for {ctx.agent_name.upper()}.")
        print(f"  (This gets appended to the input. Type 'done' on a new line to finish.)")
        print()

        lines = []
        while True:
            line = input("  | ")
            if line.strip().lower() == "done":
                break
            lines.append(line)

        extra_input = "\n".join(lines)
        combined = (
            f"{ctx.proposed_input}\n\n"
            f"---\n\n"
            f"Contexto adicional del CEO:\n\n{extra_input}"
        )

        return GateResult(
            action="modify",
            modified_input=combined,
            note=extra_input,
        )

    elif choice == "s":
        reason = input("\n  Reason for stopping (optional): ").strip()
        return GateResult(action="stop", note=reason or "Manual stop at gate")

    else:
        return GateResult(action="proceed")


def auto_gate(ctx: GateContext) -> GateResult:
    """Auto-approve gate — proceeds without human interaction."""
    return GateResult(action="proceed")


# Default gates: Layer 2 agents
DEFAULT_GATES = {"audit", "reflect", "decide"}
