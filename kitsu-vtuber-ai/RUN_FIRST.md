# First Steps (kitsu-vtuber-ai)

This checklist captures everything you need to do immediately after cloning the repository in order to run the local development environment safely and in compliance with third‑party licences.

---

## 1. Prerequisites

| Requirement | Notes |
| --- | --- |
| Python 3.11 + [Poetry](https://python-poetry.org/docs/) | Workers target Python 3.11. |
| Media tooling (`ffmpeg`, `portaudio`, `libsndfile`) | Required for ASR/TTS audio support. |
| `espeak-ng` | Needed for Coqui/Piper to generate real speech (otherwise the TTS worker stays in synthetic mode). |
| OBS Studio (WebSocket v5) | For scene control/panic macros. |
| VTube Studio (optional) | For avatar expression control. |
| [pnpm](https://pnpm.io/) 8+ | Only if you intend to run the telemetry dashboard. |

**Windows quick install**

```powershell
choco install ffmpeg portaudio libsndfile espeak-ng
```

Validate the binaries:

```powershell
ffmpeg -version
Get-Command ffmpeg
poetry run python -c "import sounddevice"
```

---

## 2. Install project dependencies

```bash
cd kitsu-vtuber-ai
poetry install
```

(Optional) telemetry stack:

```bash
cd ../kitsu-telemetry
poetry install
pnpm install --prefix ui
```

---

## 3. Configure environment variables

```bash
cp kitsu-vtuber-ai/.env.example kitsu-vtuber-ai/.env
```

Minimum values to update in `kitsu-vtuber-ai/.env`:

- `OBS_WS_URL` / `OBS_WS_PASSWORD`
- `TWITCH_CHANNEL` / `TWITCH_OAUTH_TOKEN`
- `VTS_URL` / `VTS_AUTH_TOKEN`
- `ASR_INPUT_DEVICE` – numeric identifier from `poetry run python -m apps.asr_worker.devices`
- `POLICY_URL` / `TTS_API_URL` to point the orchestrator at the local policy and TTS workers (defaults cover localhost)
- Leave `ASR_FAKE_AUDIO` unset (or `0`) to capture from your microphone; set it to `1` to keep the worker silent during tests.
- Optional: `PIPELINE_DISABLE=service1,service2` to skip integrations until you have credentials

Keep `ORCH_HOST`, `CONTROL_PANEL_HOST`, etc. at `127.0.0.1` unless you need remote access.

---

## 4. Start everything with one command

### Windows

```powershell
cd kitsu-vtuber-ai
powershell -ExecutionPolicy Bypass -File .\scripts\run_pipeline.ps1 start
```

### Cross-platform (inside Poetry)

```bash
cd kitsu-vtuber-ai
poetry run python -m apps.pipeline_runner.main
```

The runner supervises orchestrator, control panel, policy, ASR, and TTS workers, restarting on crashes and streaming JSON logs. Services listed in `PIPELINE_DISABLE` are skipped with a warning (e.g. `twitch_ingest`, `avatar_controller`, `obs_controller` while credentials are missing).

Stop with `scripts/run_pipeline.ps1 stop` or `Ctrl+C` in the Poetry shell.

---

## 5. Verify the environment

Run the key tests:

```bash
poetry run pytest tests/test_asr_worker.py tests/test_asr_pipeline.py tests/test_telemetry_integration.py
```

To list audio devices and confirm your microphone selection:

```powershell
poetry run python -m apps.asr_worker.devices
```

Set `ASR_INPUT_DEVICE` to the `Identifier` column for the device you want. The runner logs whether it is using fake audio or capturing through `sounddevice`.

Quick microphone sanity check (prints recognised text live):

```powershell
poetry run python scripts/asr_mic_tester.py
```

Use this before running the full pipeline to confirm faster-whisper hears you.

---

## 6. Optional – Telemetry dashboard

1. `cp kitsu-telemetry/.env.example kitsu-telemetry/.env`
2. `cp kitsu-telemetry/ui/.env.example kitsu-telemetry/ui/.env.local`
3. Start the API: `poetry run uvicorn api.main:app --reload --host 127.0.0.1 --port 8001`
4. Start the UI: `pnpm dev -- --host 127.0.0.1 --port 5173`
5. Open `http://127.0.0.1:5173` and confirm it connects to the orchestrator / control panel.

---

## 7. Quality gates

```bash
poetry lock --check
poetry run ruff .
poetry run black --check .
poetry run mypy
poetry run pytest -q
poetry run pre-commit run --all-files   # optional but recommended
```

Install the hooks with `poetry run pre-commit install`.

---

## 8. Licensing

Review the third-party notices in `licenses/third_party/` **before** sharing demos or recordings:

- `llama3_license.pdf` – Meta Llama 3 usage.
- `coqui_tts_model_card.pdf` – model licensing for Coqui/Piper.
- `live2d_lumi_license.pdf` – avatar attribution requirements.

---

## 9. Incident response & rollback

1. Trigger the panic macro (mute + BRB scene).
2. Restart specific services with `scripts/service_manager.ps1`.
3. Stop everything with `scripts/run_pipeline.ps1 -Action stop` if recovery fails.
4. Record the incident in `docs/incidents/<date>.md` with timestamps and mitigation steps.

---

You now have a reproducible path to boot the entire VTuber stack locally: configure `.env`, install dependencies, run the pipeline supervisor, and validate with the test suite. Add OBS/VTS/Twitch credentials when you are ready for full integrations, and install `espeak-ng` to enable real TTS audio. Happy hacking!

