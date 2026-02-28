# cordada-ceo-agents

A 9-agent pipeline for CEO-level decision-making, document generation, and stakeholder communication. Built on the Claude Agent SDK with MCP integrations.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        CAPA 1 — ALIMENTACIÓN                        │
│                                                                     │
│   DISCOVER ──→ EXTRACT ──→ VALIDATE ──→ COMPILE                    │
│   (research)   (parse)     (verify)     (draft)                    │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    CAPA 2 — INTERPRETACIÓN Y DECISIÓN               │
│                                                                     │
│   AUDIT ──→ REFLECT ──→ DECIDE                                     │
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
│   (adapt to channel)  (parse feedback, re-inject)                  │
└─────────────────────────────────────────────────────────────────────┘
```

## Agents

| # | Agent | Layer | Purpose |
|---|-------|-------|---------|
| 01 | **DISCOVER** | Feed | Research and rank sources on any topic |
| 02 | **EXTRACT** | Feed | Pull key data, arguments, frameworks from sources |
| 03 | **VALIDATE** | Feed | Verify accuracy, consistency, bias, regulatory risk |
| 04 | **COMPILE** | Feed | Generate structured document (Minto Pyramid) |
| 05 | **AUDIT** | Interpret | Multi-expert panel review (legal, persuasion, logic) |
| 06 | **REFLECT** | Decide | Strategic stress-test before distribution |
| 07 | **DECIDE** | Decide | Present 2-3 options with trade-offs for CEO decision |
| 08 | **DISTRIBUTE** | Distribute | Adapt deliverable to channel (WhatsApp, Slack, email) |
| 09 | **COLLECT+ITERATE** | Feedback | Parse stakeholder feedback, re-inject into pipeline |

## Design Patterns Used

| Pattern | Where | Reference |
|---------|-------|-----------|
| Sequential Workflow | Full Layer 1 pipeline | Gullí (2025) Ch. 6 |
| Tool Use | DISCOVER, VALIDATE | Gullí (2025) Ch. 5 |
| RAG | EXTRACT, COMPILE | Gullí (2025) Ch. 11 |
| Multi-Agent Debate | AUDIT | Gullí (2025) Ch. 8 |
| Reflection | REFLECT | Gullí (2025) Ch. 4 |
| Planning | COMPILE | Gullí (2025) Ch. 6 |
| Human-in-the-Loop | DECIDE | Gullí (2025) Ch. 13 |
| Guardrails | VALIDATE | Gullí (2025) Ch. 12 |
| Memory | Cross-session context | Gullí (2025) Ch. 9 |

## Two Ways to Use

### 1. Manual (Claude.ai)

Copy any `agents/*.md` file into a new Claude chat as the opening message. Claude will ask for inputs, then execute. No code required.

### 2. Programmatic (CLI + Claude Agent SDK)

Run agents from your terminal. Each agent gets its own API call with isolated context.

```bash
# Run a single agent
python -m orchestrator.agent_runner --agent discover --input "deuda privada LatAm gobernanza"

# Run the full pipeline
python -m orchestrator.pipeline --topic "análisis de gobernanza para due diligence institucional"

# Run from a specific stage
python -m orchestrator.pipeline --from compile --input ./outputs/validated_data.md
```

## Quick Start

See [setup_guide.md](setup_guide.md) for detailed installation instructions.

```bash
# 1. Clone
git clone git@github.com:YOUR_USERNAME/cordada-ceo-agents.git
cd cordada-ceo-agents

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure API key
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY

# 4. Run
python -m orchestrator.agent_runner --agent discover --input "tu tema de investigación"
```

## Project Structure

```
cordada-ceo-agents/
├── README.md                 ← You are here
├── setup_guide.md            ← Step-by-step installation
├── agents/                   ← Agent prompts (usable standalone in Claude.ai)
│   ├── 01_discover.md
│   ├── 02_extract.md
│   ├── 03_validate.md
│   ├── 04_compile.md
│   ├── 05_audit.md
│   ├── 06_reflect.md
│   ├── 07_decide.md
│   ├── 08_distribute.md
│   └── 09_collect_iterate.md
├── orchestrator/             ← Python orchestration code
│   ├── __init__.py
│   ├── config.py             ← Configuration and model selection
│   ├── agent_runner.py       ← Run individual agents via API
│   └── pipeline.py           ← Chain agents into full pipeline
├── examples/                 ← Usage examples
│   └── carta_aportantes.py
├── outputs/                  ← Pipeline outputs land here (gitignored)
├── requirements.txt
├── .env.example
└── .gitignore
```

## References

- Gullí, A. (2025). *Agentic Design Patterns: A Hands-On Guide to Building Intelligent Systems*. Springer Nature.
- Anthropic. (2025). [Building agents with the Claude Agent SDK](https://www.anthropic.com/engineering/building-agents-with-the-claude-agent-sdk).
- Anthropic. (2025). [Code execution with MCP](https://www.anthropic.com/engineering/code-execution-with-mcp).
- Anthropic. (2025). [Introducing advanced tool use](https://www.anthropic.com/engineering/advanced-tool-use).

## License

Private repository. All rights reserved. Cordada SpA.
