from __future__ import annotations

import logging
import os
import time
from typing import Tuple

import httpx
from fastapi import FastAPI
from pydantic import BaseModel, Field

logger = logging.getLogger("kitsu.policy")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

DEFAULT_MODEL = os.getenv("LLM_MODEL_NAME", "llama3:8b-instruct-q4")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
POLICY_FORCE_MOCK = os.getenv("POLICY_FORCE_MOCK", "0") == "1"

PROMPT_TEMPLATE = """
You are Kitsu.exe, a chaotic-but-kawaii VTuber fox. Speak English.
Persona style: {style}. Family friendly mode is ALWAYS ON.
You must answer in XML with the structure:
<speech>text to speak</speech><mood>kawaii|chaotic</mood><actions>comma,separated,actions</actions>
The <speech> must be short (<90 tokens), upbeat, and match the persona.
Avoid disallowed content and keep PG-13.
User message: "{message}"
""".strip()


class PolicyRequest(BaseModel):
    text: str = Field(..., min_length=1)
    persona_style: str = Field("kawaii", description="Current persona style")


class PolicyResponse(BaseModel):
    content: str
    latency_ms: float
    source: str


async def call_ollama(prompt: str, timeout: float = 15.0) -> Tuple[str, str]:
    if POLICY_FORCE_MOCK:
        return build_mock_reply(prompt), "mock"
    try:
        async with httpx.AsyncClient(base_url=OLLAMA_URL, timeout=timeout) as client:
            response = await client.post(
                "/api/generate",
                json={"model": DEFAULT_MODEL, "prompt": prompt, "stream": False},
            )
            response.raise_for_status()
            payload = response.json()
            content = payload.get("response") or ""
            if "<speech>" not in content:
                content = build_mock_reply(prompt)
                return content, "mock"
            return content, "ollama"
    except Exception as exc:  # pragma: no cover - network conditions
        logger.warning("Falling back to mock policy response: %s", exc)
        return build_mock_reply(prompt), "mock"


def build_mock_reply(prompt: str) -> str:
    if "chaotic" in prompt.lower():
        mood = "chaotic"
        speech = "Eeee! Let's cause some wholesome chaos together!"
        actions = "sweat,heart"
    else:
        mood = "kawaii"
        speech = "Hehe~ Staying adorable and safe for chat!"
        actions = "sparkle,heart"
    return f"<speech>{speech}</speech><mood>{mood}</mood><actions>{actions}</actions>"


async def generate_response(payload: PolicyRequest) -> PolicyResponse:
    prompt = PROMPT_TEMPLATE.format(style=payload.persona_style, message=payload.text)
    start = time.perf_counter()
    content, source = await call_ollama(prompt)
    elapsed = (time.perf_counter() - start) * 1000
    return PolicyResponse(content=content, latency_ms=round(elapsed, 2), source=source)


app = FastAPI(title="Kitsu Policy Worker", version="0.2.0")


@app.post("/respond", response_model=PolicyResponse)
async def respond(payload: PolicyRequest) -> PolicyResponse:
    logger.info("Policy request text=%s style=%s", payload.text, payload.persona_style)
    return await generate_response(payload)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "apps.policy_worker.main:app",
        host="0.0.0.0",
        port=8081,
        reload=os.getenv("UVICORN_RELOAD") == "1",
    )
