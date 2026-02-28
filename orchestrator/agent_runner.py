"""
Agent Runner — Execute individual agents via the Claude API.

Each agent runs in its own API call with isolated context.
The agent's markdown prompt becomes the system message.
The user's input becomes the first user message.

Programmatic usage:
    from orchestrator.agent_runner import run_agent
    output = run_agent("discover", "deuda privada LatAm")

CLI usage:
    python -m orchestrator.agent_runner --agent discover --input "deuda privada LatAm"
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

import anthropic

from .config import (
    ANTHROPIC_API_KEY,
    AGENTS,
    OUTPUTS_DIR,
    get_model,
    get_agent_prompt,
)


# Shared client — created once, reused across calls
_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    """Get or create the shared Anthropic client."""
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


def run_agent(
    agent_name: str,
    user_input: str,
    output_path: Path | None = None,
    interactive: bool = False,
    save: bool = True,
    verbose: bool = True,
) -> str:
    """
    Run a single agent with the given input.

    Args:
        agent_name: Name of the agent (e.g., 'discover', 'compile')
        user_input: The user's input text
        output_path: Optional path to save the output
        interactive: If True, enable multi-turn conversation
        save: If True, auto-save output to disk (default: True)
        verbose: If True, print progress banners (default: True)

    Returns:
        The agent's response text
    """
    system_prompt = get_agent_prompt(agent_name)
    model = get_model(agent_name)
    client = _get_client()

    if verbose:
        print(f"\n{'='*60}")
        print(f"  AGENT: {agent_name.upper()}")
        print(f"  MODEL: {model}")
        print(f"  LAYER: {AGENTS[agent_name]['layer']}")
        print(f"{'='*60}\n")

    if interactive:
        response = _run_interactive(client, model, system_prompt, user_input, agent_name)
    else:
        message = client.messages.create(
            model=model,
            max_tokens=8096,
            system=system_prompt,
            messages=[{"role": "user", "content": user_input}],
        )
        response = message.content[0].text

    # Save output
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(response, encoding="utf-8")
        if verbose:
            print(f"\n  Output saved to: {output_path}")
    elif save:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        auto_path = OUTPUTS_DIR / f"{agent_name}_{timestamp}.md"
        auto_path.write_text(response, encoding="utf-8")
        if verbose:
            print(f"\n  Output saved to: {auto_path}")

    return response


def _run_interactive(
    client: anthropic.Anthropic,
    model: str,
    system_prompt: str,
    initial_input: str,
    agent_name: str,
) -> str:
    """
    Run an agent in interactive mode (multi-turn conversation).
    The agent asks questions, you answer, it executes when ready.
    """
    messages = [{"role": "user", "content": initial_input}]
    full_response = ""

    print("  Interactive mode. Type your answers. Type 'done' to finish.\n")

    while True:
        message = client.messages.create(
            model=model,
            max_tokens=8096,
            system=system_prompt,
            messages=messages,
        )

        assistant_text = message.content[0].text
        full_response = assistant_text

        print(f"\n  {agent_name.upper()}:\n")
        print(assistant_text)

        if message.stop_reason == "end_turn":
            user_reply = input("\n  Your response (or 'done' to finish): ").strip()
            if user_reply.lower() == "done":
                break

            messages.append({"role": "assistant", "content": assistant_text})
            messages.append({"role": "user", "content": user_reply})

    return full_response


def main():
    parser = argparse.ArgumentParser(
        description="Run a cordada-ceo-agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m orchestrator.agent_runner --agent discover --input "deuda privada LatAm"
  python -m orchestrator.agent_runner --agent compile --input-file ./notes.md
  python -m orchestrator.agent_runner --agent audit --input-file ./draft.md -i

Available agents:
  discover    — Research and rank sources
  extract     — Pull key data from sources
  validate    — Verify accuracy and consistency
  compile     — Generate structured document
  audit       — Multi-expert panel review
  reflect     — Strategic stress-test
  decide      — Present options with trade-offs
  distribute  — Adapt deliverable to channel
  collect_iterate — Parse feedback and re-inject
        """,
    )

    parser.add_argument(
        "--agent",
        required=True,
        choices=list(AGENTS.keys()),
        help="Which agent to run",
    )
    parser.add_argument(
        "--input",
        type=str,
        help="Direct text input for the agent",
    )
    parser.add_argument(
        "--input-file",
        type=str,
        help="Path to a file to use as input",
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Path to save the output (default: outputs/<agent>_<timestamp>.md)",
    )
    parser.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="Run in interactive mode (multi-turn conversation)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all available agents",
    )

    args = parser.parse_args()

    if args.list:
        print("\nAvailable agents:\n")
        for name, info in sorted(AGENTS.items(), key=lambda x: x[1]["order"]):
            model_tag = "+" if name in {"audit", "reflect", "decide"} else " "
            print(f"  {model_tag} {info['order']:02d}. {name:<18} [{info['layer']:<10}] {info['description']}")
        print("\n+ = Uses premium model (Opus)")
        return

    # Resolve input
    if args.input_file:
        user_input = Path(args.input_file).read_text(encoding="utf-8")
    elif args.input:
        user_input = args.input
    elif args.interactive:
        user_input = "Estoy listo. Hazme las preguntas para comenzar."
    else:
        print("Error: Provide --input, --input-file, or use -i for interactive mode")
        sys.exit(1)

    # Resolve output path
    output_path = Path(args.output) if args.output else None

    # Run
    response = run_agent(
        agent_name=args.agent,
        user_input=user_input,
        output_path=output_path,
        interactive=args.interactive,
    )

    if not args.interactive:
        print(f"\n  {args.agent.upper()} response:\n")
        print(response)


if __name__ == "__main__":
    main()
