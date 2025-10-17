# AIVT Local Development Guide

This workspace contains two tightly coupled projects:

- **`kitsu-vtuber-ai/`** – the AI control-plane and runtime workers (ASR, policy, TTS, OBS/VTS/Twitch bridges).
- **`kitsu-telemetry/`** – the telemetry API and dashboard.

The instructions below reflect the current tooling, including the unified pipeline runner.

---

## 1. Prerequisites

| Component | Purpose | Suggested install |
| --- | --- | --- |
| Python 3.11 + [Poetry](https://python-poetry.org/docs/) | Worker runtime & dependency management | `pipx install poetry` |
| Node.js 18 + [pnpm](https://pnpm.io/) | *Optional – telemetry UI* | `npm install -g pnpm` |
| OBS Studio (WebSocket v5) | Scenes + panic macros | Download from obsproject.com |
| VTube Studio (optional) | Avatar control | Steam or official site |
| `ffmpeg`, `portaudio`, `libsndfile` | Audio capture / playback | `brew install` / `apt install` / `choco install` |
| `espeak-ng` | Required for real TTS output (Coqui/Piper phonemes) | `choco install espeak-ng` on Windows |

GPU metrics are collected automatically when NVIDIA drivers and `pynvml` are present (already listed in `pyproject.toml`).

---

## 2. Clone & prepare env files

```bash
git clone https://github.com/<your-org>/AIVT.git
cd AIVT

cp kitsu-vtuber-ai/.env.example kitsu-vtuber-ai/.env
# Optional – telemetry pieces
cp kitsu-telemetry/.env.example kitsu-telemetry/.env
cp kitsu-telemetry/ui/.env.example kitsu-telemetry/ui/.env.local
```

Fill in, at minimum:

- OBS: `OBS_WS_URL`, `OBS_WS_PASSWORD`
- Twitch: `TWITCH_CHANNEL`, `TWITCH_OAUTH_TOKEN`
- VTube Studio: `VTS_URL`, `VTS_AUTH_TOKEN`
- Audio: set `ASR_INPUT_DEVICE` to the numeric ID printed by `poetry run python -m apps.asr_worker.devices`
- Set `ASR_FAKE_AUDIO=0` to capture from your microphone (the runner defaults to the safe `1` unless overridden)
- Optional: `PIPELINE_DISABLE` (comma-separated services to skip, e.g. `twitch_ingest,avatar_controller`)

Keep everything on `127.0.0.1` unless you truly need remote access.

---

## 3. Install dependencies

```bash
# Core runtime
cd kitsu-vtuber-ai
poetry install

# Telemetry (optional)
cd ../kitsu-telemetry
poetry install
pnpm install --prefix ui
```

---

## 4. Run the whole stack (recommended)

We ship a supervisor that launches every worker, restarts crashes, and pipes logs.

### Windows (PowerShell)

```powershell
cd .\kitsu-vtuber-ai
powershell -ExecutionPolicy Bypass -File .\scripts\run_pipeline.ps1 start
```

- `stop` and `status` actions are also supported.
- Logs stream to the console and are written under `logs/`.

> VS Code tip: run `Terminal -> Run Task -> pipeline:start` to spin up the supervisor inside the integrated terminal. Use the paired `pipeline:status` / `pipeline:stop` tasks to inspect or tear it down, and reach for `telemetry:api` or `telemetry:ui` only when you want the optional dashboard pieces.

### Cross-platform (inside Poetry)

```bash
cd kitsu-vtuber-ai
poetry run python -m apps.pipeline_runner.main
```

#### Useful environment overrides

| Variable | Effect |
| --- | --- |
| `PIPELINE_DISABLE=twitch_ingest,avatar_controller` | Skip specific services |
| `ASR_INPUT_DEVICE=32` | Pick the PortAudio device index detected by the listing command |
| `ASR_FAKE_AUDIO=1` | Force silent (fake) audio |
| `TTS_DISABLE_COQUI=1` or `TTS_DISABLE_PIPER=1` | Force a single TTS backend for debugging |

Services log their status on startup; missing env vars are reported and the runner continues instead of crashing.

---

## 5. Manual commands (if you prefer individual shells)

```bash
poetry run uvicorn apps.orchestrator.main:app --reload --host ${ORCH_HOST:-127.0.0.1} --port ${ORCH_PORT:-8000}
poetry run uvicorn apps.control_panel_backend.main:app --reload --host ${CONTROL_PANEL_HOST:-127.0.0.1} --port ${CONTROL_PANEL_PORT:-8100}
poetry run python -m apps.asr_worker.main
poetry run python -m apps.policy_worker.main
poetry run python -m apps.tts_worker.main
```

This was the old workflow; the pipeline runner simply does the above for you with supervision and restart logic.

---

## 6. Verify functionality

Run the key test suites:

```bash
poetry run pytest tests/test_asr_worker.py tests/test_asr_pipeline.py tests/test_telemetry_integration.py
```

These cover the ASR segmentation/transcription path plus TTS telemetry instrumentation.

---

## 7. Telemetry dashboard (optional)

```bash
# API
cd kitsu-telemetry
poetry run uvicorn api.main:app --reload --host ${API_HOST:-127.0.0.1} --port ${API_PORT:-8001}

# UI
cd ui
pnpm dev -- --host 127.0.0.1 --port 5173
```

Set `PUBLIC_ORCH_BASE_URL`, `PUBLIC_ORCH_WS_URL`, and `PUBLIC_CONTROL_BASE_URL` in `ui/.env.local` to reference `http://127.0.0.1:8000` and `http://127.0.0.1:8100`.

---

## 8. Troubleshooting

| Symptom | Fix |
| --- | --- |
| `port already in use` on orchestrator/control/policy | Stop old processes (`scripts/run_pipeline.ps1 stop`) or change the ports in `.env` |
| TTS warning: “No espeak backend found” | Install `espeak-ng` (or keep running in synthetic mode) |
| ASR keeps using silence | Set `ASR_FAKE_AUDIO=0` and `ASR_INPUT_DEVICE=<numeric id>`; confirm in logs that `sounddevice` is in use |
| OBS/VTS/Twitch skipped | Add the required env vars or list the services in `PIPELINE_DISABLE` |
| GPU metrics disabled | Install NVIDIA drivers or ignore (the runner auto-disables telemetry when unavailable) |

---

## 9. Repository structure

```
AIVT/
├── kitsu-vtuber-ai/          # core runtime (this guide)
├── kitsu-telemetry/          # telemetry API + UI
├── licenses/                 # third-party notices
└── README.md (you are here)
```

For more details, including licensing requirements and the operations playbook, read `kitsu-vtuber-ai/README.md` and `kitsu-vtuber-ai/RUN_FIRST.md`.
