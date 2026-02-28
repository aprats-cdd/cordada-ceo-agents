"""
Project Manager — Create a GitHub repo per investigation/decision with full traceability.

Each project is a Git repository where every agent output is committed individually,
creating a complete audit trail of what was observed, modeled, and decided.

Usage:
    python -m orchestrator.project create "due-diligence-fondo-xyz" --topic "análisis de gobernanza"
    python -m orchestrator.project status "due-diligence-fondo-xyz"
    python -m orchestrator.project list
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from .config import GITHUB_ORG, PROJECTS_DIR, AGENTS


def _run_cmd(cmd: list[str], cwd: str | Path | None = None, check: bool = True) -> str:
    """Run a shell command and return stdout."""
    result = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(cmd)}\n"
            f"stderr: {result.stderr.strip()}"
        )
    return result.stdout.strip()


def _run_cmd_with_retry(
    cmd: list[str],
    cwd: str | Path | None = None,
    retries: int = 4,
) -> str:
    """Run a command with exponential backoff retries for network operations."""
    import time

    for attempt in range(retries):
        try:
            return _run_cmd(cmd, cwd=cwd, check=True)
        except RuntimeError:
            if attempt == retries - 1:
                raise
            wait = 2 ** (attempt + 1)
            print(f"  ⏳ Network error, retrying in {wait}s...")
            time.sleep(wait)
    return ""  # unreachable


def create_project(
    name: str,
    topic: str,
    description: str | None = None,
    pipeline: list[str] | None = None,
) -> Path:
    """
    Create a new GitHub repo for a project and set up the local structure.

    Args:
        name: Project slug (e.g., 'due-diligence-fondo-xyz')
        topic: Research topic or decision context
        description: Optional longer description
        pipeline: Planned agent sequence (default: standard pipeline)

    Returns:
        Path to local project directory
    """
    project_slug = f"cordada-proyecto-{name}"
    project_dir = PROJECTS_DIR / project_slug
    pipeline = pipeline or ["discover", "extract", "validate", "compile", "audit", "reflect"]

    if project_dir.exists():
        print(f"Project already exists: {project_dir}")
        return project_dir

    # Create GitHub repo
    print(f"\n📦 Creating GitHub repo: {GITHUB_ORG}/{project_slug}")
    repo_desc = description or f"Cordada CEO Agents — {topic[:80]}"

    _run_cmd_with_retry([
        "gh", "repo", "create",
        f"{GITHUB_ORG}/{project_slug}",
        "--private",
        "--description", repo_desc,
        "--clone",
    ], cwd=PROJECTS_DIR)

    # Initialize project structure
    now = datetime.now(timezone.utc).isoformat()

    manifest = {
        "project": name,
        "repo": f"{GITHUB_ORG}/{project_slug}",
        "topic": topic,
        "description": description or "",
        "created_at": now,
        "updated_at": now,
        "pipeline": pipeline,
        "status": "created",
        "agents_completed": [],
        "current_iteration": 1,
        "runs": [],
    }

    # Write manifest
    manifest_path = project_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # Write README
    readme = _generate_project_readme(manifest)
    (project_dir / "README.md").write_text(readme, encoding="utf-8")

    # Create pipeline directory
    (project_dir / "pipeline").mkdir(exist_ok=True)

    # Initial commit
    _run_cmd(["git", "add", "."], cwd=project_dir)
    _run_cmd(
        ["git", "commit", "-m", f"[INIT] Proyecto: {name}\n\nTopic: {topic}\nPipeline: {' → '.join(p.upper() for p in pipeline)}"],
        cwd=project_dir,
    )
    _run_cmd_with_retry(["git", "push", "-u", "origin", "main"], cwd=project_dir)

    print(f"✅ Project created: {project_dir}")
    print(f"   GitHub: https://github.com/{GITHUB_ORG}/{project_slug}")

    return project_dir


def commit_agent_output(
    project_dir: Path,
    agent_name: str,
    output: str,
    step: int,
    total_steps: int,
    model: str,
    topic: str,
    iteration: int = 1,
) -> None:
    """
    Commit an agent's output to the project repo with full metadata.

    Each commit captures what was produced, by which agent, with what model,
    creating a complete audit trail.
    """
    now = datetime.now(timezone.utc)
    agent_info = AGENTS[agent_name]
    order = agent_info["order"]

    # Determine output path based on iteration
    if iteration == 1:
        output_dir = project_dir / "pipeline"
    else:
        output_dir = project_dir / "iterations" / f"v{iteration}"
        output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / f"{order:02d}_{agent_name}.md"

    # Write output with metadata header
    header = (
        f"---\n"
        f"agent: {agent_name}\n"
        f"model: {model}\n"
        f"layer: {agent_info['layer']}\n"
        f"step: {step}/{total_steps}\n"
        f"iteration: {iteration}\n"
        f"timestamp: {now.isoformat()}\n"
        f"---\n\n"
    )
    output_path.write_text(header + output, encoding="utf-8")

    # Update manifest
    manifest = load_manifest(project_dir)
    run_entry = {
        "agent": agent_name,
        "model": model,
        "step": step,
        "total_steps": total_steps,
        "iteration": iteration,
        "timestamp": now.isoformat(),
        "file": str(output_path.relative_to(project_dir)),
    }
    manifest["runs"].append(run_entry)
    manifest["updated_at"] = now.isoformat()

    if agent_name not in manifest["agents_completed"]:
        manifest["agents_completed"].append(agent_name)

    # Update status
    if step == total_steps:
        manifest["status"] = "completed"
    else:
        manifest["status"] = f"in_progress ({agent_name})"

    save_manifest(project_dir, manifest)

    # Update README
    readme = _generate_project_readme(manifest)
    (project_dir / "README.md").write_text(readme, encoding="utf-8")

    # Git commit
    _run_cmd(["git", "add", "."], cwd=project_dir)

    commit_msg = (
        f"[{agent_name.upper()}] Step {step}/{total_steps} — {agent_info['description']}\n"
        f"\n"
        f"Agent: {agent_name}\n"
        f"Model: {model}\n"
        f"Layer: {agent_info['layer']}\n"
        f"Iteration: {iteration}\n"
        f"Topic: {topic}\n"
    )
    _run_cmd(["git", "commit", "-m", commit_msg], cwd=project_dir)

    print(f"  📝 Committed: [{agent_name.upper()}] step {step}/{total_steps}")


def save_pipeline_state(
    project_dir: Path,
    paused_at: str,
    step: int,
    total_steps: int,
    pending_input: str,
    outputs: dict[str, str],
    note: str = "",
) -> None:
    """
    Save pipeline state to manifest for later resumption.

    Called when the pipeline stops at a gate. Stores enough context
    to resume exactly where it left off.
    """
    now = datetime.now(timezone.utc)
    manifest = load_manifest(project_dir)

    manifest["pipeline_state"] = {
        "paused_at": paused_at,
        "step": step,
        "total_steps": total_steps,
        "pending_input": pending_input,
        "outputs": outputs,
        "note": note,
        "paused_at_timestamp": now.isoformat(),
    }
    manifest["status"] = f"paused at {paused_at.upper()} gate"
    manifest["updated_at"] = now.isoformat()

    save_manifest(project_dir, manifest)

    # Update README
    readme = _generate_project_readme(manifest)
    (project_dir / "README.md").write_text(readme, encoding="utf-8")

    # Commit the state
    _run_cmd(["git", "add", "."], cwd=project_dir)
    _run_cmd(
        ["git", "commit", "-m",
         f"[GATE] Pipeline paused at {paused_at.upper()}\n\n"
         f"Step: {step}/{total_steps}\n"
         f"Note: {note or 'Awaiting CEO review'}"],
        cwd=project_dir,
    )

    print(f"  Pipeline state saved (paused at {paused_at.upper()})")


def push_project(project_dir: Path) -> None:
    """Push all commits to GitHub."""
    print(f"\n  Pushing to GitHub...")
    _run_cmd_with_retry(["git", "push"], cwd=project_dir)
    manifest = load_manifest(project_dir)
    print(f"  https://github.com/{manifest['repo']}")


def load_manifest(project_dir: Path) -> dict:
    """Load the project manifest."""
    manifest_path = project_dir / "manifest.json"
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def save_manifest(project_dir: Path, manifest: dict) -> None:
    """Save the project manifest."""
    manifest_path = project_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def get_project_dir(name: str) -> Path:
    """Resolve a project name to its directory path."""
    project_slug = f"cordada-proyecto-{name}"
    project_dir = PROJECTS_DIR / project_slug
    if not project_dir.exists():
        raise FileNotFoundError(f"Project not found: {project_dir}")
    return project_dir


def list_projects() -> list[dict]:
    """List all existing projects with their status."""
    projects = []
    if not PROJECTS_DIR.exists():
        return projects

    for d in sorted(PROJECTS_DIR.iterdir()):
        manifest_path = d / "manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            projects.append(manifest)

    return projects


def _generate_project_readme(manifest: dict) -> str:
    """Generate a project README from the manifest."""
    pipeline_str = " → ".join(p.upper() for p in manifest["pipeline"])
    completed = manifest.get("agents_completed", [])
    runs = manifest.get("runs", [])

    lines = [
        f"# {manifest['project']}",
        f"",
        f"**Topic:** {manifest['topic']}",
        f"**Status:** {manifest['status']}",
        f"**Created:** {manifest['created_at'][:10]}",
        f"**Pipeline:** {pipeline_str}",
        f"",
    ]

    if manifest.get("description"):
        lines += [manifest["description"], ""]

    # Progress
    lines += ["## Progress", ""]
    for agent in manifest["pipeline"]:
        status = "✅" if agent in completed else "⬜"
        agent_info = AGENTS.get(agent, {})
        desc = agent_info.get("description", "")
        lines.append(f"- {status} **{agent.upper()}** — {desc}")
    lines.append("")

    # Audit trail
    if runs:
        lines += ["## Audit Trail", ""]
        lines.append("| Step | Agent | Model | Timestamp | File |")
        lines.append("|------|-------|-------|-----------|------|")
        for run in runs:
            ts = run["timestamp"][:19].replace("T", " ")
            lines.append(
                f"| {run['step']}/{run['total_steps']} "
                f"| {run['agent'].upper()} "
                f"| {run['model'].split('-')[1]} "  # sonnet or opus
                f"| {ts} "
                f"| [{run['file']}]({run['file']}) |"
            )
        lines.append("")

    lines += [
        "---",
        f"*Generated by [cordada-ceo-agents](https://github.com/{manifest['repo']})*",
    ]

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Manage cordada-ceo-agents projects",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Create a new project
  python -m orchestrator.project create "due-diligence-fondo-xyz" \\
      --topic "Análisis de gobernanza para due diligence institucional"

  # Check project status
  python -m orchestrator.project status "due-diligence-fondo-xyz"

  # List all projects
  python -m orchestrator.project list
        """,
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # create
    create_parser = subparsers.add_parser("create", help="Create a new project")
    create_parser.add_argument("name", type=str, help="Project name slug")
    create_parser.add_argument("--topic", type=str, required=True, help="Research topic")
    create_parser.add_argument("--description", type=str, help="Longer description")
    create_parser.add_argument(
        "--pipeline",
        nargs="*",
        choices=list(AGENTS.keys()),
        help="Agent sequence (default: discover → reflect)",
    )

    # status
    status_parser = subparsers.add_parser("status", help="Show project status")
    status_parser.add_argument("name", type=str, help="Project name slug")

    # list
    subparsers.add_parser("list", help="List all projects")

    args = parser.parse_args()

    if args.command == "create":
        create_project(
            name=args.name,
            topic=args.topic,
            description=args.description,
            pipeline=args.pipeline,
        )

    elif args.command == "status":
        try:
            project_dir = get_project_dir(args.name)
            manifest = load_manifest(project_dir)
        except FileNotFoundError as e:
            print(f"Error: {e}")
            sys.exit(1)

        print(f"\n📋 Project: {manifest['project']}")
        print(f"   Topic: {manifest['topic']}")
        print(f"   Status: {manifest['status']}")
        print(f"   Pipeline: {' → '.join(p.upper() for p in manifest['pipeline'])}")
        print(f"   Completed: {', '.join(a.upper() for a in manifest['agents_completed']) or 'none'}")
        print(f"   Runs: {len(manifest['runs'])}")
        print(f"   Repo: https://github.com/{manifest['repo']}")

    elif args.command == "list":
        projects = list_projects()
        if not projects:
            print("\nNo projects found.")
            return

        print(f"\n{'Project':<35} {'Status':<20} {'Agents':<10} {'Created':<12}")
        print("─" * 80)
        for p in projects:
            print(
                f"{p['project']:<35} "
                f"{p['status']:<20} "
                f"{len(p['agents_completed'])}/{len(p['pipeline']):<7} "
                f"{p['created_at'][:10]}"
            )


if __name__ == "__main__":
    main()
