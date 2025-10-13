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

### Captura de microfone no Windows
- Liste os dispositivos suportados pelos backends `sounddevice` e `PyAudio` com um único comando:
  ```powershell
  poetry run python -m kitsu_vtuber_ai.apps.asr_worker.devices
  ```
- Utilize `--json` para integrar com scripts ou salvar a lista completa: `poetry run python -m kitsu_vtuber_ai.apps.asr_worker.devices --json > devices.json`.
- Defina `ASR_INPUT_DEVICE` com o nome retornado pelo `sounddevice` (string exata) ou com o índice numérico indicado para `PyAudio`. Caso nenhum backend esteja disponível, ajuste `ASR_FAKE_AUDIO=1` para manter o worker em modo silencioso durante testes.
- Atualize `ASR_SAMPLE_RATE`, `ASR_FRAME_MS` e `ASR_SILENCE_MS` se precisar alinhar o tempo de frame às placas de captura ou interfaces de áudio específicas.

### Instalando `ffmpeg`, `libsndfile` e `portaudio` no Windows
- Via [Chocolatey](https://chocolatey.org/install):
  ```powershell
  choco install ffmpeg portaudio libsndfile
  ```
- Sem gerenciador de pacotes:
  1. Baixe o pacote "release full" do FFmpeg em <https://www.gyan.dev/ffmpeg/builds/> e extraia em `C:\ffmpeg` (adicione `C:\\ffmpeg\\bin` ao `PATH`).
  2. Instale o `libsndfile` via `.exe` oficial em <https://github.com/libsndfile/libsndfile/releases> garantindo que a pasta `bin/` esteja no `PATH`.
  3. Copie o `portaudio_x64.dll` do pacote pré-compilado disponível em <http://files.portaudio.com/download.html> para uma pasta presente no `PATH` (ex.: `C:\AudioSDK`).
- Valide a instalação no PowerShell (ajuste o caminho conforme a pasta escolhida para as DLLs):
  ```powershell
  ffmpeg -version
  Get-Command ffmpeg
  Get-ChildItem "C:\\AudioSDK" -Filter "*sndfile*.dll"
  Get-ChildItem "C:\\AudioSDK" -Filter "*portaudio*.dll"
  ```

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
- `TELEMETRY_API_KEY` / `ORCHESTRATOR_API_KEY`: tokens opcionais para proteger os endpoints `/events` (telemetria) e `/persona`/`/toggle` quando acessados por integrações externas.
- `ORCHESTRATOR_URL`: endereço HTTP utilizado pelos workers e integrações (Twitch, OBS, VTS) para publicar eventos no orquestrador.
- `TTS_OUTPUT_DIR`: pasta onde os áudios sintetizados são cacheados (padrão `artifacts/tts`).
- `TTS_MODEL_NAME` / `PIPER_MODEL`: identificadores dos modelos Coqui/Piper carregados pelos workers (ver [TTS Worker](#tts-worker)).
- `TWITCH_CHANNEL` / `TWITCH_OAUTH_TOKEN`: credenciais do bot `twitchio` responsável por ler comandos em tempo real. Defina `TWITCH_BOT_NICK` e `TWITCH_DEFAULT_SCENE` se desejar personalizar o nickname ou a cena fallback.
- `OBS_WS_URL` / `OBS_WS_PASSWORD`: endpoint do **obs-websocket v5** e senha configurada em OBS. `OBS_SCENES` aceita uma lista separada por vírgula utilizada pelo script demo; `OBS_PANIC_FILTER` indica o filtro ativado pelo macro de pânico.
- `VTS_URL` / `VTS_AUTH_TOKEN`: endereço do servidor WebSocket do VTube Studio e token persistido após a primeira autorização do plugin. Ajuste `VTS_PLUGIN_NAME`/`VTS_DEVELOPER` para identificar o plugin nas configurações do VTS.
- `KITSU_LOG_ROOT`: diretório onde cada serviço grava arquivos `.log` em JSON rotacionados diariamente (padrão `logs`).
- `GPU_METRICS_INTERVAL_SECONDS`: frequência, em segundos, do coletor NVML que publica eventos `hardware.gpu` na telemetria.

### CORS do orquestrador
O `apps.orchestrator.main` aplica `CORSMiddleware` automaticamente. Defina `ORCH_CORS_ALLOW_ORIGINS` com uma lista separada por vírgula contendo as origens autorizadas (por exemplo `http://localhost:5173,http://127.0.0.1:5173`). Por padrão o middleware habilita `GET`, `POST`, `OPTIONS` e upgrades de WebSocket; use `ORCH_CORS_ALLOW_ALL=1` apenas em ambientes de desenvolvimento controlados.

## Estrutura
- `apps/`: serviços principais (ASR, política, TTS, orquestração, integrações OBS/VTS/Twitch, backend de controle).
- `libs/`: utilitários compartilhados e memória.
- `configs/`: perfis e regras de segurança/moderação.
- `scripts/`: utilitários para desenvolvimento.
- `tests/`: testes de fumaça via `pytest`.

## Qualidade
- Lockfile: `poetry lock --check`
- Lint: `poetry run ruff .`
- Formatação: `poetry run black --check .`
- Tipagem: `poetry run mypy`
- Testes: `poetry run pytest -q` (ou `python -m pytest -q` após `python -m pip install pytest pytest-asyncio`)
- Pré-commit: `poetry run pre-commit run --all-files`

> Instale os hooks localmente com `poetry run pre-commit install` (o arquivo [`./.pre-commit-config.yaml`](.pre-commit-config.yaml) já está configurado para `apps/`, `libs/` e `tests/`).

## QA & soak harness
- Ajuste `SOAK_POLICY_URL`/`SOAK_TELEMETRY_URL` no `.env` conforme o ambiente.
- Inicie todos os serviços (`pwsh scripts/run_all_no_docker.ps1 -Action start`).
- Execute `poetry run python -m kitsu_vtuber_ai.apps.soak_harness.main --duration-minutes 120 --output artifacts/soak/summary.json` (use `--max-turns` em execuções rápidas).
- O resumo agrega latências média/p95 por estágio e publica um evento `soak.result` consumido pelo painel (`Resultados do soak test`).

### Logs estruturados e métricas de hardware
- Todos os serviços (`apps/`) utilizam `libs.common.configure_json_logging` para emitir logs estruturados tanto no `stderr` quanto no diretório configurado por `KITSU_LOG_ROOT`. Cada linha é um JSON com `ts`, `service`, `logger`, `level`, `message` e extras opcionais.
- O orquestrador inicializa um `GPUMonitor` baseado em `pynvml` que publica periodicamente eventos `hardware.gpu` (temperatura, utilização, fan, memória e consumo) para a API de telemetria. Ajuste `GPU_METRICS_INTERVAL_SECONDS` para controlar a frequência ou remova `pynvml` do ambiente para desativar a coleta.


## Licenças e créditos obrigatórios
- **Llama 3 8B Instruct (Meta)** via Ollama – leia e acompanhe `licenses/third_party/llama3_license.pdf` antes de qualquer distribuição pública ou demo gravada.
- **Coqui-TTS (modelo selecionado)** – requisitos detalhados em `licenses/third_party/coqui_tts_model_card.pdf`, incluindo limitações de uso comercial.
- **Avatar Live2D “Lumi”** – atribuição explícita conforme `licenses/third_party/live2d_lumi_license.pdf` em transmissões, vídeos e materiais promocionais.

Mantenha essas referências sempre disponíveis ao compartilhar builds ou gravações do projeto.


## Operações e release
### Checklist do piloto
- Antes: rodar o soak recente, validar áudio/vídeo (OBS + VTS), conferir tokens e presets, preparar macro de pânico.
- Durante: manter o painel aberto, registrar incidentes em `#kitsu-ops`, inspecionar `/status` a cada 30 minutos.
- Pós-show: exportar CSV da telemetria, rodar soak curto (`--max-turns 5`), arquivar incidentes/clipes.

### Rollback e incidentes
1. Disparar o botão de pânico (mute + cena BRB).
2. Reiniciar serviços específicos com `scripts/service_manager.ps1`.
3. Se necessário, interromper tudo com `scripts/run_all_no_docker.ps1 -Action stop`.
4. Documentar o ocorrido em `docs/incidents/` e anexar métricas/CSV.

### Empacotamento da release
- Gerar o bundle Windows-first via `pwsh scripts/package_release.ps1 -OutputPath artifacts/release -Zip`.
- O script copia `README.md`, `RUN_FIRST.md`, `.env.example`, scripts PowerShell e `licenses/third_party/`.
- Compartilhar o ZIP somente após concluir o checklist de piloto e QA.

## APIs do Orquestrador
- `GET /status`: snapshot completo da persona, módulos, cena atual e último pedido de TTS.
- `POST /toggle/{module}`: habilita/desabilita módulos (`asr_worker`, `policy_worker`, `tts_worker`, `avatar_controller`, `obs_controller`, `twitch_ingest`).
- `POST /persona`: ajusta estilo (`kawaii`, `chaotic`, `calm`), nível de caos/energia e modo familiar.
- `POST /tts`: registra um pedido de fala (texto + voz preferida).
- `POST /obs/scene`: altera a cena atual do OBS (com reconexão automática e macro de pânico).
- `POST /vts/expr`: aplica expressão no avatar via VTube Studio (WebSocket autenticado).
- `POST /ingest/chat`: registra mensagens do chat/assistente para alimentar a memória.
- `POST /events/asr`: recebe eventos `asr_partial`/`asr_final` do worker de ASR e difunde pelo WebSocket.
- `WS /stream`: difusão em tempo real dos eventos acima e das métricas simuladas.

## Memória
- Buffer curto de conversas (ring buffer) com sumarização sintética a cada 6 mensagens.
- Sumários persistidos em SQLite (`data/memory.sqlite3`) com restauração automática (`RESTORE_CONTEXT=true`, janela padrão 2h).
- Exposto no `/status` sob `memory.current_summary` e `restore_context`.

## Política / LLM
- `apps/policy_worker` consulta o Ollama (`OLLAMA_URL`) usando por padrão o modelo **Mixtral** (`LLM_MODEL_NAME=mixtral:8x7b-instruct-q4_K_M`). Execute `ollama pull mixtral:8x7b-instruct-q4_K_M` antes do primeiro boot.
- O endpoint `POST /respond` retorna um fluxo SSE (`text/event-stream`) com eventos `start`, `token`, `retry` e `final`. Cada `token` representa o streaming incremental dos trechos XML; o evento `final` inclui métricas (`latency_ms`, `stats`) e metadados da persona.
- O prompt combina instruções de sistema + few-shots para reforçar o estilo kawaii/caótico, energia/nível de caos (`chaos_level`, `energy`) e modo familiar (`POLICY_FAMILY_FRIENDLY`).
- A filtragem familiar é reforçada por um pipeline de moderação síncrono (`configs/safety/` + `libs.safety.ModerationPipeline`). Prompts proibidos retornam uma mensagem segura imediatamente; respostas finais passam por varredura adicional e, se necessário, são sanitizadas antes de chegar ao TTS.
- O worker tenta reconectar/repetir (`POLICY_RETRY_ATTEMPTS`, `POLICY_RETRY_BACKOFF`) e, em caso de falha ou resposta inválida, volta ao mock amistoso (`POLICY_FORCE_MOCK=1` ou fallback automático), preservando o formato `<speech/><mood/><actions/>`.

## TTS Worker
- O serviço (`apps/tts_worker`) prioriza o Coqui-TTS (`TTS_MODEL_NAME`) e recorre ao Piper (`PIPER_MODEL`, `PIPER_PATH`) quando o primeiro não está disponível. Caso nenhum backend seja carregado, um sintetizador determinístico gera silêncio para testes.
- Saídas são cacheadas em disco (`artifacts/tts`) com metadados JSON (voz, latência, visemas). Chamadas repetidas reutilizam o arquivo local.
- Use `TTS_DISABLE_COQUI=1` ou `TTS_DISABLE_PIPER=1` para forçar um backend específico durante depuração.
- O método `cancel_active()` interrompe jobs em andamento antes do próximo trecho sintetizado, útil para cenários de "barge-in".

## Próximos Passos
- Conectar com o painel de telemetria (repo `kitsu-telemetry`).
- Expandir integrações ao vivo (OBS, VTube Studio, Twitch) com reconexão resiliente. ✅ Bot da Twitch controla módulos/cenas, controlador OBS reconecta com backoff e cliente VTS autentica via WebSocket.
- Ajustar o pipeline Coqui/Piper para vozes definitivas e latências < 1.2 s.
