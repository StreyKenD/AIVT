"""Safety configuration assets for filtros de conteúdo."""

from importlib.resources import files
from pathlib import Path
from typing import Iterable

PACKAGE_ROOT = files(__package__)


def load_lines(name: str) -> Iterable[str]:
    data = PACKAGE_ROOT.joinpath(name).read_text(encoding="utf-8")
    for raw_line in data.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        yield line


def load_json(name: str) -> dict[str, str]:
    import json

    return json.loads(PACKAGE_ROOT.joinpath(name).read_text(encoding="utf-8"))


__all__ = ["load_lines", "load_json"]
