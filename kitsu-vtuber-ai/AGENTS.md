# AGENTS.md

## Purpose
This repository powers the Kitsu.exe VTuber AI runtime. Follow the conventions below when proposing changes so agents stay aligned.

## How to run (MVP)
1. Python 3.11 + Poetry installed.
2. Install deps: `poetry install`.
3. Configure `.env` from `.env.example` (set `ASR_INPUT_DEVICE` via `poetry run python -m apps.asr_worker.devices`).
4. Launch everything with one command:
   - Windows: `powershell -ExecutionPolicy Bypass -File scripts/run_pipeline.ps1 start`
   - Cross-platform: `poetry run python -m apps.pipeline_runner.main`
   - Services can be skipped with `PIPELINE_DISABLE` (e.g. `twitch_ingest,avatar_controller`).
5. Install `espeak-ng` if you expect real TTS audio; without it the worker stays in synthetic mode.

## Runtime dependencies
- OBS Studio with the **OBS WebSocket v5** plugin (`obsws-python` compatible).
- VTube Studio (optional) for avatar expressions.
- `ffmpeg`, `portaudio`, `libsndfile`, and `espeak-ng` on the host.
- Ollama running Llama 3 8B (or the configured fallback model) for policy responses.

## Quality
- Lint/format: `poetry run ruff . && poetry run black --check .`
- Types: `poetry run mypy`
- Tests: `poetry run pytest tests/test_asr_worker.py tests/test_asr_pipeline.py tests/test_telemetry_integration.py`
- Keep docs in sync (`README.md`, `RUN_FIRST.md`, `.env.example`) when behaviour changes.

## Style & restrictions
- Prefer asynchronous patterns (FastAPI/httpx/websockets) and avoid blocking calls.
- Do not add heavyweight dependencies without agreement.
- Keep audio code injectable so fake audio remains an option for CI.
- TTS: continue targeting Coqui/Piper with permissive voices and document licences in `licenses/third_party/`.
- LLM: default to Ollama + Llama 3 8B (note attribution in the README).

## Safety & moderation
- Family-friendly defaults stay enabled.
- Keep blocklists/regex in `configs/safety/`; moderation pipeline must return a friendly fallback when content is rejected.

## Memory
- Short-term ring buffer, long-term SQLite summaries. Respect the `RESTORE_CONTEXT` flag for restores.

## PR acceptance criteria
- CI/tests/lint pass.
- Change is scoped, well described, and docs updated when relevant.
- `.env.example`, README, RUN_FIRST, and scripts stay in sync with runtime expectations.
