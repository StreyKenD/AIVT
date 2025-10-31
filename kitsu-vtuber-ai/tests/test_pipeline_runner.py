from __future__ import annotations

import asyncio
import importlib
import sys
import textwrap
from pathlib import Path
from typing import List

import pytest

runner = importlib.import_module("apps.pipeline_runner.main")
ServiceSpec = runner.ServiceSpec
from libs.config import reload_app_config


def _write_minimal_config(tmp_path: Path) -> Path:
    config_file = tmp_path / "kitsu.yaml"
    config_file.write_text(
        textwrap.dedent(
            """
            version: 1
            orchestrator:
              bind_host: 127.0.0.1
              bind_port: 9000
            policy:
              bind_host: 127.0.0.1
              bind_port: 9100
              ollama_url: http://127.0.0.1:11434
            tts:
              bind_host: 127.0.0.1
              bind_port: 9200
            """
        ).strip()
    )
    return config_file


def test_service_specs_build_from_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_file = _write_minimal_config(tmp_path)
    monkeypatch.setenv("KITSU_CONFIG_FILE", str(config_file))
    monkeypatch.setenv("OLLAMA_AUTOSTART", "0")  # avoid spawning ollama in specs
    reload_app_config()

    monkeypatch.setattr(runner, "_is_port_available", lambda host, port: True)
    monkeypatch.setattr(runner, "_ollama_reachability_predicate", lambda url: (lambda: (True, None)))

    specs = list(runner._service_specs(sys.executable))
    names = [spec.name for spec in specs]

    expected = {
        "orchestrator",
        "control_panel",
        "policy_worker",
        "asr_worker",
        "tts_worker",
        "avatar_controller",
        "obs_controller",
        "twitch_ingest",
    }
    assert expected.issubset(set(names))

    orchestrator_spec = next(spec for spec in specs if spec.name == "orchestrator")
    assert orchestrator_spec.command[:3] == [
        sys.executable,
        "-m",
        "uvicorn",
    ]
    assert orchestrator_spec.command[3] == "apps.orchestrator.main:app"
    assert orchestrator_spec.health_check is not None
    assert orchestrator_spec.health_check.url.endswith("/health")


@pytest.mark.asyncio
async def test_run_pipeline_honours_disabled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: List[tuple[str, str]] = []

    specs = [
        ServiceSpec(name="svc_one", command=["python", "-c", "print('one')"]),
        ServiceSpec(name="svc_two", command=["python", "-c", "print('two')"]),
    ]

    monkeypatch.setenv("PIPELINE_DISABLE", "svc_two")
    monkeypatch.setenv("KITSU_LOG_ROOT", str(tmp_path / "logs"))

    async def fake_run_service(
        spec: ServiceSpec,
        env: dict[str, str],
        stop_event: asyncio.Event,
    ) -> None:
        calls.append((spec.name, env["KITSU_LOG_ROOT"]))
        stop_event.set()

    monkeypatch.setattr(runner, "_service_specs", lambda python: specs)
    monkeypatch.setattr(runner, "_run_service", fake_run_service)

    await runner.run_pipeline()

    assert calls == [("svc_one", str((tmp_path / "logs").resolve()))]
