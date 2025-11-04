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

### Service contracts
- Shared request/response shapes now live in `libs/contracts/`. ASR, TTS, policy, and control-plane workers all import these Pydantic models so we only define the wire format once.
- Thin async HTTP helpers (e.g. the orchestrator publisher used by the ASR worker) are under `libs/clients/`. Use these instead of ad-hoc `httpx` calls when a service needs to reach another one.
- Each worker module (`apps/*`) keeps its FastAPI app or runner logic, but they no longer import code from another worker; cross-service communication goes through the contracts/clients packages.

### Configuration
- Service settings (ports, downstream URLs, ASR/VAD tuning) now live in `config/kitsu.yaml`. Copy `config/kitsu.example.yaml`, tweak each section (`orchestrator`, `policy`, `tts`, `asr`, `memory`), and keep it under version control for reproducible deployments.
- `.env` is still respected for secrets and quick overrides, but the YAML file is the source of truth. Set `KITSU_CONFIG_FILE` if you need to load from a different location.

- `asr.backend` selects the speech recogniser (`whisper` uses Faster-Whisper; `sherpa` uses Sherpa-ONNX for low-latency CPU decoding). When using Sherpa, install `sherpa-onnx` and point `asr.sherpa.*` at your model files.
#### Sherpa-ONNX backend
1. `pip install sherpa-onnx` (optional dependency).
2. Download a model (for example, the small English Zipformer package):
   ```bash
   mkdir -p models/sherpa-onnx/en
   curl -L -o models/sherpa-onnx/en/tokens.txt https://huggingface.co/csukuangfj/sherpa-onnx-zipformer-en-2023-06-26/resolve/main/tokens.txt
   curl -L -o models/sherpa-onnx/en/encoder.onnx https://huggingface.co/csukuangfj/sherpa-onnx-zipformer-en-2023-06-26/resolve/main/encoder.onnx
   curl -L -o models/sherpa-onnx/en/decoder.onnx https://huggingface.co/csukuangfj/sherpa-onnx-zipformer-en-2023-06-26/resolve/main/decoder.onnx
   curl -L -o models/sherpa-onnx/en/joiner.onnx https://huggingface.co/csukuangfj/sherpa-onnx-zipformer-en-2023-06-26/resolve/main/joiner.onnx
   ```
3. Update `config/kitsu.yaml` (or set env overrides) with the downloaded paths under `asr.sherpa.*` and set `asr.backend` to `sherpa`.

- `policy.backend` controls which LLM connector the policy worker uses:
  - `ollama` (default): streams from the local Ollama daemon at `policy.ollama_url`. Pull the model referenced by `LLM_MODEL_NAME` (Mixtral by default) with `ollama pull`.
  - `openai`: calls the OpenAI Chat Completions API. Install the optional dependencies with `poetry install -E openai`, set `OPENAI_API_KEY`, and choose the target model via `policy.openai.model`.
  - `local`: runs HuggingFace Transformers locally. Install with `poetry install -E local-llm` (installs `transformers` + `torch`) and configure `policy.local.model_path` / `tokenizer_path` / `device` / `max_new_tokens` as needed.
- `tts.backend` toggles between voice synthesizers:
  - `coqui` (default): uses lightweight multi-speaker Coqui models and honours `tts.coqui.speaker_map` for voice aliases.
  - `xtts`: loads Coqui XTTS v2 for multilingual voice cloning; set `tts.xtts.default_speaker_wav` (or map names via `tts.xtts.speaker_wavs`) and optionally override per-voice languages.
  - `bark`: runs Suno Bark for highly expressive output. Latency is higher—best suited for pre-recorded or “special effect” lines.
  - Combine with `tts.fallback_backends` (e.g. `["piper"]`) to fail over to CPU-friendly voices when a premium backend is unavailable.

### Quick sanity check

With the pipeline running, trigger a headless exchange from the CLI:

```bash
poetry run python examples/quick_conversation.py --text "Testing from the command line"
```

Add `--preset hype` to swap persona presets before sending the message, or `--no-tts` if you only want policy output.

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

Use `PIPELINE_DISABLE` to skip integrations you do not have credentials for (e.g. `PIPELINE_DISABLE=twitch_ingest,avatar_controller`). The value is case-insensitive and accepts a comma-separated list; skipped services are logged at startup while the remaining workers retain automatic restarts and log streaming.

When the policy backend is set to `ollama`, the runner checks `OLLAMA_AUTOSTART` (default `1`). Leave it enabled to auto-launch `ollama serve` on the local machine, or set it to `0`/`false` when you already manage the daemon or point at a remote host.

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
- `TELEMETRY_API_KEY` / `ORCHESTRATOR_API_KEY`: optional tokens to protect the `/events` endpoint (telemetry) and `/persona`/`/toggle` when accessed by external integrations. The orchestrator, GPU monitor, workers, and soak harness add the telemetry key as `X-API-Key`; configure the same secret on the telemetry server to enforce authentication.
- `ORCHESTRATOR_URL`: HTTP address used by workers and integrations (Twitch, OBS, VTS) to publish events to the orchestrator.

> Tip: once `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET`, and `TWITCH_REFRESH_TOKEN` are stored in `.env`, refresh the chat token any time with `poetry run python scripts/refresh_twitch_token.py`.
- `TTS_CACHE_DIR` / `tts.cache_dir`: folder where synthesized audio is cached (default `artifacts/tts_cache`).
- `tts.coqui.model_name` / `tts.piper.model`: checkpoints loaded by the speech synthesizers (override temporarily with `TTS_MODEL_NAME` / `PIPER_MODEL`).
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
- Tests: focus first on `poetry run pytest tests/test_config_loader.py tests/test_pipeline_runner.py tests/test_orchestrator.py::test_chat_pipeline_hits_policy_and_tts`; follow up with `poetry run pytest -q` (or `python -m pytest -q` after `python -m pip install pytest pytest-asyncio`)
- Pre-commit: `poetry run pre-commit run --all-files`

> Install the hooks locally with `poetry run pre-commit install` (the [`./.pre-commit-config.yaml`](.pre-commit-config.yaml) file already targets `apps/`, `libs/`, and `tests/`).

### VS Code setup
- Install **Black Formatter** (`ms-python.black-formatter`) for on-save formatting.
- Install **Ruff** (`charliermarsh.ruff`) for lint diagnostics inside the editor.
- With the repo's `.vscode/settings.json` checked in, these extensions align VS Code with the configured format and lint tooling.

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
- `apps/policy_worker` supports pluggable LLM connectors configured via `policy.backend` (`ollama`, `openai`, or `local`). The default Ollama path streams from `policy.ollama_url` and uses **Mixtral** (`LLM_MODEL_NAME=mixtral:8x7b-instruct-q4_K_M`)—run `ollama pull mixtral:8x7b-instruct-q4_K_M` (or your chosen model) before the first boot. For OpenAI, install the optional extra with `poetry install -E openai` and set `OPENAI_API_KEY`/`policy.openai.model`. For local transformers, install `poetry install -E local-llm` and point `policy.local.model_path` (plus `tokenizer_path`, `device`, etc.) at the HF model you want to serve.
- The `POST /respond` endpoint returns an SSE stream (`text/event-stream`) with `start`, `token`, `retry`, and `final` events. Each `token` represents the incremental XML stream; the `final` event includes metrics (`latency_ms`, `stats`) and persona metadata.
- The prompt combines system instructions and few-shots to reinforce the kawaii/chaotic style, energy/chaos levels (`chaos_level`, `energy`), and family mode (`POLICY_FAMILY_FRIENDLY`).
- Family-friendly filtering is enforced by a synchronous moderation pipeline (`configs/safety/` + `libs.safety.ModerationPipeline`). Forbidden prompts return a safe message immediately; final responses go through an additional scan and, if necessary, are sanitized before reaching TTS.
- The worker retries (`POLICY_RETRY_ATTEMPTS`, `POLICY_RETRY_BACKOFF`) and, if the LLM cannot produce valid XML, emits a final SSE event with empty content and `meta.status=error` so downstream services can decide how to recover without playing canned speech.

## TTS Worker
- The service (`apps/tts_worker`) instantiates synthesizers from `tts.backend` and `tts.fallback_backends`. Coqui remains the default, XTTS v2 adds multilingual voice cloning (using `tts.xtts.default_speaker_wav` or per-voice mappings), and Bark provides highly expressive, characterful speech. A deterministic silent synth is always kept as a last resort.
- Outputs are cached under `tts.cache_dir` (default `artifacts/tts_cache`) with JSON metadata capturing voice, backend, latency, and visemes so repeated lines reuse the generated audio.
- Customise voices with config: map aliases to Coqui speakers via `tts.coqui.speaker_map`, point XTTS voices to reference WAVs via `tts.xtts.speaker_wavs`, and tweak Bark prompts/temperatures through `tts.bark.*`.
- Install optional extras as needed—`poetry install -E bark` pulls in Suno Bark dependencies, while `poetry install` already provides Coqui/XTTS. Bark is CPU-friendly but slower; XTTS benefits from GPU acceleration and requires high-quality reference audio.
- The `cancel_active()` method still stops in-progress jobs before the next synthesized chunk, making barge-in/interrupt scenarios safe.

## Local Web UI & Overlay
- A lightweight chat console lives at `http://127.0.0.1:8000/webui/chat`. It connects to the orchestrator WebSocket, streams partial tokens, and lets you send text prompts (optionally skipping TTS) without opening the full telemetry dashboard.
- OBS-friendly captions are available at `http://127.0.0.1:8000/webui/overlay`. Load the page as a browser source with transparency enabled to display Kitsu’s current line on stream.
- `POST /chat/respond` accepts `{text, play_tts}` to trigger the same pipeline programmatically (handy for scripts or testing without the UI).
- Both pages are static HTML/JS bundles served directly by the orchestrator, so no extra build step is required.

## Next steps
- Connect with the telemetry dashboard (`kitsu-telemetry` repo).
- Expand live integrations (OBS, VTube Studio, Twitch) with resilient reconnection. ✅ The Twitch bot controls modules/scenes, the OBS controller reconnects with backoff, and the VTS client authenticates via WebSocket.
- Tune the Coqui/Piper pipeline for final voices and < 1.2 s latency.
