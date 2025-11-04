from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Dict, Tuple

import pytest

from apps.tts_worker.service import PiperSynthesizer
from libs.config.models import PiperTTSSettings


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("model", "", "PIPER_MODEL is not configured"),
        ("model", "   ", "PIPER_MODEL is not configured"),
        ("binary", "", "PIPER_PATH is not configured"),
        ("binary", "   ", "PIPER_PATH is not configured"),
    ],
)
def test_piper_synthesizer_requires_non_empty_config(field, value, message) -> None:
    kwargs = {"binary": "/usr/bin/piper", "model": "/models/en_US.onnx"}
    kwargs[field] = value
    config = PiperTTSSettings(**kwargs)
    with pytest.raises(RuntimeError, match=message):
        PiperSynthesizer(config)


@pytest.mark.parametrize(
    "config_value, expected_flag",
    [
        ("", False),
        ("   ", False),
        (None, False),
        ("/models/piper/config.json", True),
    ],
)
def test_piper_synthesizer_respects_optional_config(
    config_value, expected_flag
) -> None:
    kwargs = {"binary": "/usr/bin/piper", "model": "/models/en_US.onnx"}
    if config_value is not None:
        kwargs["config"] = config_value
    config = PiperTTSSettings(**kwargs)

    synth = PiperSynthesizer(config)

    captured: Dict[str, Tuple[str, ...]] = {}

    class _Stdin:
        def write(self, _data: bytes) -> None:  # match StreamWriter signature
            return None

        async def drain(self) -> None:
            return None

        def close(self) -> None:
            return None

    class _Proc:
        def __init__(self) -> None:
            self.stdin = _Stdin()

        async def communicate(self) -> tuple[bytes, bytes]:
            return b"", b""

        @property
        def returncode(self) -> int:
            return 0

    async def _fake_exec(*cmd: str, **_: object) -> _Proc:
        captured["cmd"] = tuple(cmd)
        return _Proc()

    original_exec = getattr(asyncio, "create_subprocess_exec")
    setattr(asyncio, "create_subprocess_exec", _fake_exec)
    try:

        async def _invoke() -> None:
            await synth.synthesize("hello", None, destination=Path("/tmp/output.wav"))

        asyncio.run(_invoke())
    finally:
        setattr(asyncio, "create_subprocess_exec", original_exec)

    cmd_list = list(captured["cmd"])
    has_config = "--config" in cmd_list
    assert has_config is expected_flag
    if expected_flag and config_value is not None:
        config_index = cmd_list.index("--config") + 1
        assert Path(cmd_list[config_index]) == Path(config_value.strip())
