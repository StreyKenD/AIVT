from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import logging
import os
import signal
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse
from typing import Callable, Dict, Iterable, List, Optional

import httpx

from libs.config import get_app_config

from .utils import (
    combine_predicates,
    ollama_binary_predicate,
    ollama_reachability_predicate,
    port_predicate,
)


logger = logging.getLogger("kitsu.pipeline")


@dataclass(slots=True)
class ServiceSpec:
    name: str
    command: List[str]
    restart: bool = True
    restart_delay: float = 5.0
    env_overrides: Dict[str, str] = field(default_factory=dict)
    predicate: Optional[Callable[[], tuple[bool, Optional[str]]]] = None
    health_check: Optional["HealthCheckSpec"] = None


@dataclass(slots=True)
class HealthCheckSpec:
    url: str
    interval: float = 15.0
    timeout: float = 5.0
    retries: int = 3


async def _pipe_stream(
    service: str,
    stream: asyncio.StreamReader | None,
    level: int,
) -> None:
    if stream is None:
        return
    try:
        while True:
            line = await stream.readline()
            if not line:
                break
            logger.log(level, "[%s] %s", service, line.decode(errors="replace").rstrip())
    except asyncio.CancelledError:  # pragma: no cover - shutdown path
        pass


async def _monitor_health(
    service: str,
    spec: HealthCheckSpec,
    process: asyncio.subprocess.Process,
    stop_event: asyncio.Event,
) -> None:
    await asyncio.sleep(spec.interval)
    failures = 0
    async with httpx.AsyncClient(timeout=spec.timeout) as client:
        while not stop_event.is_set():
            if process.returncode is not None:
                break
            try:
                response = await client.get(spec.url)
                if response.status_code >= 500:
                    raise RuntimeError(f"HTTP {response.status_code}")
                failures = 0
            except Exception as exc:  # pragma: no cover - network guard
                failures += 1
                logger.warning(
                    "%s health check failed (%s/%s): %s",
                    service,
                    failures,
                    spec.retries,
                    exc,
                )
                if failures >= spec.retries:
                    logger.error(
                        "%s deemed unhealthy after %s failures; terminating process",
                        service,
                        failures,
                    )
                    with contextlib.suppress(ProcessLookupError):
                        process.terminate()
                    break
            else:
                await asyncio.sleep(spec.interval)
                continue
            await asyncio.sleep(spec.interval)


async def _run_service(
    spec: ServiceSpec,
    base_env: Dict[str, str],
    stop_event: asyncio.Event,
) -> None:
    if spec.predicate is not None:
        try:
            should_start, reason = spec.predicate()
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.error("Skipping %s: predicate failed (%s)", spec.name, exc)
            return
        if not should_start:
            if reason:
                logger.warning("Skipping %s: %s", spec.name, reason)
            else:
                logger.info("Skipping %s (predicate declined start)", spec.name)
            return
    attempt = 0
    env = base_env.copy()
    env.update(spec.env_overrides)

    while not stop_event.is_set():
        attempt += 1
        logger.info("Starting %s (attempt %d)", spec.name, attempt)
        try:
            process = await asyncio.create_subprocess_exec(
                *spec.command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            logger.debug(
                "%s spawned pid=%s command=%s env_overrides=%s",
                spec.name,
                process.pid,
                spec.command,
                spec.env_overrides or {},
            )
        except FileNotFoundError as exc:  # pragma: no cover - configuration error
            logger.error("Unable to start %s: %s", spec.name, exc)
            return

        stdout_task = asyncio.create_task(_pipe_stream(spec.name, process.stdout, logging.INFO))
        stderr_task = asyncio.create_task(_pipe_stream(spec.name, process.stderr, logging.ERROR))
        health_task = None
        if spec.health_check is not None:
            health_task = asyncio.create_task(
                _monitor_health(spec.name, spec.health_check, process, stop_event),
                name=f"health:{spec.name}",
            )
        wait_process = asyncio.create_task(process.wait())
        wait_stop = asyncio.create_task(stop_event.wait())

        done, pending = await asyncio.wait(
            {wait_process, wait_stop},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

        if stop_event.is_set():
            logger.info("Stopping %s...", spec.name)
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=10.0)
            except (asyncio.TimeoutError, ProcessLookupError):
                logger.warning("%s did not exit after terminate; killing", spec.name)
                with contextlib.suppress(ProcessLookupError):
                    process.kill()
                    await process.wait()
            await asyncio.gather(
                *(task for task in (stdout_task, stderr_task, health_task) if task),
                return_exceptions=True,
            )
            break

        returncode = process.returncode
        await asyncio.gather(
            *(task for task in (stdout_task, stderr_task, health_task) if task),
            return_exceptions=True,
        )
        logger.info("%s exited with code %s", spec.name, returncode)

        if not spec.restart or returncode == 0:
            break
        logger.warning(
            "%s crashed (code %s); restarting in %.1fs (next attempt %d)",
            spec.name,
            returncode,
            spec.restart_delay,
            attempt + 1,
        )
        await asyncio.sleep(spec.restart_delay)

    # cancel the pipe readers if still running
    for task in (stdout_task, stderr_task):
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


def _disabled_services() -> set[str]:
    base = os.getenv("PIPELINE_DISABLE", "")
    disabled = {name.strip().lower() for name in base.split(",") if name.strip()}

    prefix = "PIPELINE_DISABLE_"
    for key, raw_value in os.environ.items():
        if not key.startswith(prefix):
            continue
        service = key[len(prefix) :].strip().lower()
        if not service:
            continue
        value = (raw_value or "").strip().lower()
        if not value or value not in {"0", "false", "no", "off"}:
            disabled.add(service)
    return disabled


def _require_env(vars_needed: List[str]) -> tuple[bool, Optional[str]]:
    missing = [name for name in vars_needed if not os.getenv(name)]
    if missing:
        return False, f"missing env vars: {', '.join(missing)}"
    return True, None


def _ollama_autostart_enabled() -> bool:
    value = os.getenv("OLLAMA_AUTOSTART", "1")
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _ollama_host_port(ollama_url: str) -> tuple[str, int]:
    parsed = urlparse(ollama_url)
    host = parsed.hostname or "127.0.0.1"
    if parsed.port is not None:
        return host, parsed.port
    return host, 11434


def _is_local_host(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        normalized = host.lower()
        return normalized in {"localhost"} or normalized.startswith("127.")


def _health_host(host: str) -> str:
    normalized = host.strip().lower()
    if normalized in {"0.0.0.0", "::", ""}:
        return "127.0.0.1"
    return host


def _service_specs(python: str) -> Iterable[ServiceSpec]:
    settings = get_app_config()
    orch_cfg = settings.orchestrator
    policy_cfg = settings.policy
    tts_cfg = settings.tts

    orch_host = os.getenv("ORCH_HOST", orch_cfg.bind_host)
    orch_port = os.getenv("ORCH_PORT", str(orch_cfg.bind_port))
    orch_port_int = int(orch_port)
    control_host = os.getenv("CONTROL_PANEL_HOST", "127.0.0.1")
    control_port = os.getenv("CONTROL_PANEL_PORT", "8100")
    control_port_int = int(control_port)
    policy_host = os.getenv("POLICY_HOST", policy_cfg.bind_host)
    policy_port = int(os.getenv("POLICY_PORT", str(policy_cfg.bind_port)))
    tts_host = os.getenv("TTS_HOST", tts_cfg.bind_host)
    tts_port = int(os.getenv("TTS_PORT", str(tts_cfg.bind_port)))
    ollama_url = os.getenv("OLLAMA_URL", policy_cfg.ollama_url)
    ollama_host, ollama_port = _ollama_host_port(ollama_url)
    ollama_autostart = _ollama_autostart_enabled()

    specs: List[ServiceSpec] = []

    if ollama_autostart:
        if _is_local_host(ollama_host):
            specs.append(
                ServiceSpec(
                    name="ollama",
                    command=["ollama", "serve"],
                    predicate=combine_predicates(
                        (
                            ollama_binary_predicate(),
                            port_predicate(ollama_host, ollama_port),
                        )
                    ),
                    restart=True,
                    restart_delay=5.0,
                    env_overrides={
                        "OLLAMA_HOST": ollama_host,
                        "OLLAMA_PORT": str(ollama_port),
                    },
                )
            )
        else:
            logger.info("Skipping Ollama autostart for non-local host %s", ollama_host)

    policy_predicates: List[Callable[[], tuple[bool, Optional[str]]]] = [
        port_predicate(policy_host, policy_port)
    ]
    if not (ollama_autostart and _is_local_host(ollama_host)):
        policy_predicates.append(ollama_reachability_predicate(ollama_url))

    specs.extend(
        [
            ServiceSpec(
                name="orchestrator",
                command=[
                    python,
                    "-m",
                    "uvicorn",
                    "apps.orchestrator.main:app",
                    "--host",
                    orch_host,
                    "--port",
                    orch_port,
                ],
                predicate=port_predicate(orch_host, orch_port_int),
                health_check=HealthCheckSpec(
                    url=f"http://{_health_host(orch_host)}:{orch_port_int}/health",
                    interval=20.0,
                    timeout=5.0,
                    retries=3,
                ),
            ),
            ServiceSpec(
                name="control_panel",
                command=[
                    python,
                    "-m",
                    "uvicorn",
                    "apps.control_panel_backend.main:app",
                    "--host",
                    control_host,
                    "--port",
                    control_port,
                ],
                predicate=port_predicate(control_host, control_port_int),
            ),
            ServiceSpec(
                name="policy_worker",
                command=[python, "-m", "apps.policy_worker.main"],
                predicate=combine_predicates(policy_predicates),
                health_check=HealthCheckSpec(
                    url=f"http://{_health_host(policy_host)}:{policy_port}/health",
                    interval=20.0,
                    timeout=5.0,
                    retries=3,
                ),
            ),
            ServiceSpec(
                name="asr_worker",
                command=[python, "-m", "apps.asr_worker.main"],
            ),
            ServiceSpec(
                name="tts_worker",
                command=[python, "-m", "apps.tts_worker.main"],
                predicate=port_predicate(tts_host, tts_port),
                health_check=HealthCheckSpec(
                    url=f"http://{_health_host(tts_host)}:{tts_port}/health",
                    interval=20.0,
                    timeout=5.0,
                    retries=3,
                ),
            ),
            ServiceSpec(
                name="avatar_controller",
                command=[python, "-m", "apps.avatar_controller.main"],
                predicate=lambda: _require_env(["VTS_URL", "VTS_AUTH_TOKEN"]),
            ),
            ServiceSpec(
                name="obs_controller",
                command=[python, "-m", "apps.obs_controller.main"],
                predicate=lambda: _require_env(["OBS_WS_URL", "OBS_WS_PASSWORD"]),
            ),
            ServiceSpec(
                name="twitch_ingest",
                command=[python, "-m", "apps.twitch_ingest.main"],
                predicate=lambda: _require_env(["TWITCH_OAUTH_TOKEN", "TWITCH_CHANNEL"]),
            ),
        ]
    )

    return specs


async def run_pipeline() -> None:
    base_env = os.environ.copy()
    log_root_value = base_env.get("KITSU_LOG_ROOT")
    if log_root_value:
        log_root_path = Path(log_root_value)
    else:
        log_root_path = Path("logs")
    if not log_root_path.is_absolute():
        log_root_path = (Path.cwd() / log_root_path).resolve()
    base_env["KITSU_LOG_ROOT"] = str(log_root_path)

    python = sys.executable
    disabled = _disabled_services()
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop_event.set)
            except NotImplementedError:  # pragma: no cover - Windows fallback
                pass
    except RuntimeError:
        # In some embedded contexts signal handlers cannot be registered.
        pass

    specs = [spec for spec in _service_specs(python) if spec.name.lower() not in disabled]
    if not specs:
        logger.warning("No services selected; exiting.")
        return

    tasks = [
        asyncio.create_task(_run_service(spec, base_env, stop_event), name=f"svc:{spec.name}")
        for spec in specs
    ]

    logger.info("Pipeline runner started with services: %s", ", ".join(spec.name for spec in specs))

    try:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for spec, result in zip(specs, results):
            if isinstance(result, Exception):
                logger.debug("Service %s finished with %r", spec.name, result)
    finally:
        stop_event.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("Pipeline runner stopped.")


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    try:
        await run_pipeline()
    except KeyboardInterrupt:  # pragma: no cover - interactive use
        logger.info("Pipeline interrupted by user")


if __name__ == "__main__":
    asyncio.run(main())
