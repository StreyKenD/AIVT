from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

router = APIRouter()

logger = logging.getLogger(__name__)
WEB_UI_ROOT = Path(__file__).resolve().parent.parent / "webui"


def _load_web_asset(filename: str) -> str:
    path = WEB_UI_ROOT / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Page not found")
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:  # pragma: no cover - defensive guard
        logger.error("Failed to read web asset %s: %s", path, exc)
        raise HTTPException(status_code=500, detail="Unable to load asset") from exc


@router.get("/webui/chat", response_class=HTMLResponse)
async def chat_console() -> HTMLResponse:
    return HTMLResponse(_load_web_asset("chat.html"))


@router.get("/webui/overlay", response_class=HTMLResponse)
async def overlay_page() -> HTMLResponse:
    return HTMLResponse(_load_web_asset("overlay.html"))
