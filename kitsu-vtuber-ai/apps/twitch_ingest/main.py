from __future__ import annotations

import asyncio
import logging
import os
import random
from dataclasses import dataclass
from typing import Callable, Dict

try:
    from twitchio.ext import commands
except ImportError:  # pragma: no cover - optional dependency
    commands = None  # type: ignore

logger = logging.getLogger("kitsu.twitch")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))


@dataclass
class ChatEvent:
    author: str
    message: str


class TwitchStub:
    def __init__(self) -> None:
        self.handlers: Dict[str, Callable[[ChatEvent], None]] = {}

    def register_command(self, command: str, handler: Callable[[ChatEvent], None]) -> None:
        self.handlers[command] = handler

    async def emit(self, message: str) -> None:
        if not message.startswith("!"):
            return
        command, *rest = message.split()
        handler = self.handlers.get(command)
        if handler:
            handler(ChatEvent(author="chat", message=" ".join(rest)))

    async def run(self) -> None:
        commands_list = ["!mute", "!style kawaii", "!style chaos", "!scene gameplay"]
        while True:
            await self.emit(random.choice(commands_list))
            await asyncio.sleep(3.0)


async def run_twitch_loop() -> None:
    if commands is None:
        logger.warning("twitchio not installed; using local stub")
    stub = TwitchStub()

    def mute_handler(event: ChatEvent) -> None:
        logger.info("[Twitch] Mute command received from %s", event.author)

    def style_handler(event: ChatEvent) -> None:
        logger.info("[Twitch] Style command payload=%s", event.message)

    def scene_handler(event: ChatEvent) -> None:
        logger.info("[Twitch] Scene command payload=%s", event.message)

    stub.register_command("!mute", mute_handler)
    stub.register_command("!style", style_handler)
    stub.register_command("!scene", scene_handler)
    await stub.run()


def main() -> None:
    logger.info("Twitch ingest starting (simulated)")
    try:
        asyncio.run(run_twitch_loop())
    except KeyboardInterrupt:  # pragma: no cover
        logger.info("Twitch ingest stopped")


if __name__ == "__main__":
    main()
