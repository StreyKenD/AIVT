AIVT — Execution Plan (No Docker, Windows/CUDA)
1) Objectives & Success Criteria

Primary Goal: Ship a monetizable, fully local VTuber AI pipeline for Twitch in English using open-source/open-weights components.

Key Success Metrics

End-to-end response (chat → speech on stream) median latency ≤ 1.2s; p95 ≤ 1.8s.

Stream stability: ≤ 1 forced restart per 4h session.

Moderation incidents (blocked outputs) correctly handled: 100% (no policy leaks).

Crash-free rate: 99% during 2h pilot.

Definition of Done (DoD)

ASR (faster-whisper), Policy (Mixtral via Ollama), TTS (Piper) all live with real Twitch chat.

OBS and VTube Studio integrations functional (scene switch + lip-sync via visemes).

Semantic memory and PG-13 moderation enabled.

Basic Control Panel (web) displays health + latency graphs.

CI on Windows (lint/type/tests) green; .env.example complete; README updated.

2) Scope (What we will build)

Real-time pipeline: ASR (partial/final) → Policy (Mixtral streaming) → TTS (Piper + visemes + interruption).

Integrations: Twitch chat ingestion/commands; OBS scene control; VTS expressions + lip-sync.

Safety & Memory: PG-13 moderation across the chain; semantic memory with short summaries.

Ops & UX: Minimal Control Panel (status/latency/logs/buttons), telemetry (latencies/events), Windows-only scripts, GitHub CI.

Out of Scope (for MVP)

Multilingual voice; cloud deployment; sophisticated facial rig logic; Docker images.

3) Architecture & Tech Choices

ASR: faster-whisper (CUDA, CTranslate2 int8), VAD (WebRTC-VAD or Silero).

Policy LLM: Mixtral (Ollama) with token streaming, concise persona prompts.

TTS: Piper (MIT voices) with viseme timeline; queue + cancel on new speech; audio cache.

Controllers: obsws-python (OBS WS v5), VTS WebSocket client.

Chat: twitchio with OAuth, rate-limit & reconnect.

Memory: SQLite summaries + “mood/energy/last_actions”.

Moderation: Lightweight lexical rules + policy guardrails before/after LLM.

UI: Small SvelteKit panel reading /status & WS /stream.

OS: Windows 10/11 + CUDA; no Docker.

4) Work Plan & Milestones (4 Weeks)
Week 1 — Foundations & First Voice

Deliverables

Pre-commit + ruff/black/isort/mypy; GitHub Actions (Windows runner).

.env.example unified; PowerShell scripts to run each service.

TTS Piper implemented: voices (2–3 EN MIT), visemes JSON, queue + cancel, audio cache.

Basic latency logging (synthesis time, queue delay).

Acceptance

apps/tts_worker returns WAV + visemes in ≤ 250ms for 1–2s utterances on RTX 4060 Ti (voice-dependent).

CI green; README “Run without Docker (Windows)”.

Risks & Mitigations

Voice quality/latency variance: benchmark 2–3 voices; pick best.

Week 2 — ASR + Policy (Streaming)

Deliverables

ASR faster-whisper with VAD; partials every ~200–300ms; finals on pause.

Policy Mixtral (Ollama) with token streaming; persona prompt; timeouts + retries.

End-to-end local loop (mic → ASR → Mixtral → TTS) in a dev harness.

Acceptance

Partial transcript median delay ≤ 600ms; final transcripts coherent.

Policy returns streamed content chunks; total generation for short replies ≤ 350–500ms (quantized Mixtral, concise prompt).

Risks & Mitigations

LLM stall/latency spikes: use Q4_K_M/Q5; strict prompt budget; abort after N ms and fall back to short safe reply.

Week 3 — Live Integrations (Twitch/OBS/VTS) + Moderation

Deliverables

Twitch ingestion (twitchio), commands !mute, !style, !scene, !redeem.

OBS control (scene switch) and VTS expressions + lip-sync from visemes.

Moderation PG-13 pre-ASR (post-text), pre-Policy, post-Policy; friendly rewrites when blocked.

Semantic memory: short summaries + sentiment/mood; snapshot in /status.

Acceptance

On stream, a viewer message can change scene or style, and the model responds by voice, with mouth movement synced.

Blocked content never surfaces in TTS; logs show reason.

Risks & Mitigations

VTS license missing for production: develop in dev mode; purchase before pilot stream.

OBS/VTS websocket flaps: add reconnect with backoff; clear error toasts.

Week 4 — Control Panel, Telemetry & Hardening

Deliverables

Control Panel: status, health, persona controls, latency mini-charts, logs; buttons Panic/Mute/Presets.

Telemetry: stage latencies (ASR/LLM/TTS), TTS interruptions, failure counters; CSV export; simple graphs.

Load test: 2h “soak” session locally; bug-bash.

Pilot stream checklist and roll-back plan.

Acceptance

Median E2E latency ≤ 1.2s, p95 ≤ 1.8s in a 30-min rehearsal.

Panel reflects module states; toggles work in real time.

Zero crashes during 2h soak (or graceful restart ≤ 30s once).

Risks & Mitigations

Spikes during peak chat: short replies policy, TTS cancel, prioritization.

ASR noise: tweak VAD thresholds; optional noise gate/AGC.

5) Issue Backlog (mapped to weeks)

Week 1

infra/base-hygiene (CI + scripts + README)

feature/tts-piper-visemes (voices, visemes, cancel, cache)

Week 2

feature/asr-fasterwhisper-stream (VAD, partial/final)

feature/policy-mixtral-ollama (streaming, prompt, retries)

Week 3

feature/twitchio-live (OAuth, commands, memory ingest)

feature/obs-vts-integration (scene/expressions + lip-sync)

feature/moderation-rules (PG-13, toggles)

Week 4

feature/memory-semantic-summary (summaries + mood)

feature/control-panel-ui (status + latency + buttons)

feature/telemetry-metrics (graphs + CSV)

ci/github-actions (final polishing, smoke test)

6) Testing & QA Strategy

Unit tests: workers (ASR/Policy/TTS) and orchestrator API/WS; mocks for Ollama/Twitch/OBS/VTS.

Latency harness: scripts measuring stage times (ASR/LLM/TTS) and full E2E.

Resilience tests: kill/restart service; ensure auto-reconnect.

Content safety tests: curated prompts with edge cases (slur lists, adult content), ensure block or sanitize.

Soak testing: continuous local session (2h) with synthetic chat.

7) Operational Playbooks

Run (Windows, no Docker): PowerShell scripts per service (run_orchestrator.ps1, run_asr.ps1, run_policy.ps1, run_tts.ps1, run_twitch.ps1, run_obs.ps1, run_vts.ps1).

Secrets: .env only; never commit. Use sample .env.example.

Observability: telemetry page + logs; CSV export for postmortems.

Roll-back: feature flags USE_STUB_* to revert modules; panic/mute in panel.

8) Risks & Dependencies

VTS License required for commercial streams (buy before pilot).

GPU VRAM/thermals: long sessions can throttle; monitor temps; keep replies short.

Voice licensing: choose Piper voices marked MIT (document chosen model files).

Twitch API rate limits: conservative command usage; backoff.

9) Team & RACI (can be 1-person with roles)

Owner (Responsible): You (CodeFox) — implement & drive.

Accountable: You.

Consulted: Me (tech lead support), Twitch/OBS/VTS docs.

Informed: Future collaborators/test viewers.

10) Communication & Tracking

GitHub Project: “MVP 0.1 — Kitsu Live (local)”.

Labels: phase:mvp, latency, area:*, windows, safety.

PR Template: include scope, latency impact, test plan, screenshots/gifs.

Daily notes: brief log of latency, errors, actions.