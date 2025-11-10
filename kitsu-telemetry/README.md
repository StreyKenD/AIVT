# Kitsu Telemetry

Telemetry module for the Kitsu.exe ecosystem, composed of a FastAPI service and a SvelteKit interface styled with Tailwind CSS.

## Prerequisites
- Python 3.11+
- Poetry or `pip` to install dependencies
- Node.js 18+ with `pnpm`

## Quick setup
1. Copy `.env.example` to `.env` and adjust the variables as needed (host, port, allowed origins, and the SQLite path).
2. Inside `ui/`, copy `.env.example` to `.env.local` (for example `cp ui/.env.example ui/.env.local`) and update `PUBLIC_ORCH_BASE_URL`, `PUBLIC_ORCH_WS_URL`, **and** `PUBLIC_CONTROL_BASE_URL` so they point to the orchestrator and the control backend (`http://{ORCH_HOST}:{ORCH_PORT}` and `http://{CONTROL_PANEL_HOST}:{CONTROL_PANEL_PORT}`).
3. Install the Python dependencies:
   ```bash
   poetry install
   ```
4. Initialize the UI:
   ```bash
   cd kitsu-telemetry/ui
   pnpm install
   pnpm dev
   ```

## Environment variables
- API (`.env`):
  - `API_HOST`: bind interface used by the FastAPI server (defaults to `127.0.0.1`).
  - `API_PORT`: HTTP port exposed by the telemetry API (defaults to `8001`).
- `TELEMETRY_ALLOWED_ORIGINS`: comma-separated list of allowed origins for HTTP calls (defaults to `http://localhost:5173`).
- `TELEMETRY_DB_PATH`: path to the SQLite file that stores events (defaults to `./telemetry.db`).
- `TELEMETRY_API_KEY`: required key for authenticating requests (`X-API-KEY`); leave empty to disable protection (not recommended outside local environments).
- `TELEMETRY_RETENTION_SECONDS`: automatic retention window. Events older than this value (e.g. `14400` for 4h) are purged after each ingestion.
- UI (`ui/.env.local`):
  - `PUBLIC_ORCH_BASE_URL`: orchestrator HTTP endpoint (e.g. `http://127.0.0.1:9000`).
  - `PUBLIC_ORCH_WS_URL`: WebSocket base (`ws://127.0.0.1:9000`); the app automatically appends `/stream`.
  - `PUBLIC_CONTROL_BASE_URL`: URL for the control backend (`kitsu-vtuber-ai/apps/control_panel_backend`) that aggregates metrics and commands (defaults to `http://127.0.0.1:8100`).

> Make sure `PUBLIC_ORCH_*` is aligned with `ORCH_HOST`/`ORCH_PORT` defined in the `kitsu-vtuber-ai` repository.

## Running API and UI together
Open two terminals (or use a supervisor like `tmux`):

```bash
# Terminal 1 - API
poetry run uvicorn api.main:app --reload --host ${API_HOST:-127.0.0.1} --port ${API_PORT:-8001}

# Terminal 2 - UI
cd ui
pnpm dev -- --host 127.0.0.1 --port 5173
```

When you visit `http://localhost:5173`, the dashboard will:
- Call `GET /status` on the orchestrator using `PUBLIC_ORCH_BASE_URL` to fill persona, modules, and memory.
- Open the WebSocket at `${PUBLIC_ORCH_WS_URL}/stream` (watch for the `connected` log in the browser console).
- Query the control backend (`PUBLIC_CONTROL_BASE_URL`) for aggregated metrics, CSV download, panic/mute commands, and presets.
- Send events manually to the orchestrator/telemetry when the dashboard actions are used.

> With `TELEMETRY_API_KEY` configured, include `X-API-KEY: <value>` in REST requests from the dashboard, scripts, or inspection tools.

> When running everything on the same machine, keep `ORCH_CORS_ALLOW_ORIGINS` aligned with the origins above to avoid CORS errors.
> Troubles with aliases or types? Run `pnpm exec svelte-kit sync` inside `ui/` before restarting the dev server.

## Structure
- `api/`: telemetry API code (FastAPI + SQLite).
- `ui/`: SvelteKit front-end with Tailwind that consumes the live orchestrator and telemetry streams.
- `tests/`: smoke tests for endpoints and CSV export.

## Key endpoints
- `POST /events` – batch ingestion with optional authentication via `X-API-KEY`.
- `GET /events` – paginated listing with `type`/`source` filters.
- `GET /events/export` – streaming CSV export.
- `GET /metrics/latest` – aggregates metrics (count, avg/max/min latency, percentiles, and temperature) by type inside a sliding window (`window_seconds`). `hardware.gpu` events include `temperature_c`, `utilization_pct`, `memory_*`, and `power_w`.
- `POST /maintenance/prune` – manually purge events older than `max_age_seconds`.

## Tests
Run from the repository root:
```bash
poetry lock --check
poetry run pytest -q
```
> Alternative with `pip`: `python -m pip install pytest httpx` followed by `python -m pytest -q`.

## Required licenses and credits
- **Llama 3 8B Instruct (Meta)** – models and demos that use derived data must cite `licenses/third_party/llama3_license.pdf`.
- **Coqui-TTS** – any voice asset exposed via telemetry must comply with `licenses/third_party/coqui_tts_model_card.pdf`.
- **Live2D Avatar “Lumi”** – include the reference to `licenses/third_party/live2d_lumi_license.pdf` in public dashboards, videos, or screenshots that display the avatar.
