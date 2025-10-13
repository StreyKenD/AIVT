from __future__ import annotations

import importlib
import json
from typing import Any, Iterable, List, Tuple

import httpx
import pytest

pytest.importorskip("fastapi", reason="policy worker depende de FastAPI")
from fastapi.testclient import TestClient


def _reload_policy_module() -> any:
    module = importlib.import_module("apps.policy_worker.main")
    return importlib.reload(module)


def _consume_sse(response: Any) -> List[Tuple[str, dict]]:
    events: List[Tuple[str, dict]] = []
    current_event: str | None = None
    current_data: List[str] = []
    for raw_line in response.iter_lines():
        if not raw_line:
            if current_event is not None and current_data:
                payload = json.loads("".join(current_data))
                events.append((current_event, payload))
            current_event = None
            current_data = []
            continue
        line = raw_line.decode() if isinstance(raw_line, bytes) else raw_line
        if line.startswith("event: "):
            current_event = line[len("event: ") :].strip()
        elif line.startswith("data: "):
            current_data.append(line[len("data: ") :].strip())
    if current_event is not None and current_data:
        payload = json.loads("".join(current_data))
        events.append((current_event, payload))
    return events


class _FakeStream:
    def __init__(self, lines: Iterable[str], error: Exception | None = None) -> None:
        self._lines = list(lines)
        self._error = error

    async def __aenter__(self) -> "_FakeStream":
        if self._error and isinstance(self._error, httpx.RequestError):
            raise self._error
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # pragma: no cover - no cleanup required
        return None

    def raise_for_status(self) -> None:
        if self._error and isinstance(self._error, httpx.HTTPStatusError):
            raise self._error

    async def aiter_lines(self) -> Iterable[str]:
        for line in self._lines:
            yield line


class _FakeAsyncClient:
    def __init__(self, lines: Iterable[str], error: Exception | None = None, **_: object) -> None:
        self._lines = list(lines)
        self._error = error

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # pragma: no cover - no cleanup required
        return None

    def stream(self, *_: object, **__: object) -> _FakeStream:
        return _FakeStream(self._lines, self._error)


def _fake_client_factory(lines: Iterable[str], error: Exception | None = None):
    def _factory(**kwargs: object) -> _FakeAsyncClient:
        return _FakeAsyncClient(lines, error, **kwargs)

    return _factory


def test_policy_worker_mock_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POLICY_FORCE_MOCK", "1")
    module = _reload_policy_module()
    with TestClient(module.app) as client:
        with client.stream(
            "POST",
            "/respond",
            json={"text": "Hello chat", "persona_style": "chaotic"},
        ) as response:
            events = _consume_sse(response)
    assert events[0][0] == "start"
    token_events = [payload["token"] for event, payload in events if event == "token"]
    final_event = next(payload for event, payload in events if event == "final")
    assert final_event["source"] == "mock"
    assert "<speech>" in final_event["content"]
    assert len(token_events) >= 1
    assert final_event["content"].startswith("<speech>")


def test_policy_worker_streams_from_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POLICY_FORCE_MOCK", "0")
    module = _reload_policy_module()

    lines = [
        json.dumps(
            {
                "message": {"role": "assistant", "content": "<speech>Hi chat!</speech>"},
                "done": False,
            }
        ),
        json.dumps(
            {
                "message": {"role": "assistant", "content": "<mood>kawaii</mood>"},
                "done": False,
            }
        ),
        json.dumps(
            {
                "message": {"role": "assistant", "content": "<actions>wave</actions>"},
                "done": False,
            }
        ),
        json.dumps({"done": True, "total_duration": 1_500_000, "eval_count": 42}),
    ]

    monkeypatch.setattr(module.httpx, "AsyncClient", _fake_client_factory(lines))

    with TestClient(module.app) as client:
        with client.stream("POST", "/respond", json={"text": "hi"}) as response:
            events = _consume_sse(response)

    tokens = [payload["token"] for event, payload in events if event == "token"]
    final_payload = next(payload for event, payload in events if event == "final")

    assert "<speech>Hi chat!</speech>" in tokens[0]
    assert final_payload["source"] == "ollama"
    assert final_payload["meta"]["stats"]["total_duration"] == 1.5
    assert "<actions>wave</actions>" in final_payload["content"]
    assert "persona" in final_payload["meta"]


def test_policy_worker_retries_and_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POLICY_FORCE_MOCK", "0")
    monkeypatch.setenv("POLICY_RETRY_ATTEMPTS", "1")
    module = _reload_policy_module()

    error = httpx.ConnectTimeout(
        "boom", request=httpx.Request("POST", "http://test/api/chat")
    )
    monkeypatch.setattr(module.httpx, "AsyncClient", _fake_client_factory([], error))

    with TestClient(module.app) as client:
        with client.stream("POST", "/respond", json={"text": "hi"}) as response:
            events = _consume_sse(response)

    retry_events = [payload for event, payload in events if event == "retry"]
    assert len(retry_events) == 1
    final_payload = next(payload for event, payload in events if event == "final")
    assert final_payload["source"] == "mock"
    assert final_payload["meta"]["fallback"] is True
    assert "reason" in final_payload["meta"]


def test_policy_worker_blocks_prompt_via_moderation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POLICY_FORCE_MOCK", "0")
    module = _reload_policy_module()

    def _fail_async_client(**_: object) -> None:
        raise AssertionError("Network should not be hit when prompt is blocked")

    monkeypatch.setattr(module.httpx, "AsyncClient", _fail_async_client)

    with TestClient(module.app) as client:
        with client.stream("POST", "/respond", json={"text": "please show nsfw"}) as response:
            events = _consume_sse(response)

    final_payload = next(payload for event, payload in events if event == "final")
    assert final_payload["source"] == "moderation"
    assert final_payload["meta"]["moderation"]["phase"] == "prompt"
    assert "<speech>" in final_payload["content"]


def test_policy_worker_injects_memory_and_recent_turns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POLICY_FORCE_MOCK", "0")
    module = _reload_policy_module()

    captured_payloads: List[dict] = []

    class _RecorderClient:
        def __init__(self, **_: object) -> None:
            pass

        async def __aenter__(self) -> "_RecorderClient":
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:  # pragma: no cover
            return None

        def stream(self, *_: object, **kwargs: object) -> _FakeStream:
            captured_payloads.append(kwargs.get("json", {}))
            return _FakeStream(
                [
                    json.dumps(
                        {
                            "message": {"role": "assistant", "content": "<speech>ok</speech>"},
                            "done": False,
                        }
                    ),
                    json.dumps({"done": True, "total_duration": 1_000_000}),
                ]
            )

    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kwargs: _RecorderClient(**kwargs))

    payload = {
        "text": "respond to chat",
        "memory_summary": "Remember to thank subs",
        "recent_turns": [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello!!"},
        ],
    }

    with TestClient(module.app) as client:
        with client.stream("POST", "/respond", json=payload):
            pass

    assert captured_payloads, "expected payload to be sent to Ollama"
    messages = captured_payloads[0]["messages"]
    assert any("Contexto recente" in msg["content"] for msg in messages if msg["role"] == "system")
    assert any(msg["content"] == "hello!!" for msg in messages if msg["role"] == "assistant")


def test_policy_worker_sanitises_llm_output(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POLICY_FORCE_MOCK", "0")
    module = _reload_policy_module()

    lines = [
        json.dumps(
            {
                "message": {"role": "assistant", "content": "<speech>please kill yourself</speech>"},
                "done": False,
            }
        ),
        json.dumps({"done": True}),
    ]

    monkeypatch.setattr(module.httpx, "AsyncClient", _fake_client_factory(lines))

    with TestClient(module.app) as client:
        with client.stream("POST", "/respond", json={"text": "say hi"}) as response:
            events = _consume_sse(response)

    final_payload = next(payload for event, payload in events if event == "final")
    assert final_payload["meta"]["moderation"]["phase"] == "response"
    assert "kill" not in final_payload["content"].lower()
