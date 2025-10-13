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

## Dependências de runtime
- Python 3.11+ com [Poetry](https://python-poetry.org/) para gerenciar o ambiente virtual.
- `obsws-python 1.7.2`, alinhado ao protocolo **OBS WebSocket v5** (habilite o plugin nativo do OBS 28+).
- Binários externos para áudio/vídeo: `ffmpeg`, `portaudio`, `libsndfile` e drivers das interfaces em uso.
- Opcional, porém recomendado para desenvolvimento: OBS Studio e VTube Studio atualizados para testar integrações.

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
5. Para inspecionar o orquestrador (FastAPI + WebSocket):
   ```bash
   poetry run uvicorn apps.orchestrator.main:app --reload --host ${ORCH_HOST:-127.0.0.1} --port ${ORCH_PORT:-8000}
   curl http://${ORCH_HOST:-127.0.0.1}:${ORCH_PORT:-8000}/status
   ```

> **Atribuição**: O modelo LLM padrão é **Llama 3 8B Instruct** servido pelo Ollama.

### Como rodar sem Docker (Windows)

1. Instale o [Python 3.11](https://www.python.org/downloads/windows/) (habilite "Add python.exe to PATH") e o [Poetry](https://python-poetry.org/docs/).
2. Clone o repositório, abra **PowerShell 7+ (pwsh)** e configure o ambiente virtual:
   ```powershell
   poetry env use 3.11
   poetry install
   ```
3. Copie o arquivo de variáveis: `Copy-Item .env.example .env` e edite as credenciais (Twitch OAuth, OBS, VTS etc.).
4. Opcional porém recomendado: instale os hooks locais com `poetry run pre-commit install` para ativar `ruff`, `black`, `isort` e `mypy` antes dos commits.
5. Use os scripts de automação em `scripts/` para iniciar ou encerrar cada serviço individualmente:
   ```powershell
   pwsh scripts/run_orchestrator.ps1 -Action start   # inicia o orquestrador (FastAPI)
   pwsh scripts/run_asr.ps1 -Action status           # verifica o worker de ASR
   pwsh scripts/run_tts.ps1 -Action stop             # encerra o worker de TTS
   ```
6. Para subir tudo de uma vez (sem Docker), execute:
   ```powershell
   pwsh scripts/run_all_no_docker.ps1 -Action start
   ```
   Utilize `-Action stop` para derrubar todos os serviços ou `-Action status` para conferir os PIDs ativos.

## Variáveis de ambiente essenciais
As variáveis abaixo controlam como o orquestrador expõe seus endpoints HTTP/WebSocket e como os eventos são encaminhados para o módulo de telemetria:

- `ORCH_HOST`: interface de bind utilizada pelo `uvicorn` (padrão `127.0.0.1`). Use `0.0.0.0` ao expor a API para outras máquinas ou para a UI hospedada fora do host local.
- `ORCH_PORT`: porta pública do orquestrador. Alinhe esse valor com `PUBLIC_ORCH_BASE_URL` e `PUBLIC_ORCH_WS_URL` no repositório `kitsu-telemetry`; o valor recomendado para desenvolvimento é `8000`.
- `TELEMETRY_API_URL`: URL base (ex.: `http://localhost:8001/api`) para onde os eventos de estado são publicados. Quando vazia, o orquestrador funciona sem telemetria externa.

### CORS do orquestrador
O `apps.orchestrator.main` aplica `CORSMiddleware` automaticamente. Defina `ORCH_CORS_ALLOW_ORIGINS` com uma lista separada por vírgula contendo as origens autorizadas (por exemplo `http://localhost:5173,http://127.0.0.1:5173`). Por padrão o middleware habilita `GET`, `POST`, `OPTIONS` e upgrades de WebSocket; use `ORCH_CORS_ALLOW_ALL=1` apenas em ambientes de desenvolvimento controlados.

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
- Testes: `poetry run pytest -q` (ou `python -m pytest -q` após `python -m pip install pytest pytest-asyncio`)
- Pré-commit: `poetry run pre-commit run --all-files`

> Instale os hooks localmente com `poetry run pre-commit install` (o arquivo [`./.pre-commit-config.yaml`](.pre-commit-config.yaml) já está configurado para `apps/`, `libs/` e `tests/`).

## Licenças e créditos obrigatórios
- **Llama 3 8B Instruct (Meta)** via Ollama – leia e acompanhe `licenses/third_party/llama3_license.pdf` antes de qualquer distribuição pública ou demo gravada.
- **Coqui-TTS (modelo selecionado)** – requisitos detalhados em `licenses/third_party/coqui_tts_model_card.pdf`, incluindo limitações de uso comercial.
- **Avatar Live2D “Lumi”** – atribuição explícita conforme `licenses/third_party/live2d_lumi_license.pdf` em transmissões, vídeos e materiais promocionais.

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
