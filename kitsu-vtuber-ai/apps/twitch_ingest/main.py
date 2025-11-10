from __future__ import annotations

# Twitch ingest bridge that relays chat commands to the orchestrator.

import asyncio
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Dict, Optional, Protocol

import httpx

from libs.common import configure_json_logging

try:  # pragma: no cover - optional dependency for real Twitch connectivity
    from twitchio.ext import commands
except ImportError:  # pragma: no cover - executed when dependency missing locally
    commands = None  # type: ignore


configure_json_logging("twitch_ingest")
logger = logging.getLogger("kitsu.twitch")


CommandHandler = Callable[["ChatMessage"], Awaitable[None]]


@dataclass(slots=True)
class ChatMessage:
    author: str
    content: str


class TwitchBridge(Protocol):
    async def toggle_tts(self, enabled: bool) -> None: ...

    async def update_persona(
        self, *, style: Optional[str], chaos: Optional[float], energy: Optional[float]
    ) -> None: ...

    async def set_scene(self, scene: str) -> None: ...

    async def emit_chat(self, role: str, text: str) -> None: ...


class RateLimiter:
    """Simple leaky bucket per command to keep Twitch spam in check."""

    def __init__(self, cooldown_seconds: float) -> None:
        self._cooldown = cooldown_seconds
        self._last_invocation: Dict[str, float] = {}

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        last = self._last_invocation.get(key)
        if last is not None and (now - last) < self._cooldown:
            return False
        self._last_invocation[key] = now
        return True


class OrchestratorBridge:
    """HTTP bridge responsible for invoking orchestrator actions."""

    def __init__(self, base_url: str, api_key: Optional[str] = None) -> None:
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"))
        if api_key:
            self._headers = {
                "X-API-Key": api_key,
                "Authorization": f"Bearer {api_key}",
            }
        else:
            self._headers = None

    async def toggle_tts(self, enabled: bool) -> None:
        await self._post("/toggle/tts_worker", {"enabled": enabled})

    async def update_persona(
        self, *, style: Optional[str], chaos: Optional[float], energy: Optional[float]
    ) -> None:
        payload: Dict[str, object] = {}
        if style is not None:
            payload["style"] = style
        if chaos is not None:
            payload["chaos_level"] = chaos
        if energy is not None:
            payload["energy"] = energy
        if payload:
            await self._post("/persona", payload)

    async def set_scene(self, scene: str) -> None:
        await self._post("/obs/scene", {"scene": scene})

    async def emit_chat(self, role: str, text: str) -> None:
        await self._post("/ingest/chat", {"role": role, "text": text})

    async def close(self) -> None:
        await self._client.aclose()

    async def _post(self, path: str, payload: Dict[str, object]) -> None:
        headers = self._headers
        try:
            await self._client.post(path, json=payload, headers=headers)
        except Exception as exc:  # pragma: no cover - network guard
            logger.warning("Failed to notify orchestrator %s: %s", path, exc)


class TwitchCommandRouter:
    """Parses Twitch commands and dispatches to orchestrator actions."""

    _STYLE_RE = re.compile(
        r"^(?P<style>\w+)(\s+(?P<chaos>\d+(?:\.\d+)?))?(\s+(?P<energy>\d+(?:\.\d+)?))?$"
    )

    def __init__(self, bridge: TwitchBridge, cooldown_seconds: float = 3.0) -> None:
        self._bridge: TwitchBridge = bridge
        self._handlers: Dict[str, CommandHandler] = {}
        self._rate_limiter = RateLimiter(cooldown_seconds)
        self._register_default_handlers()

    async def handle(self, message: ChatMessage) -> None:
        if not message.content.startswith("!"):
            await self._bridge.emit_chat("user", message.content)
            return
        command, *rest = message.content.split(maxsplit=1)
        handler = self._handlers.get(command.lower())
        if handler is None:
            logger.debug("Ignoring unknown command %s", command)
            return
        if not self._rate_limiter.allow(command.lower()):
            logger.info("Rate limit triggered for %s", command)
            return
        payload = rest[0] if rest else ""
        await handler(ChatMessage(author=message.author, content=payload))

    def register(self, command: str, handler: CommandHandler) -> None:
        self._handlers[command.lower()] = handler

    def _register_default_handlers(self) -> None:
        self.register("!mute", self._handle_mute)
        self.register("!unmute", self._handle_unmute)
        self.register("!scene", self._handle_scene)
        self.register("!style", self._handle_style)

    async def _handle_mute(self, message: ChatMessage) -> None:
        logger.info("[%s] mute requested", message.author)
        await self._bridge.toggle_tts(False)

    async def _handle_unmute(self, message: ChatMessage) -> None:
        logger.info("[%s] unmute requested", message.author)
        await self._bridge.toggle_tts(True)

    async def _handle_scene(self, message: ChatMessage) -> None:
        scene = message.content.strip() or os.getenv(
            "TWITCH_DEFAULT_SCENE", "Just Chatting"
        )
        logger.info("[%s] scene=%s", message.author, scene)
        await self._bridge.set_scene(scene)

    async def _handle_style(self, message: ChatMessage) -> None:
        match = self._STYLE_RE.match(message.content.strip())
        if not match:
            logger.info(
                "[%s] invalid style payload: %s", message.author, message.content
            )
            return
        style = match.group("style")
        chaos = match.group("chaos")
        energy = match.group("energy")
        await self._bridge.update_persona(
            style=style,
            chaos=float(chaos) / 100 if chaos else None,
            energy=float(energy) / 100 if energy else None,
        )


class StubBot:
    """Fallback loop emitting demo commands for local smoke tests."""

    def __init__(self, router: TwitchCommandRouter) -> None:
        self._router = router
        self._commands = [
            "!style kawaii 30 70",
            "!scene Gameplay",
            "!mute",
            "!unmute",
            "Kitsu, how are you?",
        ]

    async def run(self) -> None:
        idx = 0
        while True:
            payload = self._commands[idx % len(self._commands)]
            idx += 1
            await self._router.handle(ChatMessage(author="stub", content=payload))
            await asyncio.sleep(2.0)


async def run() -> None:
    orchestrator_url = os.getenv("ORCHESTRATOR_URL", "http://127.0.0.1:9000")
    api_key = os.getenv("ORCHESTRATOR_API_KEY")
    bridge = OrchestratorBridge(orchestrator_url, api_key)
    router = TwitchCommandRouter(bridge)

    if commands is None:
        logger.warning("Twitch stub enabled: twitchio not installed")
        bot = StubBot(router)
        await bot.run()
        return

    twitch_token = os.getenv("TWITCH_OAUTH_TOKEN")
    twitch_channel = os.getenv("TWITCH_CHANNEL")
    if not twitch_token or not twitch_channel:
        logger.warning("Twitch stub enabled: credentials missing; using stub bot")
        bot = StubBot(router)
        await bot.run()
        return

    nick = os.getenv("TWITCH_BOT_NICK", "kitsu-bot")

    class TwitchBot(commands.Bot):  # type: ignore[misc]
        def __init__(self) -> None:
            super().__init__(  # type: ignore[call-arg]
                token=twitch_token,
                prefix="!",
                initial_channels=[twitch_channel],
                nick=nick,
            )
            self.nick = nick

        async def event_ready(self) -> None:  # pragma: no cover - twitch runtime
            logger.info("Connected to Twitch as %s", self.nick)

        async def event_message(self, message):  # pragma: no cover - twitch runtime
            if message.echo:
                return
            await router.handle(
                ChatMessage(author=message.author.name, content=message.content)
            )

    bot = TwitchBot()
    try:
        await bot.start()
    finally:  # pragma: no cover - runtime cleanup
        await bridge.close()


def main() -> None:
    logger.info("Starting Twitch ingest loop")
    try:
        asyncio.run(run())
    except KeyboardInterrupt:  # pragma: no cover - manual stop
        logger.info("Twitch ingest stopped")


if __name__ == "__main__":
    main()
