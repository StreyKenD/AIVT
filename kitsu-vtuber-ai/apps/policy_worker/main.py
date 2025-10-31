from __future__ import annotations

import asyncio
import html
import importlib
import json
import logging
import os
import time
import uuid
from typing import Any, AsyncIterator, Dict, Iterable, List, Optional

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from libs.common import configure_json_logging
from libs.config import get_app_config
from libs.contracts import PolicyRequestPayload
from libs.safety import ModerationPipeline
from libs.telemetry import TelemetryClient

configure_json_logging("policy_worker")
logger = logging.getLogger("kitsu.policy")

settings = get_app_config()
policy_cfg = settings.policy
orchestrator_cfg = settings.orchestrator

def _resolve_model_name() -> str:
    backend = policy_cfg.backend
    if backend == "openai":
        return policy_cfg.openai.model or policy_cfg.model_name
    if backend == "local":
        return policy_cfg.local.model_path or policy_cfg.model_name
    return policy_cfg.model_name


MODEL_NAME = _resolve_model_name()
OLLAMA_URL = policy_cfg.ollama_url
OPENAI_CONFIG = policy_cfg.openai
LOCAL_LLM_CONFIG = policy_cfg.local
POLICY_BACKEND = policy_cfg.backend
POLICY_FAMILY_FRIENDLY = policy_cfg.family_friendly
POLICY_STREAM_TIMEOUT = policy_cfg.stream_timeout
POLICY_RETRY_ATTEMPTS = policy_cfg.retry_attempts
POLICY_RETRY_BACKOFF = policy_cfg.retry_backoff
POLICY_TEMPERATURE = policy_cfg.temperature

MODERATION = ModerationPipeline()
TELEMETRY = (
    TelemetryClient(
        orchestrator_cfg.telemetry_url,
        api_key=orchestrator_cfg.telemetry_api_key,
        service="policy_worker",
    )
    if orchestrator_cfg.telemetry_url
    else None
)


async def _publish_policy_metric(event_type: str, payload: Dict[str, Any]) -> None:
    if TELEMETRY is None:
        return
    try:
        await TELEMETRY.publish(event_type, payload)
    except Exception as exc:  # pragma: no cover - telemetry guard
        logger.debug("Failed to send policy metric: %s", exc)


async def _response_preview(response: httpx.Response, limit: int = 256) -> str:
    try:
        content = await response.aread()
    except Exception:
        return "<response body unavailable>"
    encoding = response.encoding or "utf-8"
    if not content:
        return "<empty response>"
    try:
        payload = json.loads(content)
        if isinstance(payload, dict):
            if "error" in payload and isinstance(payload["error"], str):
                return payload["error"]
            return json.dumps(payload, ensure_ascii=False)[:limit]
    except json.JSONDecodeError:
        pass
    try:
        return content[:limit].decode(encoding, errors="replace")
    except Exception:
        return content[:limit].decode("utf-8", errors="replace")


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


def _family_mode(payload: "PolicyRequestPayload") -> bool:
    if payload.family_friendly is not None:
        return payload.family_friendly
    return POLICY_FAMILY_FRIENDLY


def _wrap_safe_xml(text: str, mood: str = "kawaii") -> str:
    sanitized = html.escape(text.strip()) or "Vamos manter tudo fofinho!"
    actions = "smile" if mood == "kawaii" else "wink"
    return (
        f"<speech>{sanitized}</speech><mood>{mood}</mood><actions>{actions}</actions>"
    )


class PolicyResponse(BaseModel):
    content: str
    latency_ms: float
    source: str
    request_id: str
    meta: Dict[str, Any] = Field(default_factory=dict)


class LLMStreamError(RuntimeError):
    """Raised when the configured LLM backend fails to return a valid reply."""


def _load_optional_module(name: str):
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError:
        return None


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
    payload: PolicyRequestPayload, family_mode: bool
) -> Dict[str, Any]:
    return {
        "style": payload.persona_style,
        "chaos_level": round(payload.chaos_level, 2),
        "energy": round(payload.energy, 2),
        "family_friendly": family_mode,
    }


def _build_messages(
    payload: PolicyRequestPayload, family_mode: bool
) -> List[Dict[str, str]]:
    template = payload.persona_prompt or SYSTEM_PROMPT_TEMPLATE
    try:
        system_prompt = template.format(
            style=payload.persona_style,
            energy=payload.energy,
            chaos=payload.chaos_level,
            family="ON" if family_mode else "OFF",
        )
    except KeyError:
        system_prompt = template
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


class BaseLLMClient:
    backend: str = "unknown"

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name

    async def stream_response(
        self,
        payload: PolicyRequestPayload,
        request_id: str,
        start_time: float,
        persona: Dict[str, Any],
        family_mode: bool,
        attempt: int,
    ) -> AsyncIterator[str]:
        raise NotImplementedError


class OllamaLLMClient(BaseLLMClient):
    backend = "ollama"

    def __init__(self, base_url: str, model_name: str) -> None:
        super().__init__(model_name)
        self._base_url = base_url.rstrip('/')

    async def stream_response(
        self,
        payload: PolicyRequestPayload,
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
            async with httpx.AsyncClient(base_url=self._base_url, timeout=timeout) as client:
                async with client.stream(
                    "POST",
                    "/api/chat",
                    json={
                        "model": self.model_name,
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
                            raise LLMStreamError(chunk["error"])
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
                                    "source": self.backend,
                                },
                            )
                        if chunk.get("done"):
                            final_metadata = chunk
                            break
        except httpx.HTTPStatusError as exc:
            body_preview = await _response_preview(exc.response)
            if "model not found" in body_preview.lower():
                body_preview = (
                    f"{body_preview}. Install the model with ollama pull {self.model_name} " +
                    "or update LLM_MODEL_NAME."
                )
            raise LLMStreamError(
                f"Ollama HTTP {exc.response.status_code}: {body_preview}"
            ) from exc
        except (httpx.RequestError, asyncio.TimeoutError) as exc:
            raise LLMStreamError(f"Ollama request failed: {exc}") from exc

        if not aggregated_tokens:
            raise LLMStreamError("No tokens returned from Ollama")

        content = ''.join(aggregated_tokens).strip()
        if not all(tag in content for tag in ("<speech>", "<mood>", "<actions>")):
            raise LLMStreamError("Invalid XML payload from Ollama")

        latency_ms = (time.perf_counter() - start_time) * 1000
        stats = _extract_stats(final_metadata)
        policy_response = PolicyResponse(
            content=content,
            latency_ms=round(latency_ms, 2),
            source=self.backend,
            request_id=request_id,
            meta={
                "persona": persona,
                "model": self.model_name,
                "stats": stats,
                "retries": attempt,
            },
        )
        await _publish_policy_metric(
            "policy.response",
            {
                "request_id": request_id,
                "status": "ok",
                "source": self.backend,
                "latency_ms": round(latency_ms, 2),
                "persona": persona,
                "retries": attempt,
                "text_length": len(payload.text),
                "model": self.model_name,
                "stats": stats,
            },
        )
        yield _format_sse("final", policy_response.dict())


class OpenAILLMClient(BaseLLMClient):
    backend = "openai"

    def __init__(self, config: OpenAISettings, model_name: str) -> None:
        super().__init__(model_name)
        self._config = config
        self._base_url = config.base_url.rstrip('/')

    def _resolve_headers(self) -> Dict[str, str]:
        api_key_env = self._config.api_key_env or "OPENAI_API_KEY"
        api_key = os.getenv(api_key_env)
        if not api_key:
            raise LLMStreamError(
                f"OpenAI API key not found. Set {api_key_env} in the environment to use the OpenAI backend."
            )
        headers = {"Authorization": f"Bearer {api_key}"}
        if self._config.organization:
            headers["OpenAI-Organization"] = self._config.organization
        return headers

    async def stream_response(
        self,
        payload: PolicyRequestPayload,
        request_id: str,
        start_time: float,
        persona: Dict[str, Any],
        family_mode: bool,
        attempt: int,
    ) -> AsyncIterator[str]:
        messages = _build_messages(payload, family_mode)
        aggregated_tokens: List[str] = []
        finish_reason = None
        timeout = httpx.Timeout(self._config.timeout_seconds)
        headers = self._resolve_headers()
        body = {
            "model": self.model_name,
            "messages": messages,
            "stream": True,
            "temperature": POLICY_TEMPERATURE,
        }

        try:
            async with httpx.AsyncClient(base_url=self._base_url, timeout=timeout) as client:
                async with client.stream(
                    "POST",
                    "/chat/completions",
                    headers=headers,
                    json=body,
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        line = line.strip()
                        if not line.startswith("data:"):
                            continue
                        data = line[len("data:") :].strip()
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                        except json.JSONDecodeError:
                            logger.debug("Discarding non-JSON chunk from OpenAI: %s", data)
                            continue
                        choices = chunk.get("choices") or []
                        if not choices:
                            continue
                        choice = choices[0]
                        delta = choice.get("delta") or {}
                        token = delta.get("content")
                        if token:
                            aggregated_tokens.append(token)
                            yield _format_sse(
                                "token",
                                {
                                    "token": token,
                                    "index": len(aggregated_tokens) - 1,
                                    "request_id": request_id,
                                    "source": self.backend,
                                },
                            )
                        finish_reason = choice.get("finish_reason") or finish_reason
        except httpx.HTTPStatusError as exc:
            body_preview = await _response_preview(exc.response)
            raise LLMStreamError(
                f"OpenAI HTTP {exc.response.status_code}: {body_preview}"
            ) from exc
        except (httpx.RequestError, asyncio.TimeoutError) as exc:
            raise LLMStreamError(f"OpenAI request failed: {exc}") from exc

        if not aggregated_tokens:
            raise LLMStreamError("No tokens returned from OpenAI")

        content = ''.join(aggregated_tokens).strip()
        latency_ms = (time.perf_counter() - start_time) * 1000
        stats: Dict[str, Any] = {}
        if finish_reason:
            stats["finish_reason"] = finish_reason
        policy_response = PolicyResponse(
            content=content,
            latency_ms=round(latency_ms, 2),
            source=self.backend,
            request_id=request_id,
            meta={
                "persona": persona,
                "model": self.model_name,
                "stats": stats,
                "retries": attempt,
            },
        )
        await _publish_policy_metric(
            "policy.response",
            {
                "request_id": request_id,
                "status": "ok",
                "source": self.backend,
                "latency_ms": round(latency_ms, 2),
                "persona": persona,
                "retries": attempt,
                "text_length": len(payload.text),
                "model": self.model_name,
                "stats": stats,
            },
        )
        yield _format_sse("final", policy_response.dict())


class LocalTransformersClient(BaseLLMClient):
    backend = "local"

    def __init__(self, config: LocalLLMSettings, model_name: str) -> None:
        super().__init__(model_name)
        self._config = config
        self._pipeline = None

    def _ensure_pipeline(self):
        if self._pipeline is not None:
            return self._pipeline
        transformers = _load_optional_module("transformers")
        if transformers is None:
            raise LLMStreamError(
                "transformers is required for the local backend. Install it with pip install transformers torch."
            )
        model_id = self._config.model_path or self.model_name
        tokenizer_id = self._config.tokenizer_path or model_id
        device = (self._config.device or "auto").lower()
        pipeline_kwargs: Dict[str, Any] = {}
        if device != "auto":
            if device in {"cpu", "-1"}:
                pipeline_kwargs["device"] = -1
            elif device in {"cuda", "0"}:
                pipeline_kwargs["device"] = 0
            else:
                try:
                    pipeline_kwargs["device"] = int(device)
                except ValueError as exc:  # pragma: no cover - defensive guard
                    raise LLMStreamError(f"Unsupported local device setting: {self._config.device}") from exc
        try:
            self._pipeline = transformers.pipeline(
                "text-generation",
                model=model_id,
                tokenizer=tokenizer_id,
                return_full_text=False,
                **pipeline_kwargs,
            )
        except Exception as exc:  # pragma: no cover - dependency guard
            raise LLMStreamError(
                f"Failed to load local transformers model '{model_id}': {exc}"
            ) from exc
        return self._pipeline

    @staticmethod
    def _messages_to_prompt(messages: List[Dict[str, str]]) -> str:
        lines = []
        for message in messages:
            role = message.get("role", "user")
            content = message.get("content", "")
            if role == "system":
                prefix = "[SYSTEM]"
            elif role == "assistant":
                prefix = "[ASSISTANT]"
            else:
                prefix = "[USER]"
            lines.append(f"{prefix} {content}")
        lines.append("[ASSISTANT]")
        return "\n".join(lines)

    async def stream_response(
        self,
        payload: PolicyRequestPayload,
        request_id: str,
        start_time: float,
        persona: Dict[str, Any],
        family_mode: bool,
        attempt: int,
    ) -> AsyncIterator[str]:
        pipeline = self._ensure_pipeline()
        messages = _build_messages(payload, family_mode)
        prompt = self._messages_to_prompt(messages)
        loop = asyncio.get_running_loop()
        try:
            outputs = await loop.run_in_executor(
                None,
                lambda: pipeline(
                    prompt,
                    max_new_tokens=self._config.max_new_tokens,
                    temperature=self._config.temperature,
                    do_sample=self._config.temperature > 0,
                ),
            )
        except Exception as exc:  # pragma: no cover - dependency guard
            raise LLMStreamError(f"Local model generation failed: {exc}") from exc
        if not outputs:
            raise LLMStreamError("Local model produced no output")
        generated = outputs[0]
        text = (
            generated.get("generated_text")
            or generated.get("text")
            or ""
        ).strip()
        if not text:
            raise LLMStreamError("Local model returned empty response")
        yield _format_sse(
            "token",
            {
                "token": text,
                "index": 0,
                "request_id": request_id,
                "source": self.backend,
            },
        )
        latency_ms = (time.perf_counter() - start_time) * 1000
        stats = {"tokens": len(text.split())}
        policy_response = PolicyResponse(
            content=text,
            latency_ms=round(latency_ms, 2),
            source=self.backend,
            request_id=request_id,
            meta={
                "persona": persona,
                "model": self.model_name,
                "stats": stats,
                "retries": attempt,
            },
        )
        await _publish_policy_metric(
            "policy.response",
            {
                "request_id": request_id,
                "status": "ok",
                "source": self.backend,
                "latency_ms": round(latency_ms, 2),
                "persona": persona,
                "retries": attempt,
                "text_length": len(payload.text),
                "model": self.model_name,
                "stats": stats,
            },
        )
        yield _format_sse("final", policy_response.dict())


def _create_llm_client() -> BaseLLMClient:
    backend = POLICY_BACKEND
    if backend == "openai":
        return OpenAILLMClient(OPENAI_CONFIG, MODEL_NAME)
    if backend == "local":
        return LocalTransformersClient(LOCAL_LLM_CONFIG, MODEL_NAME)
    return OllamaLLMClient(OLLAMA_URL, MODEL_NAME)


LLM_CLIENT = _create_llm_client()


async def policy_event_generator(payload: PolicyRequestPayload) -> AsyncIterator[str]:
    request_id = uuid.uuid4().hex
    family_mode = _family_mode(payload)
    persona = _build_persona_snapshot(payload, family_mode)
    start = time.perf_counter()
    prompt_guard = await MODERATION.guard_prompt(payload.text)
    source = LLM_CLIENT.backend
    if not prompt_guard.allowed:
        source = "moderation"
    response_moderation: Optional[Dict[str, str]] = None

    yield _format_sse(
        "start",
        {
            "request_id": request_id,
            "model": MODEL_NAME,
            "persona": persona,
            "source": source,
        },
    )

    if not prompt_guard.allowed:
        logger.info(
            "Policy request blocked by moderation (request_id=%s reason=%s)",
            request_id,
            prompt_guard.reason,
        )
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

    last_error: Optional[Exception] = None
    attempts_allowed = max(POLICY_RETRY_ATTEMPTS, 0)
    attempts_made = -1

    for attempt in range(attempts_allowed + 1):
        try:
            attempts_made = attempt
            async for chunk in LLM_CLIENT.stream_response(payload, request_id, start, persona, family_mode, attempt):
                event, data = _parse_sse(chunk)
                if (
                    event == "token"
                    and data.get("source") == LLM_CLIENT.backend
                    and not response_moderation
                ):
                    guard = await MODERATION.guard_response(data.get("token", ""))
                    if not guard.allowed:
                        response_moderation = {
                            "phase": "response",
                            "reason": guard.reason or "blocked",
                        }
                        logger.warning(
                            "Policy streaming token moderated (request_id=%s reason=%s)",
                            request_id,
                            guard.reason,
                        )
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
                        logger.warning(
                            "Policy final response sanitized (request_id=%s reason=%s)",
                            request_id,
                            guard.reason,
                        )
                    elif response_moderation:
                        data.setdefault("meta", {})["moderation"] = response_moderation
                        chunk = _format_sse("final", data)
                yield chunk
            return
        except LLMStreamError as exc:
            last_error = exc
            logger.warning(
                "%s stream failed (attempt %s/%s) for request %s: %s",
                LLM_CLIENT.backend,
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

    retries = attempts_made + 1 if attempts_made >= 0 else 0
    latency_ms = (time.perf_counter() - start) * 1000
    error_text = str(last_error) if last_error else "Unknown policy failure"
    logger.error(
        "Policy worker returning error response (request_id=%s retries=%s error=%s)",
        request_id,
        retries,
        error_text,
    )
    meta: Dict[str, Any] = {
        "persona": persona,
        "model": MODEL_NAME,
        "fallback": True,
        "status": "error",
        "error": error_text,
        "retries": retries,
    }
    if response_moderation:
        meta["moderation"] = response_moderation
    response = PolicyResponse(
        content="",
        latency_ms=round(latency_ms, 2),
        source=LLM_CLIENT.backend,
        request_id=request_id,
        meta=meta,
    )
    await _publish_policy_metric(
        "policy.response",
        {
            "request_id": request_id,
            "status": "error",
            "source": LLM_CLIENT.backend,
            "latency_ms": round(latency_ms, 2),
            "persona": persona,
            "model": MODEL_NAME,
            "retries": retries,
            "text_length": len(payload.text),
            "error": error_text,
        },
    )
    yield _format_sse("final", response.dict())


app = FastAPI(title="Kitsu Policy Worker", version="0.3.0")


@app.post("/respond")
async def respond(payload: PolicyRequestPayload) -> StreamingResponse:
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
        host=policy_cfg.bind_host,
        port=policy_cfg.bind_port,
        reload=os.getenv("UVICORN_RELOAD") == "1",
    )




