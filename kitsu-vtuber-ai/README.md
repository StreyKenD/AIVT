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
5. (Opcional) Suba todos os workers (incluindo o novo orquestrador e os stubs) em paralelo via PowerShell:
   ```powershell
   scripts/run_all.ps1
   ```

   Helpers individuais (`scripts/run_*.ps1`, quando presentes) delegam o ciclo de vida dos serviços para `scripts/service_manager.ps1`. O gerenciador grava o PID **do worker real** (por exemplo `python.exe`/`uvicorn.exe`) em `.pids/<serviço>.pid`, procurando de forma recursiva pelos descendentes do wrapper (`poetry`, `pwsh`, etc.) imediatamente após o `Start-Process`. Assim, o comando `stop` encerra o worker certo antes de limpar o arquivo de PID. Se algum serviço spawnar múltiplos filhos, passe pistas adicionais com `-ChildProcessNames` no helper correspondente para facilitar a resolução:

   ```powershell
   scripts/service_manager.ps1 start orchestrator `
       -Command "poetry run uvicorn apps.orchestrator.main:app --reload" `
       -ChildProcessNames @('python', 'uvicorn')
   ```

   Com isso, `scripts/service_manager.ps1 stop orchestrator` derruba o PID persistido (worker) e, se necessário, faz fallback para o processo pai sem deixar shims órfãos.

6. Para inspecionar o orquestrador (FastAPI + WebSocket):
   ```bash
   poetry run uvicorn apps.orchestrator.main:app --reload --host ${ORCH_HOST:-127.0.0.1} --port ${ORCH_PORT:-8000}
   curl http://${ORCH_HOST:-127.0.0.1}:${ORCH_PORT:-8000}/status
   ```

> **Atribuição**: O modelo LLM padrão é **Llama 3 8B Instruct** servido pelo Ollama.

## ASR em tempo real (faster-whisper + VAD)
- O worker de ASR utiliza [`faster-whisper`](https://github.com/SYSTRAN/faster-whisper) com suporte a GPU (CUDA) e quantização `int8_float16` por padrão. Se a inicialização em GPU falhar, o worker faz fallback automático para CPU (`int8`) e registra um aviso nos logs.
- Captura de áudio direta via `sounddevice` (RAW WASAPI/DirectSound). Caso o backend não esteja disponível, tenta `PyAudio`; na ausência de ambos, opera em modo sintético (`ASR_FAKE_AUDIO=1`) apenas para testes.
- VAD local com [`webrtcvad`](https://github.com/wiseman/py-webrtcvad) identifica segmentos de fala. Ajuste o modo de agressividade com `ASR_VAD_AGGRESSIVENESS` (0-3) ou desative via `ASR_VAD=none` se estiver usando outra solução de detecção.
- Parciais emitidas a cada `ASR_PARTIAL_INTERVAL_MS` (200 ms padrão) e finais após `ASR_SILENCE_MS` (500 ms padrão) de silêncio. Nos testes de bancada com uma RTX 4060 Ti, a latência média dos parciais ficou abaixo de 600 ms.
- Eventos são publicados no broker do orquestrador (`POST /events/asr`) como `asr_partial` e `asr_final`, contendo `segment`, `text`, `confidence`, `started_at`, `ended_at` e métricas (`latency_ms` ou `duration_ms`). O WebSocket `/stream` propaga essas mensagens em tempo real para o painel/UI.

### Variáveis específicas do ASR
- `ASR_MODEL`: modelo Whisper (`small.en`, `medium.en`, etc.).
- `ASR_DEVICE`: prioridade de dispositivo (`cuda`, `cpu`).
- `ASR_COMPUTE_TYPE`: override opcional do compute type (`int8_float16`, `int8`...).
- `ASR_SAMPLE_RATE`: taxa de amostragem (Hz, padrão `16000`).
- `ASR_FRAME_MS`: tamanho de frame em ms (padrão `20`).
- `ASR_PARTIAL_INTERVAL_MS`: intervalo mínimo entre parciais (ms).
- `ASR_SILENCE_MS`: janela de silêncio para finalizar um segmento (ms).
- `ASR_VAD`: `webrtc` (padrão) ou `none`.
- `ASR_VAD_AGGRESSIVENESS`: agressividade do VAD (0-3).
- `ASR_INPUT_DEVICE`: ID/nome do dispositivo de captura (opcional).
- `ASR_FAKE_AUDIO`: force modo sintético (para testes sem microfone).
- `ORCHESTRATOR_URL`: URL base alternativa para publicar eventos; por padrão deriva de `ORCH_HOST`/`ORCH_PORT`.

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
- O worker tenta reconectar/repetir (`POLICY_RETRY_ATTEMPTS`, `POLICY_RETRY_BACKOFF`) e, em caso de falha ou resposta inválida, volta ao mock amistoso (`POLICY_FORCE_MOCK=1` ou fallback automático), preservando o formato `<speech/><mood/><actions/>`.

## Próximos Passos
- Integrar memória persistente e sumarização.
- Conectar com o painel de telemetria (repo `kitsu-telemetry`).
- Acrescentar chamadas reais para Ollama/Coqui-TTS quando disponíveis.
