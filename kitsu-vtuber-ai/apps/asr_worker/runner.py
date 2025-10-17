from __future__ import annotations

import asyncio
import sys
from contextlib import asynccontextmanager
from typing import AsyncIterator

from .audio import MicrophoneStream
from .config import ASRConfig, load_config
from .logger import logger
from .metrics import create_telemetry
from .orchestrator import OrchestratorClient
from .pipeline import SimpleASRPipeline
from .transcription import build_transcriber
from .vad import PassthroughVAD, build_vad


SpeechPipeline = SimpleASRPipeline


@asynccontextmanager
async def acquire_audio_source(config: ASRConfig) -> AsyncIterator[MicrophoneStream]:
    async with MicrophoneStream(config) as source:
        yield source


async def run(config: ASRConfig | None = None) -> None:
    config = config or load_config()
    orchestrator = OrchestratorClient(config.orchestrator_url)
    telemetry = create_telemetry()
    attempt = 0
    backoff = 1.0
    try:
        transcriber = build_transcriber(config)
        while True:
            attempt += 1
            current_backoff = backoff
            try:
                vad = build_vad(config)
            except Exception as exc:
                logger.exception("ASR worker failed to initialise VAD: %s", exc)
                logger.warning(
                    "Falling back to passthrough VAD. Set ASR_VAD=none to disable VAD explicitly."
                )
                vad = PassthroughVAD(config.frame_bytes)

            pipeline = SpeechPipeline(
                config=config,
                transcriber=transcriber,
                vad=vad,
                orchestrator=orchestrator,
                telemetry=telemetry,
            )

            if attempt == 1:
                logger.info(
                    (
                        "Starting ASR worker with model=%s, sample_rate=%s Hz, frame_ms=%s, "
                        "partial_interval_ms=%s, vad=%s"
                    ),
                    config.model_name,
                    config.sample_rate,
                    config.frame_duration_ms,
                    config.partial_interval_ms,
                    vad.__class__.__name__,
                )
            else:
                logger.warning(
                    "ASR worker restarting audio capture (attempt %d, backoff %.1fs)",
                    attempt,
                    current_backoff,
                )

            await telemetry.cycle_started(attempt, current_backoff)

            try:
                async with acquire_audio_source(config) as source:
                    await pipeline.process(source.frames())
                logger.warning("Audio frame stream ended; restarting capture loop")
                await telemetry.cycle_completed(attempt, "stream_end")
            except asyncio.CancelledError:
                current_task = asyncio.current_task()
                if current_task is not None and current_task.cancelled():
                    raise
                logger.warning(
                    "ASR capture loop cancelled unexpectedly on attempt %d; retrying",
                    attempt,
                    exc_info=True,
                )
                await telemetry.cycle_completed(attempt, "cancelled")
            except Exception as exc:
                logger.exception("ASR worker capture loop failed: %s", exc)
                await telemetry.cycle_completed(attempt, "error", detail=type(exc).__name__)

            await asyncio.sleep(current_backoff)
            backoff = min(current_backoff * 2, 30.0)
    finally:
        await telemetry.aclose()
        await orchestrator.aclose()


async def run_worker(config: ASRConfig | None = None) -> None:
    """Backward-compatible entry point for existing callers/tests."""

    await run(config)


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\n[ASR] stopped by user", file=sys.stderr)


if __name__ == "__main__":
    main()
