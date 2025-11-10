from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any, Dict

import httpx


DEFAULT_BASE_URL = "http://127.0.0.1:9000"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Send a one-off chat message to the orchestrator and print the response. "
            "The pipeline runner must be active before you call this script."
        )
    )
    parser.add_argument(
        "--text",
        required=True,
        help="User message to send to the VTuber brain.",
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"Orchestrator base URL (default: {DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--preset",
        help="Optional persona preset to apply before sending the message (e.g. cozy, hype).",
    )
    parser.add_argument(
        "--no-tts",
        action="store_true",
        help="Skip TTS playback; only produce the policy response.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="HTTP timeout in seconds for orchestrator requests.",
    )
    return parser


async def _apply_preset_if_requested(
    client: httpx.AsyncClient,
    preset: str | None,
) -> None:
    if not preset:
        return
    response = await client.post("/control/preset", json={"preset": preset})
    response.raise_for_status()
    data = response.json()
    print(f"Preset set to '{data.get('preset', preset)}'\n")


def _print_payload(payload: Dict[str, Any]) -> None:
    status = payload.get("status")
    if status:
        print(f"Request status: {status}")
    body = payload.get("payload") or {}
    content = body.get("content", "").strip()
    if content:
        print("\nAssistant response:\n")
        print(content)
    meta = body.get("meta") or {}
    if meta:
        print("\nMetadata:")
        print(json.dumps(meta, indent=2))


async def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    async with httpx.AsyncClient(base_url=base_url, timeout=args.timeout) as client:
        try:
            await _apply_preset_if_requested(client, args.preset)
            response = await client.post(
                "/chat/respond",
                json={"text": args.text, "play_tts": not args.no_tts},
            )
        except httpx.RequestError as exc:
            print(f"Failed to reach orchestrator at {base_url}: {exc}", file=sys.stderr)
            return 1

    if response.status_code == 202:
        print(
            "Policy worker is processing the request (HTTP 202). Check /stream for token events."
        )
        return 0

    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        print(
            f"Orchestrator returned HTTP {exc.response.status_code}: {exc}",
            file=sys.stderr,
        )
        try:
            error_payload = exc.response.json()
        except ValueError:
            error_payload = exc.response.text
        print(f"Details: {error_payload}", file=sys.stderr)
        return 1

    try:
        payload = response.json()
    except ValueError:
        print("Received non-JSON response from orchestrator.", file=sys.stderr)
        print(response.text)
        return 1

    _print_payload(payload)
    return 0


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
    except KeyboardInterrupt:
        exit_code = 130
    sys.exit(exit_code)
