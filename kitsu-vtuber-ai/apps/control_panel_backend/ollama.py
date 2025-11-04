from __future__ import annotations

import asyncio
import asyncio.subprocess  # noqa: F401  (ensures asyncio.subprocess.DEVNULL is available)
import contextlib
import ipaddress
import logging
import os
from typing import Any, Optional
from urllib.parse import urlparse

import httpx

logger = logging.getLogger("kitsu.control_panel.ollama")

_DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
_PROBE_TIMEOUT = httpx.Timeout(2.5, connect=1.0)
_POLL_INTERVAL = 0.5


def parse_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if not normalized:
        return default
    return normalized not in {"0", "false", "no", "off"}


def _is_local_host(host: str) -> bool:
    candidate = host.strip() or "127.0.0.1"
    try:
        return ipaddress.ip_address(candidate).is_loopback
    except ValueError:
        lowered = candidate.lower()
        return lowered in {"localhost"} or lowered.startswith("127.")


class OllamaSupervisor:
    """Manages the lifecycle and status probing of a local Ollama daemon."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        autostart: bool = True,
    ) -> None:
        self._base_url = (base_url or _DEFAULT_OLLAMA_URL).rstrip("/")
        parsed = urlparse(self._base_url)
        self._host = parsed.hostname or "127.0.0.1"
        self._port = parsed.port or (443 if parsed.scheme == "https" else 11434)
        self._autostart = autostart
        self._is_local = _is_local_host(self._host)
        self._proc: asyncio.subprocess.Process | None = None
        self._status: str = "unknown"
        self._last_error: Optional[str] = None
        self._lock = asyncio.Lock()

    @property
    def can_manage(self) -> bool:
        return self._is_local

    @property
    def manages_process(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    async def startup(self) -> None:
        if not self._autostart:
            await self.refresh_status()
            return
        try:
            await self.ensure_started()
        except FileNotFoundError:
            self._last_error = "ollama executable not found in PATH"
            logger.warning(self._last_error)
        except Exception as exc:  # pragma: no cover - defensive guard
            self._last_error = str(exc)
            logger.warning("Ollama autostart failed: %s", exc)
        finally:
            if self._status == "unknown":
                await self.refresh_status()

    async def ensure_started(self, *, force: bool = False) -> None:
        async with self._lock:
            if not (self._autostart or force):
                await self.refresh_status()
                return
            if not self._is_local:
                if force:
                    raise RuntimeError("Cannot start Ollama on a remote host")
                await self.refresh_status()
                return
            if self._proc and self._proc.returncode is None:
                await self.refresh_status()
                return
            if await self._probe():
                self._status = "online"
                return
            await self._spawn_process()
        await self._wait_until_ready()

    async def refresh_status(self) -> str:
        is_online = await self._probe()
        self._status = "online" if is_online else "offline"
        return self._status

    async def status(self) -> dict[str, Any]:
        await self.refresh_status()
        return {
            "backend": "ollama",
            "url": self._base_url,
            "status": self._status,
            "autostart": self._autostart and self._is_local,
            "is_local": self._is_local,
            "managed": self.manages_process,
            "host": self._host,
            "port": self._port,
            "pid": self._proc.pid if self.manages_process else None,
            "last_error": self._last_error,
        }

    async def shutdown(self) -> None:
        async with self._lock:
            proc = self._proc
            self._proc = None
        if proc is None:
            return
        if proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()
                await proc.wait()
        self._status = "offline"

    async def _wait_until_ready(self, timeout: float = 30.0) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            proc = self._proc
            if proc is not None and proc.returncode is not None:
                self._status = "offline"
                self._last_error = f"ollama exited with code {proc.returncode}"
                return
            if await self._probe():
                self._status = "online"
                self._last_error = None
                return
            await asyncio.sleep(_POLL_INTERVAL)
        self._status = "offline"
        self._last_error = "Timed out waiting for Ollama to come online"

    async def _probe(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT) as client:
                response = await client.get(f"{self._base_url}/api/version")
                response.raise_for_status()
            self._last_error = None
            return True
        except Exception as exc:  # pragma: no cover - network guard
            self._last_error = str(exc)
            return False

    async def _spawn_process(self) -> None:
        env = os.environ.copy()
        env.setdefault("OLLAMA_HOST", self._host)
        env.setdefault("OLLAMA_PORT", str(self._port))
        self._proc = await asyncio.create_subprocess_exec(
            "ollama",
            "serve",
            env=env,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )


__all__ = ["OllamaSupervisor", "parse_bool"]
