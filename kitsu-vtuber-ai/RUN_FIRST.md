# First Steps (kitsu-vtuber-ai)

This checklist captures everything you need to do immediately after cloning the repository in order to run the local development environment safely and in compliance with third-party licences.

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

## 3. Configure the runtime

### 3.1 Copy the service config

```bash
cp kitsu-vtuber-ai/config/kitsu.example.yaml kitsu-vtuber-ai/config/kitsu.yaml
```

Edit `config/kitsu.yaml` to match your environment:

- `asr.input_device`: numeric identifier from `poetry run python -m apps.asr_worker.devices`
- `orchestrator.public_url`: the URL workers should use to publish events (defaults to `http://127.0.0.1:8000`)
- `asr.backend`: choose `whisper` (default) or `sherpa`. For Sherpa, install `pip install sherpa-onnx` and provide the `asr.sherpa.*` model paths (tokens/encoder/decoder/joiner or a YAML config).
- `policy.backend`: pick `ollama` (default), `openai`, or `local`. Install `poetry install -E openai` and set `OPENAI_API_KEY` for the OpenAI path, or `poetry install -E local-llm` and update `policy.local.*` for local transformers.
- `tts.backend` / `tts.fallback_backends`: decide which synthesizers to load (`coqui`, `xtts`, `bark`, etc.). Provide XTTS reference voices with `tts.xtts.default_speaker_wav` or `tts.xtts.speaker_wavs`, and tweak Bark prompts via `tts.bark.*`. Bark is heavier-install its dependencies with `poetry install -E bark` before enabling it.
- `policy.endpoint_url` / `tts.endpoint_url`: URLs the orchestrator calls for policy/TTS responses
- `orchestrator.telemetry_url` and `telemetry_api_key`: point to the telemetry API if you run it locally (`http://127.0.0.1:8001` by default)
- Adjust bind hosts/ports if you expose services externally; set `KITSU_CONFIG_FILE` to load from a custom path.

### 3.2 Environment overrides

```bash
cp kitsu-vtuber-ai/.env.example kitsu-vtuber-ai/.env
```

`.env` now primarily holds secrets and optional overrides. Update at least:

- `OBS_WS_URL` / `OBS_WS_PASSWORD`
- `TWITCH_CHANNEL` / `TWITCH_OAUTH_TOKEN`
- `VTS_URL` / `VTS_AUTH_TOKEN`
- LLM overrides if you do not want to edit the YAML directly: `POLICY_BACKEND`, `OPENAI_API_KEY`, `OPENAI_MODEL`, or `LOCAL_LLM_*`.
- TTS overrides for quick experiments: `TTS_BACKEND`, `TTS_MODEL_NAME`, `PIPER_MODEL`, plus the Bark/XTTS knobs (`BARK_*`, `XTTS_*`) without touching `config/kitsu.yaml`.
- Optional: `PIPELINE_DISABLE=service1,service2` to skip integrations until you have credentials

Most pipeline configuration lives in `config/kitsu.yaml`; leave the `.env` values unset unless you need ad-hoc overrides.

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
poetry run pytest tests/test_config_loader.py tests/test_pipeline_runner.py \
                 tests/test_orchestrator.py::test_chat_pipeline_hits_policy_and_tts \
                 tests/test_asr_worker.py tests/test_asr_pipeline.py tests/test_telemetry_integration.py
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

- Optional: set `MIC_TEST_OUTPUT=logs/mic_test.log` (or another path) when using the mic tester to save console transcripts into a file for later reference.

---

## 6. Local web UI (optional)

- With the orchestrator running, open `http://127.0.0.1:8000/webui/chat` in a browser to send text prompts and watch streaming responses without relying on the microphone.
- For OBS subtitles, add a browser source that points to `http://127.0.0.1:8000/webui/overlay` and enable a transparent background.

## 7. Optional - Telemetry dashboard

1. `cp kitsu-telemetry/.env.example kitsu-telemetry/.env`
2. `cp kitsu-telemetry/ui/.env.example kitsu-telemetry/ui/.env.local`
3. Start the API: `poetry run uvicorn api.main:app --reload --host 127.0.0.1 --port 8001`
4. Start the UI: `pnpm dev -- --host 127.0.0.1 --port 5173`
5. Open `http://127.0.0.1:5173` and confirm it connects to the orchestrator / control panel.

---

## 8. Quality gates

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

## 9. Licensing

Review the third-party notices in `licenses/third_party/` **before** sharing demos or recordings:

- `llama3_license.pdf` – Meta Llama 3 usage.
- `coqui_tts_model_card.pdf` – model licensing for Coqui/Piper.
- `live2d_lumi_license.pdf` – avatar attribution requirements.

---

## 10. Incident response & rollback

1. Trigger the panic macro (mute + BRB scene).
2. Restart specific services with `scripts/service_manager.ps1`.
3. Stop everything with `scripts/run_pipeline.ps1 -Action stop` if recovery fails.
4. Record the incident in `docs/incidents/<date>.md` with timestamps and mitigation steps.

---

You now have a reproducible path to boot the entire VTuber stack locally: configure `.env`, install dependencies, run the pipeline supervisor, and validate with the test suite. Add OBS/VTS/Twitch credentials when you are ready for full integrations, and install `espeak-ng` to enable real TTS audio. Happy hacking!

