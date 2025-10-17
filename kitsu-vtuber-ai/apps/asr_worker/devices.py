from __future__ import annotations

import argparse
import json
import contextlib
from dataclasses import asdict, dataclass
from typing import Iterable, List, Optional, Sequence

from .utils import load_module_if_available


@dataclass
class DeviceEntry:
    backend: str
    identifier: str
    name: str
    channels: int
    host: Optional[str]
    is_default: bool


def _safe_query_sounddevice(sounddevice: object) -> Iterable[DeviceEntry]:
    query_devices = getattr(sounddevice, "query_devices", None)
    if query_devices is None:
        return []
    devices = list(query_devices())
    hostapis: Sequence[dict] = []
    query_hostapis = getattr(sounddevice, "query_hostapis", None)
    if callable(query_hostapis):
        with contextlib.suppress(Exception):
            hostapis = list(query_hostapis())  # type: ignore[assignment]
    default_input_index: Optional[int] = None
    default = getattr(sounddevice, "default", None)
    if default is not None:
        device_tuple = getattr(default, "device", None)
        if isinstance(device_tuple, Sequence) and device_tuple:
            candidate = device_tuple[0]
            if isinstance(candidate, int):
                default_input_index = candidate

    entries: list[DeviceEntry] = []
    for index, device in enumerate(devices):
        channels = int(device.get("max_input_channels", 0))
        if channels <= 0:
            continue
        host_label: Optional[str] = None
        host_idx = device.get("hostapi")
        if host_idx is not None and 0 <= int(host_idx) < len(hostapis):
            host_label = str(hostapis[int(host_idx)].get("name", host_idx))
        entries.append(
            DeviceEntry(
                backend="sounddevice",
                identifier=str(index),
                name=str(device.get("name", index)),
                channels=channels,
                host=host_label,
                is_default=default_input_index == index,
            )
        )
    return entries


def _safe_query_pyaudio(pyaudio: object) -> Iterable[DeviceEntry]:
    PyAudio = getattr(pyaudio, "PyAudio", None)
    if PyAudio is None:
        return []
    instance = PyAudio()
    entries: list[DeviceEntry] = []
    default_index: Optional[int] = None
    get_default_info = getattr(instance, "get_default_input_device_info", None)
    if callable(get_default_info):
        with contextlib.suppress(Exception):
            default_info = get_default_info()
            default_index = (
                int(default_info.get("index")) if "index" in default_info else None
            )
    try:
        get_count = getattr(instance, "get_device_count", None)
        if not callable(get_count):
            return []
        count = int(get_count())
        for index in range(count):
            info = instance.get_device_info_by_index(index)  # type: ignore[attr-defined]
            channels = int(info.get("maxInputChannels", 0))
            if channels <= 0:
                continue
            entries.append(
                DeviceEntry(
                    backend="pyaudio",
                    identifier=str(index),
                    name=str(info.get("name", index)),
                    channels=channels,
                    host=str(info.get("hostApi", "")),
                    is_default=default_index == index,
                )
            )
    finally:
        close = getattr(instance, "terminate", None)
        if callable(close):
            with contextlib.suppress(Exception):
                close()
    return entries


def gather_devices(
    *,
    sounddevice: Optional[object] = None,
    pyaudio: Optional[object] = None,
) -> List[DeviceEntry]:
    """Collect available audio input devices from optional backends."""

    entries: list[DeviceEntry] = []
    sd_module = (
        sounddevice
        if sounddevice is not None
        else load_module_if_available("sounddevice")
    )
    if sd_module is not None:
        with contextlib.suppress(Exception):
            entries.extend(_safe_query_sounddevice(sd_module))

    pa_module = pyaudio if pyaudio is not None else load_module_if_available("pyaudio")
    if pa_module is not None:
        with contextlib.suppress(Exception):
            entries.extend(_safe_query_pyaudio(pa_module))

    entries.sort(key=lambda item: (item.backend, item.name.lower()))
    return entries


def _format_table(entries: Sequence[DeviceEntry]) -> str:
    if not entries:
        return "No input devices were found."
    headers = ("Backend", "Identifier", "Name", "Channels", "Host", "Default")
    rows = [headers]
    for entry in entries:
        rows.append(
            (
                entry.backend,
                entry.identifier,
                entry.name,
                str(entry.channels),
                entry.host or "-",
                "✔" if entry.is_default else "",
            )
        )
    widths = [max(len(row[col]) for row in rows) for col in range(len(headers))]
    lines = []
    for row in rows:
        padded = [value.ljust(width) for value, width in zip(row, widths)]
        lines.append("  ".join(padded))
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="List the audio devices available to the ASR worker.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Show the result in JSON (UTF-8).",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    entries = gather_devices()
    if args.json:
        print(
            json.dumps(
                [asdict(entry) for entry in entries], ensure_ascii=False, indent=2
            )
        )
    else:
        print(_format_table(entries))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI
    import sys

    raise SystemExit(main(sys.argv[1:]))
