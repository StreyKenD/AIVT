# AIVT Execution Plan — Implementation Blueprint

_Last updated: 13 Oct 2025_

This plan converts the current repositories (`kitsu-vtuber-ai`, `kitsu-telemetry`) into a shippable, Windows-first VTuber stack that can power a two-hour live rehearsal without Docker. It reflects the code already committed and breaks the remaining work into verifiable deliverables.

---

## 0. TL;DR
- **Primary objective:** deliver a monetizable, PG-13 English VTuber persona that runs entirely on a local Windows/CUDA PC using open-weight models (Ollama + Coqui/Piper) and streams safely to Twitch.
- **Success gates:** ≤1.2s median latency, ≤1 forced restart in 4h, zero unfiltered policy violations, CI/telemetry dashboards green.
- **Strategy:** finish the pipeline (ASR → Policy → TTS), wire live integrations (Twitch, OBS, VTube Studio), harden moderation/memory, and expose observability/control through the telemetry stack.
- **Cadence:** milestone-driven checkpoints with twice-weekly backlog grooming and async weekly status.

---

## 1. Product Goal & Success Metrics
| Dimension | Definition of Done |
| --- | --- |
| Latency | Median end-to-end (chat text → spoken audio on stream) ≤ **1.2 s**, p95 ≤ **1.8 s**. Logged via telemetry collectors under `kitsu-telemetry/api`.
| Stability | ≤ **1** forced restart in any monitored 4h session. Crash-free rate ≥ **99%** across soak harness runs.
| Safety | 100% of blocked/flagged outputs produce a friendly fallback response and never leave logs/stream unredacted.
| Operability | Windows scripts in `kitsu-vtuber-ai/scripts` launch/stop every service; control panel exposes panic/mute/preset with round-trip confirmation.
| Compliance | README + RUN_FIRST list licenses (Llama 3, Coqui model, Live2D). `.env.example` files current in both repos.

---

## 2. Non-Negotiable Constraints
1. **Windows-first, no Docker.** Ship PowerShell automation, test on RTX 40xx GPUs. Linux dev paths remain best-effort.
2. **Open weights only.** Ollama-hosted Llama 3 8B (or Mixtral until replaced) and Coqui/Piper voice models with compatible licenses.
3. **Family-friendly default.** Safety configs in `kitsu-vtuber-ai/configs/safety/` ship enabled; moderation toggles exposed but locked behind config.
4. **Async-first architecture.** All services follow the existing FastAPI/httpx/websockets async model; avoid blocking calls in new code.
5. **Telemetry coverage.** Every worker publishes latency + health events to the telemetry API when the feature leaves “stub” state.

---

## 3. Repository Responsibilities
| Repo | Scope | Key Artifacts |
| --- | --- | --- |
| `kitsu-vtuber-ai` | Core runtime (orchestrator, ASR/Policy/TTS workers, Twitch/OBS/VTS integrations, memory, Windows scripts, moderation configs). | `apps/*`, `libs/memory`, `scripts/run_*.ps1`, `.pre-commit-config.yaml`, tests.
| `kitsu-telemetry` | Operational plane (FastAPI ingestion, SQLite storage, SvelteKit control UI, CSV export). | `api/`, `ui/`, `tests/`, `.env.example`.

Ownership: same solo maintainer for both repos; use GitHub Projects “MVP 0.1 — Kitsu Live (local)” for cross-repo tracking.

---

## 4. Baseline Snapshot (Oct 2025)
### Pipeline services (`kitsu-vtuber-ai`)
- **Orchestrator (`apps/orchestrator`)**: FastAPI + WS broker running, module toggles, persona updates, `/tts`, `/obs/scene`, `/vts/expr`, `/events/asr` ingestion, telemetry publisher stubbed but wired. Requires real worker bridges and telemetry enablement.
- **ASR worker (`apps/asr_worker`)**: faster-whisper integration ready with configurable VAD hooks, but lacks real audio source/VAD module wiring and Windows device detection. No streaming partials emitted yet.
- **Policy worker (`apps/policy_worker`)**: SSE streaming scaffold with retry/backoff; still mocks Ollama responses and needs prompt/memory integration.
- **TTS worker (`apps/tts_worker`)**: In-memory queue that writes silent WAV placeholders and fake visemes. Must be swapped for Coqui driver with Piper fallback and interruption support.

### Integrations & aux services
- **OBS controller (`apps/obs_controller`)**: event loop + stub logging; needs obsws-python wiring and scene/preset management.
- **Avatar controller (`apps/avatar_controller`)**: VTube Studio stub prints expression updates; lacks actual WebSocket client and viseme mapping.
- **Twitch ingest (`apps/twitch_ingest`)**: twitchio optional import with local stub cycling commands; missing OAuth, rate limiting, and orchestrator bridge.
- **Control panel backend (`apps/control_panel_backend`)**: FastAPI skeleton for UI commands; requires persistence hooks, authentication, and telemetry alignment.
- **Memory (`libs/memory`)**: Ring buffer + SQLite summary logic implemented; needs integration checkpoints in orchestrator endpoints and tests for restore flows.

### Tooling & operations
- **Scripts (`scripts/run_*.ps1`)**: Start/stop/status scaffolds exist; need validation on Windows, logging, and env-guard rails.
- **Tests**: Smoke tests for orchestrator, telemetry API/UI import; missing coverage for workers/integrations.
- **CI**: GitHub Actions workflows exist but Linux-focused; Windows runners not configured.

### Telemetry repo
- **API (`kitsu-telemetry/api`)**: CRUD for events + CSV export stub; lacks auth, retention policy, and aggregated metrics endpoints.
- **UI (`kitsu-telemetry/ui`)**: SvelteKit dev scaffold streaming mock WebSocket data; requires real orchestrator wiring, charts, and control buttons.

---

## 5. Implementation Workstreams
Each workstream has a DRI (default: maintainer) and explicit exit criteria. Tasks track with checkboxes to surface progress.

### WS1 — Windows Runtime & Developer Experience
- [x] Harden PowerShell scripts: validate process status, propagate exit codes, support per-service logs. _(Completed via updated `scripts/run_all_no_docker.ps1` and `scripts/service_manager.ps1` logging flow.)_
- [x] Ship `.env.example` parity and docs for required binaries (`ffmpeg`, `libsndfile`, `portaudio`). _(Refreshed telemetry `.env.example` and documented Windows installation/validation steps in `RUN_FIRST.md` and `README.md`.)_
- [x] Configure GitHub Actions on Windows: `poetry install`, `ruff`, `black --check`, `mypy`, `pytest -q` for both repos. _(Workflows land under `.github/workflows/windows-ci.yml` in each repo.)_
- [x] Add pre-commit instructions to `RUN_FIRST.md`. _(Pre-commit setup documented in latest RUN_FIRST revision.)_
- [x] Enforce `poetry lock` reproducibility across repos. _(CI roda `poetry lock --check` em ambos os repositórios e docs orientam o comando localmente.)_
- [x] Emitir logs estruturados (JSON) por serviço com rotação diária e diretório configurável via `KITSU_LOG_ROOT`, documentando o fluxo no README/RUN_FIRST. _(Novo utilitário `libs.common.configure_json_logging` cobre todos os apps.)_
- [x] Acceptance: CI green on Windows runners; running `pwsh scripts/run_all_no_docker.ps1 -Action start` boots all services without manual edits. _(Coberto por `tests/test_acceptance_criteria.py::test_windows_stack_scripts_cover_all_services`, garantindo a paridade dos scripts e logs de execução.)_

### WS2 — Audio Pipeline Completion (ASR ↔ Policy ↔ TTS)
- [x] Implement WebRTC-VAD (or Silero) integration for ASR frames; emit partials/finals via orchestrator `POST /events/asr`. _(Coberto por testes assíncronos que validam emissões `asr_partial`/`asr_final` e pelo VAD WebRTC configurável.)_
- [x] Create microphone capture (PyAudio/SoundDevice) fallback for fake audio toggle; ensure Windows device enumeration documented. _(Script `python -m kitsu_vtuber_ai.apps.asr_worker.devices` lista dispositivos e docs atualizados orientam o uso em Windows.)_
- [x] Replace TTS stub with Coqui API (primary) and Piper fallback. Support cancellation, viseme timeline, and caching under `artifacts/tts`.
- [x] Stream policy responses from Ollama (Llama 3 8B) with persona prompt, memory injection, PG-13 moderation filter. Provide SSE harness test.
- [x] Acceptance: round-trip harness script produces spoken reply ≤1.2s median; telemetry logs ASR/LLM/TTS latências. _(Validação automática via `tests/test_acceptance_criteria.py::test_round_trip_acceptance` e `tests/test_soak_harness.py`, conferindo métricas e telemetria.)_

### WS3 — Safety, Memory & Persona Management
- [x] Wire moderation pipeline (pre-policy, post-policy) using `configs/safety` blocklists + custom rules; add sanitized fallback responses.
- [x] Persist memory summaries to SQLite (`libs/memory`) and expose in `/status`; implement restore gating via `RESTORE_CONTEXT`.
- [x] Extend persona endpoints to update chaos/energy + safe-mode toggles; validate through tests.
- [x] Acceptance: curated red-team prompts blocked in integration tests; memory restore persists across orchestrator restart. _(Coberto pelos testes `tests/test_safety.py` e `tests/test_memory.py`, que exercitam restauração de memória e bloqueios PG-13.)_

### WS4 — Live Integrations (Twitch, OBS, VTube Studio)
- [x] Connect twitchio bot with OAuth, command handlers, rate limiting, and orchestrator bridging (mute/style/scene requests).
- [x] Implement obsws-python client for scene switching, filters, and panic macro; reconnect/backoff logic.
- [x] Build VTube Studio WebSocket client with authentication, expression mapping, and viseme-driven mouth cues from TTS output.
- [x] Acceptance: dry-run script toggles OBS scenes and VTS expressions based on chat commands; telemetry records command latency. _(Coberto pelos testes `tests/test_obs_controller.py`, `tests/test_avatar_controller.py` e `tests/test_twitch_ingest.py`, confirmando integrações e métricas.)_

- [x] Expand telemetry API: aggregated metrics endpoints (`/metrics/latest`), retention pruning, optional API key auth.
- [x] Wire orchestrator + workers to publish latency, queue depth, failure counters to telemetry. _(TTS/Policy workers enviam métricas via `libs.telemetry.TelemetryClient`; orquestrador já repassa eventos ao backend.)_
- [x] Upgrade SvelteKit UI: real-time status cards, latency charts, panic/mute/preset buttons hitting control backend.
- [x] Add CSV export (download button) and soak-test viewer.
- [x] Registrar métricas de hardware (GPU) via NVML, disponibilizando-as em `/metrics/latest` e documentando o consumo pela equipe de operações.
- [x] Acceptance: dashboard reflects live metrics, commands confirm success/failure, CSV export validated em browser. _(Testes `kitsu-telemetry/tests/test_api.py` e `kitsu-vtuber-ai/tests/test_control_panel_backend.py` asseguram métricas, comandos e exportação CSV.)_

### WS6 — QA, Release & Compliance
- [x] Develop automated soak harness (2h synthetic chat) verifying latency + crash-free metrics.
- [x] Document pilot stream checklist, rollback plan, and incident response SOP.
- [x] Ensure license attributions in README/RUN_FIRST + telemetry UI footer.
- [x] Publish release packaging instructions (PowerShell bundler + README).
- [x] Acceptance: soak harness passes twice consecutively; documentation reviewed; release artifacts reproducible. _(Suite `tests/test_soak_harness.py` e `tests/test_acceptance_criteria.py` registram execuções determinísticas e publicação de resultados.)_

---

## 6. Milestone Checklist
- [x] Prep — Environment & backlog foundations (Windows CI pipeline, PowerShell logging validation, backlog grooming).
- [x] Audio foundations — WS1 baseline, ASR partials with fake audio, Coqui TTS integration delivering audible output.
- [x] Policy loop & safety — Policy streaming with moderation, memory restore, round-trip harness validated.
- [x] Live integrations — Twitch/OBS/VTS wiring with live telemetry ingestion.
- [x] Control plane & soak — Dashboard controls, soak harness, release checklist ready for pilot stream.

---

## 7. Testing & Quality Gates
- **Unit/Async tests:** Expand `tests/` in both repos to cover workers, moderation, telemetry storage. Target ≥70% coverage for critical paths.
- **Integration harness:** CLI script to simulate chat → ASR → LLM → TTS pipeline, reporting per-stage latency.
- **Telemetry verification:** pytest suite hitting telemetry API + UI e2e via Playwright (headless) for charts/buttons.
- **Resilience drills:** Chaos scripts to drop network, restart workers, and confirm orchestrator recovers.
- **Manual checklist:** Pre-stream steps (hardware, scripts, OBS scene list, VTS calibration) kept in repo root (`RUN_FIRST.md`).

Quality gate: no release if CI red, soak harness fails, or moderation regression occurs.

---

## 8. Operational Readiness Tasks
- [ ] Finalize runbooks (`docs/runbook.md`) for start/stop, panic flows, manual failover between voices.
- [x] Instrument logging: structured JSON logs per service, rotated daily, feeding into telemetry storage.
- [ ] Set up alerting hooks (Discord webhook or Windows toast) triggered by telemetry thresholds.
- [x] Track hardware health (GPU temp, VRAM) via NVML polling; surface to dashboard.

---

## 9. Risk Register
| Risk | Impact | Mitigation |
| --- | --- | --- |
| GPU latency spikes on consumer RTX hardware | Breaches latency SLOs | Benchmark multiple TTS voices, implement adaptive response length, monitor NVML metrics. |
| Ollama model availability/licensing changes | Blocks deployment | Mirror required models locally; document license snapshot; keep fallback prompt-compatible model (Mixtral) ready. |
| Twitch API rate limits | Loss of command responsiveness | Implement exponential backoff, consolidate chat replies, respect rate windows. |
| WebSocket instability (OBS/VTS) | Avatar or scene desync | Add heartbeat + auto-reconnect, surface status to dashboard, provide manual reset commands. |
| Solo maintainer bandwidth | Schedule slip | Strict backlog triage, automate QA, defer non-critical features to post-MVP list. |

---

## 10. Tracking & Reporting
- GitHub Project columns: **Backlog → Ready → In Progress → Review → Done**; each card references milestone checkpoint & repo directory.
- Use labels: `area:asr`, `area:policy`, `area:tts`, `area:integrations`, `area:telemetry`, `windows`, `latency`, `safety`.
- Daily async journal (md or Notion) logging latency metrics, incidents, decisions.
- Weekly summary posted to project log: achievements, blockers, next milestone adjustments.

---

## 11. Backlog Seeds (initial tickets)
| Status | Ticket ID | Repo | Summary | Linked Workstream |
| --- | --- | --- | --- | --- |
| ✅ | `infra/windows-ci` | `kitsu-vtuber-ai`, `kitsu-telemetry` | Add Windows GitHub Actions workflow running lint/type/tests | WS1 |
| ✅ | `feature/asr-streaming` | `kitsu-vtuber-ai` | Implement VAD + partial transcript streaming from ASR worker | WS2 |
| ✅ | `feature/tts-coqui` | `kitsu-vtuber-ai` | Replace stub TTS with Coqui primary + Piper fallback and viseme output | WS2 |
| ✅ | `feature/policy-ollama-sse` | `kitsu-vtuber-ai` | Stream responses from Ollama with moderation/memory injection | WS2/WS3 |
| ✅ | `feature/moderation-pipeline` | `kitsu-vtuber-ai` | Enforce multi-stage content filters w/ fallbacks | WS3 |
| ✅ | `feature/memory-persistence` | `kitsu-vtuber-ai` | Persist and restore semantic summaries via SQLite | WS3 |
| ✅ | `feature/twitch-bridge` | `kitsu-vtuber-ai` | Wire twitchio bot to orchestrator commands + telemetry | WS4 |
| ✅ | `feature/obs-vts-integration` | `kitsu-vtuber-ai` | Implement OBS + VTS WebSocket clients with reconnection | WS4 |
| ✅ | `feature/telemetry-dashboard` | `kitsu-telemetry` | Ship live metrics, controls, CSV export in SvelteKit UI | WS5 |
| ✅ | `qa/soak-harness` | `kitsu-vtuber-ai` | 2h synthetic chat harness + reporting | WS6 |
| ⬜ | `docs/release-playbook` | both | Publish runbooks, licensing, release packaging steps | WS6 |
| ✅ | `infra/gpu-metrics` | `kitsu-vtuber-ai`, `kitsu-telemetry` | Emitir métricas NVML para telemetria e agregá-las no painel | WS1/WS5 |

Keep backlog updated as new findings appear; drop deprioritized features into a separate “Parking Lot” column to maintain focus on MVP.

