# AGENTS.md

## Purpose
This repository is part of the Kitsu.exe project (VTuber AI). Follow these contracts when proposing changes.

## How to run (MVP)
- Python 3.11+
- Install deps: `poetry install` (or `pip install -r requirements.txt`)
- Configure `.env` from `.env.example`
- Dev:
  - Orchestrator/Backend: `uvicorn apps.control_panel_backend.main:app --reload`
  - (Repo B) Telemetry API: `uvicorn api.main:app --reload`
  - (Repo B) SvelteKit UI: `pnpm i && pnpm dev`

## Runtime dependencies
- OBS Studio with the **OBS WebSocket v5** plugin enabled (`obsws-python` pinned to `1.7.2`).
- External audio/video binaries: `ffmpeg`, `portaudio`, `libsndfile`.
- Python 3.11+ and Poetry for isolated environments; keep the version documented in the README.

## Quality
- Lint/format: `ruff . && black --check .`
- Types: `mypy` (permissive level)
- Tests: `pytest -q` (goal: pass 100% of the smoke tests)
- Commits: Conventional (`feat:`, `fix:`, `chore:`…)

## Style and restrictions
- Asynchronous by default (FastAPI/httpx/websockets).
- Do not add heavy libraries without justification.
- No unnecessary `any` in new code (TS/pytypes).
- TTS: **Coqui-TTS** with a permissive model (non-XTTS) – keep the model card in `licenses/third_party/`.
- LLM: **Ollama** with **Llama 3 8B** (attribution required in the README).

## Safety/Moderation
- “Family mode” ON by default.
- Blocklists/regex in `configs/safety/`.
- Filter profanity and TOS content; provide a friendly fallback.

## Memory
- Short-term: ring buffer (last N messages).
- Persistent: SQLite summaries; restore on boot when `RESTORE_CONTEXT=true`.

## PR acceptance criteria
- Build and tests pass.
- Lint/format OK.
- PR is small, clearly described, and checklist updated.
- Update `RUN_FIRST.md` if you change endpoints.
