import asyncio
import os
import sys
import platform
from dataclasses import dataclass
from typing import List, Tuple, Dict

"""
Lightweight supervisor for local development.
- Runs all services in parallel (single window).
- Prefixes logs with the service name.
- Supports Poetry (use the -UsePoetry flag).
- Closes everything with Ctrl+C (uses taskkill /T /F on Windows to terminate the process tree).

Usage:
  # without Poetry
  python scripts/dev_supervisor.py

  # with Poetry
  poetry run python scripts/dev_supervisor.py -UsePoetry

Useful env vars:
  ORCH_HOST=127.0.0.1
  ORCH_PORT=8000
"""

IS_WINDOWS = platform.system().lower().startswith("win")


@dataclass
class Service:
    name: str
    cmd: str


def build_services(use_poetry: bool) -> List[Service]:
    orch_host = os.getenv("ORCH_HOST", "127.0.0.1")
    orch_port = os.getenv("ORCH_PORT", "8000")

    services: List[Tuple[str, str]] = [
        (
            "orchestrator",
            f"uvicorn apps.orchestrator.main:app --reload --host {orch_host} --port {orch_port}",
        ),
        ("control_panel", "uvicorn apps.control_panel_backend.main:app --reload"),
        ("asr_worker", "python -m apps.asr_worker.main"),
        ("policy_worker", "python -m apps.policy_worker.main"),
        ("tts_worker", "python -m apps.tts_worker.main"),
        ("avatar_controller", "python -m apps.avatar_controller.main"),
        ("obs_controller", "python -m apps.obs_controller.main"),
        ("twitch_ingest", "python -m apps.twitch_ingest.main"),
    ]
    if use_poetry:
        services = [(n, f"poetry run {c}") for n, c in services]
    return [Service(n, c) for n, c in services]


async def run_service(
    svc: Service, cwd: str, procs: Dict[str, asyncio.subprocess.Process]
):
    # shell=True to interpret the full command with pipes/redirection when needed
    proc = await asyncio.create_subprocess_shell(
        svc.cmd,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    procs[svc.name] = proc
    print(f"[SUP] {svc.name} started (pid={proc.pid})")
    assert proc.stdout is not None
    try:
        async for line in proc.stdout:
            try:
                text = line.decode(errors="replace").rstrip()
            except Exception:
                text = str(line)
            print(f"[{svc.name}] {text}")
    except asyncio.CancelledError:
        # handled during shutdown
        pass
    finally:
        rc = await proc.wait()
        print(f"[SUP] {svc.name} exited code={rc}")


async def main():
    use_poetry = "-UsePoetry" in sys.argv
    repo_root = os.path.realpath(os.path.join(os.path.dirname(__file__), ".."))
    os.chdir(repo_root)

    services = build_services(use_poetry)
    procs: Dict[str, asyncio.subprocess.Process] = {}

    # create tasks for each service
    tasks = [asyncio.create_task(run_service(s, repo_root, procs)) for s in services]
    print("[SUP] launching services...")
    print("[SUP] working dir:", repo_root)
    print("[SUP] Ctrl+C to stop all services")

    try:
        await asyncio.gather(*tasks)
    except KeyboardInterrupt:
        print("\n[SUP] interrupt received, shutting down...")
    finally:
        # attempt a clean shutdown
        await terminate_all(procs)


async def terminate_all(procs: Dict[str, asyncio.subprocess.Process]):
    if not procs:
        return
    # First try to terminate gracefully
    for name, p in procs.items():
        if p.returncode is None:
            try:
                if IS_WINDOWS:
                    # force kill the process tree on Windows
                    # /T kills child processes; /F forces termination
                    os.system(f"taskkill /PID {p.pid} /T /F >NUL 2>&1")
                else:
                    p.terminate()
            except Exception as e:
                print(f"[SUP] error terminate {name}: {e}")

    # Wait briefly
    await asyncio.sleep(0.5)

    # Ensure processes are gone
    for name, p in procs.items():
        if p.returncode is None:
            try:
                if IS_WINDOWS:
                    os.system(f"taskkill /PID {p.pid} /T /F >NUL 2>&1")
                else:
                    p.kill()
            except Exception as e:
                print(f"[SUP] error kill {name}: {e}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # fallback
        print("\n[SUP] interrupted (outer)")
