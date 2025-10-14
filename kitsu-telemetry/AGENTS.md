# AGENTS.md

## Scope
Files in this directory describe the telemetry API and UI for the Kitsu.exe project. Follow the guidelines below when modifying any file under `kitsu-telemetry/`.

## General style
- Prefer asynchronous, typed code (explicit type hints in Python and TypeScript).
- Use self-descriptive names and keep comments short and purposeful.
- Keep the documentation in English.

## Backend (Python)
- Use FastAPI with clear routes (`/health`, `/events`, `/events/export`).
- Persist data with SQLite using `aiosqlite`; initialize the database when the app starts.
- Stream CSV exports (`text/csv`) to avoid loading everything into memory.

## Frontend (SvelteKit)
- UI built with Tailwind CSS.
- Create accessible components (add `aria-*` attributes when appropriate).
- The WebSocket mock must allow local testing without a real-time backend.

## Tests
- Ensure the test suite runs with `pytest -q` at the repository root.
- Include smoke tests for loading the app via Uvicorn and for the CSV export.
