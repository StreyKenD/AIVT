from __future__ import annotations

from typing import Optional

from fastapi import Header, HTTPException, status

from .broker import EventBroker
from .state import OrchestratorState

_state: Optional[OrchestratorState] = None
_broker: Optional[EventBroker] = None
_api_key: Optional[str] = None


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


def set_api_key(value: Optional[str]) -> None:
    global _api_key
    if value is None:
        _api_key = None
        return
    stripped = value.strip()
    _api_key = stripped or None


def require_orchestrator_token(
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    authorization: Optional[str] = Header(default=None),
) -> None:
    if _api_key is None:
        return
    if x_api_key == _api_key:
        return
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() == "bearer" and token == _api_key:
            return
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing API key",
    )


__all__ = [
    "get_state",
    "get_broker",
    "set_state",
    "set_broker",
    "set_api_key",
    "require_orchestrator_token",
]
