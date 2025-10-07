from __future__ import annotations

import asyncio
from pathlib import Path

from libs.memory.controller import MemoryController


def test_memory_controller_persist(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.sqlite3"

    async def scenario() -> None:
        controller = MemoryController(buffer_size=8, summary_interval=3, database_path=db_path)
        await controller.prepare(restore=False)

        await controller.add_turn("user", "Hello there!")
        await controller.add_turn("assistant", "Hi hi!")
        summary = await controller.add_turn("user", "Let's play!")
        assert summary is not None
        assert summary.summary_text
        assert "Let's" in summary.summary_text

        restored = MemoryController(buffer_size=8, summary_interval=3, database_path=db_path)
        loaded = await restored.prepare(restore=True)
        assert loaded is not None
        assert loaded.summary_text == summary.summary_text
        assert restored.snapshot()["restore_enabled"] is True

    asyncio.run(scenario())
