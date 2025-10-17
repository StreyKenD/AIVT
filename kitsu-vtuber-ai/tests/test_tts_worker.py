from __future__ import annotations

import os

import pytest

from apps.tts_worker.service import PiperSynthesizer


@pytest.mark.parametrize(
    "env_var, value, message",
    [
        ("PIPER_MODEL", "", "PIPER_MODEL is not configured"),
        ("PIPER_MODEL", "   ", "PIPER_MODEL is not configured"),
        ("PIPER_PATH", "", "PIPER_PATH is not configured"),
        ("PIPER_PATH", "   ", "PIPER_PATH is not configured"),
    ],
)
def test_piper_synthesizer_requires_non_empty_env(monkeypatch, env_var, value, message):
    """Ensure Piper validates the raw environment values before Path conversion."""

    # provide defaults that pass validation unless overridden by the parametrized case
    monkeypatch.setenv("PIPER_PATH", os.fspath("/usr/bin/piper"))
    monkeypatch.setenv("PIPER_MODEL", os.fspath("/models/en_US.onnx"))

    monkeypatch.setenv(env_var, value)

    with pytest.raises(RuntimeError, match=message):
        PiperSynthesizer()
