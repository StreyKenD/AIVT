from __future__ import annotations

from . import chat, control, events, integrations, persona, system, tts, webui

ALL_ROUTERS = [
    system.router,
    persona.router,
    tts.router,
    integrations.router,
    chat.router,
    control.router,
    events.router,
    webui.router,
]

__all__ = ["ALL_ROUTERS"]
