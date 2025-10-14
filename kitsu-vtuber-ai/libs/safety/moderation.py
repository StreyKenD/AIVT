from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Iterable, Sequence

from configs.safety import load_json, load_lines


@dataclass
class ModerationResult:
    allowed: bool
    reason: str | None
    sanitized_text: str


class ModerationPipeline:
    """Aplica blocklists síncronas com interface assíncrona opcional."""

    def __init__(
        self,
        *,
        pre_blocklist: Sequence[str] | None = None,
        post_blocklist: Sequence[str] | None = None,
        fallback_key: str = "blocked",
    ) -> None:
        self._pre_patterns = self._compile(
            pre_blocklist or tuple(load_lines("blocklist_pre.txt"))
        )
        self._post_patterns = self._compile(
            post_blocklist or tuple(load_lines("blocklist_post.txt"))
        )
        self._fallbacks = load_json("fallbacks.json")
        self._fallback_key = fallback_key

    @staticmethod
    def _compile(terms: Iterable[str]) -> list[re.Pattern[str]]:
        patterns: list[re.Pattern[str]] = []
        for term in terms:
            escaped = re.escape(term).replace("\\*", ".*")
            patterns.append(re.compile(rf"(?i)\b{escaped}\b"))
        return patterns

    def _match(
        self, text: str, patterns: Sequence[re.Pattern[str]]
    ) -> re.Pattern[str] | None:
        for pattern in patterns:
            if pattern.search(text):
                return pattern
        return None

    async def guard_prompt(self, prompt: str) -> ModerationResult:
        return await asyncio.get_running_loop().run_in_executor(
            None, self._guard_prompt_sync, prompt
        )

    def _guard_prompt_sync(self, prompt: str) -> ModerationResult:
        match = self._match(prompt, self._pre_patterns)
        if match is None:
            return ModerationResult(True, None, prompt)
        sanitized = self._fallbacks.get(self._fallback_key, "Mensagem bloqueada.")
        return ModerationResult(False, f"pre_block:{match.pattern}", sanitized)

    async def guard_response(self, response: str) -> ModerationResult:
        return await asyncio.get_running_loop().run_in_executor(
            None, self._guard_response_sync, response
        )

    def _guard_response_sync(self, response: str) -> ModerationResult:
        match = self._match(response, self._post_patterns)
        if match is None:
            return ModerationResult(True, None, response)
        sanitized = self._fallbacks.get(self._fallback_key, "Mensagem bloqueada.")
        return ModerationResult(False, f"post_block:{match.pattern}", sanitized)


__all__ = ["ModerationPipeline", "ModerationResult"]
