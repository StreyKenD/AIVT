"""Decision engine for routing ASR events through policy/TTS workers.

This module isolates the orchestration logic that decides when to invoke the
policy worker, how to react to streaming tokens, and when to queue TTS work.  By
keeping the sequencing and streaming pipeline here we allow the state manager to
focus on persona/module tracking while the event dispatcher worries about fan
out.
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import suppress
from typing import Any, Dict, List, Optional, TYPE_CHECKING, cast

from libs.contracts import ASRFinalEvent, ASREventPayload, PolicyRequestPayload, TTSRequestPayload

from .event_dispatcher import EventDispatcher
from .metrics import observe_latency, record_failure

if TYPE_CHECKING:  # pragma: no cover - typing helper
    from .state_manager import OrchestratorState, PolicyInvoker, TTSInvoker

logger = logging.getLogger(__name__)

class StreamingReplySession:
    """Fan-out streaming LLM tokens into incremental TTS chunks."""

    SENTENCE_ENDINGS = (".", "!", "?", "...", "…", "。", "！", "？")
    MIN_CHUNK_CHARS = 60
    MAX_CHUNK_CHARS = 220

    def __init__(
        self,
        dispatcher: EventDispatcher,
        state: "OrchestratorState",
        tts_invoker: "TTSInvoker",
        *,
        synthesize: bool,
    ) -> None:
        self._dispatcher = dispatcher
        self._state = state
        self._tts_invoker = tts_invoker
        self._synthesize = synthesize and not state.tts_muted
        self._queue: Optional[asyncio.Queue[Optional[tuple[int, str]]]] = None
        self._consumer_task: Optional[asyncio.Task[None]] = None
        self._buffer: List[str] = []
        self._chunk_index = 0
        self.chunk_count = 0
        self._request_id: Optional[str] = None
        self._first_token_at: Optional[float] = None
        self._tts_first_chunk_at: Optional[float] = None
        self._policy_started_at = time.perf_counter()
        self._policy_finished_at: Optional[float] = None
        self._closed = False
        self._last_voice: Optional[str] = None
        self.mode = "streaming" if self._synthesize else "text-only"

    async def start(self) -> None:
        if not self._synthesize:
            return
        self._queue = asyncio.Queue()
        self._consumer_task = asyncio.create_task(self._consume_queue())

    async def handle_event(self, event: str, data: Dict[str, Any]) -> None:
        if event == "start":
            request_id = data.get("request_id")
            if isinstance(request_id, str):
                self._request_id = request_id
            return
        if event == "token":
            await self._handle_token(data.get("token"))
            return
        if event == "final":
            await self._handle_final()
            return
        if event == "retry":
            self._buffer.clear()

    @property
    def requires_fallback(self) -> bool:
        return self._synthesize and self.chunk_count == 0

    @property
    def voice_hint(self) -> Optional[str]:
        return self._last_voice

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._queue is not None:
            await self._queue.put(None)
        if self._consumer_task is not None:
            with suppress(asyncio.CancelledError):
                await self._consumer_task
        self._policy_finished_at = self._policy_finished_at or time.perf_counter()
        if self._policy_finished_at is not None:
            await self._dispatcher.publish_pipeline_metric(
                "policy_total",
                (self._policy_finished_at - self._policy_started_at) * 1000,
                self._request_id,
                self.mode,
            )

    async def _handle_token(self, token_value: Any) -> None:
        if not isinstance(token_value, str) or not token_value:
            return
        self._buffer.append(token_value)
        if self._first_token_at is None:
            self._first_token_at = time.perf_counter()
            await self._dispatcher.publish_pipeline_metric(
                "policy_first_token",
                (self._first_token_at - self._policy_started_at) * 1000,
                self._request_id,
                self.mode,
            )
        await self._flush_if_ready(force=False)

    async def _handle_final(self) -> None:
        await self._flush_if_ready(force=True)

    async def _flush_if_ready(self, *, force: bool) -> None:
        if not self._buffer:
            return
        if force or self._should_flush():
            chunk = self._drain_buffer()
            if chunk:
                await self._queue_chunk(chunk)

    def _should_flush(self) -> bool:
        text = "".join(self._buffer)
        if len(text) >= self.MAX_CHUNK_CHARS:
            return True
        stripped = text.rstrip()
        if len(stripped) < self.MIN_CHUNK_CHARS:
            return False
        return any(stripped.endswith(marker) for marker in self.SENTENCE_ENDINGS)

    def _drain_buffer(self) -> Optional[str]:
        if not self._buffer:
            return None
        text = "".join(self._buffer).strip()
        self._buffer.clear()
        return text or None

    async def _queue_chunk(self, text: str) -> None:
        if not text or not self._synthesize or self._queue is None:
            return
        await self._queue.put((self._chunk_index, text))
        self.chunk_count += 1
        self._chunk_index += 1

    async def _consume_queue(self) -> None:
        assert self._queue is not None
        while True:
            item = await self._queue.get()
            if item is None:
                break
            index, text = item
            await self._synthesize_chunk(index, text)

    async def _synthesize_chunk(self, index: int, text: str) -> None:
        request_id = self._request_id or "stream"
        chunk_request_id = f"{request_id}-chunk-{index}"
        start = time.perf_counter()
        try:
            result = await self._tts_invoker(text, None, chunk_request_id)
        except Exception:
            latency_ms = (time.perf_counter() - start) * 1000
            logger.exception("TTS chunk generation failed")
            self._state._mark_module_latency("tts_worker", latency_ms, health="offline")
            return
        latency_ms = (time.perf_counter() - start) * 1000
        if result is None:
            self._state._mark_module_latency("tts_worker", latency_ms, health="offline")
            return
        self._state._mark_module_latency("tts_worker", latency_ms, health="online")
        self._last_voice = result.get("voice") or self._last_voice
        chunk_payload = {
            "index": index,
            "request_id": chunk_request_id,
            "audio_path": result.get("audio_path"),
            "voice": result.get("voice"),
            "latency_ms": latency_ms,
            "text_length": len(text),
            "mode": "streaming",
        }
        await self._dispatcher.publish({"type": "tts_chunk", "payload": chunk_payload})
        if self._tts_first_chunk_at is None:
            self._tts_first_chunk_at = time.perf_counter()
            await self._dispatcher.publish_pipeline_metric(
                "tts_first_chunk",
                (self._tts_first_chunk_at - self._policy_started_at) * 1000,
                self._request_id,
                self.mode,
            )


class DecisionEngine:
    """Encapsulates the ASR → Policy → TTS decision tree."""

    def __init__(
        self,
        state: "OrchestratorState",
        dispatcher: EventDispatcher,
        policy_invoker: "PolicyInvoker",
        tts_invoker: "TTSInvoker",
    ) -> None:
        self._state = state
        self._dispatcher = dispatcher
        self._policy_invoker = policy_invoker
        self._tts_invoker = tts_invoker
        self._segment_lock = asyncio.Lock()
        self._active_segments: Dict[int, object] = {}
        self._completed_segments: Dict[int, float] = {}

    @property
    def policy_invoker(self) -> "PolicyInvoker":
        return self._policy_invoker

    def update_policy_invoker(self, invoker: "PolicyInvoker") -> None:
        self._policy_invoker = invoker

    @property
    def tts_invoker(self) -> "TTSInvoker":
        return self._tts_invoker

    def update_tts_invoker(self, invoker: "TTSInvoker") -> None:
        self._tts_invoker = invoker

    async def handle_asr_partial(self, event: ASREventPayload) -> None:
        """Process a streaming transcription chunk."""
        if event.type != "asr_partial":
            return
        text = event.text.strip()
        if not text:
            return
        registered = await self._register_segment(event.segment)
        if not registered:
            return
        try:
            await self._process_asr_stream(text, event.segment, is_final=False)
        finally:
            await self._complete_segment(event.segment)

    async def handle_asr_final(self, event: ASREventPayload) -> None:
        """Process a final transcript and trigger the policy pipeline."""
        if event.type != "asr_final":
            return
        final_event = cast(ASRFinalEvent, event)
        text = final_event.text.strip()
        if not text:
            return
        await self._state.record_turn("user", text)
        if await self._segment_already_processed(final_event.segment):
            return
        registered = await self._register_segment(final_event.segment)
        if not registered:
            return
        try:
            await self._process_asr_stream(text, final_event.segment, is_final=True)
        finally:
            await self._complete_segment(final_event.segment)

    async def process_manual_prompt(
        self, text: str, *, synthesize: bool = True
    ) -> Optional[Dict[str, Any]]:
        """Entry point used by /chat/respond to inject user text."""
        clean = text.strip()
        if not clean:
            return None
        await self._state.record_turn("user", clean)
        return await self._run_policy_pipeline(
            clean,
            synthesize=synthesize,
            is_final=True,
            segment_id=None,
        )

    async def _process_asr_stream(
        self, text: str, segment: int, *, is_final: bool
    ) -> None:
        await self._run_policy_pipeline(
            text,
            synthesize=not self._state.tts_muted,
            is_final=is_final,
            segment_id=segment,
        )

    async def _run_policy_pipeline(
        self,
        text: str,
        *,
        synthesize: bool,
        is_final: bool,
        segment_id: Optional[int],
    ) -> Optional[Dict[str, Any]]:
        del segment_id  # Reserved for future metric correlation
        request_body = self._build_policy_request(text, is_final=is_final)
        start = time.perf_counter()
        should_stream = synthesize and not self._state.tts_muted
        stream_session = StreamingReplySession(
            self._dispatcher,
            self._state,
            self._tts_invoker,
            synthesize=should_stream,
        )
        await stream_session.start()
        try:
            final_payload = await self._policy_invoker(
                request_body, self._state._broker, stream_session.handle_event
            )
        finally:
            await stream_session.close()
        latency_ms = (time.perf_counter() - start) * 1000
        observe_latency("policy", latency_ms / 1000.0)
        if final_payload is None:
            self._state._mark_module_latency("policy_worker", latency_ms, health="offline")
            logger.warning("Policy worker returned no final payload for request")
            record_failure("policy")
            return None
        status_meta = None
        if isinstance(final_payload, dict):
            meta = final_payload.get("meta")
            if isinstance(meta, dict):
                status_meta = meta.get("status")
        if isinstance(status_meta, str):
            normalized = status_meta.lower()
            if normalized == "busy":
                self._state._mark_module_latency("policy_worker", latency_ms, health="degraded")
                logger.warning("Policy worker busy; deferring response")
                return None
            if normalized == "error":
                self._state._mark_module_latency("policy_worker", latency_ms, health="offline")
                record_failure("policy")
            else:
                self._state._mark_module_latency("policy_worker", latency_ms, health="online")
        else:
            self._state._mark_module_latency("policy_worker", latency_ms, health="online")

        await self._dispatcher.publish({"type": "policy_final", "payload": final_payload})

        speech_content = _extract_speech(final_payload.get("content", ""))
        if not speech_content:
            speech_content = (final_payload.get("content") or "").strip()
        if not speech_content:
            return final_payload

        if not should_stream:
            await self._state.record_turn("assistant", speech_content)
            return final_payload

        chunked_audio = stream_session.chunk_count > 0
        voice_hint = stream_session.voice_hint or final_payload.get("meta", {}).get("voice")

        if not chunked_audio:
            tts_start = time.perf_counter()
            tts_result = await self._tts_invoker(
                speech_content,
                voice_hint,
                final_payload.get("request_id"),
            )
            tts_latency_ms = (time.perf_counter() - tts_start) * 1000
            observe_latency("tts", tts_latency_ms / 1000.0)
            if isinstance(tts_result, dict) and tts_result.get("status") == "busy":
                self._state._mark_module_latency("tts_worker", tts_latency_ms, health="degraded")
                logger.warning("TTS worker busy; skipping synthesis for now")
                return final_payload
            if tts_result is not None:
                self._state._mark_module_latency("tts_worker", tts_latency_ms, health="online")
                await self._dispatcher.publish({"type": "tts_generated", "payload": tts_result})
                if isinstance(tts_result, dict):
                    voice_hint = tts_result.get("voice") or voice_hint
            else:
                self._state._mark_module_latency("tts_worker", tts_latency_ms, health="offline")
                record_failure("tts")
        await self._state.record_tts(
            TTSRequestPayload(
                text=speech_content,
                voice=voice_hint,
                request_id=final_payload.get("request_id"),
            )
        )
        return final_payload

    def _build_policy_request(self, text: str, *, is_final: bool) -> Dict[str, Any]:
        persona = self._state.persona.snapshot()
        payload: Dict[str, Any] = {
            "text": text,
            "is_final": is_final,
            "persona_style": persona["style"],
            "chaos_level": persona["chaos_level"],
            "energy": persona["energy"],
            "family_friendly": persona["family_mode"],
        }
        persona_prompt = self._state._persona_prompts.get(self._state.active_preset)
        if persona_prompt:
            payload["persona_prompt"] = persona_prompt
        if self._state.last_summary:
            payload["memory_summary"] = self._state.last_summary.summary_text
        recent_turns = [
            {"role": turn.role, "content": turn.text}
            for turn in self._state.memory.buffer.as_list()[-6:]
        ]
        if recent_turns:
            payload["recent_turns"] = recent_turns
        return payload

    async def _register_segment(self, segment: int) -> bool:
        async with self._segment_lock:
            if segment in self._active_segments or segment in self._completed_segments:
                return False
            token = asyncio.current_task() or object()
            self._active_segments[segment] = token
            return True

    async def _complete_segment(self, segment: int) -> None:
        async with self._segment_lock:
            self._active_segments.pop(segment, None)
            self._completed_segments[segment] = time.time()
            self._prune_completed_segments_locked()

    async def _segment_already_processed(self, segment: int) -> bool:
        async with self._segment_lock:
            if segment in self._active_segments:
                return True
            if segment in self._completed_segments:
                self._completed_segments.pop(segment, None)
                return True
        return False

    def _prune_completed_segments_locked(self) -> None:
        if len(self._completed_segments) <= 64:
            return
        cutoff = time.time() - 300
        for seg, ts in list(self._completed_segments.items()):
            if ts < cutoff:
                self._completed_segments.pop(seg, None)


def _extract_speech(content: Optional[str]) -> str:
    if not content:
        return ""
    import html  # Local import to avoid circular dependency
    import re

    pattern = re.compile(r"<speech>(.*?)</speech>", re.IGNORECASE | re.DOTALL)
    match = pattern.search(content)
    if not match:
        return ""
    value = html.unescape(match.group(1))
    return value.strip()


__all__ = ["DecisionEngine", "StreamingReplySession"]
