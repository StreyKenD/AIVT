from __future__ import annotations

import asyncio
import sys
from contextlib import asynccontextmanager
from typing import AsyncIterator

from libs.monitoring.resource import ResourceMonitor

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
    resource_monitor = ResourceMonitor(
        cpu_threshold=config.resource_cpu_threshold_pct,
        gpu_threshold=config.resource_gpu_threshold_pct,
        sample_interval=config.resource_check_interval_seconds,
    )
    attempt = 1
    try:
        transcriber = build_transcriber(config)
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
            allow_non_english=config.allow_non_english,
            resource_monitor=resource_monitor,
        )

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

        await telemetry.cycle_started(attempt, 0.0)

        try:
            async with acquire_audio_source(config) as source:
                await pipeline.process(source.frames())
        except asyncio.CancelledError:
            await telemetry.cycle_completed(attempt, "cancelled")
            raise
        except Exception as exc:
            logger.exception("ASR worker capture loop failed: %s", exc)
            await telemetry.cycle_completed(
                attempt, "error", detail=type(exc).__name__
            )
            raise
        else:
            logger.warning(
                "ASR worker capture loop ended unexpectedly; requesting supervisor restart"
            )
            await telemetry.cycle_completed(attempt, "stream_end")
            raise RuntimeError("ASR audio stream ended unexpectedly")
    finally:
        resource_monitor.shutdown()
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
