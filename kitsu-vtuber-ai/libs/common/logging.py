from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import IO, Any, Dict

__all__ = ["configure_json_logging"]

_LOG_DIR_ENV = "KITSU_LOG_ROOT"
_NUM_BACKUPS = 7


class JsonFormatter(logging.Formatter):
    """Formatter que serializa registros de log em JSON."""

    def __init__(self, service_name: str) -> None:
        super().__init__()
        self._service_name = service_name
        baseline = logging.LogRecord(
            name="_baseline",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="",
            args=(),
            exc_info=None,
        )
        self._reserved = set(baseline.__dict__.keys()) | {
            "service",
            "level",
            "message",
            "logger",
            "ts",
            "exception",
        }

    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "service": self._service_name,
            "level": record.levelname.lower(),
            "message": record.getMessage(),
            "logger": record.name,
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in self._reserved
        }
        if extras:
            payload["extra"] = extras
        return json.dumps(payload, ensure_ascii=False)


def configure_json_logging(
    service_name: str,
    *,
    level: int | str = logging.INFO,
    stream: IO[str] | None = None,
) -> None:
    """Configura logging estruturado (JSON) para o serviço informado."""

    name_to_level = getattr(logging, "_nameToLevel", {})
    env_level = os.getenv("LOG_LEVEL")
    if isinstance(name_to_level, dict):
        if env_level:
            candidate = name_to_level.get(env_level.upper())
            if isinstance(candidate, int):
                level = candidate
        elif isinstance(level, str):
            candidate = name_to_level.get(level.upper())
            if isinstance(candidate, int):
                level = candidate

    root = logging.getLogger()
    root.setLevel(level)

    for handler in list(root.handlers):
        root.removeHandler(handler)
        try:
            handler.close()
        except Exception:  # pragma: no cover - fechamento defensivo
            pass

    formatter = JsonFormatter(service_name)

    stream_handler = logging.StreamHandler(stream)
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)

    log_dir = Path(os.getenv(_LOG_DIR_ENV, "logs"))
    log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = TimedRotatingFileHandler(
        log_dir / f"{service_name}.log",
        when="midnight",
        backupCount=_NUM_BACKUPS,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)
