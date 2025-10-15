# First Steps (Kitsu.exe Core)

This guide summarizes what you must do right after cloning the repository to run the local development environment safely and in compliance with the model licenses.

## 1. Prerequisites
- Python 3.11+ installed (the workers target 3.11 in production).
- [Poetry](https://python-poetry.org/docs/) 1.6+ installed.
- System dependencies for audio/WebRTC (`portaudio`, `ffmpeg`, `libsndfile`) when running the TTS/ASR services.
- (Optional) [pnpm](https://pnpm.io/) 8+ for the telemetry dashboard in the sibling `kitsu-telemetry` repository.

### 1.1 Install audio/video binaries (Windows)
- With [Chocolatey](https://chocolatey.org/install):
  ```powershell
  choco install ffmpeg portaudio libsndfile
  ```
- Without Chocolatey, download the prebuilt binaries:
  1. **FFmpeg**: download the "release full" package from <https://www.gyan.dev/ffmpeg/builds/> and extract it to `C:\ffmpeg`.
  2. **libsndfile**: grab the `.exe` installer at <https://github.com/libsndfile/libsndfile/releases> (add `bin\\` to `PATH`).
  3. **PortAudio**: use the precompiled package at <http://files.portaudio.com/download.html> (copy `portaudio_x64.dll` to a folder on `PATH`).
- After installing, validate in PowerShell (adjust the paths to match where you extracted the DLLs):
  ```powershell
  ffmpeg -version
  Get-Command ffmpeg
  Get-ChildItem "C:\\AudioSDK" -Filter "*sndfile*.dll"
  Get-ChildItem "C:\\AudioSDK" -Filter "*portaudio*.dll"
  ```

## 2. Install project dependencies
```bash
poetry install
```

## 3. Configure environment variables
Copy `.env.example` to `.env`, fill in the credentials (Twitch, OBS, VTube Studio, Ollama, Coqui-TTS, etc.), and align the orchestration/control/telemetry endpoints:

```env
ORCH_HOST=127.0.0.1
ORCH_PORT=8000
ORCH_CORS_ALLOW_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
CONTROL_PANEL_HOST=127.0.0.1
CONTROL_PANEL_PORT=8100
ORCHESTRATOR_BASE_URL=http://127.0.0.1:8000
TELEMETRY_BASE_URL=http://127.0.0.1:8001
TELEMETRY_API_URL=http://127.0.0.1:8001
TELEMETRY_API_KEY=dev-secret
ORCHESTRATOR_URL=http://127.0.0.1:8000
ORCHESTRATOR_API_KEY=
SAFETY_MODE=family
RESTORE_CONTEXT=false
GPU_METRICS_INTERVAL_SECONDS=30
TWITCH_CHANNEL=your_channel
TWITCH_OAUTH_TOKEN=oauth:xxxxxxx
TWITCH_BOT_NICK=kitsu-bot
TWITCH_CLIENT_ID=
TWITCH_CLIENT_SECRET=
TWITCH_REFRESH_TOKEN=
OBS_WS_URL=ws://127.0.0.1:4455
OBS_WS_PASSWORD=
VTS_URL=ws://127.0.0.1:8001
VTS_AUTH_TOKEN=
KITSU_LOG_ROOT=logs
```

> Set `ORCH_HOST` to `0.0.0.0` if the panel/UI will run from a different machine. `TELEMETRY_API_URL` must point to the API from the `kitsu-telemetry` repository, while `TELEMETRY_BASE_URL` and `ORCHESTRATOR_BASE_URL` keep the control panel backend in sync.
>
> On Windows, prefer an absolute path for `KITSU_LOG_ROOT` (for example, `C:\\kitsu\\logs`) so logs survive repo cleanups.
>
> For VTube Studio, open the plugin menu and authorize "Kitsu.exe Controller"; copy the generated token to `VTS_AUTH_TOKEN`. Generate the Twitch OAuth token with `chat:read chat:edit` scopes and update `TWITCH_OAUTH_TOKEN`. If you save `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET`, and `TWITCH_REFRESH_TOKEN`, you can rotate tokens later with `poetry run python scripts/refresh_twitch_token.py`.
>
> To find the correct microphone, run `poetry run python -m kitsu_vtuber_ai.apps.asr_worker.devices`. The command prints the name (sounddevice) and index (PyAudio) that can be used in `ASR_INPUT_DEVICE`. Use `ASR_FAKE_AUDIO=1` for hardware-free tests.

## 4. Validate quality locally
Run the minimal suite before submitting any change:
```bash
poetry lock --check
poetry run ruff check .
poetry run black --check .
poetry run mypy
poetry run pytest -q
```
> Without Poetry, install `pytest` and `pytest-asyncio` with `python -m pip install pytest pytest-asyncio` and run `python -m pytest -q`.

## 5. Enable pre-commit hooks
Install the hooks defined in `.pre-commit-config.yaml` to automatically enforce lint/format/type checks before commits:
```bash
poetry run pre-commit install
```

## 6. Mandatory license notices
Using the models requires accepting third-party terms. Read and keep copies of these documents under `licenses/third_party/`:
- **Llama 3 8B Instruct (Meta)** – see `licenses/third_party/llama3_license.pdf` before redistributing or demoing the model.
- **Coqui-TTS** (model selected by the project policy) – restrictions detailed in `licenses/third_party/coqui_tts_model_card.pdf`.
- **Live2D Avatar “Lumi”** – attribution required per `licenses/third_party/live2d_lumi_license.pdf`.

> Ensure any public distribution or demo of the project includes the references above and complies with each vendor's terms.

## 7. Start the FastAPI services
- Control panel backend: `poetry run uvicorn apps.control_panel_backend.main:app --reload --host ${CONTROL_PANEL_HOST:-127.0.0.1} --port ${CONTROL_PANEL_PORT:-8100}`
- Orchestrator (using the configured variables):
  ```bash
  poetry run uvicorn apps.orchestrator.main:app --reload --host ${ORCH_HOST:-127.0.0.1} --port ${ORCH_PORT:-8000}
  ```
- Validate the API: `curl http://${ORCH_HOST:-127.0.0.1}:${ORCH_PORT:-8000}/status`
- Control backend health check: `curl http://${CONTROL_PANEL_HOST:-127.0.0.1}:${CONTROL_PANEL_PORT:-8100}/health`
- Windows automation (no Docker):
  - Start everything: `pwsh scripts/run_all_no_docker.ps1 -Action start`
  - Check status: `pwsh scripts/run_all_no_docker.ps1 -Action status`
  - Stop services: `pwsh scripts/run_all_no_docker.ps1 -Action stop`
- Structured JSON logs live under `KITSU_LOG_ROOT`, one file per service, rotated daily.
- (Optional) Parallel PowerShell scripts: `scripts\run_all.ps1 -UsePoetry`

## 8. Validate with the telemetry UI
1. In the `../kitsu-telemetry` repository, configure `.env` (API) and `ui/.env.local` so `PUBLIC_ORCH_BASE_URL`, `PUBLIC_ORCH_WS_URL`, **and** `PUBLIC_CONTROL_BASE_URL` point to `http://{ORCH_HOST}:{ORCH_PORT}` and `http://{CONTROL_PANEL_HOST}:{CONTROL_PANEL_PORT}`.
2. Start the telemetry API: `poetry run uvicorn api.main:app --reload --port 8001`.
3. Start the UI:
   ```bash
   cd kitsu-telemetry/ui
   pnpm install
   pnpm dev
   ```
4. Open `http://localhost:5173` and confirm that:
   - The dashboard shows the orchestrator `GET /status` (via the control backend).
   - Cards and latency charts update as workers process events.
   - Panic/mute/preset buttons provide feedback and reflect in the snapshot.
   - Export CSV downloads `telemetry-*.csv`, and the soak test table lists recent results.
   - The WebSocket connection reports `connected`.

> If you see CORS blocks, verify that `ORCH_CORS_ALLOW_ORIGINS` includes the origin shown in the browser console.

## 9. Run the soak harness (QA)
- Configure `SOAK_POLICY_URL`, `SOAK_TELEMETRY_URL`, and `SOAK_DURATION_MINUTES` in `.env` if you need to override the defaults.
- Start all services (`pwsh scripts/run_all_no_docker.ps1 -Action start`).
- Execute the harness for 2 hours (or use `--max-turns` for a quick check):
  ```bash
  poetry run python -m kitsu_vtuber_ai.apps.soak_harness.main --duration-minutes 120 --output artifacts/soak/summary.json
  ```
- The final summary is saved to the file above and also emitted as a `soak.result` telemetry event. Watch the dashboard at `http://localhost:5173` to monitor the results table.

> To publish GPU metrics, install [pynvml](https://pypi.org/project/pynvml/) (already listed in `pyproject.toml`). If no NVIDIA driver is available, the collector disables itself automatically.

## 10. Broadcast pilot checklist
### Before going live
- Validate audio/video with a local recording test (OBS + VTS).
- Ensure the latest soak harness run completed without failures (<24h).
- Review `.env` and tokens (Twitch, OBS, VTS, Ollama, Telemetry) and renew those expiring within 48h.
- Confirm the persona preset and assets (Coqui/Piper models) match the README version.
- Prepare the welcome message and panic macro in OBS.

### During the stream
- Keep the telemetry dashboard open (dashboard + latency) to observe spikes.
- Log incidents in real time in the internal channel (`#kitsu-ops`).
- Every 30 minutes, verify the modules are still online via `/status`.

### After the show
- Export the telemetry CSV and attach it to the daily log.
- Run the short soak harness again (`--max-turns 5`) to detect immediate regressions.
- Archive clips and incidents in the operations runbook.

## 11. Rollback and incident response
1. Trigger the panic macro (`/control/panic`) from the dashboard and mute TTS.
2. Switch the OBS scene to "BRB" or "Starting Soon".
3. Restart the affected service with `pwsh scripts/service_manager.ps1 -Service <name> -Action restart`.
4. If the issue persists, run `pwsh scripts/run_all_no_docker.ps1 -Action stop` and notify the audience.
5. Log the incident in `docs/incidents/<date>.md` with timestamp, suspected cause, and mitigation.

## 12. Package the release
- Update `poetry.lock`/`pyproject.toml` and ensure `poetry lock --check` passes.
- Generate the Windows-only bundle:
  ```powershell
  pwsh scripts/package_release.ps1 -OutputPath artifacts/release -Zip
  ```
- The script creates a folder with `README.md`, `RUN_FIRST.md`, `.env.example`, PowerShell scripts, and licenses under `licenses/third_party/`.
- Validate the resulting ZIP, complete the checklist in item 10, and publish it to the internal channel before distributing the build.
