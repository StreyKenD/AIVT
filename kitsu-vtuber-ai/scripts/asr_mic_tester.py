from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import sys

from apps.asr_worker.audio import MicrophoneStream
from apps.asr_worker.config import load_config
from apps.asr_worker.pipeline import SimpleASRPipeline
from apps.asr_worker.transcription import build_transcriber


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

    try:
        await _capture_loop(stop_event)
    finally:
        stop_event.set()


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:  # pragma: no cover - interactive
        print("\n[mic-test] stopped by user.")


