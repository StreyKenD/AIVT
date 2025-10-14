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
- List the supported devices for the `sounddevice` and `PyAudio` backends in a single command:
  ```powershell
  poetry run python -m kitsu_vtuber_ai.apps.asr_worker.devices
  ```
- Use `--json` to integrate with scripts or store the full list: `poetry run python -m kitsu_vtuber_ai.apps.asr_worker.devices --json > devices.json`.
- Set `ASR_INPUT_DEVICE` with the name returned by `sounddevice` (exact string) or the numeric index reported for `PyAudio`. If no backend is available, set `ASR_FAKE_AUDIO=1` to keep the worker silent during tests.
- Adjust `ASR_SAMPLE_RATE`, `ASR_FRAME_MS`, and `ASR_SILENCE_MS` if you need to sync the frame timing with capture cards or specific audio interfaces.

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
1. Install [Poetry](https://python-poetry.org/) and Python 3.11+.
2. Copy `.env.example` to `.env` and fill in the credentials.
3. Install dependencies:
   ```bash
   poetry install
   ```
4. Start the control panel backend (FastAPI):
   ```bash
   poetry run uvicorn apps.control_panel_backend.main:app --reload
   ```
5. Inspect the orchestrator (FastAPI + WebSocket):
   ```bash
   poetry run uvicorn apps.orchestrator.main:app --reload --host ${ORCH_HOST:-127.0.0.1} --port ${ORCH_PORT:-8000}
   curl http://${ORCH_HOST:-127.0.0.1}:${ORCH_PORT:-8000}/status
   ```

> **Attribution**: The default LLM is **Llama 3 8B Instruct** served by Ollama.

### How to run without Docker (Windows)

1. Install [Python 3.11](https://www.python.org/downloads/windows/) (enable "Add python.exe to PATH") and [Poetry](https://python-poetry.org/docs/).
2. Clone the repository, open **PowerShell 7+ (pwsh)**, and configure the virtual environment:
   ```powershell
   poetry env use 3.11
   poetry install
   ```
3. Copy the environment file: `Copy-Item .env.example .env` and edit the credentials (Twitch OAuth, OBS, VTS, etc.).
4. Optional but recommended: install local hooks with `poetry run pre-commit install` to enable `ruff`, `black`, `isort`, and `mypy` before commits.
5. Use the automation scripts under `scripts/` to start or stop each service individually:
   ```powershell
   pwsh scripts/run_orchestrator.ps1 -Action start   # start the orchestrator (FastAPI)
   pwsh scripts/run_asr.ps1 -Action status           # check the ASR worker
   pwsh scripts/run_tts.ps1 -Action stop             # stop the TTS worker
   ```
6. To start everything at once (no Docker):
   ```powershell
   pwsh scripts/run_all_no_docker.ps1 -Action start
   ```
   Use `-Action stop` to shut everything down or `-Action status` to inspect active PIDs.

## Essential environment variables
These variables control how the orchestrator exposes HTTP/WebSocket endpoints and where events are forwarded for telemetry:

- `ORCH_HOST`: bind interface used by `uvicorn` (default `127.0.0.1`). Use `0.0.0.0` when exposing the API to other machines or to a UI hosted outside the local host.
- `ORCH_PORT`: public port for the orchestrator. Align this value with `PUBLIC_ORCH_BASE_URL` and `PUBLIC_ORCH_WS_URL` in the `kitsu-telemetry` repository; `8000` is the recommended development value.
- `TELEMETRY_API_URL`: base URL (e.g., `http://localhost:8001/api`) where state events are published. When empty, the orchestrator runs without external telemetry.
- `TELEMETRY_API_KEY` / `ORCHESTRATOR_API_KEY`: optional tokens to protect the `/events` endpoint (telemetry) and `/persona`/`/toggle` when accessed by external integrations.
- `ORCHESTRATOR_URL`: HTTP address used by workers and integrations (Twitch, OBS, VTS) to publish events to the orchestrator.
- `TTS_OUTPUT_DIR`: folder where synthesized audio is cached (default `artifacts/tts`).
- `TTS_MODEL_NAME` / `PIPER_MODEL`: identifiers for the Coqui/Piper models loaded by the workers (see [TTS Worker](#tts-worker)).
- `TWITCH_CHANNEL` / `TWITCH_OAUTH_TOKEN`: credentials for the `twitchio` bot responsible for reading commands in real time. Set `TWITCH_BOT_NICK` and `TWITCH_DEFAULT_SCENE` if you want to customize the nickname or the fallback scene.
- `OBS_WS_URL` / `OBS_WS_PASSWORD`: **obs-websocket v5** endpoint and password configured in OBS. `OBS_SCENES` accepts a comma-separated list used by the demo script; `OBS_PANIC_FILTER` indicates the filter triggered by the panic macro.
- `VTS_URL` / `VTS_AUTH_TOKEN`: WebSocket endpoint and persistent token for VTube Studio. Adjust `VTS_PLUGIN_NAME`/`VTS_DEVELOPER` to identify the plugin inside VTS settings.
- `KITSU_LOG_ROOT`: directory where each service writes daily-rotated JSON `.log` files (default `logs`).
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
- Start all services (`pwsh scripts/run_all_no_docker.ps1 -Action start`).
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
3. If needed, stop everything with `scripts/run_all_no_docker.ps1 -Action stop`.
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
- The worker retries (`POLICY_RETRY_ATTEMPTS`, `POLICY_RETRY_BACKOFF`) and falls back to the friendly mock (`POLICY_FORCE_MOCK=1` or automatic fallback) when the response fails or is invalid, preserving the `<speech/><mood/><actions/>` format.

## TTS Worker
- The service (`apps/tts_worker`) prioritizes Coqui-TTS (`TTS_MODEL_NAME`) and falls back to Piper (`PIPER_MODEL`, `PIPER_PATH`) when the former is unavailable. If neither backend loads, a deterministic synthesizer generates silence for tests.
- Outputs are cached on disk (`artifacts/tts`) with JSON metadata (voice, latency, visemes). Repeated calls reuse the local file.
- Use `TTS_DISABLE_COQUI=1` or `TTS_DISABLE_PIPER=1` to force a specific backend while debugging.
- The `cancel_active()` method stops in-progress jobs before the next synthesized chunk, useful for barge-in scenarios.

## Next steps
- Connect with the telemetry dashboard (`kitsu-telemetry` repo).
- Expand live integrations (OBS, VTube Studio, Twitch) with resilient reconnection. ✅ The Twitch bot controls modules/scenes, the OBS controller reconnects with backoff, and the VTS client authenticates via WebSocket.
- Tune the Coqui/Piper pipeline for final voices and < 1.2 s latency.
