(Hello, AI pals! This section is specifically written for AI agents like GitHub Copilot, OpenAI Codex, or ChatGPT who might work on this repository. If you're a human, you're welcome to read on for insight into how we keep the project AI-friendly. In other words, this is where we teach our robot helpers how to code like a pro, in a style consistent with the project.)

Purpose

This repository powers an AI VTuber system called Kitsu.exe (that's the codename). Our goal is to maintain a clean, modular, and stable codebase for the VTuber runtime, while allowing rapid iteration and contributions - including those from AI-based developers. We want AI agents contributing to this repo to stay aligned with our design and style conventions, so we don't end up in a merge conflict nightmare or, worse, with an AI that has 20 different coding styles arguing inside it.

In short, AGENTS.md is the guide for any AI (or human) that contributes to ensure consistency and prevent chaos (the coding kind of chaos, not the fun personality kind).

Project Summary for AI

What is this project* It's an AI-driven VTuber runtime. The architecture is microservice-based (see the README architecture section above for full details). The core idea: an AI listens to audio (or text), understands it via an LLM, and responds with synthesized speech, while controlling a VTuber avatar and possibly interacting with streaming platforms. We have multiple components communicating via async APIs.

Key components (recap for agents):

ASR (Automatic Speech Recognition) Worker: Listens on the microphone, uses Whisper model to transcribe speech to text.

Policy/LLM Worker: Handles the conversation logic using a large language model. This is the "brain" generating responses. It connects to Ollama by default, but `policy.backend` can switch the worker to the OpenAI API or a local transformers pipeline when required.

TTS Worker: Turns text into speech audio with Coqui by default, and can switch to XTTS voice cloning or Bark for expressive delivery when configured.

Orchestrator: The FastAPI server that coordinates everything (receives ASR results, sends to LLM, then sends LLM output to TTS, etc.). Also exposes an API/WebSocket for external control.

Integrations: OBS controller, VTube Studio controller, Twitch chat ingest, etc., each as separate async workers.

Control Panel (telemetry): A backend (FastAPI) and front-end (Svelte) that display metrics and allow sending commands to the system (not core to conversation but important for operations).

The project structure is already outlined in README. As an AI agent, you should know:

Code is primarily in Python (for backend) and a bit of TypeScript/Svelte (for the dashboard UI).

Python code is organized into the apps and libs as described. Each app is basically a small service with its own main.py.

Communication is done via HTTP/WS calls (e.g., orchestrator calls internal functions of workers or via event publishing).

We use asyncio and event loops extensively. No blocking sleeps or infinite loops without awaits, except the supervised loop that restarts services.

Configuration lives in `config/kitsu.yaml`, with `.env` remaining for secrets and quick overrides. Load settings via the shared config loader (`libs.config`) rather than hard-coding values. Use `policy.backend` to select the LLM connector (ollama, openai, or local transformers) and `tts.backend`/`tts.fallback_backends` to pick the speech engines (coqui, xtts, bark, etc.) while keeping optional dependencies behind Poetry extras. Whenever you add a knob, mirror it in `config/kitsu.example.yaml`, document it in the READMEs, and ensure the loader exposes the matching env override.

Directories and Key Files

For quick reference, as an AI agent:

apps/orchestrator/: main API (main.py sets up FastAPI routes, including a /stream WS endpoint and various HTTP endpoints for status, persona, etc.). It also serves the lightweight browser UI (`/webui/chat`) and overlay captions (`/webui/overlay`) that connect to the same event stream for quick testing.

apps/asr_worker/: contains main.py (which sets up the ASR process), runner.py (which ties together audio input, VAD, and transcription pipeline), vad.py (voice activity detection logic), transcription.py (the Whisper integration), and config.py (ASR config like frame size, VAD mode, etc.), plus other utilities.

apps/policy_worker/: will have code to call the LLM (maybe an Ollama client wrapper), stream responses, handle retries or reconnections to the LLM engine.

apps/tts_worker/: includes code to interface with Coqui TTS and Piper. Possibly with a queue system if multiple requests come.

apps/obs_controller/ & avatar_controller/: connect to OBS and VTube Studio APIs (likely using libraries or websockets).

apps/twitch_ingest/: uses twitchio to connect to chat and feed messages.

apps/control_panel_backend/: merges orchestrator info and telemetry DB queries to serve to the UI.

apps/pipeline_runner/: this one orchestrates launching all the above as subprocesses or threads. It's the supervisor.

libs/common/: contains logging.py (we saw structured logging config), possibly HTTP client helpers or shared schemas.

libs/contracts/: centralised Pydantic models that describe every HTTP payload exchanged between services (ASR events, control commands, TTS requests, etc.). Reuse these instead of redefining schemas.

libs/clients/: thin async wrappers around cross-service HTTP calls (e.g. the orchestrator publisher used by ASR). Import from here when a worker needs to contact another service.

config/: centralised YAML (`config/kitsu.yaml`) that feeds the shared config loader. Copy the example file and adjust per-environment instead of scattering new environment variables.

libs/memory/: the memory management (likely a class to store recent chat and a class for DB persistence).

libs/telemetry/: client that sends events (like ASR timing, TTS completion, etc.) to the telemetry API.

configs/safety/: might contain word filters or JSON of disallowed content and the friendly replacements.

scripts/: e.g., run_pipeline.ps1, maybe old scripts like run_all.ps1 or something, and possibly a service_manager.ps1 to install Windows services (just guessing from context).

tests/: tests for ASR, telemetry, etc. Good to check these to see expected behaviors.

Understanding these will help you (the AI) navigate where to make changes.

Coding Conventions & Style (for AI Agents)

We follow standard Python conventions with some specifics:

PEP8 compliant: Use 4 spaces indent, snake_case for functions and variables, CapWords for classes. Max line length ~88 (black's default). Our CI runs Black and Ruff, so your code will be auto-checked for format and common lint issues. Aim to write code that passes black --check and ruff as is
GitHub
.

Type Annotations: We like to use Python type hints. Functions and methods should have type annotations for parameters and return types when reasonable. We run mypy for static type checking
GitHub
. If you're unsure of a type, use Any or make it generic, but better to be specific if you can.

Asynchronous Design: Prefer async def and await for anything that might wait on I/O (network calls to LLM, file reads, etc.)
GitHub
. If using external libraries that have sync APIs (for example, a TTS library that's only sync), run them in a ThreadPool via await loop.run_in_executor to avoid blocking the event loop.

No Busy Waiting: Don't write loops that sleep or block waiting for something without giving control back (except in the controlled case of the pipeline runner which is basically supervising processes and even that uses async to some extent). Use asyncio primitives (queues, events) or callbacks for signaling between tasks.

Logging: Use import logging; logger = logging.getLogger(__name__) or similar to get a module-specific logger. Our configure_json_logging(service_name) is called in each main to set up JSON formatting. Log messages should be meaningful. Include context like IDs or names if logging within a loop etc. For errors, use logger.exception within an except to get stack trace. For expected conditions, use logger.warning or info. Debug logs are off by default but can be enabled, so feel free to add logger.debug for very detailed internals that might help in debugging without spamming normal output.

Error Handling: Each service's main loop (see ASR run_forever) is wrapped in a try/except to catch exceptions and keep running
GitHub
. When writing code inside these loops, handle exceptions gracefully - if an error is recoverable, catch it, log a warning, maybe send an error event to telemetry, but don't let it crash out unless it's truly unrecoverable. This system should ideally never hard-crash; it should self-recover or at least fail only one component. For instance, if TTS fails to synthesize (maybe due to a bad input), it should log error and maybe output a default "..." audio or skip, rather than bringing down the whole pipeline.

Modularity: When adding new features, try to do so in a self-contained way. If it's big, consider making a new module in apps/ or a new file in libs/. For example, if adding a new ASR backend (say Sherpa-ONNX), implement it as an alternative Transcriber class and allow selection via config, rather than cluttering the existing Whisper code with if sherpa: ... if whisper: .... If the feature introduces a new cross-service payload, extend `libs/contracts` and, when needed, add a helper to `libs/clients` so other workers stay decoupled.

Configuration: Use the ASRConfig, TTSConfig, etc., dataclasses or similar patterns that we have. The .env provides environment variables which populate these configs. Don't introduce global variables; use config objects passed around or module-level constants that are configured at startup. This makes it easier to adjust settings and for AI agents to see all config in one place.

Shared Resources: If multiple services need to talk, they do so via orchestrator or via the telemetry DB. Avoid making services read/write each other's files or global states. Keep them loosely coupled (this also means an AI agent can safely modify one service without worrying about hidden interactions).

Testing: Write tests for new code if possible. For AI agents, this means you might need to generate test functions. Look at existing tests (like tests/test_asr_worker.py) to mimic style. We use pytest. Ensure any new dependencies in tests are added to dev requirements. Tests should clean up after themselves (e.g., if you write to a file or db, remove it or use temp). At minimum, the targeted suites (`tests/test_config_loader.py`, `tests/test_pipeline_runner.py`, and the orchestrator chat pipeline test) should pass before you ship config or coordination changes.

Git Commit Messages: (If an AI is generating commit messages) make them clear. E.g., "Fix memory restore logic to respect flag" or "Add support for Bark TTS backend". We auto-link issues if you mention them.

Pull Request Descriptions: (If an AI gets so far as to open PRs) - detail what changed and why. Keep PRs focused; don't mix unrelated changes.

Stay in Scope: Don't suddenly refactor the whole codebase in one go (tempting for an AI that sees improvements everywhere!). It's better to do iterative improvements. For example, if converting a synchronous function to async, do it for one service and test, rather than all at once which could break many things.

No Hardcoded Secrets: Obviously, don't include personal API keys. Use env vars.

Documentation Updates: If an AI agent changes how a feature works or adds a config, it should also update the relevant docs (README, AGENTS.md, .env.example, etc.)
GitHub
. We've seen AIs forget this - but we're explicitly telling you now! Keep docs and code consistent.

By adhering to these conventions, AI agents can effectively contribute without introducing style inconsistencies or bugs. We treat AI contributions with the same review process as human ones, so an AI PR will be checked for passing tests, adherence to these guidelines, and overall architecture fit before merge
GitHub
.

Guidance for Common Tasks

Here are some typical modifications an AI (or human) might be asked to do, and how to approach them:

"Refactor X for clarity/performance": Make sure you understand what X does (read comments, tests). Break it into smaller functions if too large. Ensure unit tests still pass after refactor. If performance, consider algorithmic improvements or using asynchronous calls where possible. Example: refactoring the VAD energy threshold logic - ensure not to break the WebRTC mode, and test with a short audio sample.

"Integrate new model Y": Suppose we want to add Whisper-large or a new TTS. Find a Python API for it, create a new class or module under libs/ or appropriate app. Feature-flag it via config/env (so users opt-in to new model). Make sure it doesn't tank performance or require impossible dependencies without checks. Document the addition.

"Fix a bug in conversation flow": E.g., AI repeats itself. Possibly an issue with memory or prompt. Check the libs/memory and orchestrator how prompts are constructed. This might involve prompt tweaking or logic to avoid resending AI's own words in context. Be careful to test after changes by running a conversation (you can simulate by calling orchestrator endpoints).

"Improve moderation": If asked to enhance the safety filter, you might update regex in configs/safety or add a moderation step (could integrate something like OpenAI's content filter, but that's an external API - likely out of scope for offline mode). In any case, ensure the pipeline always replaces or refuses disallowed content rather than outputting it
GitHub
.

"Implement concurrent processing": There is a concept of streaming where ASR, LLM, TTS operate concurrently for low latency
arxiv.org
. If improving that, you might need to ensure partial ASR results trigger LLM early, and LLM streams to TTS. This is complex - coordinate with orchestrator. Use asyncio queues or background tasks. Don't block - leverage that producer-consumer pattern as mentioned in research
arxiv.org
.

Always keep in mind the "why": we want this AI VTuber to be responsive, reliable, and fun. Code changes should serve those ends. And when in doubt, leave a comment for the next person (or AI) to know what you intended.

Example tooling: `examples/quick_conversation.py` exercises the orchestrator `/chat/respond` endpoint without OBS/VTS. Keep this script (and the docs that mention it) updated whenever response payloads change.

PR Acceptance Criteria Recap

For an AI agent making a PR (pull request), these are the things the maintainers will check:

Does poetry run ruff . show 0 errors* Does poetry run black --check . pass* (If not, fix formatting)
GitHub
.

Does poetry run mypy pass type checks (no new type errors introduced)*
GitHub

Do all tests pass (pytest -q)* If you added new functionality, did you add tests for it*

Is the change scoped and not doing two things at once* Big bang contributions will get more scrutiny.

Are docs updated* If you changed env variables or usage, did you update .env.example and README accordingly*
GitHub

For AI agents: Did you follow these guidelines* No obvious style mismatches or weird code* We'll be on the lookout for signs of "AI drift" (when an AI decides to rewrite everything in its own image).

Once all is good, the maintainer will merge. If something is off, we'll comment - and yes, you as an AI agent are allowed to respond and push follow-up commits if you're able to in that context.

With this guidance, we hope AI and human contributors can work together harmoniously. After all, this project is about a virtual character - it's only fitting that virtual coders help build it!

So go forth, write clean code, keep the VTuber cute and wholesome (unless it's an intentionally chaotic gremlin, which is fine too), and let's make something awesome.
