# First Steps (Kitsu Telemetry)

Quick guide to configure and validate the telemetry module (API + UI) after cloning the repository.

## 1. Prerequisites
- Python 3.11+ with [Poetry](https://python-poetry.org/)
- Node.js 18+ with `pnpm`
- SQLite available (bundled with Python)

## 2. Install dependencies
```bash
poetry install
cd ui
pnpm install
cd ..
```

## 3. Configure environment variables

Create the `.env` file (API) from `.env.example` and adjust the values for your environment:

```
API_HOST=127.0.0.1
API_PORT=8001
TELEMETRY_ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
TELEMETRY_DB_PATH=./telemetry.db
TELEMETRY_API_KEY=dev-secret
TELEMETRY_RETENTION_SECONDS=14400
```

For the UI, copy `ui/.env.example` to `ui/.env.local`, keeping it aligned with the orchestrator (`kitsu-vtuber-ai`) and the control backend:

```
PUBLIC_ORCH_BASE_URL=http://127.0.0.1:8000
PUBLIC_ORCH_WS_URL=ws://127.0.0.1:8000
PUBLIC_CONTROL_BASE_URL=http://127.0.0.1:8100
```

> Ensure `ORCH_HOST`, `ORCH_PORT`, and `ORCH_CORS_ALLOW_ORIGINS` are configured in the `kitsu-vtuber-ai` repository with compatible values. The client automatically appends `/stream` to `PUBLIC_ORCH_WS_URL` and uses `PUBLIC_CONTROL_BASE_URL` to reach the control backend.

## 4. Run API and UI
Open two terminals or sessions:

```bash
# Terminal 1
poetry run uvicorn api.main:app --reload --host ${API_HOST:-127.0.0.1} --port ${API_PORT:-8001}

# Terminal 2
cd ui
pnpm dev -- --host 127.0.0.1 --port 5173
```

Visit `http://localhost:5173` and confirm:
- Orchestrator status indicator in **green** (`GET /status` request via the control backend).
- Real-time events flowing in the dashboard after actions (WebSocket connected).
- Cards and latency charts updating via `GET /metrics/latest`.
- CSV export available (**Export CSV** button) and soak test results listed.
- Panic/mute/preset commands triggering on the orchestrator (check the logs for events).

## 5. Quick tests
Validate the endpoints periodically:
```bash
poetry lock --check
poetry run pytest -q
```
> Alternative with `pip`: `python -m pip install pytest httpx` followed by `python -m pytest -q`.

## 6. Licenses and credits
- **Llama 3 8B Instruct (Meta)** – see `licenses/third_party/llama3_license.pdf`.
- **Coqui-TTS** – requirements in `licenses/third_party/coqui_tts_model_card.pdf`.
- **Live2D Avatar “Lumi”** – mandatory attribution in `licenses/third_party/live2d_lumi_license.pdf`.

> When exposing the dashboard publicly (dashboards, screenshots, demos), include the references above alongside the material.
