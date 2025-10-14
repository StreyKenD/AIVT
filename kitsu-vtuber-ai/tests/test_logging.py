from __future__ import annotations

import io
import json
import logging
from pathlib import Path

import pytest

from libs.common import configure_json_logging


@pytest.fixture()
def log_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KITSU_LOG_ROOT", str(tmp_path))
    return tmp_path


def test_configure_json_logging_emits_json(log_dir: Path) -> None:
    stream = io.StringIO()
    configure_json_logging("test_service", stream=stream)
    logger = logging.getLogger("kitsu.test")
    logger.info("hello", extra={"context": "demo"})
    stream.seek(0)
    line = stream.readline().strip()
    assert line, "expected JSON payload"
    payload = json.loads(line)
    assert payload["service"] == "test_service"
    assert payload["level"] == "info"
    assert payload["message"] == "hello"
    assert payload["logger"] == "kitsu.test"
    assert payload["extra"] == {"context": "demo"}

    log_file = log_dir / "test_service.log"
    assert log_file.exists()
    data = log_file.read_text(encoding="utf-8").strip().splitlines()
    assert data, "expected log lines"
    first_entry = json.loads(data[0])
    assert first_entry["service"] == "test_service"
