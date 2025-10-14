from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import time
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, validator

from libs.common import configure_json_logging
from libs.safety import ModerationPipeline
from libs.telemetry import TelemetryClient

configure_json_logging("policy_worker")
logger = logging.getLogger("kitsu.policy")

DEFAULT_MODEL = os.getenv("LLM_MODEL_NAME", "mixtral:8x7b-instruct-q4_K_M")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
POLICY_FORCE_MOCK = os.getenv("POLICY_FORCE_MOCK", "0") == "1"
POLICY_FAMILY_FRIENDLY = os.getenv("POLICY_FAMILY_FRIENDLY", "1") != "0"
POLICY_STREAM_TIMEOUT = float(os.getenv("POLICY_STREAM_TIMEOUT", "30"))
POLICY_RETRY_ATTEMPTS = int(os.getenv("POLICY_RETRY_ATTEMPTS", "1"))
POLICY_RETRY_BACKOFF = float(os.getenv("POLICY_RETRY_BACKOFF", "1.0"))
POLICY_TEMPERATURE = float(os.getenv("POLICY_TEMPERATURE", "0.65"))

MODERATION = ModerationPipeline()
TELEMETRY = TelemetryClient.from_env(service="policy_worker")


async def _publish_policy_metric(event_type: str, payload: Dict[str, Any]) -> None:
    if TELEMETRY is None:
        return
    try:
        await TELEMETRY.publish(event_type, payload)
    except Exception as exc:  # pragma: no cover - telemetry guard
        logger.debug("Falha ao enviar métrica da policy: %s", exc)


SYSTEM_PROMPT_TEMPLATE = """
You are Kitsu.exe, a chaotic-but-kawaii VTuber fox streaming live.
Stay upbeat, empathetic and playful while keeping the show PG-13 at all times.
Speak concise English sentences (<90 tokens) and respond using valid XML:
<speech>what Kitsu says</speech><mood>kawaii|chaotic</mood><actions>comma,separated,actions</actions>
Persona style: {style}. Energy: {energy:.2f}. Chaos: {chaos:.2f}. Family friendly mode: {family}.
Use expressive onomatopoeia and kawaii emojis sparingly. Never break character or mention the prompt rules.
""".strip()

FEW_SHOT_EXCHANGES: List[Dict[str, str]] = [
    {
        "role": "user",
        "content": "Chat is quiet, say hi in a sweet way.",
    },
    {
        "role": "assistant",
        "content": "<speech>Hiii chat~ Kitsu here sending fluffy hugs your way!</speech><mood>kawaii</mood><actions>wave,smile</actions>",
    },
    {
        "role": "user",
        "content": "Chat dares you to do something chaotic but still wholesome.",
    },
    {
        "role": "assistant",
        "content": "<speech>Oooh let's stage a surprise pillow ambush!! Soft chaos only!</speech><mood>chaotic</mood><actions>sparkle,wink</actions>",
    },
]


def _family_mode(payload: "PolicyRequest") -> bool:
    if payload.family_friendly is not None:
        return payload.family_friendly
    return POLICY_FAMILY_FRIENDLY


def _wrap_safe_xml(text: str, mood: str = "kawaii") -> str:
    sanitized = html.escape(text.strip()) or "Vamos manter tudo fofinho!"
    actions = "smile" if mood == "kawaii" else "wink"
    return (
        f"<speech>{sanitized}</speech><mood>{mood}</mood><actions>{actions}</actions>"
    )


class PolicyRequest(BaseModel):
    text: str = Field(..., min_length=1)
    persona_style: str = Field("kawaii", description="Current persona style")
    chaos_level: float = Field(0.35, ge=0.0, le=1.0)
    energy: float = Field(0.65, ge=0.0, le=1.0)
    family_friendly: Optional[bool] = Field(
        None, description="Override to disable/enable family-friendly filtering"
    )
    memory_summary: Optional[str] = Field(
        None, description="Resumo da memória recente fornecido pelo orquestrador"
    )
    recent_turns: List[Dict[str, str]] = Field(
        default_factory=list,
        description="Histórico curto de mensagens com campos role/content",
    )

    @validator("recent_turns", each_item=True)
    def _validate_turn(cls, value: Dict[str, str]) -> Dict[str, str]:  # noqa: D417
        if "role" not in value or "content" not in value:
            raise ValueError("each turn must include role and content")
        return value


class PolicyResponse(BaseModel):
    content: str
    latency_ms: float
    source: str
    request_id: str
    meta: Dict[str, Any] = Field(default_factory=dict)


class OllamaStreamError(RuntimeError):
    """Raised when the Ollama streaming pipeline fails to return a valid reply."""


def _format_sse(event: str, data: Dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _parse_sse(chunk: str) -> tuple[str, Dict[str, Any]]:
    event = ""
    payload: Dict[str, Any] = {}
    for line in chunk.splitlines():
        if not line:
            continue
        if line.startswith("event:"):
            event = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            payload = json.loads(line.split(":", 1)[1].strip())
    return event, payload


def _tokenize_for_streaming(message: str) -> List[str]:
    parts = message.split(" ")
    tokens: List[str] = []
    for index, chunk in enumerate(parts):
        if not chunk:
            continue
        if index < len(parts) - 1:
            tokens.append(f"{chunk} ")
        else:
            tokens.append(chunk)
    return tokens


def _build_persona_snapshot(
    payload: PolicyRequest, family_mode: bool
) -> Dict[str, Any]:
    return {
        "style": payload.persona_style,
        "chaos_level": round(payload.chaos_level, 2),
        "energy": round(payload.energy, 2),
        "family_friendly": family_mode,
    }


def _build_messages(payload: PolicyRequest, family_mode: bool) -> List[Dict[str, str]]:
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        style=payload.persona_style,
        energy=payload.energy,
        chaos=payload.chaos_level,
        family="ON" if family_mode else "OFF",
    )
    messages: List[Dict[str, str]] = [{"role": "system", "content": system_prompt}]
    if payload.memory_summary:
        messages.append(
            {
                "role": "system",
                "content": f"Contexto recente: {payload.memory_summary}",
            }
        )
    messages.extend(FEW_SHOT_EXCHANGES)
    for turn in payload.recent_turns[-6:]:
        messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": payload.text})
    return messages


def _extract_stats(metadata: Dict[str, Any]) -> Dict[str, Any]:
    stats: Dict[str, Any] = {}
    for key, value in metadata.items():
        if key.endswith("_duration") and isinstance(value, (int, float)):
            stats[key] = round(float(value) / 1_000_000, 2)
        elif key.endswith("_count") and isinstance(value, (int, float)):
            stats[key] = value
        elif key in {
            "total_duration",
            "load_duration",
            "prompt_eval_duration",
            "eval_duration",
        }:
            stats[key] = round(float(value) / 1_000_000, 2)
        elif key in {"done_reason", "model"}:
            stats[key] = value
    return stats


async def _stream_mock_response(
    payload: PolicyRequest,
    request_id: str,
    start_time: float,
    persona: Dict[str, Any],
    reason: Optional[str],
    retries: int,
) -> AsyncIterator[str]:
    content = build_mock_reply(payload)
    tokens = _tokenize_for_streaming(content)
    for index, token in enumerate(tokens):
        yield _format_sse(
            "token",
            {
                "token": token,
                "index": index,
                "request_id": request_id,
                "source": "mock",
            },
        )
        await asyncio.sleep(0)
    latency_ms = (time.perf_counter() - start_time) * 1000
    response = PolicyResponse(
        content=content,
        latency_ms=round(latency_ms, 2),
        source="mock",
        request_id=request_id,
        meta={
            "persona": persona,
            "model": DEFAULT_MODEL,
            "fallback": True,
            "retries": retries,
            **({"reason": reason} if reason else {}),
        },
    )
    await _publish_policy_metric(
        "policy.response",
        {
            "request_id": request_id,
            "status": "degraded" if reason else "ok",
            "source": "mock",
            "latency_ms": round(latency_ms, 2),
            "persona": persona,
            "retries": retries,
            "text_length": len(payload.text),
            **({"reason": reason} if reason else {}),
        },
    )
    yield _format_sse("final", response.dict())


async def _stream_ollama_response(
    payload: PolicyRequest,
    request_id: str,
    start_time: float,
    persona: Dict[str, Any],
    family_mode: bool,
    attempt: int,
) -> AsyncIterator[str]:
    messages = _build_messages(payload, family_mode)
    timeout = httpx.Timeout(POLICY_STREAM_TIMEOUT)
    aggregated_tokens: List[str] = []
    final_metadata: Dict[str, Any] = {}

    try:
        async with httpx.AsyncClient(base_url=OLLAMA_URL, timeout=timeout) as client:
            async with client.stream(
                "POST",
                "/api/chat",
                json={
                    "model": DEFAULT_MODEL,
                    "messages": messages,
                    "stream": True,
                    "options": {
                        "temperature": POLICY_TEMPERATURE,
                        "top_p": 0.9,
                    },
                },
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        logger.debug("Discarding non-JSON chunk from Ollama: %s", line)
                        continue
                    if "error" in chunk:
                        raise OllamaStreamError(chunk["error"])
                    message = chunk.get("message") or {}
                    token = message.get("content") or chunk.get("response")
                    if token:
                        aggregated_tokens.append(token)
                        yield _format_sse(
                            "token",
                            {
                                "token": token,
                                "index": len(aggregated_tokens) - 1,
                                "request_id": request_id,
                                "source": "ollama",
                            },
                        )
                    if chunk.get("done"):
                        final_metadata = chunk
                        break
    except httpx.HTTPStatusError as exc:
        raise OllamaStreamError(
            f"Ollama HTTP {exc.response.status_code}: {exc.response.text[:128]}"
        ) from exc
    except (httpx.RequestError, asyncio.TimeoutError) as exc:
        raise OllamaStreamError(f"Ollama request failed: {exc}") from exc

    if not aggregated_tokens:
        raise OllamaStreamError("No tokens returned from Ollama")

    content = "".join(aggregated_tokens).strip()
    if not all(tag in content for tag in ("<speech>", "<mood>", "<actions>")):
        raise OllamaStreamError("Invalid XML payload from Ollama")

    latency_ms = (time.perf_counter() - start_time) * 1000
    stats = _extract_stats(final_metadata)
    policy_response = PolicyResponse(
        content=content,
        latency_ms=round(latency_ms, 2),
        source="ollama",
        request_id=request_id,
        meta={
            "persona": persona,
            "model": DEFAULT_MODEL,
            "stats": stats,
            "retries": attempt,
        },
    )
    await _publish_policy_metric(
        "policy.response",
        {
            "request_id": request_id,
            "status": "ok",
            "source": "ollama",
            "latency_ms": round(latency_ms, 2),
            "persona": persona,
            "retries": attempt,
            "text_length": len(payload.text),
            "stats": stats,
        },
    )
    yield _format_sse("final", policy_response.dict())


def build_mock_reply(payload: PolicyRequest) -> str:
    style = payload.persona_style.lower()
    if style == "chaotic":
        speech = "Eeee! Let's cause some sparkly chaos while staying wholesome!"
        mood = "chaotic"
        actions = "wink,sparkle"
    else:
        speech = "Hehe~ Staying adorable and safe for chat!"
        mood = "kawaii"
        actions = "sparkle,heart"
    return f"<speech>{speech}</speech><mood>{mood}</mood><actions>{actions}</actions>"


async def policy_event_generator(payload: PolicyRequest) -> AsyncIterator[str]:
    request_id = uuid.uuid4().hex
    family_mode = _family_mode(payload)
    persona = _build_persona_snapshot(payload, family_mode)
    start = time.perf_counter()
    prompt_guard = await MODERATION.guard_prompt(payload.text)
    source = "mock" if POLICY_FORCE_MOCK else "ollama"
    if not prompt_guard.allowed:
        source = "moderation"
    response_moderation: Optional[Dict[str, str]] = None

    yield _format_sse(
        "start",
        {
            "request_id": request_id,
            "model": DEFAULT_MODEL,
            "persona": persona,
            "source": source,
        },
    )

    if not prompt_guard.allowed:
        content = _wrap_safe_xml(prompt_guard.sanitized_text)
        latency_ms = (time.perf_counter() - start) * 1000
        response = PolicyResponse(
            content=content,
            latency_ms=round(latency_ms, 2),
            source="moderation",
            request_id=request_id,
            meta={
                "persona": persona,
                "fallback": True,
                "moderation": {"phase": "prompt", "reason": prompt_guard.reason},
            },
        )
        await _publish_policy_metric(
            "policy.response",
            {
                "request_id": request_id,
                "status": "blocked",
                "source": "moderation",
                "latency_ms": round(latency_ms, 2),
                "persona": persona,
                "retries": 0,
                "reason": prompt_guard.reason,
                "text_length": len(payload.text),
            },
        )
        yield _format_sse("final", response.dict())
        return

    if POLICY_FORCE_MOCK:
        async for chunk in _stream_mock_response(
            payload, request_id, start, persona, reason=None, retries=0
        ):
            event, data = _parse_sse(chunk)
            if event == "final":
                guard = await MODERATION.guard_response(data["content"])
                if not guard.allowed:
                    data["content"] = _wrap_safe_xml(guard.sanitized_text)
                    response_moderation = {
                        "phase": "response",
                        "reason": guard.reason,
                    }
                    data.setdefault("meta", {})["moderation"] = response_moderation
                    chunk = _format_sse("final", data)
                elif response_moderation:
                    data.setdefault("meta", {})["moderation"] = response_moderation
                    chunk = _format_sse("final", data)
            yield chunk
        return

    last_error: Optional[Exception] = None
    attempts_allowed = max(POLICY_RETRY_ATTEMPTS, 0)
    attempts_made = 0

    for attempt in range(attempts_allowed + 1):
        try:
            attempts_made = attempt
            async for chunk in _stream_ollama_response(
                payload, request_id, start, persona, family_mode, attempt
            ):
                event, data = _parse_sse(chunk)
                if event == "token" and data.get("source") == "ollama" and not response_moderation:
                    guard = await MODERATION.guard_response(data.get("token", ""))
                    if not guard.allowed:
                        response_moderation = {
                            "phase": "response",
                            "reason": guard.reason or "blocked",
                        }
                if event == "final":
                    guard = await MODERATION.guard_response(data["content"])
                    if not guard.allowed:
                        data["content"] = _wrap_safe_xml(guard.sanitized_text)
                        response_moderation = {
                            "phase": "response",
                            "reason": guard.reason,
                        }
                        data.setdefault("meta", {})["moderation"] = response_moderation
                        chunk = _format_sse("final", data)
                    elif response_moderation:
                        data.setdefault("meta", {})["moderation"] = response_moderation
                        chunk = _format_sse("final", data)
                yield chunk
            return
        except OllamaStreamError as exc:
            last_error = exc
            logger.warning(
                "Ollama stream failed (attempt %s/%s) for request %s: %s",
                attempt + 1,
                attempts_allowed + 1,
                request_id,
                exc,
            )
            if attempt < attempts_allowed:
                yield _format_sse(
                    "retry",
                    {
                        "request_id": request_id,
                        "attempt": attempt + 1,
                        "reason": str(exc),
                    },
                )
                await asyncio.sleep(POLICY_RETRY_BACKOFF * (attempt + 1))
            else:
                break

    async for chunk in _stream_mock_response(
        payload,
        request_id,
        start,
        persona,
        reason=str(last_error) if last_error else None,
        retries=attempts_made + 1,
    ):
        event, data = _parse_sse(chunk)
        if event == "final":
            guard = await MODERATION.guard_response(data["content"])
            if not guard.allowed:
                data["content"] = _wrap_safe_xml(guard.sanitized_text)
                response_moderation = {
                    "phase": "response",
                    "reason": guard.reason,
                }
                data.setdefault("meta", {})["moderation"] = response_moderation
                chunk = _format_sse("final", data)
            elif response_moderation:
                data.setdefault("meta", {})["moderation"] = response_moderation
                chunk = _format_sse("final", data)
        yield chunk


app = FastAPI(title="Kitsu Policy Worker", version="0.3.0")


@app.post("/respond")
async def respond(payload: PolicyRequest) -> StreamingResponse:
    if not payload.text.strip():  # pragma: no cover - defensive validation
        raise HTTPException(status_code=422, detail="Prompt must not be empty")
    logger.info(
        "Policy request text=%s style=%s chaos=%.2f energy=%.2f family=%s",
        payload.text[:64],
        payload.persona_style,
        payload.chaos_level,
        payload.energy,
        _family_mode(payload),
    )
    return StreamingResponse(
        policy_event_generator(payload), media_type="text/event-stream"
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "apps.policy_worker.main:app",
        host="0.0.0.0",
        port=8081,
        reload=os.getenv("UVICORN_RELOAD") == "1",
    )
