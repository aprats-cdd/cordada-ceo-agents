"""
Event Bus — re-exported from domain layer.

The canonical implementation lives in ``domain.events``.
This module exists for backward compatibility:

    from orchestrator.event_bus import EventBus  # still works
"""

from domain.events import AgentEvent, EventBus, InvariantViolation  # noqa: F401

__all__ = ["AgentEvent", "EventBus", "InvariantViolation"]
