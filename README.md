# cordada-ceo-agents

A 10-agent pipeline for CEO-level decision-making, document generation, and stakeholder communication. Built on the Anthropic Messages API with integrated tools (web search, Google Workspace, Slack).

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        CAPA 1 — ALIMENTACIÓN                        │
│                                                                     │
│   DISCOVER ──→ EXTRACT ──→ VALIDATE ──→ COMPILE                    │
│   (research)   (parse)     (verify)     (draft)                    │
│   🔧 web,drive  🔧 drive    🔧 web                                  │
│      slack        slack                                             │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    CAPA 2 — INTERPRETACIÓN Y DECISIÓN               │
│                                                                     │
│   AUDIT ──→ REFLECT ──→ DECIDE            ⛩ Gates: CEO review      │
│   (multi-expert)  (stress-test)  (options + trade-offs)            │
│                                       │                             │
│                                       ▼                             │
│                                   CEO DECIDES                       │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    CAPA 3 — DISTRIBUCIÓN Y FEEDBACK                 │
│                                                                     │
│   DISTRIBUTE ──→ COLLECT + ITERATE ──→ (back to AUDIT)             │
│   🔧 slack,gmail  🔧 slack,gmail                                    │
│   (adapt to channel)  (parse feedback, re-inject)                  │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                        SOPORTE — CONTEXT                            │
│                                                                     │
│   CONTEXT  🔧 drive, gmail, slack, calendar                        │
│   (search internal sources, suggest answers)                       │
└─────────────────────────────────────────────────────────────────────┘
```

## Agents

| # | Agent | Layer | Tools | Purpose |
|---|-------|-------|-------|---------|
| 01 | **DISCOVER** | Feed | web_search, drive, slack | Research and rank sources on any topic |
| 02 | **EXTRACT** | Feed | drive, slack | Pull key data, arguments, frameworks from sources |
| 03 | **VALIDATE** | Feed | web_search | Verify accuracy, consistency, bias, regulatory risk |
| 04 | **COMPILE** | Feed | — | Generate structured document (Minto Pyramid) |
| 05 | **AUDIT** | Interpret | — | Multi-expert panel review (legal, persuasion, logic) |
| 06 | **REFLECT** | Decide | — | Strategic stress-test before decision |
| 07 | **DECIDE** | Decide | — | Present 2-3 options with trade-offs for CEO decision |
| 08 | **DISTRIBUTE** | Distribute | slack, gmail | Adapt deliverable to channel (WhatsApp, Slack, email) |
| 09 | **COLLECT+ITERATE** | Feedback | slack, gmail | Parse stakeholder feedback, re-inject into pipeline |
| 10 | **CONTEXT** | Support | drive, gmail, slack, calendar | Search internal sources to suggest answers |

## Tool System

Agents access external data via a tool system with automatic fallback:

```
Credentials available?
  YES → Direct API call (Google Workspace / Slack SDK)
   NO → call_claude_as_proxy() → Claude + MCP tools (Gmail, Drive, Slack)
         Auth error? → Same fallback
         Write op fails? → Return content for manual action
```

**Agents are never blind.** Even without Google or Slack credentials, every tool routes through Claude as a data retrieval proxy. The calling agent gets the same JSON format regardless of source.

### Available Tools

| Tool | Type | Used by |
|------|------|---------|
| `web_search` | Anthropic server | DISCOVER, VALIDATE |
| `search_google_drive` | Custom | DISCOVER, CONTEXT |
| `read_google_drive_document` | Custom | EXTRACT |
| `search_gmail` | Custom | COLLECT_ITERATE, CONTEXT |
| `read_gmail_message` | Custom | COLLECT_ITERATE |
| `draft_gmail` | Custom | DISTRIBUTE |
| `search_slack` | Custom | DISCOVER, COLLECT_ITERATE, CONTEXT |
| `read_slack_thread` | Custom | EXTRACT, COLLECT_ITERATE |
| `send_slack_message` | Custom | DISTRIBUTE |
| `read_calendar` | Custom | CONTEXT |

## Gate System

Gates are checkpoints where the pipeline pauses for CEO review:

```
Pipeline: DISCOVER → EXTRACT → VALIDATE → COMPILE → ⛩ AUDIT → ⛩ REFLECT → ⛩ DECIDE → ⛩ DISTRIBUTE → ⛩ COLLECT_ITERATE
                                                      ↑ gates ↑
```

At each gate the CEO can:
- **Proceed** — run the next agent as-is
- **Modify** — add context or instructions before running
- **Stop** — pause the pipeline, save state, resume later

## Four Ways to Use

### 1. Python API

```python
from orchestrator import investigate, agent, decide, context

# Full pipeline with gates
results = investigate(
    "due-diligence-fondo-xyz",
    topic="Análisis de gobernanza para due diligence institucional",
    gates={"audit", "reflect"},
)

# Resume a stopped pipeline
results = investigate("due-diligence-fondo-xyz", resume=True,
    gate_input="Aprobado. Usar panel: legal CMF + persuasión + lógica.")

# Single agents
output = agent("discover", "deuda privada LatAm gobernanza")
options = decide("Resolver gobernanza antes de due diligence")
answer = context("¿Cuál es el AUM actual de Cordada?")

# Claude as data proxy (for custom integrations)
from orchestrator import call_claude_as_proxy
data = call_claude_as_proxy("Search Gmail for emails about due diligence")
```

### 2. CLI

```bash
# Run the full pipeline
python -m orchestrator run --topic "gobernanza" --gates audit reflect

# Run a single agent
python -m orchestrator agent discover --input "deuda privada LatAm"

# Interactive mode
python -m orchestrator agent audit --input-file ./draft.md -i

# Project mode (GitHub traceability)
python -m orchestrator run --topic "gobernanza" --project "due-diligence-xyz"

# Resume a stopped pipeline
python -m orchestrator run --resume "due-diligence-xyz"
```

### 3. Manual (Claude.ai)

Copy any `agents/*.md` file into a new Claude chat as the opening message. Claude will ask for inputs, then execute. No code required.

### 4. Project Mode (GitHub Traceability)

Each investigation creates its own private GitHub repo. Every agent output is committed individually, creating a complete audit trail.

```bash
python -m orchestrator project create "carta-aportantes-q1" \
    --topic "Comunicación trimestral a aportantes"
python -m orchestrator project status "carta-aportantes-q1"
python -m orchestrator project list
```

**What you get:** A private repo at `github.com/cordada/cordada-proyecto-{name}` with:
- Each agent output committed individually (1 commit per step)
- Structured commit messages with agent, model, and step metadata
- `manifest.json` tracking full run history
- Auto-generated `README.md` with progress and audit trail

## Quick Start

```bash
# 1. Clone
git clone git@github.com:YOUR_USERNAME/cordada-ceo-agents.git
cd cordada-ceo-agents

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure
cp .env.example .env
# Edit .env: add ANTHROPIC_API_KEY (required)
# Optional: GOOGLE_CREDENTIALS_PATH, SLACK_BOT_TOKEN

# 4. Run
python -m orchestrator agent discover --input "tu tema de investigación"
```

### Configuration (.env)

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Claude API key |
| `GITHUB_ORG` | No | GitHub org for projects (default: cordada) |
| `GOOGLE_CREDENTIALS_PATH` | No | Google service account JSON for Drive/Gmail/Calendar |
| `GOOGLE_DELEGATE_EMAIL` | No | Email to impersonate with domain-wide delegation |
| `SLACK_BOT_TOKEN` | No | Slack bot token (xoxb-...) for search/read/send |

> Without Google/Slack credentials, tools automatically fall back to `call_claude_as_proxy()`.

## Project Structure

```
cordada-ceo-agents/
├── README.md
├── agents/                   ← Agent prompts (usable standalone in Claude.ai)
│   ├── 01_discover.md
│   ├── 02_extract.md
│   ├── 03_validate.md
│   ├── 04_compile.md
│   ├── 05_audit.md
│   ├── 06_reflect.md
│   ├── 07_decide.md
│   ├── 08_distribute.md
│   ├── 09_collect_iterate.md
│   └── 10_context.md
├── orchestrator/
│   ├── __init__.py           ← Public API (investigate, agent, decide, context)
│   ├── config.py             ← Configuration, model selection, agent registry
│   ├── agent_runner.py       ← Run agents via API with tool execution loop
│   ├── pipeline.py           ← Chain agents with gate-based pause/resume
│   ├── gates.py              ← Gate handlers (terminal, auto)
│   ├── tools.py              ← Tool definitions, executors, Claude proxy fallback
│   └── project.py            ← GitHub repo creation + traceability
├── outputs/                  ← Pipeline outputs (gitignored)
├── projects/                 ← Project repos (gitignored)
├── requirements.txt
├── .env.example
└── .gitignore
```

## Model Selection

| Agent | Model | Reason |
|-------|-------|--------|
| DISCOVER → DISTRIBUTE | claude-sonnet-4-20250514 | Best balance of quality and cost |
| AUDIT, REFLECT, DECIDE | claude-opus-4-6 | Strategic evaluation requires maximum quality |
| Claude proxy fallback | claude-sonnet-4-20250514 | Data retrieval proxy |

## Design Patterns

| Pattern | Where | Reference |
|---------|-------|-----------|
| Sequential Workflow | Full Layer 1 pipeline | Gullí (2025) Ch. 6 |
| Tool Use | DISCOVER, VALIDATE, EXTRACT, DISTRIBUTE | Gullí (2025) Ch. 5 |
| RAG | EXTRACT, COMPILE | Gullí (2025) Ch. 11 |
| Multi-Agent Debate | AUDIT | Gullí (2025) Ch. 8 |
| Reflection | REFLECT | Gullí (2025) Ch. 4 |
| Human-in-the-Loop | Gates at AUDIT → COLLECT_ITERATE | Gullí (2025) Ch. 13 |
| Guardrails | VALIDATE | Gullí (2025) Ch. 12 |
| Graceful Degradation | Tool fallback via Claude proxy | — |

## References

- Gullí, A. (2025). *Agentic Design Patterns: A Hands-On Guide to Building Intelligent Systems*. Springer Nature.
- Anthropic. (2025). [Building agents with the Claude Agent SDK](https://www.anthropic.com/engineering/building-agents-with-the-claude-agent-sdk).
- Anthropic. (2025). [Code execution with MCP](https://www.anthropic.com/engineering/code-execution-with-mcp).
- Anthropic. (2025). [Introducing advanced tool use](https://www.anthropic.com/engineering/advanced-tool-use).

## License

Private repository. All rights reserved. Cordada SpA.
