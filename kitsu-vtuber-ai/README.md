# Kitsu.exe Core (kitsu-vtuber-ai)

Kitsu.exe é a espinha dorsal da VTuber IA "Kitsu" – uma raposa kawaii e caótica que conversa, reage e controla seu avatar ao vivo. O pipeline principal segue **ASR → LLM → TTS**, com integrações para Twitch, OBS e VTube Studio. Consulte também o [RUN_FIRST.md](RUN_FIRST.md) para o checklist inicial de configuração local e avisos de licenciamento obrigatórios.

```
[Twitch Chat / Voz]
        |
        v
  [ASR Worker] --texto--> [Policy Worker (LLM)] --fala/mood--> [TTS Worker]
        |                                             |
        |                                             v
        +--> [Orchestrator] <--> [OBS Controller] <--> [Avatar Controller]
                              \--> [Control Panel Backend]
```

## Visão
- Persona inicial: **kawaii & chaotic**, idioma inglês.
- Arquitetura distribuída com workers assíncronos.
- Memória curta e persistente com sumários salvos em SQLite.
- Telemetria e painel de controle externo (ver repositório `kitsu-telemetry`).

## Rodando localmente
1. Instale [Poetry](https://python-poetry.org/) e Python 3.11+.
2. Copie `.env.example` para `.env` e preencha as credenciais.
3. Instale as dependências:
   ```bash
   poetry install
   ```
4. Levante o backend de controle (FastAPI):
   ```bash
   poetry run uvicorn apps.control_panel_backend.main:app --reload
   ```
5. (Opcional) Suba todos os workers (incluindo o novo orquestrador e os stubs) em paralelo via PowerShell:
   ```powershell
   scripts/run_all.ps1
   ```

6. Para inspecionar o orquestrador (FastAPI + WebSocket):
   ```bash
   poetry run uvicorn apps.orchestrator.main:app --reload --port 8100
   ```

> **Atribuição**: O modelo LLM padrão é **Llama 3 8B Instruct** servido pelo Ollama.

## Estrutura
- `apps/`: serviços principais (ASR, política, TTS, orquestração, integrações OBS/VTS/Twitch, backend de controle).
- `libs/`: utilitários compartilhados e memória.
- `configs/`: perfis e regras de segurança/moderação.
- `scripts/`: utilitários para desenvolvimento.
- `tests/`: testes de fumaça via `pytest`.

## Qualidade
- Lint: `poetry run ruff .`
- Formatação: `poetry run black --check .`
- Tipagem: `poetry run mypy`
- Testes: `poetry run pytest -q`
- Pré-commit: `poetry run pre-commit run --all-files`

> Instale os hooks localmente com `poetry run pre-commit install` (o arquivo [`./.pre-commit-config.yaml`](.pre-commit-config.yaml) já está configurado para `apps/`, `libs/` e `tests/`).

## Licenças e atribuições
- LLM padrão: **Llama 3 8B Instruct** via Ollama – leia `licenses/third_party/llama3_license.pdf` antes de redistribuir modelos ou gerar demos públicas.
- TTS: modelo permissivo do **Coqui-TTS** – consulte `licenses/third_party/coqui_tts_model_card.pdf` para requisitos de uso.
- Avatar Live2D “Lumi”: crédito obrigatório conforme `licenses/third_party/live2d_lumi_license.pdf` em qualquer apresentação pública.

Mantenha essas referências sempre disponíveis ao compartilhar builds ou gravações do projeto.

## APIs do Orquestrador
- `GET /status`: snapshot completo da persona, módulos, cena atual e último pedido de TTS.
- `POST /toggle/{module}`: habilita/desabilita módulos (`asr_worker`, `policy_worker`, `tts_worker`, `avatar_controller`, `obs_controller`, `twitch_ingest`).
- `POST /persona`: ajusta estilo (`kawaii`, `chaotic`, `calm`), nível de caos/energia e modo familiar.
- `POST /tts`: registra um pedido de fala (texto + voz preferida).
- `POST /obs/scene`: altera a cena atual do OBS (stub).
- `POST /vts/expr`: aplica expressão no avatar (stub).
- `POST /ingest/chat`: registra mensagens do chat/assistente para alimentar a memória.
- `WS /stream`: difusão em tempo real dos eventos acima e das métricas simuladas.

## Memória
- Buffer curto de conversas (ring buffer) com sumarização sintética a cada 6 mensagens.
- Sumários persistidos em SQLite (`data/memory.sqlite3`) com restauração automática (`RESTORE_CONTEXT=true`, janela padrão 2h).
- Exposto no `/status` sob `memory.current_summary` e `restore_context`.

## Política / LLM
- `apps/policy_worker` consulta o Ollama (`OLLAMA_URL`) com o modelo padrão `llama3:8b-instruct-q4`.
- Respostas seguem o formato XML `<speech/><mood/><actions/>`; fallback mock controlado por `POLICY_FORCE_MOCK=1` para ambientes offline.

## Próximos Passos
- Integrar memória persistente e sumarização.
- Conectar com o painel de telemetria (repo `kitsu-telemetry`).
- Acrescentar chamadas reais para Ollama/Coqui-TTS quando disponíveis.
