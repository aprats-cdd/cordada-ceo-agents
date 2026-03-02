"""
Event Bus — records every agent execution as a traceable event,
validates the epistemic invariant, and persists an audit trail.

Core invariant enforced:

    OBSERVATION → MODEL → DECISION

    - A DECISION must have upstream MODEL events
    - A MODEL must have upstream OBSERVATION events
    - An OBSERVATION can start the chain or follow a DECISION (feedback loop)
    - A DECISION never feeds directly into another DECISION
    - A DECISION never feeds directly from OBSERVATIONS

The bus is file-backed (one JSON file per pipeline run) so events
survive crashes and can be reviewed post-mortem.

Usage:
    from orchestrator.event_bus import EventBus

    bus = EventBus(run_id="pipeline_20260302_120000")
    bus.publish("discover", output, evaluation)
    bus.publish("extract", output, evaluation)
    # ...
    bus.get_trail()  # full audit trail
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path

from .canonical import (
    AGENT_CANON,
    AgentEvaluation,
    EpistemicPhase,
    validate_epistemic_chain,
    get_upstream_agent,
)

logger = logging.getLogger(__name__)


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


class InvariantViolation(Exception):
    """Raised when the epistemic invariant is violated."""


class EventBus:
    """Pipeline event bus with epistemic invariant enforcement.

    Args:
        run_id: Unique identifier for this pipeline run.
        persist_dir: Directory to write the event log JSON.
        strict: If True, raise on invariant violations.
                If False, log warning and continue.
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
    ) -> AgentEvent:
        """Record an agent execution event.

        Args:
            agent_name: Which agent produced this output.
            output: The agent's output text.
            evaluation: Optional canonical evaluation result.
            input_text: The input the agent received.

        Returns:
            The created AgentEvent.

        Raises:
            InvariantViolation: If strict=True and the epistemic chain breaks.
        """
        canon = AGENT_CANON.get(agent_name)
        phase = canon.phase.value if canon else "unknown"

        # Find upstream event
        upstream_event = self.events[-1] if self.events else None
        upstream_agent = upstream_event.agent if upstream_event else None

        # Validate invariant
        valid, note = validate_epistemic_chain(agent_name, upstream_agent)
        if not valid:
            if self.strict:
                raise InvariantViolation(note)
            logger.warning("EPISTEMIC INVARIANT: %s", note)

        # Create event
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
        )

        self.events.append(event)
        self._persist()

        # Log event
        score_str = f" [{evaluation.score}/10]" if evaluation else ""
        phase_icon = {"observation": "OBS", "model": "MOD", "decision": "DEC"}.get(phase, "???")
        logger.info(
            "EVENT %s [%s] %s%s%s",
            event.event_id,
            phase_icon,
            agent_name.upper(),
            score_str,
            "" if valid else f" !! {note}",
        )

        return event

    def get_trail(self) -> list[dict]:
        """Return the full audit trail as a list of dicts."""
        return [asdict(e) for e in self.events]

    def get_chain_summary(self) -> str:
        """Return a human-readable summary of the epistemic chain."""
        if not self.events:
            return "No events recorded."

        lines: list[str] = []
        phase_icons = {
            "observation": "OBS",
            "model": "MOD",
            "decision": "DEC",
        }

        for e in self.events:
            icon = phase_icons.get(e.epistemic_phase, "???")
            score = ""
            if e.evaluation:
                score = f" [{e.evaluation.get('score', '?')}/10]"
            valid = "" if e.invariant_valid else " !! VIOLATION"
            lines.append(f"  [{icon}] {e.agent.upper()}{score}{valid}")

        # Show chain flow
        phases = [e.epistemic_phase for e in self.events]
        chain = " → ".join(
            phase_icons.get(p, "???") for p in phases
        )
        lines.append(f"\n  Chain: {chain}")

        # Invariant status
        violations = [e for e in self.events if not e.invariant_valid]
        if violations:
            lines.append(f"\n  INVARIANT VIOLATIONS: {len(violations)}")
            for v in violations:
                lines.append(f"    - {v.invariant_note}")
        else:
            lines.append("\n  Epistemic invariant: VALID")

        return "\n".join(lines)

    def get_scores_summary(self) -> str:
        """Return a summary of evaluation scores."""
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

        # Average score
        scores = [
            e.evaluation["score"]
            for e in self.events
            if e.evaluation and "score" in e.evaluation
        ]
        if scores:
            avg = sum(scores) / len(scores)
            lines.append(f"\n  Average: {avg:.1f}/10")

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
