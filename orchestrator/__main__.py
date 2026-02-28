"""
Unified CLI entry point for cordada-ceo-agents.

Usage:
    python -m orchestrator run --topic "tema" --project "nombre"
    python -m orchestrator agent discover --input "tema"
    python -m orchestrator project list
"""

import argparse
import sys
from pathlib import Path

from .config import AGENTS


def main():
    parser = argparse.ArgumentParser(
        prog="orchestrator",
        description="cordada-ceo-agents — CEO-level agent pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  run       Run the full pipeline (optionally with GitHub traceability)
  agent     Run a single agent
  project   Manage project repos
  list      List available agents

Examples:
  # Full pipeline with GitHub repo
  python -m orchestrator run --topic "gobernanza" --project "due-diligence-xyz"

  # Full pipeline, local only
  python -m orchestrator run --topic "gobernanza"

  # Single agent
  python -m orchestrator agent discover --input "deuda privada LatAm"

  # Project management
  python -m orchestrator project create "nombre" --topic "tema"
  python -m orchestrator project status "nombre"
  python -m orchestrator project list
        """,
    )

    subparsers = parser.add_subparsers(dest="command")

    # --- run ---
    run_parser = subparsers.add_parser(
        "run",
        help="Run the agent pipeline",
    )
    run_parser.add_argument("--topic", type=str, required=True, help="Research topic")
    run_parser.add_argument("--project", type=str, help="Project name for GitHub traceability")
    run_parser.add_argument("--project-description", type=str, help="Project description")
    run_parser.add_argument("--from", dest="from_agent", default="discover", choices=list(AGENTS.keys()))
    run_parser.add_argument("--to", dest="to_agent", default="reflect", choices=list(AGENTS.keys()))
    run_parser.add_argument("--interactive-at", nargs="*", default=[], choices=list(AGENTS.keys()))

    # --- agent ---
    agent_parser = subparsers.add_parser(
        "agent",
        help="Run a single agent",
    )
    agent_parser.add_argument("name", choices=list(AGENTS.keys()), help="Agent to run")
    agent_parser.add_argument("--input", type=str, help="Direct text input")
    agent_parser.add_argument("--input-file", type=str, help="File to use as input")
    agent_parser.add_argument("-i", "--interactive", action="store_true", help="Interactive mode")
    agent_parser.add_argument("--output", type=str, help="Output file path")

    # --- project ---
    project_parser = subparsers.add_parser(
        "project",
        help="Manage project repos",
    )
    project_sub = project_parser.add_subparsers(dest="project_command")

    create_p = project_sub.add_parser("create")
    create_p.add_argument("name", type=str)
    create_p.add_argument("--topic", type=str, required=True)
    create_p.add_argument("--description", type=str)

    status_p = project_sub.add_parser("status")
    status_p.add_argument("name", type=str)

    project_sub.add_parser("list")

    # --- list ---
    subparsers.add_parser("list", help="List available agents")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    if args.command == "run":
        from .pipeline import run_pipeline

        run_pipeline(
            topic=args.topic,
            from_agent=args.from_agent,
            to_agent=args.to_agent,
            interactive_at=set(args.interactive_at),
            project_name=args.project,
            project_description=args.project_description,
        )

    elif args.command == "agent":
        from .agent_runner import run_agent

        # Resolve input
        if args.input_file:
            user_input = Path(args.input_file).read_text(encoding="utf-8")
        elif args.input:
            user_input = args.input
        elif args.interactive:
            user_input = "Estoy listo. Hazme las preguntas para comenzar."
        else:
            print("Error: Provide --input, --input-file, or -i")
            sys.exit(1)

        output_path = Path(args.output) if args.output else None

        response = run_agent(
            agent_name=args.name,
            user_input=user_input,
            output_path=output_path,
            interactive=args.interactive,
        )

        if not args.interactive:
            print(f"\n  {args.name.upper()} response:\n")
            print(response)

    elif args.command == "project":
        from .project import main as project_main

        # Re-parse with project subcommand argv
        sys.argv = ["orchestrator.project"] + sys.argv[2:]
        project_main()

    elif args.command == "list":
        from .config import PREMIUM_AGENTS

        print("\nAvailable agents:\n")
        for name, info in sorted(AGENTS.items(), key=lambda x: x[1]["order"]):
            tag = "+" if name in PREMIUM_AGENTS else " "
            print(f"  {tag} {info['order']:02d}. {name:<18} [{info['layer']:<10}] {info['description']}")
        print("\n+ = Premium model (Opus). All others use Sonnet.")


if __name__ == "__main__":
    main()
