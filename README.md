# cordada-ceo-agents

A 10-agent pipeline for CEO-level decision-making, document generation, and stakeholder communication. Built on the Anthropic Messages API with integrated tools (web search, Google Workspace, Slack).

**Core invariant:** Every decision is sustained by explicit models, and every model by traceable observations. The epistemic chain is always `OBSERVATION → MODEL → DECISION` — never decision→decision, never observation→decision.

---

## Architecture

The system is a 3-layer pipeline of 9 sequential agents plus 1 support agent. Data flows strictly downward through layers. Each layer boundary is a human checkpoint (gate). Each agent occupies a defined epistemic phase and is evaluated by its canonical domain expert.

> **Interactive diagram:** open [`docs/architecture.html`](docs/architecture.html) in a browser for an animated, Material 3-styled version of the diagram below.

```
                              user input
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  LAYER 1 — FEED                                        runs: automatic │
│                                                        model: Sonnet   │
│                                                                        │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐         │
│  │ DISCOVER │───▶│ EXTRACT  │───▶│ VALIDATE │───▶│ COMPILE  │         │
│  │          │    │          │    │          │    │          │         │
│  │ Research │    │ Parse    │    │ Verify   │    │ Draft    │         │
│  │ & rank   │    │ key data │    │ accuracy │    │ document │         │
│  │ sources  │    │ from     │    │ & check  │    │ (Minto   │         │
│  │          │    │ sources  │    │ bias     │    │ Pyramid) │         │
│  └──────────┘    └──────────┘    └──────────┘    └──────────┘         │
│   web_search      drive_read      web_search      (no tools)          │
│   drive_search    slack_thread                                        │
│   slack_search                                                        │
└──────────────────────────────────┬──────────────────────────────────────┘
                                   │ compiled document
                                   ▼
                              ┌─── ⛩ ───┐
                              │  GATE   │ CEO: proceed / modify / stop
                              └─── ┬ ───┘
                                   │
┌──────────────────────────────────▼──────────────────────────────────────┐
│  LAYER 2 — INTERPRET & DECIDE                          runs: gated     │
│                                                        model: Opus     │
│                                                                        │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐                         │
│  │  AUDIT   │───▶│ REFLECT  │───▶│  DECIDE  │                         │
│  │          │    │          │    │          │                         │
│  │ Multi-   │    │ Strategic│    │ 2-3      │                         │
│  │ expert   │    │ stress   │    │ options  │                         │
│  │ panel    │    │ test     │    │ + trade- │                         │
│  │ review   │    │          │    │ offs     │                         │
│  └──────────┘    └──────────┘    └──────────┘                         │
│   (no tools)      (no tools)      (no tools)                          │
│        ▲                                                               │
│        │ feedback loop (iteration N+1)                                 │
└────────┼─────────────────────────┬─────────────────────────────────────┘
         │                         │ CEO-approved decision
         │                    ┌─── ⛩ ───┐
         │                    │  GATE   │ CEO confirms action
         │                    └─── ┬ ───┘
         │                         │
┌────────┼─────────────────────────▼─────────────────────────────────────┐
│  LAYER 3 — DISTRIBUTE & FEEDBACK                       runs: gated    │
│                                                        model: Sonnet  │
│                                                                       │
│  ┌────────────┐    ┌────────────────┐                                 │
│  │ DISTRIBUTE │───▶│ COLLECT +      │──┐                              │
│  │            │    │ ITERATE        │  │                              │
│  │ Adapt to   │    │                │  │ re-inject feedback           │
│  │ channel    │    │ Parse feedback │  │ into Layer 2                 │
│  │ (email,    │    │ from stake-    │  │                              │
│  │ Slack)     │    │ holders        │  │                              │
│  └────────────┘    └────────────────┘  │                              │
│   slack_send        slack_search       │                              │
│   gmail_draft       gmail_search       │                              │
│                     slack_thread       │                              │
│                     gmail_read         │                              │
└────────────────────────────────────────┘
         │
         └──────────────────────────────────── loops back to AUDIT ──────┘

═══════════════════════════════════════════════════════════════════════════

┌─────────────────────────────────────────────────────────────────────────┐
│  SUPPORT — CONTEXT MIDDLEWARE                 intercepts all agents     │
│                                               model: 2× Sonnet calls   │
│                                                                        │
│  When any agent asks a question in interactive mode:                    │
│                                                                        │
│  ┌─────────┐    ┌─────────┐    ┌─────────────┐                        │
│  │  PLAN   │───▶│ EXECUTE │───▶│ SYNTHESIZE  │                        │
│  │         │    │         │    │             │                        │
│  │ Claude  │    │ Run     │    │ Claude      │                        │
│  │ reads   │    │ planned │    │ interprets  │                        │
│  │ agent   │    │ queries │    │ results +   │                        │
│  │ output, │    │ via     │    │ scores 1-10 │                        │
│  │ designs │    │ tools   │    │ as domain   │                        │
│  │ search  │    │         │    │ expert for  │                        │
│  │ queries │    │         │    │ the calling │                        │
│  │         │    │         │    │ agent's rol │                        │
│  └─────────┘    └─────────┘    └─────────────┘                        │
│   Sonnet call    drive,gmail    Sonnet call                            │
│                  slack,calendar  score >= 5 → show to CEO              │
└─────────────────────────────────────────────────────────────────────────┘

═══════════════════════════════════════════════════════════════════════════

  EPISTEMIC CHAIN — invariant enforced by EventBus

  DISCOVER ─▶ EXTRACT ─▶ VALIDATE ─▶ COMPILE ─▶ AUDIT ─▶ REFLECT ─▶ DECIDE ─▶ DISTRIBUTE
  [  OBS  ]   [  OBS  ]   [  OBS  ]   [ MOD  ]   [ MOD ]   [ MOD  ]   [ DEC  ]   [ DEC   ]
  ◄──────── observation ──────────►   ◄────── model ──────►   ◄── decision ──►
                                                     ▲
  COLLECT_ITERATE ───────────────────────────────────┘
  [     OBS      ]    (feedback = new observations → re-enter model phase)

  Rules:  MOD must have upstream OBS or MOD — never DEC
          DEC must have upstream MOD — never OBS or DEC
          OBS can start chain or follow DEC (feedback loop)

═══════════════════════════════════════════════════════════════════════════

  EVENT BUS — persisted audit trail per pipeline run

  After each agent:
    1. Validate epistemic invariant (raise or warn on violation)
    2. Run canonical evaluation (Claude Sonnet as domain expert → score 1-10)
    3. Publish AgentEvent to bus (persisted to events_{run_id}.json)

  Pipeline output includes:
    [OBS] DISCOVER      [7/10]
    [OBS] EXTRACT       [8/10]
    [OBS] VALIDATE      [6/10]
    [MOD] COMPILE       [8/10]
    [MOD] AUDIT         [7/10]
    [MOD] REFLECT       [9/10]
    [DEC] DECIDE        [8/10]

    Chain: OBS → OBS → OBS → MOD → MOD → MOD → DEC
    Epistemic invariant: VALID
    Average: 7.6/10
```

### Key design properties

| Property | Guarantee |
|----------|-----------|
| **Data flow** | Strictly sequential within a layer. Each agent receives the full output of its predecessor plus truncated context from prior agents. |
| **Model tiering** | Layer 2 (AUDIT, REFLECT, DECIDE) uses Opus for maximum reasoning quality. All other agents use Sonnet for cost efficiency. |
| **Gate semantics** | Gates are *blocking checkpoints*. The pipeline pauses and persists state. The CEO can resume hours or days later. Three actions: `proceed`, `modify` (inject context), `stop` (save + exit). |
| **Tool fallback** | Every tool has a 3-tier strategy: (1) direct API if credentials exist, (2) Claude proxy if auth fails, (3) `manual_fallback` for write operations without credentials. Agents never receive an error for missing credentials. |
| **Feedback loop** | COLLECT_ITERATE feeds back to AUDIT, not DISCOVER. This avoids re-researching; it re-evaluates the same document with new stakeholder input. |
| **CONTEXT middleware** | CONTEXT intercepts every agent question in interactive mode. It runs a 3-phase pipeline (PLAN → EXECUTE → SYNTHESIZE) using two lightweight Sonnet calls. Scoring is contextual: Claude adopts the canonical domain expert for the calling agent's role (e.g., auditor for VALIDATE, strategy advisor for DECIDE). Only suggestions scoring ≥ 5/10 reach the CEO. |
| **Epistemic invariant** | `OBSERVATION → MODEL → DECISION`. Every decision is sustained by explicit models, every model by traceable observations. The EventBus validates this at every agent transition. A DECISION never rests on another DECISION or directly on OBSERVATIONS. Structurally enforced by `canonical.py` phase assignments. |
| **Canonical evaluation** | After each agent runs, its output is evaluated by Claude adopting the perspective of the canonical domain expert for that agent's role (e.g., auditor for VALIDATE, strategy advisor for DECIDE). Scored 1-10 on criteria specific to each agent. Results persist in the EventBus. |
| **Event bus** | Every agent execution publishes an `AgentEvent` to a file-backed bus (`events_{run_id}.json`). Events include: epistemic phase, evaluation score, invariant check, input/output summaries. Enables post-mortem analysis and quality tracking across runs. |
| **Token budget** | Context accumulation is dynamically sized to fit within model limits. Prior outputs are proportionally truncated — the most recent agent's output is always passed in full. |
| **Graceful shutdown** | Ctrl+C during a pipeline run saves state to manifest and commits to GitHub. The pipeline can be resumed exactly where it stopped. |

## Agents — Canonical Definitions

Each agent has a defined epistemic phase, a canonical referent (domain expert that evaluates its output), and specific evaluation criteria.

| # | Agent | Phase | Canonical Referent | Purpose | Output Artifact |
|---|-------|-------|--------------------|---------|-----------------|
| 01 | **DISCOVER** | OBS | Analista senior de research | Buscar, filtrar y priorizar fuentes relevantes | Catálogo de fuentes con fichas bibliográficas |
| 02 | **EXTRACT** | OBS | Data analyst financiero | Extraer datos, argumentos y cifras de las fuentes | Fichas de extracción estructuradas |
| 03 | **VALIDATE** | OBS | Auditor / fact-checker | Verificar precisión, consistencia, sesgo y vigencia | Reporte de validación con scoring por dato |
| 04 | **COMPILE** | MOD | Consultor estratégico senior | Transformar observaciones en documento estructurado | Documento Minto Pyramid con trazabilidad |
| 05 | **AUDIT** | MOD | Panel multi-experto (legal, financiero, reg.) | Revisión multi-dimensional del modelo | Veredicto con scoring dimensional |
| 06 | **REFLECT** | MOD | Devil's advocate estratégico | Stress-test de supuestos y escenarios adversos | Reporte de robustez y sensibilidad |
| 07 | **DECIDE** | DEC | Strategy advisor de C-suite | Presentar opciones sustentadas en modelos | Menú de decisión con trade-offs |
| 08 | **DISTRIBUTE** | DEC | Director de comunicaciones corporativas | Adaptar la decisión al canal y destinatario | Mensaje adaptado por canal |
| 09 | **COLLECT+IT** | OBS | Product manager senior | Estructurar feedback como nuevas observaciones | Feedback con scoring señal/ruido |
| 10 | **CONTEXT** | — | (per-agent, see middleware) | Middleware: PLAN → EXECUTE → SYNTHESIZE | Sugerencias con score 1-10 |

### Evaluation criteria per agent

Each agent is scored 1-10 on 5 criteria specific to its role. Example for **COMPILE** (model phase):

1. **Estructura lógica** — ¿La pirámide argumental es coherente (tesis→argumentos→evidencia)?
2. **Trazabilidad** — ¿Cada afirmación del modelo apunta a observaciones de VALIDATE?
3. **Completitud** — ¿El modelo incorpora todas las observaciones relevantes?
4. **Claridad** — ¿Un lector externo puede seguir el argumento sin conocimiento previo?
5. **Fidelidad** — ¿El modelo NO agrega interpretaciones sin sustento en observaciones?

Full criteria for all agents are defined in `orchestrator/canonical.py:AGENT_CANON`.

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

## CONTEXT Middleware Architecture

CONTEXT is a 3-phase middleware that intercepts every agent question in interactive mode. Instead of showing raw search results, it uses Claude to interpret what's needed, design searches, and evaluate results with domain-appropriate rigor.

```
Agent asks question in interactive mode
        │
        ▼
┌── PHASE 1: PLAN ──────────────────────────────────────────────────┐
│  Claude Sonnet reads the agent's output + knows which agent is    │
│  asking. Extracts the actual information needs (not regex).       │
│  Designs targeted queries per source:                             │
│                                                                   │
│  DISCOVER asks about AUM →                                        │
│    Drive: "reporte mensual AUM patrimonio"                        │
│    Gmail: "from:ceo@cordada.cl AUM"                               │
│                                                                   │
│  DECIDE asks about stakeholders →                                 │
│    Slack: "#directorio gobernanza reestructuración"               │
│    Gmail: "Fernando reestructuración propuesta"                   │
│                                                                   │
│  Output: JSON search plan with tool + params per question         │
└───────────────────────────────┬───────────────────────────────────┘
                                │
                                ▼
┌── PHASE 2: EXECUTE ───────────────────────────────────────────────┐
│  Runs each planned query via tools.execute_tool()                 │
│  (direct API → proxy fallback, same as agents)                    │
│  Sources: Drive, Gmail, Slack, Calendar                           │
└───────────────────────────────┬───────────────────────────────────┘
                                │
                                ▼
┌── PHASE 3: SYNTHESIZE ────────────────────────────────────────────┐
│  Claude Sonnet interprets raw results adopting the perspective    │
│  of the canonical domain expert for the calling agent's role:     │
│                                                                   │
│  Agent        │ Canonical referent                                │
│  ─────────────┼─────────────────────────────────────────────      │
│  DISCOVER     │ Analista senior de research                       │
│  EXTRACT      │ Data analyst financiero                           │
│  VALIDATE     │ Auditor / fact-checker independiente              │
│  COMPILE      │ Consultor estratégico senior                      │
│  AUDIT        │ Panel multi-experto (legal, financiero, reg.)     │
│  REFLECT      │ Devil's advocate estratégico                      │
│  DECIDE       │ Strategy advisor de C-suite                       │
│  DISTRIBUTE   │ Director de comunicaciones corporativas           │
│  COLLECT_ITER │ Product manager senior                            │
│                                                                   │
│  Scores each suggestion 1-10 on 4 criteria:                       │
│    Relevancia · Frescura · Autoridad · Suficiencia                │
│                                                                   │
│  Score >= 5 → show to CEO with reasoning                          │
│  Score < 5  → report as "no encontré respuesta suficiente"        │
└───────────────────────────────┬───────────────────────────────────┘
                                │
                                ▼
         CEO sees:
           **¿Cuál es el AUM actual?** [8/10]
           → USD 200M al cierre de diciembre 2024
             Fuente: Drive - Reporte Mensual Dic 2024.xlsx
             Evaluación: Dato de fuente oficial, reciente, específico.

           Opciones: 1. Confirmar  2. Corregir  3. Manual
```

**Cost:** 2 lightweight Sonnet calls (~3K tokens total) per interactive turn. The quality gain — contextual queries, intelligent interpretation, domain-expert scoring — is substantial compared to the previous regex + keyword approach.

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

## Project Structure (DDD)

The codebase follows Domain-Driven Design (Evans, 2003) with clean separation between the domain model, application services, and infrastructure.

```
cordada-ceo-agents/
│
├── domain/                        ← BOUNDED CONTEXT: Core domain (no external deps)
│   ├── __init__.py                   Exports: AgentDefinition, EpistemicPhase, EventBus
│   ├── model.py                     Value objects: AgentDefinition, EpistemicPhase,
│   │                                  AgentEvaluation
│   ├── registry.py                  Single source of truth: AGENTS dict
│   │                                  (unified config + canon + evaluation criteria)
│   ├── events.py                    Domain events: AgentEvent, EventBus,
│   │                                  InvariantViolation
│   └── invariant.py                 Epistemic chain validation (pure logic, no I/O)
│
├── agents/                        ← Domain artifacts (usable standalone in Claude.ai)
│   ├── 01_discover.md ... 10_context.md
│
├── orchestrator/                  ← APPLICATION + INTERFACE layer
│   ├── __init__.py                   Public Python API + re-exports from domain/
│   ├── __main__.py                   CLI entry point
│   ├── config.py                     Infrastructure config: env vars, paths
│   │                                  (re-exports AGENTS from domain for compat)
│   ├── canonical.py                  Evaluation service: Claude API calls
│   │                                  (re-exports domain types for compat)
│   ├── event_bus.py                  Re-export from domain.events
│   ├── agent_runner.py               Agent execution: API calls, tool loop, metrics
│   ├── pipeline.py                   Pipeline orchestration: sequence, gates, context
│   ├── gates.py                      Gate handlers: terminal_gate, auto_gate
│   ├── tools.py                      Tool registry + executors + Claude proxy fallback
│   ├── context_middleware.py         3-phase CONTEXT: PLAN → EXECUTE → SYNTHESIZE
│   └── project.py                    GitHub project management
│
├── tests/                         ← Unit tests
├── docs/                          ← architecture.html (Material 3 interactive diagram)
├── examples/                      ← carta_aportantes.py
├── outputs/                       ← Pipeline outputs (gitignored)
└── projects/                      ← Project repos (gitignored)
```

### DDD layer responsibilities

| Layer | Package | Depends on | Responsibility |
|-------|---------|------------|----------------|
| **Domain** | `domain/` | nothing | Value objects, aggregates, invariants, events. Zero external dependencies. |
| **Application** | `orchestrator/` | `domain/` | Use cases: run agents, orchestrate pipelines, evaluate outputs, search context. |
| **Infrastructure** | `orchestrator/tools.py`, `config.py` | `domain/`, external APIs | Anthropic API, Google Workspace, Slack, GitHub, file I/O. |
| **Interface** | `orchestrator/__init__.py`, `__main__.py` | `application/` | Python API, CLI. |

Dependencies flow **inward**: interface → application → domain. The domain layer never imports from orchestrator.

### Unified agent definition (single source of truth)

Previously, agent identity was split across two registries that could drift:
- `config.AGENTS` — pipeline config (order, layer, file, next)
- `canonical.AGENT_CANON` — epistemic definitions (phase, criteria, referent)

Now there is ONE `AgentDefinition` per agent in `domain.registry.AGENTS`:

```python
from domain import AGENTS

agent = AGENTS["compile"]
agent.order              # 4
agent.layer              # "feed"
agent.phase              # EpistemicPhase.MODEL
agent.prompt_file        # "04_compile.md"
agent.canonical_referent # "Consultor estratégico senior (McKinsey/BCG)..."
agent.evaluation_criteria  # tuple of 5 criteria
agent["file"]            # "04_compile.md" (legacy dict access, backward compat)
```

## Model Selection

| Agent | Model | Reason |
|-------|-------|--------|
| DISCOVER → DISTRIBUTE | claude-sonnet-4-20250514 | Best balance of quality and cost |
| AUDIT, REFLECT, DECIDE | claude-opus-4-6 | Strategic evaluation requires maximum quality |
| CONTEXT middleware (2 calls) | claude-sonnet-4-20250514 | PLAN + SYNTHESIZE phases, ~3K tokens per turn |
| Canonical evaluation (1 call/agent) | claude-sonnet-4-20250514 | Post-hoc quality scoring, ~2K tokens per eval |
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
| Canonical Evaluation | Every agent scored 1-10 by domain expert | — |
| Epistemic Invariant | OBS→MOD→DEC enforced by EventBus | — |
| Event Sourcing | File-backed audit trail per pipeline run | — |
| Graceful Degradation | Tool fallback via Claude proxy | — |

## References

- Evans, E. (2003). *Domain-Driven Design: Tackling Complexity in the Heart of Software*. Addison-Wesley.
- Gullí, A. (2025). *Agentic Design Patterns: A Hands-On Guide to Building Intelligent Systems*. Springer Nature.
- Anthropic. (2025). [Building agents with the Claude Agent SDK](https://www.anthropic.com/engineering/building-agents-with-the-claude-agent-sdk).
- Anthropic. (2025). [Code execution with MCP](https://www.anthropic.com/engineering/code-execution-with-mcp).
- Anthropic. (2025). [Introducing advanced tool use](https://www.anthropic.com/engineering/advanced-tool-use).

## License

Private repository. All rights reserved. Cordada SpA.
