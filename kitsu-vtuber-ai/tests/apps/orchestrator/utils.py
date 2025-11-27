from __future__ import annotations

import asyncio
import importlib
from pathlib import Path
from typing import Any, Optional

import pytest

from libs.config import reload_app_config


def load_orchestrator(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    api_key: Optional[str] = "test-key",
) -> Any:
    monkeypatch.setenv("MEMORY_DB_PATH", str(tmp_path / "memory.sqlite3"))
    monkeypatch.setenv("RESTORE_CONTEXT", "false")
    monkeypatch.delenv("TELEMETRY_API_URL", raising=False)
    monkeypatch.delenv("TELEMETRY_API_KEY", raising=False)
    if api_key:
        monkeypatch.setenv("ORCHESTRATOR_API_KEY", api_key)
    else:
        monkeypatch.delenv("ORCHESTRATOR_API_KEY", raising=False)
    monkeypatch.delenv("PERSONA_PRESETS_FILE", raising=False)
    monkeypatch.delenv("PERSONA_DEFAULT", raising=False)
    reload_app_config()
    module = importlib.import_module("apps.orchestrator.main")
    return importlib.reload(module)


async def wait_for_event(
    queue: asyncio.Queue, event_type: str, timeout: float = 2.0
) -> dict[str, Any]:
    deadline = timeout
    while True:
        message = await asyncio.wait_for(queue.get(), timeout=deadline)
        if message.get("type") == event_type:
            return message
