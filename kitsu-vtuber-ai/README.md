# Kitsu.exe Core (kitsu-vtuber-ai)

Kitsu.exe is the backbone of the "Kitsu" VTuber AI – a kawaii, chaotic fox that chats, reacts, and drives her avatar live on stream. The main pipeline follows **ASR → LLM → TTS**, with integrations for Twitch, OBS, and VTube Studio. See [RUN_FIRST.md](RUN_FIRST.md) for the initial local setup checklist and mandatory licensing notes.

```
[Twitch Chat / Voice]
        |
        v
  [ASR Worker] --text--> [Policy Worker (LLM)] --speech/mood--> [TTS Worker]
        |                                             |
        |                                             v
        +--> [Orchestrator] <--> [OBS Controller] <--> [Avatar Controller]
                              \--> [Control Panel Backend]
```

## Vision
- Initial persona: **kawaii & chaotic**, English-speaking.
- Distributed architecture with asynchronous workers.
- Short-term and persistent memory with SQLite summaries.
- External telemetry and control panel (see the `kitsu-telemetry` repository).

## Runtime dependencies
- Python 3.11+ with [Poetry](https://python-poetry.org/) for managing the virtual environment.
- `obsws-python 1.7.2`, aligned with the **OBS WebSocket v5** protocol (enable the native plugin in OBS 28+).
- External audio/video binaries: `ffmpeg`, `portaudio`, `libsndfile`, and the drivers for your interfaces.
- Optional but recommended for development: OBS Studio and VTube Studio to validate integrations.

### Microphone capture on Windows
- List the supported devices for the `sounddevice` and `PyAudio` backends:
  ```powershell
  poetry run python -m apps.asr_worker.devices
  ```
- Use `--json` to integrate with scripts or store the full list: `poetry run python -m apps.asr_worker.devices --json > devices.json`.
- Set `ASR_INPUT_DEVICE` to the numeric identifier shown in the `Identifier` column. If no backend is available, set `ASR_FAKE_AUDIO=1` to keep the worker silent during tests.
- Adjust `ASR_SAMPLE_RATE`, `ASR_FRAME_MS`, and `ASR_SILENCE_MS` if you need to sync the frame timing with capture cards or specific audio interfaces (WebRTC VAD supports 10, 20, or 30 ms frames).

### Installing `ffmpeg`, `libsndfile`, and `portaudio` on Windows
- Via [Chocolatey](https://chocolatey.org/install):
  ```powershell
  choco install ffmpeg portaudio libsndfile
  ```
- Without a package manager:
  1. Download the "release full" build of FFmpeg from <https://www.gyan.dev/ffmpeg/builds/> and extract it to `C:\ffmpeg` (add `C:\\ffmpeg\\bin` to `PATH`).
  2. Install `libsndfile` using the official `.exe` at <https://github.com/libsndfile/libsndfile/releases> and make sure the `bin/` folder is on `PATH`.
  3. Copy `portaudio_x64.dll` from the precompiled package at <http://files.portaudio.com/download.html> to a folder on `PATH` (e.g., `C:\AudioSDK`).
- Validate the installation in PowerShell (adjust the paths to match your DLL locations):
  ```powershell
  ffmpeg -version
  Get-Command ffmpeg
  Get-ChildItem "C:\\AudioSDK" -Filter "*sndfile*.dll"
  Get-ChildItem "C:\\AudioSDK" -Filter "*portaudio*.dll"
  ```

## Running locally

### Quick start (recommended)

1. Install dependencies with `poetry install`.
2. Configure `.env` (copy from `.env.example`).
3. Launch the full stack:
   ```powershell
   # Windows
   powershell -ExecutionPolicy Bypass -File .\scripts\run_pipeline.ps1 start
   ```
   or
   ```bash
   # Cross-platform (inside Poetry)
   poetry run python -m apps.pipeline_runner.main
   ```

Use `PIPELINE_DISABLE` to skip integrations you do not have credentials for (e.g. `PIPELINE_DISABLE=twitch_ingest,avatar_controller`). The runner streams service logs and restarts crashes automatically.

Before launching the policy worker the supervisor pings `OLLAMA_URL`; if the socket is unreachable, the service is skipped with a clear warning (override with `PIPELINE_SKIP_OLLAMA_CHECK=1` when you deliberately want to start in a degraded mode).
Set `POLICY_URL` in `.env` to the policy worker base URL (defaults to `http://127.0.0.1:8081`) so the orchestrator can reach it, and expose the TTS HTTP server via `TTS_HOST`, `TTS_PORT`, and `TTS_API_URL` (defaults to `http://127.0.0.1:8070`).

### Manual shells (when you need to debug a single worker)

```bash
poetry run uvicorn apps.orchestrator.main:app --reload --host ${ORCH_HOST:-127.0.0.1} --port ${ORCH_PORT:-8000}
poetry run uvicorn apps.control_panel_backend.main:app --reload --host ${CONTROL_PANEL_HOST:-127.0.0.1} --port ${CONTROL_PANEL_PORT:-8100}
poetry run python -m apps.asr_worker.main
poetry run python -m apps.policy_worker.main
poetry run python -m apps.tts_worker.main
```

> **Attribution**: the default LLM is **Llama 3 8B Instruct** served by Ollama; ensure the license terms in `licenses/` are followed before public demos.

## Essential environment variables
These variables control how the orchestrator exposes HTTP/WebSocket endpoints and where events are forwarded for telemetry:

- `ORCH_HOST`: bind interface used by `uvicorn` (default `127.0.0.1`). Use `0.0.0.0` when exposing the API to other machines or to a UI hosted outside the local host.
- `ORCH_PORT`: public port for the orchestrator. Align this value with `PUBLIC_ORCH_BASE_URL` and `PUBLIC_ORCH_WS_URL` in the `kitsu-telemetry` repository; `8000` is the recommended development value.
- `TELEMETRY_API_URL`: base URL (e.g., `http://127.0.0.1:8001`) where state events are published. When empty, the orchestrator runs without external telemetry.
- `TELEMETRY_API_KEY` / `ORCHESTRATOR_API_KEY`: optional tokens to protect the `/events` endpoint (telemetry) and `/persona`/`/toggle` when accessed by external integrations.
- `ORCHESTRATOR_URL`: HTTP address used by workers and integrations (Twitch, OBS, VTS) to publish events to the orchestrator.

> Tip: once `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET`, and `TWITCH_REFRESH_TOKEN` are stored in `.env`, refresh the chat token any time with `poetry run python scripts/refresh_twitch_token.py`.
- `TTS_OUTPUT_DIR`: folder where synthesized audio is cached (default `artifacts/tts`).
- `TTS_MODEL_NAME` / `PIPER_MODEL`: identifiers for the Coqui/Piper models loaded by the workers (see [TTS Worker](#tts-worker)).
- `TWITCH_CHANNEL` / `TWITCH_OAUTH_TOKEN`: credentials for the `twitchio` bot responsible for reading commands in real time. Provide `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET`, and `TWITCH_REFRESH_TOKEN` if you want to let the helper script rotate tokens automatically. Set `TWITCH_BOT_NICK` and `TWITCH_DEFAULT_SCENE` to customize the nickname or fallback scene.
- `OBS_WS_URL` / `OBS_WS_PASSWORD`: **obs-websocket v5** endpoint and password configured in OBS. `OBS_SCENES` accepts a comma-separated list used by the demo script; `OBS_PANIC_FILTER` indicates the filter triggered by the panic macro.
- `VTS_URL` / `VTS_AUTH_TOKEN`: WebSocket endpoint and persistent token for VTube Studio. Adjust `VTS_PLUGIN_NAME`/`VTS_DEVELOPER` to identify the plugin inside VTS settings.
- `KITSU_LOG_ROOT`: directory where each service writes daily-rotated JSON `.log` files (default `logs`). Relative paths are resolved to an absolute location by the pipeline runner so every worker lands in the same folder.
- `GPU_METRICS_INTERVAL_SECONDS`: frequency, in seconds, for the NVML collector that publishes `hardware.gpu` events to telemetry.

### Orchestrator CORS
`apps.orchestrator.main` enables `CORSMiddleware` automatically. Set `ORCH_CORS_ALLOW_ORIGINS` with a comma-separated list of allowed origins (for example, `http://localhost:5173,http://127.0.0.1:5173`). By default, the middleware allows `GET`, `POST`, `OPTIONS`, and WebSocket upgrades; use `ORCH_CORS_ALLOW_ALL=1` only in controlled development environments.

## Structure
- `apps/`: main services (ASR, policy, TTS, orchestration, OBS/VTS/Twitch integrations, control panel backend).
- `libs/`: shared utilities and memory.
- `configs/`: safety profiles and moderation rules.
- `scripts/`: development utilities.
- `tests/`: smoke tests powered by `pytest`.

## Quality
- Lockfile: `poetry lock --check`
- Lint: `poetry run ruff .`
- Formatting: `poetry run black --check .`
- Typing: `poetry run mypy`
- Tests: `poetry run pytest -q` (or `python -m pytest -q` after `python -m pip install pytest pytest-asyncio`)
- Pre-commit: `poetry run pre-commit run --all-files`

> Install the hooks locally with `poetry run pre-commit install` (the [`./.pre-commit-config.yaml`](.pre-commit-config.yaml) file already targets `apps/`, `libs/`, and `tests/`).

## QA & soak harness
- Set `SOAK_POLICY_URL`/`SOAK_TELEMETRY_URL` in `.env` to match the environment.
- Start all services (`powershell -ExecutionPolicy Bypass -File scripts/run_pipeline.ps1 start`).
- Run `poetry run python -m kitsu_vtuber_ai.apps.soak_harness.main --duration-minutes 120 --output artifacts/soak/summary.json` (use `--max-turns` for quick executions).
- The summary aggregates per-stage average/p95 latencies and publishes a `soak.result` event consumed by the dashboard (**Soak test results**).

### Structured logs and hardware metrics
- Every service (`apps/`) uses `libs.common.configure_json_logging` to emit structured logs both to `stderr` and to the directory configured by `KITSU_LOG_ROOT`. Each line is a JSON payload with `ts`, `service`, `logger`, `level`, `message`, and optional extras.
- The orchestrator starts an NVML-based `GPUMonitor` that periodically publishes `hardware.gpu` events (temperature, utilization, fan, memory, and power) to the telemetry API. Adjust `GPU_METRICS_INTERVAL_SECONDS` to control the frequency or remove `pynvml` from the environment to disable collection.

## Licenses and required credits
- **Llama 3 8B Instruct (Meta)** via Ollama – review `licenses/third_party/llama3_license.pdf` before any public distribution or recorded demo.
- **Coqui-TTS (selected model)** – requirements detailed in `licenses/third_party/coqui_tts_model_card.pdf`, including commercial usage limits.
- **Live2D Avatar “Lumi”** – explicit attribution per `licenses/third_party/live2d_lumi_license.pdf` in streams, videos, and promotional materials.

Keep these references available whenever you share builds or recordings.

## Operations and release
### Pilot checklist
- Before: run the latest soak, validate audio/video (OBS + VTS), review tokens and presets, prepare the panic macro.
- During: keep the dashboard open, log incidents in `#kitsu-ops`, inspect `/status` every 30 minutes.
- After show: export telemetry CSV, run a short soak (`--max-turns 5`), archive incidents/clips.

### Rollback and incidents
1. Hit the panic button (mute + BRB scene).
2. Restart specific services with `scripts/service_manager.ps1`.
3. If needed, stop everything with `scripts/run_pipeline.ps1 -Action stop`.
4. Document the incident in `docs/incidents/` and attach metrics/CSV.

### Packaging the release
- Generate the Windows-first bundle via `pwsh scripts/package_release.ps1 -OutputPath artifacts/release -Zip`.
- The script copies `README.md`, `RUN_FIRST.md`, `.env.example`, PowerShell scripts, and `licenses/third_party/`.
- Share the ZIP only after completing the pilot and QA checklist.

## Orchestrator APIs
- `GET /status`: complete snapshot of persona, modules, current scene, and latest TTS request.
- `POST /toggle/{module}`: enable/disable modules (`asr_worker`, `policy_worker`, `tts_worker`, `avatar_controller`, `obs_controller`, `twitch_ingest`).
- `POST /persona`: adjust style (`kawaii`, `chaotic`, `calm`), chaos/energy levels, and family mode.
- `POST /tts`: register a speech request (text + preferred voice).
- `POST /obs/scene`: change the active OBS scene (with automatic reconnection and panic macro).
- `POST /vts/expr`: apply an expression on the avatar via VTube Studio (authenticated WebSocket).
- `POST /ingest/chat`: record chat/assistant messages to feed memory.
- `POST /events/asr`: receive `asr_partial`/`asr_final` events from the ASR worker and broadcast them over WebSocket.
- `WS /stream`: real-time broadcast of the events above and simulated metrics.

## Memory
- Short conversation buffer (ring buffer) with synthetic summaries every 6 messages.
- Summaries persisted in SQLite (`data/memory.sqlite3`) with automatic restoration (`RESTORE_CONTEXT=true`, default window 2h).
- Exposed on `/status` under `memory.current_summary` and `restore_context`.

## Policy / LLM
- `apps/policy_worker` queries Ollama (`OLLAMA_URL`) using **Mixtral** by default (`LLM_MODEL_NAME=mixtral:8x7b-instruct-q4_K_M`). Run `ollama pull mixtral:8x7b-instruct-q4_K_M` before the first boot.
- The `POST /respond` endpoint returns an SSE stream (`text/event-stream`) with `start`, `token`, `retry`, and `final` events. Each `token` represents the incremental XML stream; the `final` event includes metrics (`latency_ms`, `stats`) and persona metadata.
- The prompt combines system instructions and few-shots to reinforce the kawaii/chaotic style, energy/chaos levels (`chaos_level`, `energy`), and family mode (`POLICY_FAMILY_FRIENDLY`).
- Family-friendly filtering is enforced by a synchronous moderation pipeline (`configs/safety/` + `libs.safety.ModerationPipeline`). Forbidden prompts return a safe message immediately; final responses go through an additional scan and, if necessary, are sanitized before reaching TTS.
- The worker retries (`POLICY_RETRY_ATTEMPTS`, `POLICY_RETRY_BACKOFF`) and, if the LLM cannot produce valid XML, emits a final SSE event with empty content and `meta.status=error` so downstream services can decide how to recover without playing canned speech.

## TTS Worker
- The service (`apps/tts_worker`) prioritizes Coqui-TTS (`TTS_MODEL_NAME`) and falls back to Piper (`PIPER_MODEL`, `PIPER_PATH`) when the former is unavailable. If neither backend loads, a deterministic synthesizer generates silence for tests.
- Outputs are cached on disk (`artifacts/tts`) with JSON metadata (voice, latency, visemes). Repeated calls reuse the local file.
- Use `TTS_DISABLE_COQUI=1` or `TTS_DISABLE_PIPER=1` to force a specific backend while debugging.
- Install `espeak-ng` (or `espeak`) if you want the Coqui/Piper voices to emit real audio; without it the worker logs a warning and stays in synthetic mode.
- The `cancel_active()` method stops in-progress jobs before the next synthesized chunk, useful for barge-in scenarios.

## Next steps
- Connect with the telemetry dashboard (`kitsu-telemetry` repo).
- Expand live integrations (OBS, VTube Studio, Twitch) with resilient reconnection. ✅ The Twitch bot controls modules/scenes, the OBS controller reconnects with backoff, and the VTS client authenticates via WebSocket.
- Tune the Coqui/Piper pipeline for final voices and < 1.2 s latency.
