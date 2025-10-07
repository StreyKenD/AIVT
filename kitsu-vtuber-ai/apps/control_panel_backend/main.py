from __future__ import annotations

from typing import Any, Dict

from fastapi import FastAPI

app = FastAPI(title="Kitsu Control Panel Backend", version="0.1.0")


@app.get("/status")
def read_status() -> Dict[str, Any]:
    """Basic health endpoint with placeholder module states."""
    return {
        "status": "ok",
        "persona": {
            "style": "kawaii",
            "chaos_level": 0.2,
        },
        "modules": {
            "orchestrator": {"state": "idle", "latency_ms": 12},
            "asr_worker": {"state": "idle", "latency_ms": 32},
            "policy_worker": {"state": "idle", "latency_ms": 45},
            "tts_worker": {"state": "idle", "latency_ms": 52},
        },
    }
