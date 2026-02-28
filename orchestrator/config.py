"""
Configuration for cordada-ceo-agents.
Loads environment variables and defines defaults.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

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

# --- Model Selection ---
# claude-sonnet-4-20250514: Best balance of quality and cost for most agents
# claude-opus-4-6: Use for AUDIT, REFLECT, DECIDE where quality matters most
MODEL_DEFAULT = "claude-sonnet-4-20250514"
MODEL_PREMIUM = "claude-opus-4-6"

# Which agents use premium model
PREMIUM_AGENTS = {"audit", "reflect", "decide"}

# --- Paths ---
ROOT_DIR = Path(__file__).parent.parent
AGENTS_DIR = ROOT_DIR / "agents"
OUTPUTS_DIR = ROOT_DIR / "outputs"
OUTPUTS_DIR.mkdir(exist_ok=True)
PROJECTS_DIR = Path(os.getenv("PROJECTS_DIR", ROOT_DIR / "projects"))
PROJECTS_DIR.mkdir(exist_ok=True)

# --- Agent Registry ---
# Maps agent names to their prompt files and pipeline order
AGENTS = {
    "discover": {
        "file": "01_discover.md",
        "order": 1,
        "layer": "feed",
        "description": "Research and rank sources",
        "next": "extract",
    },
    "extract": {
        "file": "02_extract.md",
        "order": 2,
        "layer": "feed",
        "description": "Pull key data from sources",
        "next": "validate",
    },
    "validate": {
        "file": "03_validate.md",
        "order": 3,
        "layer": "feed",
        "description": "Verify accuracy and consistency",
        "next": "compile",
    },
    "compile": {
        "file": "04_compile.md",
        "order": 4,
        "layer": "feed",
        "description": "Generate structured document",
        "next": "audit",
    },
    "audit": {
        "file": "05_audit.md",
        "order": 5,
        "layer": "interpret",
        "description": "Multi-expert panel review",
        "next": "reflect",
    },
    "reflect": {
        "file": "06_reflect.md",
        "order": 6,
        "layer": "decide",
        "description": "Strategic stress-test",
        "next": "distribute",
    },
    "decide": {
        "file": "07_decide.md",
        "order": 7,
        "layer": "decide",
        "description": "Present options with trade-offs",
        "next": None,  # CEO decides, then manually triggers next
    },
    "distribute": {
        "file": "08_distribute.md",
        "order": 8,
        "layer": "distribute",
        "description": "Adapt deliverable to channel",
        "next": "collect_iterate",
    },
    "collect_iterate": {
        "file": "09_collect_iterate.md",
        "order": 9,
        "layer": "feedback",
        "description": "Parse feedback and re-inject",
        "next": "audit",  # Loop back
    },
}


def get_model(agent_name: str) -> str:
    """Return the appropriate model for an agent."""
    if agent_name in PREMIUM_AGENTS:
        return MODEL_PREMIUM
    return MODEL_DEFAULT


def get_agent_prompt(agent_name: str) -> str:
    """Load an agent's system prompt from its markdown file."""
    if agent_name not in AGENTS:
        available = ", ".join(sorted(AGENTS.keys()))
        raise ValueError(f"Unknown agent: '{agent_name}'. Available: {available}")

    prompt_path = AGENTS_DIR / AGENTS[agent_name]["file"]
    return prompt_path.read_text(encoding="utf-8")
