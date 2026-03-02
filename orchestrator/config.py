"""
Configuration for cordada-ceo-agents.

Infrastructure concern: loads environment variables and resolves paths.
Agent definitions live in ``domain.registry`` — this module re-exports
them for backward compatibility.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Re-export from domain (single source of truth)
from domain.registry import (
    AGENTS,
    PIPELINE_ORDER,
    get_model_for_agent as get_model,
    MODEL_DEFAULT,
    MODEL_PREMIUM,
    PREMIUM_AGENTS,
)

# Load .env file
load_dotenv()

# --- API Configuration ---
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
if not ANTHROPIC_API_KEY:
    raise ValueError(
        "ANTHROPIC_API_KEY not found. "
        "Copy .env.example to .env and add your key. "
        "Get one at https://console.anthropic.com/"
    )

# --- GitHub Configuration ---
GITHUB_ORG = os.getenv("GITHUB_ORG", "cordada")

# --- Google Workspace Integration ---
GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH")
GOOGLE_DELEGATE_EMAIL = os.getenv("GOOGLE_DELEGATE_EMAIL")

# --- Slack Integration ---
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")

# --- CONTEXT Middleware ---
CONTEXT_ENABLED = os.getenv("CONTEXT_ENABLED", "true").lower() in ("true", "1", "yes")

# --- Paths ---
ROOT_DIR = Path(__file__).parent.parent
AGENTS_DIR = ROOT_DIR / "agents"
OUTPUTS_DIR = ROOT_DIR / "outputs"
OUTPUTS_DIR.mkdir(exist_ok=True)
PROJECTS_DIR = Path(os.getenv("PROJECTS_DIR", ROOT_DIR / "projects"))
PROJECTS_DIR.mkdir(exist_ok=True)


def get_agent_prompt(agent_name: str) -> str:
    """Load an agent's system prompt from its markdown file."""
    if agent_name not in AGENTS:
        available = ", ".join(sorted(AGENTS.keys()))
        raise ValueError(f"Unknown agent: '{agent_name}'. Available: {available}")

    prompt_path = AGENTS_DIR / AGENTS[agent_name]["file"]
    return prompt_path.read_text(encoding="utf-8")
