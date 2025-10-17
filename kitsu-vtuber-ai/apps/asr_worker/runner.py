from __future__ import annotations

import asyncio
import sys

from .audio import MicrophoneStream
from .config import load_config
from .logger import logger
from .metrics import create_telemetry
from .orchestrator import OrchestratorClient
from .pipeline import SimpleASRPipeline
from .transcription import build_transcriber


async def run() -> None:
    config = load_config()
    orchestrator = OrchestratorClient(config.orchestrator_url)
    telemetry = create_telemetry()
    try:
        transcriber = build_transcriber(config)
        pipeline = SimpleASRPipeline(
            config,
            transcriber,
            orchestrator=orchestrator,
            telemetry=telemetry,
        )
        logger.info(
            "ASR worker ready (model=%s, sample_rate=%sHz, frame_ms=%s, partial_interval_ms=%s)",
            config.model_name,
            config.sample_rate,
            config.frame_duration_ms,
            config.partial_interval_ms,
        )
        while True:
            try:
                async with MicrophoneStream(config) as source:
                    await pipeline.run(source.frames())
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("ASR worker crashed")
                await asyncio.sleep(1)
            else:
                logger.warning("Audio stream finished; restarting after short delay")
                await asyncio.sleep(0.5)
    finally:
        await telemetry.aclose()
        await orchestrator.aclose()


async def run_worker() -> None:
    """Backward-compatible entry point for existing callers/tests."""

    await run()


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\n[ASR] stopped by user", file=sys.stderr)


if __name__ == "__main__":
    main()
