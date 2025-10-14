from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import os
import random
import re
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import httpx

from libs.common import configure_json_logging
from libs.telemetry import TelemetryClient


configure_json_logging("soak_harness")
logger = logging.getLogger("kitsu.soak")
DEFAULT_PROMPTS: Tuple[str, ...] = (
    "Chat está quieto demais, puxa assunto fofo.",
    "Um viewer pergunta como está a energia do show hoje.",
    "Reaja com empolgação a uma raid surpresa.",
    "Alguém pergunta qual será o próximo jogo.",
    "Crie uma piada PG-13 sobre raposas e café.",
    "Explique rapidamente o plano de conteúdo para amanhã.",
    "Chat pede um momento motivacional e fofo.",
)


@dataclass
class TurnRecord:
    index: int
    prompt: str
    policy_latency_ms: Optional[float] = None
    policy_source: Optional[str] = None
    tts_latency_ms: Optional[float] = None
    status: str = "ok"
    error: Optional[str] = None
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None

    def finalize(self) -> None:
        self.finished_at = time.time()


def _percentile(values: Sequence[float], percentile: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    k = (len(ordered) - 1) * (percentile / 100.0)
    lower = math.floor(k)
    upper = math.ceil(k)
    if lower == upper:
        return ordered[int(k)]
    weight = k - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _extract_speech_text(payload: str) -> str:
    match = re.search(r"<speech>(.*?)</speech>", payload, re.DOTALL | re.IGNORECASE)
    if not match:
        return payload.strip()
    content = match.group(1).strip()
    return re.sub(r"\s+", " ", content)


class SoakHarness:
    """Executa conversas sintéticas e registra métricas do pipeline."""

    def __init__(
        self,
        orchestrator_url: str,
        policy_url: str,
        *,
        telemetry_url: Optional[str] = None,
        orchestrator_token: Optional[str] = None,
        telemetry_api_key: Optional[str] = None,
        prompts: Iterable[str] = DEFAULT_PROMPTS,
        orchestrator_client: Optional[httpx.AsyncClient] = None,
        policy_client: Optional[httpx.AsyncClient] = None,
        telemetry_client: Optional[TelemetryClient] = None,
        telemetry_http_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self._orchestrator_url = orchestrator_url.rstrip("/")
        self._policy_url = policy_url.rstrip("/")
        self._telemetry_url = telemetry_url.rstrip("/") if telemetry_url else None
        self._orchestrator_token = orchestrator_token
        self._telemetry_api_key = telemetry_api_key
        self._prompts = tuple(prompts)
        if not self._prompts:
            raise ValueError("É necessário fornecer ao menos um prompt para o soak.")

        self._orchestrator_client = orchestrator_client
        self._policy_client = policy_client
        self._telemetry_client = telemetry_client
        self._telemetry_http_client = telemetry_http_client

        if self._telemetry_client is None and self._telemetry_url:
            self._telemetry_client = TelemetryClient(
                self._telemetry_url,
                api_key=telemetry_api_key,
                service="soak_harness",
            )

    async def run(
        self,
        *,
        duration_minutes: float,
        max_turns: Optional[int] = None,
        turn_interval: float = 12.0,
        warmup_turns: int = 3,
    ) -> Dict[str, Any]:
        """Executa o soak test e retorna o resumo agregado."""

        start_time = time.time()
        deadline = start_time + (duration_minutes * 60.0)
        history: List[Dict[str, str]] = []
        records: List[TurnRecord] = []
        failures: List[Dict[str, Any]] = []
        last_status: Dict[str, Any] | None = None
        telemetry_snapshot: Dict[str, Any] | None = None

        orch_client, created_orch = await self._ensure_orchestrator_client()
        policy_client, created_policy = await self._ensure_policy_client()
        telemetry_client = self._telemetry_client
        telemetry_http, created_telemetry_http = (
            await self._ensure_telemetry_http_client()
        )

        try:
            last_status = await self._fetch_status(orch_client)
            persona = (
                last_status.get("persona", {}) if isinstance(last_status, dict) else {}
            )
            chaos = float(persona.get("chaos_level", 0.35))
            energy = float(persona.get("energy", 0.6))
            family_mode = bool(persona.get("family_mode", True))
            style = str(persona.get("style", "kawaii"))

            turn_index = 0
            while time.time() < deadline:
                if max_turns is not None and turn_index >= max_turns:
                    break

                prompt = self._choose_prompt(turn_index)
                record = TurnRecord(index=turn_index + 1, prompt=prompt)
                records.append(record)

                try:
                    await self._submit_chat(orch_client, prompt)
                    policy_payload = await self._call_policy(
                        policy_client,
                        prompt,
                        history,
                        style=style,
                        chaos=chaos,
                        energy=energy,
                        family_mode=family_mode,
                    )
                    record.policy_latency_ms = policy_payload.get("latency_ms")
                    record.policy_source = policy_payload.get("source")
                    content = policy_payload.get("content", "")
                    speech_text = _extract_speech_text(content)
                    history.append({"role": "user", "content": prompt})
                    history.append({"role": "assistant", "content": content})

                    tts_latency_ms = await self._request_tts(orch_client, speech_text)
                    record.tts_latency_ms = tts_latency_ms

                    if telemetry_http is not None:
                        telemetry_snapshot = await self._fetch_metrics(telemetry_http)

                    last_status = await self._fetch_status(orch_client)
                    self._assert_modules_healthy(last_status)

                except (
                    Exception
                ) as exc:  # pragma: no cover - guard para tempo de execução real
                    record.status = "error"
                    record.error = str(exc)
                    failures.append(
                        {
                            "turn": record.index,
                            "prompt": prompt,
                            "error": str(exc),
                        }
                    )
                    logger.exception("Falha durante o turno %s", record.index)
                    await asyncio.sleep(5.0)
                finally:
                    record.finalize()

                turn_index += 1
                if turn_index < warmup_turns:
                    await asyncio.sleep(min(3.0, turn_interval))
                else:
                    await asyncio.sleep(turn_interval)

            duration_seconds = time.time() - start_time
            summary = self._build_summary(
                records,
                failures,
                duration_seconds,
                last_status,
                telemetry_snapshot,
            )

            if telemetry_client is not None:
                await telemetry_client.publish("soak.result", summary)

            return summary
        finally:
            if created_orch:
                await orch_client.aclose()
            if created_policy:
                await policy_client.aclose()
            if created_telemetry_http and telemetry_http is not None:
                await telemetry_http.aclose()
            if self._telemetry_client is not None and telemetry_client is None:
                await self._telemetry_client.aclose()

    async def _ensure_orchestrator_client(self) -> Tuple[httpx.AsyncClient, bool]:
        if self._orchestrator_client is not None:
            return self._orchestrator_client, False
        timeout = httpx.Timeout(10.0, connect=5.0, read=30.0)
        client = httpx.AsyncClient(base_url=self._orchestrator_url, timeout=timeout)
        self._orchestrator_client = client
        return client, True

    async def _ensure_policy_client(self) -> Tuple[httpx.AsyncClient, bool]:
        if self._policy_client is not None:
            return self._policy_client, False
        timeout = httpx.Timeout(15.0, connect=5.0, read=60.0)
        client = httpx.AsyncClient(base_url=self._policy_url, timeout=timeout)
        self._policy_client = client
        return client, True

    async def _ensure_telemetry_http_client(
        self,
    ) -> Tuple[Optional[httpx.AsyncClient], bool]:
        if not self._telemetry_url:
            return None, False
        if self._telemetry_http_client is not None:
            return self._telemetry_http_client, False
        timeout = httpx.Timeout(10.0, connect=5.0, read=15.0)
        client = httpx.AsyncClient(base_url=self._telemetry_url, timeout=timeout)
        self._telemetry_http_client = client
        return client, True

    async def _submit_chat(self, client: httpx.AsyncClient, prompt: str) -> None:
        headers = self._orchestrator_headers()
        response = await client.post(
            "/ingest/chat", json={"role": "user", "text": prompt}, headers=headers
        )
        response.raise_for_status()

    async def _call_policy(
        self,
        client: httpx.AsyncClient,
        prompt: str,
        history: List[Dict[str, str]],
        *,
        style: str,
        chaos: float,
        energy: float,
        family_mode: bool,
    ) -> Dict[str, Any]:
        payload = {
            "text": prompt,
            "persona_style": style,
            "chaos_level": chaos,
            "energy": energy,
            "family_friendly": family_mode,
            "recent_turns": history[-6:],
        }
        async with client.stream("POST", "/respond", json=payload) as response:
            response.raise_for_status()
            buffer: List[str] = []
            final_payload: Optional[Dict[str, Any]] = None
            async for line in response.aiter_lines():
                if line == "":
                    event, data = self._parse_sse(buffer)
                    buffer.clear()
                    if event == "final":
                        final_payload = data
                else:
                    buffer.append(line)
            if buffer:
                event, data = self._parse_sse(buffer)
                if event == "final":
                    final_payload = data

        if not final_payload:
            raise RuntimeError("Policy worker não retornou evento final")
        return final_payload

    async def _request_tts(
        self, client: httpx.AsyncClient, text: str
    ) -> Optional[float]:
        if not text:
            return None
        headers = self._orchestrator_headers()
        start = time.perf_counter()
        response = await client.post("/tts", json={"text": text}, headers=headers)
        response.raise_for_status()
        latency_ms = (time.perf_counter() - start) * 1000
        return round(latency_ms, 2)

    async def _fetch_status(self, client: httpx.AsyncClient) -> Dict[str, Any]:
        headers = self._orchestrator_headers()
        response = await client.get("/status", headers=headers)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("Resposta inesperada do orquestrador")
        return payload

    async def _fetch_metrics(self, client: httpx.AsyncClient) -> Dict[str, Any]:
        headers: Dict[str, str] = {"Accept": "application/json"}
        if self._telemetry_api_key:
            headers["X-API-Key"] = self._telemetry_api_key
        response = await client.get(
            "/metrics/latest", headers=headers, params={"window_seconds": 300}
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("Resposta inesperada da telemetria")
        return payload

    def _assert_modules_healthy(self, status_payload: Dict[str, Any]) -> None:
        modules = status_payload.get("modules")
        if not isinstance(modules, dict):
            raise RuntimeError("Snapshot de módulos inválido")
        unhealthy = [
            name for name, info in modules.items() if info.get("state") != "online"
        ]
        if unhealthy:
            raise RuntimeError(f"Módulos fora do ar: {', '.join(unhealthy)}")

    def _build_summary(
        self,
        records: Sequence[TurnRecord],
        failures: Sequence[Dict[str, Any]],
        duration_seconds: float,
        status_payload: Optional[Dict[str, Any]],
        telemetry_snapshot: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        policy_latencies = [
            rec.policy_latency_ms
            for rec in records
            if rec.policy_latency_ms is not None
        ]
        tts_latencies = [
            rec.tts_latency_ms for rec in records if rec.tts_latency_ms is not None
        ]

        def _aggregate(values: Sequence[float]) -> Dict[str, Optional[float]]:
            if not values:
                return {"avg": None, "p95": None, "max": None}
            if len(values) > 1:
                percentile = _percentile(values, 95.0)
                assert percentile is not None
                p95_value = round(percentile, 2)
            else:
                p95_value = round(values[0], 2)
            return {
                "avg": round(statistics.fmean(values), 2),
                "p95": p95_value,
                "max": round(max(values), 2),
            }

        summary = {
            "success": len(failures) == 0,
            "turns": len(records),
            "duration_seconds": round(duration_seconds, 2),
            "policy_latency_ms": _aggregate(policy_latencies),
            "tts_latency_ms": _aggregate(tts_latencies),
            "failures": failures,
            "generated_at": time.time(),
        }
        if status_payload:
            summary["last_status"] = status_payload
        if telemetry_snapshot:
            summary["telemetry_metrics"] = telemetry_snapshot
        return summary

    def _orchestrator_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._orchestrator_token:
            headers["Authorization"] = f"Bearer {self._orchestrator_token}"
        return headers

    def _choose_prompt(self, turn_index: int) -> str:
        if turn_index < len(self._prompts):
            return self._prompts[turn_index]
        return random.choice(self._prompts)

    @staticmethod
    def _parse_sse(lines: Sequence[str]) -> Tuple[str, Dict[str, Any]]:
        event = "message"
        data: Dict[str, Any] = {}
        for line in lines:
            if line.startswith("event:"):
                event = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                payload = line.split(":", 1)[1].strip()
                if payload:
                    data = json.loads(payload)
        return event, data


async def _async_main(args: argparse.Namespace) -> int:
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO))
    telemetry_url = args.telemetry_url or os.getenv("TELEMETRY_API_URL")
    telemetry_key = args.telemetry_api_key or os.getenv("TELEMETRY_API_KEY")
    orchestrator_token = args.orchestrator_token or os.getenv("ORCHESTRATOR_API_KEY")

    harness = SoakHarness(
        orchestrator_url=args.orchestrator_url,
        policy_url=args.policy_url,
        telemetry_url=telemetry_url,
        telemetry_api_key=telemetry_key,
        orchestrator_token=orchestrator_token,
    )

    summary = await harness.run(
        duration_minutes=args.duration_minutes,
        max_turns=args.max_turns,
        turn_interval=args.turn_interval,
        warmup_turns=args.warmup_turns,
    )

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        logger.info("Resumo salvo em %s", output_path)

    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if summary.get("success") else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Executa o soak test de 2h da Kitsu.exe"
    )
    parser.add_argument(
        "--orchestrator-url",
        default=os.getenv("ORCHESTRATOR_URL", "http://127.0.0.1:8000"),
        help="Endpoint base do orquestrador",
    )
    parser.add_argument(
        "--policy-url",
        default=os.getenv("SOAK_POLICY_URL")
        or os.getenv("POLICY_URL")
        or "http://127.0.0.1:8081",
        help="Endpoint base do policy worker",
    )
    parser.add_argument(
        "--telemetry-url",
        default=os.getenv("SOAK_TELEMETRY_URL"),
        help="Endpoint da API de telemetria (opcional)",
    )
    parser.add_argument(
        "--telemetry-api-key",
        default=None,
        help="Chave da API de telemetria para consultas/ingestão",
    )
    parser.add_argument(
        "--orchestrator-token",
        default=None,
        help="Token bearer para o orquestrador",
    )
    parser.add_argument(
        "--duration-minutes",
        type=float,
        default=float(os.getenv("SOAK_DURATION_MINUTES", "120")),
        help="Duração total do teste em minutos (padrão 120)",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=None,
        help="Limite de turnos (útil para execução curta ou CI)",
    )
    parser.add_argument(
        "--turn-interval",
        type=float,
        default=float(os.getenv("SOAK_TURN_INTERVAL_SECONDS", "15")),
        help="Intervalo entre turnos em segundos (padrão 15)",
    )
    parser.add_argument(
        "--warmup-turns",
        type=int,
        default=int(os.getenv("SOAK_WARMUP_TURNS", "3")),
        help="Quantidade de turnos de aquecimento antes do intervalo completo",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Arquivo opcional para salvar o resumo em JSON",
    )
    parser.add_argument(
        "--log-level",
        default=os.getenv("SOAK_LOG_LEVEL", "INFO"),
        help="Nível de log para execução",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return asyncio.run(_async_main(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
