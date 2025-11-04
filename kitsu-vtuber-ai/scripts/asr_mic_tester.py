from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import sys
from pathlib import Path
from typing import Iterator

from apps.asr_worker.audio import MicrophoneStream
from apps.asr_worker.config import load_config
from apps.asr_worker.pipeline import SimpleASRPipeline
from apps.asr_worker.transcription import build_transcriber


@contextlib.contextmanager
def _tee_stdout_from_env() -> Iterator[None]:
    destination = os.getenv("MIC_TEST_OUTPUT")
    if not destination:
        yield None
        return

    try:
        path = Path(destination).expanduser()
        parent = path.parent
        if parent and not parent.exists():
            parent.mkdir(parents=True, exist_ok=True)
        handle = path.open("a", encoding="utf-8")
    except Exception as exc:
        print(
            f"[mic-test] Failed to open MIC_TEST_OUTPUT file '{destination}': {exc}",
            file=sys.stderr,
        )
        yield None
        return

    original = sys.stdout

    class _StdoutTee:
        def __init__(self, primary, secondary) -> None:
            self._primary = primary
            self._secondary = secondary

        def write(self, data: str) -> int:
            written = self._primary.write(data)
            self._secondary.write(data)
            if written is None:
                written = len(data)
            return written

        def flush(self) -> None:
            self._primary.flush()
            self._secondary.flush()

        def writelines(self, lines) -> None:
            for line in lines:
                self.write(line)

        def isatty(self) -> bool:
            primary_isatty = getattr(self._primary, "isatty", None)
            if callable(primary_isatty):
                return primary_isatty()
            return False

        @property
        def encoding(self) -> str:
            return getattr(self._primary, "encoding", "utf-8")

        @property
        def closed(self) -> bool:
            primary_closed = getattr(self._primary, "closed", None)
            if isinstance(primary_closed, bool):
                return primary_closed
            return False

        def __getattr__(self, item):
            return getattr(self._primary, item)

    sys.stdout = _StdoutTee(original, handle)
    print(f"[mic-test] Duplicating output to {path}", file=sys.stderr)
    try:
        yield None
    finally:
        sys.stdout = original
        handle.flush()
        handle.close()


async def _capture_loop(stop_event: asyncio.Event) -> None:
    config = load_config()

    try:
        transcriber = build_transcriber(config)
    except Exception as exc:  # pragma: no cover - startup guard
        print(f"[mic-test] Failed to initialise ASR model: {exc}", file=sys.stderr)
        raise

    pipeline = SimpleASRPipeline(config, transcriber)

    try:
        while not stop_event.is_set():
            try:
                async with MicrophoneStream(config) as source:
                    print(
                        "[mic-test] Listening... press Ctrl+C to stop.",
                        flush=True,
                    )
                    pipeline_task = asyncio.create_task(pipeline.run(source.frames()))
                    stop_task = asyncio.create_task(stop_event.wait())
                    done, pending = await asyncio.wait(
                        {pipeline_task, stop_task},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    for task in pending:
                        task.cancel()
                    if stop_task in done:
                        pipeline_task.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await pipeline_task
                        break
                    if (exc := pipeline_task.exception()) is not None:
                        raise exc
                    print("[mic-test] Stream ended; restarting...", file=sys.stderr)
            except asyncio.CancelledError:
                raise
            except (RuntimeError, OSError, ValueError) as exc:
                print(f"[mic-test] Fatal audio error: {exc}", file=sys.stderr)
                stop_event.set()
                return
            except Exception as exc:
                print(f"[mic-test] Error: {exc}", file=sys.stderr)
                await asyncio.sleep(0.5)
    finally:
        await asyncio.sleep(0)


async def _main() -> None:
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _handle_stop(*_args: object) -> None:
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_stop)
        except NotImplementedError:
            pass

    with _tee_stdout_from_env():
        try:
            await _capture_loop(stop_event)
        finally:
            stop_event.set()


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:  # pragma: no cover - interactive
        print("\n[mic-test] stopped by user.")
