from __future__ import annotations

import importlib
import importlib.util
from types import ModuleType
from typing import Optional, cast


def load_module_if_available(name: str) -> Optional[ModuleType]:
    spec = importlib.util.find_spec(name)
    if spec is None:
        return None
    module = importlib.import_module(name)
    return cast(ModuleType, module)


__all__ = ["load_module_if_available"]
