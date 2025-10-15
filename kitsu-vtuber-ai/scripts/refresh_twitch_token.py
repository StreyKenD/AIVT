"""Refresh the Twitch chat OAuth token using the stored client credentials.

Usage:
    poetry run python scripts/refresh_twitch_token.py

Expected environment variables (stored in .env):
    TWITCH_CLIENT_ID
    TWITCH_CLIENT_SECRET
    TWITCH_REFRESH_TOKEN
The script reads .env, requests a new access + refresh token from Twitch, and
updates TWITCH_OAUTH_TOKEN (prefixed with 'oauth:') and TWITCH_REFRESH_TOKEN.
"""
from __future__ import annotations

import sys
from pathlib import Path

import httpx
from dotenv import dotenv_values, set_key

REQUIRED_KEYS = ("TWITCH_CLIENT_ID", "TWITCH_CLIENT_SECRET", "TWITCH_REFRESH_TOKEN")
TOKEN_ENDPOINT = "https://id.twitch.tv/oauth2/token"


def main() -> int:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        print(f"error: .env file not found at {env_path}", file=sys.stderr)
        return 1

    env = dotenv_values(env_path)
    missing = [key for key in REQUIRED_KEYS if not env.get(key)]
    if missing:
        print(
            "error: missing required environment values: "
            + ", ".join(missing)
            + "\nPopulate them in .env before running this script.",
            file=sys.stderr,
        )
        return 1

    payload = {
        "client_id": env["TWITCH_CLIENT_ID"],
        "client_secret": env["TWITCH_CLIENT_SECRET"],
        "refresh_token": env["TWITCH_REFRESH_TOKEN"],
        "grant_type": "refresh_token",
    }

    try:
        response = httpx.post(TOKEN_ENDPOINT, data=payload, timeout=10.0)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        print(f"error: Twitch token refresh failed: {exc}", file=sys.stderr)
        if exc.response is not None:
            print(f"Response: {exc.response.text}", file=sys.stderr)
        return 1

    data = response.json()
    access_token = data.get("access_token")
    refresh_token = data.get("refresh_token")
    if not access_token or not refresh_token:
        print(
            "error: Twitch response did not include access_token and refresh_token",
            file=sys.stderr,
        )
        print(f"Response payload: {data}", file=sys.stderr)
        return 1

    oauth_value = f"oauth:{access_token}"
    set_key(env_path, "TWITCH_OAUTH_TOKEN", oauth_value)
    set_key(env_path, "TWITCH_REFRESH_TOKEN", refresh_token)

    print("Successfully refreshed Twitch credentials:")
    print(f"  TWITCH_OAUTH_TOKEN={oauth_value[:20]}... (saved to .env)")
    print("  TWITCH_REFRESH_TOKEN updated in .env")
    print("Restart the Twitch ingest worker to apply the new token.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
