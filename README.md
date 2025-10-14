# AIVT Local Development Guide

The repository hosts two tightly coupled projects:

- **`kitsu-vtuber-ai/`** – the VTuber AI control plane, orchestrator, and runtime workers.
- **`kitsu-telemetry/`** – a FastAPI telemetry API with a SvelteKit dashboard that visualises metrics from the AI runtime.

Follow the numbered steps below to run everything on your machine.

## 1. Install prerequisites

1. **Python toolchain**
   - Install Python **3.11 or newer**.
   - Install [Poetry](https://python-poetry.org/docs/#installation) for dependency management (`pipx install poetry` works well).
2. **JavaScript toolchain**
   - Install Node.js **18.x** (use [nvm](https://github.com/nvm-sh/nvm) or the installer for your OS).
   - Install [pnpm](https://pnpm.io/installation) (`npm install -g pnpm`).
3. **Multimedia dependencies** – install OBS Studio with the **OBS WebSocket v5** plug-in enabled, plus the system packages `ffmpeg`, `portaudio`, and `libsndfile` (package names vary by OS; e.g. `brew install ffmpeg portaudio libsndfile` on macOS, `sudo apt install ffmpeg portaudio19-dev libsndfile1` on Ubuntu).
4. **Optional helpers** – Windows users can rely on the PowerShell scripts in `kitsu-vtuber-ai/scripts/` to start and stop worker processes.

## 2. Clone the repository

```bash
# Pick a directory where you want the project to live
cd ~/code

# Clone and enter the workspace
git clone https://github.com/<your-org>/AIVT.git
cd AIVT
```

## 3. Prepare environment files

1. **Core AI service**
   - Copy the template: `cp kitsu-vtuber-ai/.env.example kitsu-vtuber-ai/.env`.
   - Review the file and fill in credentials:
     - `OBS_WS_URL` / `OBS_WS_PASSWORD` – match your local OBS setup.
     - `TWITCH_CHANNEL` and `TWITCH_OAUTH_TOKEN` if you plan to stream.
     - `VTS_URL` and `VTS_AUTH_TOKEN` for VTube Studio integrations.
     - Update `ORCH_HOST`, `CONTROL_PANEL_HOST`, etc. if you need to expose services on different interfaces.
2. **Telemetry API**
   - Copy the template: `cp kitsu-telemetry/.env.example kitsu-telemetry/.env`.
   - Adjust `API_PORT` or `TELEMETRY_ALLOWED_ORIGINS` if the dashboard will run somewhere other than `http://localhost:5173`.
3. **Telemetry UI**
   - Copy the template: `cp kitsu-telemetry/ui/.env.example kitsu-telemetry/ui/.env.local`.
   - Point the URLs to the orchestrator (`PUBLIC_ORCH_BASE_URL` / `PUBLIC_ORCH_WS_URL`) and control backend (`PUBLIC_CONTROL_BASE_URL`) you will start in later steps.

> Tip: keep all services on `127.0.0.1` during local development to avoid CORS headaches.

## 4. Install dependencies

Perform these installs from the repository root.

```bash
# Install Python dependencies for both projects (this creates .venv environments)
cd kitsu-vtuber-ai
poetry install
cd ..

cd kitsu-telemetry
poetry install
cd ..

# Install frontend dependencies for the telemetry dashboard
cd kitsu-telemetry/ui
pnpm install
cd ../../
```

## 5. Start the core VTuber AI services

Open **two terminals** (or tabs) and run the following from the project root:

1. **Control Panel Backend** – handles configuration and acts as the main API for the UI.
   ```bash
   cd kitsu-vtuber-ai
   poetry run uvicorn apps.control_panel_backend.main:app \
     --reload --host ${CONTROL_PANEL_HOST:-127.0.0.1} --port ${CONTROL_PANEL_PORT:-8100}
   ```
2. **Orchestrator (HTTP + WebSocket)** – coordinates workers and real-time events.
   ```bash
   cd kitsu-vtuber-ai
   poetry run uvicorn apps.orchestrator.main:app \
     --reload --host ${ORCH_HOST:-127.0.0.1} --port ${ORCH_PORT:-8000}
   ```

Verify the orchestrator is healthy from another terminal:

```bash
curl http://127.0.0.1:8000/status
```

You should receive a JSON payload indicating the orchestrator is online.

## 6. Start the telemetry stack

Use two additional terminals for the telemetry backend and frontend:

1. **Telemetry API (FastAPI)**
   ```bash
   cd kitsu-telemetry
   poetry run uvicorn api.main:app \
     --reload --host ${API_HOST:-127.0.0.1} --port ${API_PORT:-8001}
   ```
   - If you set `TELEMETRY_API_KEY` in `.env`, include the header `X-API-KEY: <your key>` on client requests.

2. **Telemetry Dashboard (SvelteKit + pnpm)**
   ```bash
   cd kitsu-telemetry/ui
   pnpm dev -- --host 127.0.0.1 --port 5173
   ```
   - Visit `http://127.0.0.1:5173` in your browser. The dashboard consumes the orchestrator and control panel endpoints you configured earlier and opens a WebSocket stream using `PUBLIC_ORCH_WS_URL`.

## 7. Optional workers & helpers

- Power users can launch additional workers (e.g., ASR, TTS, safety) via the scripts under `kitsu-vtuber-ai/scripts/` once the orchestrator is running.
- On Windows, run `scripts/run_all.ps1` to start every service without Docker. Use the matching `stop_all` script to shut them down.

## 8. Troubleshooting checklist

- **CORS errors** – ensure `ORCH_CORS_ALLOW_ORIGINS` (orchestrator) and `TELEMETRY_ALLOWED_ORIGINS` (API) include the telemetry UI URL.
- **WebSocket connection refused** – confirm OBS/VTube Studio endpoints match the host/port in `.env` and that the orchestrator is listening on the same interface your browser targets.
- **Audio device issues** – set `ASR_INPUT_DEVICE` to the correct PortAudio device ID (`poetry run python scripts/list_audio_devices.py`).
- **Missing dependencies** – re-run `poetry install` or `pnpm install` if you update `pyproject.toml` or `package.json`.

With all four services running, you have the full local development environment: the AI orchestration core, the control panel backend, the telemetry API, and the telemetry dashboard.
