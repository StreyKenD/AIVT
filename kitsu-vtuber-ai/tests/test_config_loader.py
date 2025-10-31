from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from libs.config import reload_app_config


def test_env_overrides_take_precedence(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_file = tmp_path / "kitsu.yaml"
    config_file.write_text(
        textwrap.dedent(
            """
            version: 1
            policy:
              backend: ollama
              model_name: mixtral
            persona:
              default: default
              presets:
                default:
                  style: kawaii
                  chaos_level: 0.2
                  energy: 0.4
                  family_mode: true
            memory:
              buffer_size: 8
            """
        ).strip()
    )

    presets_file = tmp_path / "persona_presets.yaml"
    presets_file.write_text(
        textwrap.dedent(
            """
            mage:
              style: arcane
              chaos_level: 0.15
              energy: 0.45
              family_mode: true
            """
        ).strip()
    )

    history_path = tmp_path / "history.json"

    monkeypatch.setenv("KITSU_CONFIG_FILE", str(config_file))
    monkeypatch.setenv("POLICY_BACKEND", "openai")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("OPENAI_TIMEOUT_SECONDS", "12.5")
    monkeypatch.setenv("PERSONA_PRESETS_FILE", str(presets_file))
    monkeypatch.setenv("PERSONA_DEFAULT", "mage")
    monkeypatch.setenv("MEMORY_BUFFER_SIZE", "16")
    monkeypatch.setenv("MEMORY_HISTORY_PATH", str(history_path))

    settings = reload_app_config()

    assert settings.policy.backend == "openai"
    assert settings.policy.openai.model == "gpt-4o-mini"
    assert settings.policy.openai.timeout_seconds == 12.5
    assert settings.persona.default == "mage"
    assert settings.persona.presets_file == str(presets_file)
    assert settings.memory.buffer_size == 16
    assert settings.memory.history_path == str(history_path)


def test_config_file_only(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_file = tmp_path / "kitsu.yaml"
    config_file.write_text(
        textwrap.dedent(
            """
            version: 1
            policy:
              backend: local
              local:
                engine: transformers
                model_path: /models/llama2
            memory:
              buffer_size: 12
              summary_interval: 3
            """
        ).strip()
    )

    monkeypatch.setenv("KITSU_CONFIG_FILE", str(config_file))
    monkeypatch.delenv("POLICY_BACKEND", raising=False)
    monkeypatch.delenv("PERSONA_DEFAULT", raising=False)

    settings = reload_app_config()

    assert settings.policy.backend == "local"
    assert settings.policy.local.model_path == "/models/llama2"
    assert settings.memory.buffer_size == 12
    assert settings.memory.summary_interval == 3
