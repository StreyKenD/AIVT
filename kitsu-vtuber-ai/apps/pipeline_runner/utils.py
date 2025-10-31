from __future__ import annotations

import os
import shutil
import socket
from typing import Callable, Iterable, Optional
from urllib.parse import urlparse


Predicate = Callable[[], tuple[bool, Optional[str]]]


def is_port_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def port_predicate(host: str, port: int) -> Predicate:
    def _predicate() -> tuple[bool, Optional[str]]:
        available = is_port_available(host, port)
        if not available:
            return False, f"port {host}:{port} already in use"
        return True, None

    return _predicate


def ollama_reachability_predicate(ollama_url: str) -> Predicate:
    skip = os.getenv("PIPELINE_SKIP_OLLAMA_CHECK", "0").lower() in {"1", "true", "yes"}
    if skip:
        return lambda: (True, None)
    parsed = urlparse(ollama_url)
    scheme = parsed.scheme or "http"
    host = parsed.hostname
    if not host:
        return lambda: (False, f"invalid OLLAMA_URL: {ollama_url}")
    port = parsed.port or (443 if scheme == "https" else 80)

    def _predicate() -> tuple[bool, Optional[str]]:
        try:
            with socket.create_connection((host, port), timeout=1.5):
                return True, None
        except OSError as exc:
            return False, f"ollama unreachable at {host}:{port} ({exc})"

    return _predicate


def ollama_binary_predicate() -> Predicate:
    def _predicate() -> tuple[bool, Optional[str]]:
        if shutil.which("ollama"):
            return True, None
        return False, "ollama executable not found in PATH"

    return _predicate


def combine_predicates(predicates: Iterable[Predicate]) -> Predicate:
    checks = list(predicates)

    def _predicate() -> tuple[bool, Optional[str]]:
        for check in checks:
            ok, reason = check()
            if not ok:
                return ok, reason
        return True, None

    return _predicate


__all__ = [
    "Predicate",
    "combine_predicates",
    "is_port_available",
    "ollama_binary_predicate",
    "ollama_reachability_predicate",
    "port_predicate",
]
