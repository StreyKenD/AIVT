from __future__ import annotations

from typing import Optional

from .broker import EventBroker
from .state import OrchestratorState

_state: Optional[OrchestratorState] = None
_broker: Optional[EventBroker] = None


def set_state(state: OrchestratorState) -> None:
    global _state
    _state = state


def set_broker(broker: EventBroker) -> None:
    global _broker
    _broker = broker


def get_state() -> OrchestratorState:
    if _state is None:  # pragma: no cover - should be initialised at startup
        raise RuntimeError("Orchestrator state not initialised")
    return _state


def get_broker() -> EventBroker:
    if _broker is None:  # pragma: no cover - should be initialised at startup
        raise RuntimeError("Event broker not initialised")
    return _broker


__all__ = ["get_state", "get_broker", "set_state", "set_broker"]
