"""
Domain Events + Event Bus — traceable audit trail with invariant enforcement.

Every agent execution publishes an ``AgentEvent``.  The ``EventBus``
validates the epistemic invariant at each transition and persists
events to a JSON file per pipeline run.

This module depends ONLY on the domain layer (model, registry, invariant).
File I/O for persistence is the only side-effect, and is optional.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

from .model import AgentEvaluation, TokenUsage
from .registry import AGENTS
from .invariant import validate_epistemic_chain

logger = logging.getLogger(__name__)


class InvariantViolation(Exception):
    """Raised when the epistemic invariant is violated (strict mode)."""


@dataclass
class AgentEvent:
    """A single recorded event in the pipeline."""
    event_id: str
    timestamp: str
    run_id: str
    agent: str
    epistemic_phase: str
    input_summary: str
    output_summary: str
    evaluation: dict | None = None
    upstream_event_id: str | None = None
    invariant_valid: bool = True
    invariant_note: str = ""
    # Cost governance fields
    token_usage: dict | None = None       # serialized TokenUsage (asdict)
    cumulative_cost_usd: float = 0.0


class EventBus:
    """Pipeline event bus with epistemic invariant enforcement.

    Args:
        run_id: Unique identifier for this pipeline run.
        persist_dir: Directory to write the event log JSON.
        strict: If True, raise on invariant violations.
    """

    def __init__(
        self,
        run_id: str,
        persist_dir: Path | None = None,
        strict: bool = False,
    ):
        self.run_id = run_id
        self.strict = strict
        self.events: list[AgentEvent] = []
        self._persist_path: Path | None = None

        if persist_dir:
            persist_dir.mkdir(parents=True, exist_ok=True)
            self._persist_path = persist_dir / f"events_{run_id}.json"

    def publish(
        self,
        agent_name: str,
        output: str,
        evaluation: AgentEvaluation | None = None,
        input_text: str = "",
        token_usage: TokenUsage | None = None,
    ) -> AgentEvent:
        """Record an agent execution event."""
        agent = AGENTS.get(agent_name)
        phase = agent.phase.value if agent else "unknown"

        upstream_event = self.events[-1] if self.events else None
        upstream_agent = upstream_event.agent if upstream_event else None

        valid, note = validate_epistemic_chain(agent_name, upstream_agent)
        if not valid:
            if self.strict:
                raise InvariantViolation(note)
            logger.warning("EPISTEMIC INVARIANT: %s", note)

        # Compute cumulative cost across the run
        prev_cumulative = self.events[-1].cumulative_cost_usd if self.events else 0.0
        agent_cost = token_usage.cost_usd if token_usage else 0.0
        cumulative = round(prev_cumulative + agent_cost, 6)

        event = AgentEvent(
            event_id=f"{self.run_id}_{agent_name}_{len(self.events):03d}",
            timestamp=datetime.now().isoformat(),
            run_id=self.run_id,
            agent=agent_name,
            epistemic_phase=phase,
            input_summary=input_text[:500] + ("..." if len(input_text) > 500 else ""),
            output_summary=output[:500] + ("..." if len(output) > 500 else ""),
            evaluation=asdict(evaluation) if evaluation else None,
            upstream_event_id=upstream_event.event_id if upstream_event else None,
            invariant_valid=valid,
            invariant_note=note,
            token_usage=asdict(token_usage) if token_usage else None,
            cumulative_cost_usd=cumulative,
        )

        self.events.append(event)
        self._persist()

        score_str = f" [{evaluation.score}/10]" if evaluation else ""
        phase_icon = {"observation": "OBS", "model": "MOD", "decision": "DEC"}.get(phase, "???")
        logger.info(
            "EVENT %s [%s] %s%s%s",
            event.event_id, phase_icon, agent_name.upper(),
            score_str, "" if valid else f" !! {note}",
        )

        return event

    def get_trail(self) -> list[dict]:
        """Return the full audit trail as a list of dicts."""
        return [asdict(e) for e in self.events]

    def get_chain_summary(self) -> str:
        """Human-readable summary of the epistemic chain."""
        if not self.events:
            return "No events recorded."

        icons = {"observation": "OBS", "model": "MOD", "decision": "DEC"}
        lines: list[str] = []

        for e in self.events:
            icon = icons.get(e.epistemic_phase, "???")
            score = f" [{e.evaluation.get('score', '?')}/10]" if e.evaluation else ""
            valid = "" if e.invariant_valid else " !! VIOLATION"
            lines.append(f"  [{icon}] {e.agent.upper()}{score}{valid}")

        chain = " → ".join(icons.get(e.epistemic_phase, "???") for e in self.events)
        lines.append(f"\n  Chain: {chain}")

        violations = [e for e in self.events if not e.invariant_valid]
        if violations:
            lines.append(f"\n  INVARIANT VIOLATIONS: {len(violations)}")
            for v in violations:
                lines.append(f"    - {v.invariant_note}")
        else:
            lines.append("\n  Epistemic invariant: VALID")

        return "\n".join(lines)

    def get_scores_summary(self) -> str:
        """Summary of evaluation scores."""
        if not self.events:
            return "No events recorded."

        lines: list[str] = ["  Agent Evaluations:"]
        for e in self.events:
            if e.evaluation:
                score = e.evaluation.get("score", "?")
                reasoning = e.evaluation.get("reasoning", "")
                lines.append(f"    {e.agent.upper():20s} {score}/10 — {reasoning}")
            else:
                lines.append(f"    {e.agent.upper():20s} (not evaluated)")

        scores = [
            e.evaluation["score"]
            for e in self.events
            if e.evaluation and "score" in e.evaluation
        ]
        if scores:
            lines.append(f"\n  Average: {sum(scores)/len(scores):.1f}/10")

        return "\n".join(lines)

    def get_cost_summary(self) -> str:
        """Summary of token usage and costs across the pipeline run."""
        if not self.events:
            return "No events recorded."

        lines: list[str] = ["  Cost Summary (stop-loss report):"]
        for e in self.events:
            if e.token_usage:
                tu = e.token_usage
                lines.append(
                    f"    {e.agent.upper():20s} "
                    f"in={tu['input_tokens']:>6} out={tu['output_tokens']:>6} "
                    f"${tu['cost_usd']:.4f}  cumul=${e.cumulative_cost_usd:.4f}"
                )
            else:
                lines.append(f"    {e.agent.upper():20s} (no usage data)")

        total = self.events[-1].cumulative_cost_usd if self.events else 0.0
        lines.append(f"\n  Total pipeline cost: ${total:.4f}")
        return "\n".join(lines)

    def _persist(self) -> None:
        """Write events to disk."""
        if not self._persist_path:
            return
        try:
            data = {
                "run_id": self.run_id,
                "event_count": len(self.events),
                "events": [asdict(e) for e in self.events],
            }
            self._persist_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            logger.exception("Failed to persist events to %s", self._persist_path)
