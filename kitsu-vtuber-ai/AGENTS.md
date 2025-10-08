# AGENTS.md

## Objetivo
Este repositório faz parte do projeto Kitsu.exe (IA VTuber). Siga estes contratos ao propor mudanças.

## Como rodar (MVP)
- Python 3.11+
- Instalar deps: `poetry install` (ou `pip install -r requirements.txt`)
- Configurar `.env` a partir de `.env.example`
- Dev:
  - Orchestrator/Backend: `uvicorn apps.control_panel_backend.main:app --reload`
  - (Repo B) API Telemetria: `uvicorn api.main:app --reload`
  - (Repo B) UI SvelteKit: `pnpm i && pnpm dev`

## Dependências de runtime
- OBS Studio com plugin **OBS WebSocket v5** habilitado (`obsws-python` fixado em `1.7.2` no projeto).
- Binários externos de áudio/vídeo: `ffmpeg`, `portaudio`, `libsndfile`.
- Python 3.11+ e Poetry para ambientes isolados; mantenha a versão documentada no README.

## Qualidade
- Lint/format: `ruff . && black --check .`
- Tipos: `mypy` (nível permissivo)
- Testes: `pytest -q` (objetivo: passar 100% dos testes de fumaça)
- Commits: Convencionais (`feat:`, `fix:`, `chore:`…)

## Estilo e restrições
- Assíncrono por padrão (FastAPI/httpx/websockets).
- Sem adicionar libs pesadas sem justificativa.
- Código novo SEM `any` desnecessário (TS/pytypes).
- TTS: **Coqui-TTS** com modelo permissivo (não-XTTS) – manter model card em `licenses/third_party/`.
- LLM: **Ollama** com **Llama 3 8B** (atribuição obrigatória no README).

## Segurança/Moderação
- “Modo familiar” ON por padrão.
- Blocklists/regex em `configs/safety/`.
- Filtrar palavrões e conteúdo TOS; fallback amigável.

## Memória
- Curta: ring buffer (N últimas mensagens).
- Persistente: sumários SQLite; restaurar no boot quando `RESTORE_CONTEXT=true`.

## Critérios de aceite por PR
- Build e testes passam.
- Lint/format OK.
- PR pequeno, descrição clara, checklist atualizado.
- Se alterar endpoints, atualizar `RUN_FIRST.md`.
