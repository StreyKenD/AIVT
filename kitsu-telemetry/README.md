# Kitsu Telemetry

Módulo de telemetria para o ecossistema Kitsu.exe, composto por uma API FastAPI e uma interface SvelteKit com Tailwind CSS.

## Pré-requisitos
- Python 3.11+
- Poetry ou `pip` para instalar dependências
- Node.js 18+ com `pnpm`

## Configuração rápida
1. Copie `.env.example` para `.env` e ajuste as variáveis conforme necessário (host, porta, origens autorizadas e caminho do banco SQLite).
2. Dentro de `ui/`, copie `.env.example` para `.env.local` (por exemplo `cp ui/.env.example ui/.env.local`) e ajuste `PUBLIC_ORCH_BASE_URL`, `PUBLIC_ORCH_WS_URL` **e** `PUBLIC_CONTROL_BASE_URL` apontando para o orquestrador e o backend de controle (`http://{ORCH_HOST}:{ORCH_PORT}` e `http://{CONTROL_PANEL_HOST}:{CONTROL_PANEL_PORT}`).
3. Instale as dependências Python:
   ```bash
   poetry install
   ```
4. Inicialize a UI:
   ```bash
   cd kitsu-telemetry/ui
   pnpm install
   pnpm dev
   ```

## Variáveis de ambiente
- API (`.env`):
  - `API_HOST`: interface de bind utilizada pelo servidor FastAPI (padrão `127.0.0.1`).
  - `API_PORT`: porta HTTP exposta pela API de telemetria (padrão `8001`).
- `TELEMETRY_ALLOWED_ORIGINS`: lista separada por vírgulas das origens autorizadas para chamadas HTTP (padrão `http://localhost:5173`).
- `TELEMETRY_DB_PATH`: caminho para o arquivo SQLite que armazenará os eventos (padrão `./telemetry.db`).
- `TELEMETRY_API_KEY`: chave obrigatória para autenticar chamadas (`X-API-KEY`); deixe vazio para desabilitar a proteção (não recomendado além de ambientes locais).
- `TELEMETRY_RETENTION_SECONDS`: janela de retenção automática. Eventos mais antigos que o valor informado (ex.: `14400` para 4h) são purgados após cada ingestão.
- UI (`ui/.env.local`):
  - `PUBLIC_ORCH_BASE_URL`: endpoint HTTP do orquestrador (ex.: `http://127.0.0.1:8000`).
  - `PUBLIC_ORCH_WS_URL`: base WebSocket (`ws://127.0.0.1:8000`); o app complementa com `/stream` automaticamente.
  - `PUBLIC_CONTROL_BASE_URL`: URL do backend de controle (`kitsu-vtuber-ai/apps/control_panel_backend`) que agrega métricas e comandos (padrão `http://127.0.0.1:8100`).

> Certifique-se de alinhar `PUBLIC_ORCH_*` com `ORCH_HOST`/`ORCH_PORT` definidos no repositório `kitsu-vtuber-ai`.

## Executando API e UI em conjunto
Abra dois terminais (ou use um gerenciador como `tmux`):

```bash
# Terminal 1 - API
poetry run uvicorn api.main:app --reload --host ${API_HOST:-127.0.0.1} --port ${API_PORT:-8001}

# Terminal 2 - UI
cd ui
pnpm dev -- --host 127.0.0.1 --port 5173
```

Ao acessar `http://localhost:5173`, o painel irá:
- Chamar `GET /status` do orquestrador usando `PUBLIC_ORCH_BASE_URL` para preencher persona, módulos e memória.
- Abrir o WebSocket em `${PUBLIC_ORCH_WS_URL}/stream` (veja o log `connected` no console do navegador).
- Consultar o backend de controle (`PUBLIC_CONTROL_BASE_URL`) para métricas agregadas, download do CSV, comandos de pânico/mute e presets.
- Enviar eventos manualmente para o orquestrador/telemetria quando as ações do painel forem utilizadas.

> Com `TELEMETRY_API_KEY` configurado, inclua `X-API-KEY: <valor>` nas requisições REST do painel, scripts ou ferramentas de inspeção.

> Quando rodar tudo na mesma máquina, basta manter `ORCH_CORS_ALLOW_ORIGINS` com as origens acima para evitar erros de CORS.
> Problemas com aliases ou tipos? Rode `pnpm exec svelte-kit sync` dentro de `ui/` antes de reiniciar o servidor dev.

## Estrutura
- `api/`: código da API de telemetria (FastAPI + SQLite).
- `ui/`: front-end SvelteKit com Tailwind e mock de WebSocket para prototipagem.
- `tests/`: testes de fumaça para endpoints e exportação CSV.

## Endpoints principais
- `POST /events` – ingesta em lote com autenticação opcional via `X-API-KEY`.
- `GET /events` – lista paginada com filtros por `type`/`source`.
- `GET /events/export` – exporta CSV em streaming.
- `GET /metrics/latest` – agrega métricas (contagem, latência média/máx/mín, percentuais e temperatura) por tipo dentro de uma janela deslizante (`window_seconds`). Eventos `hardware.gpu` trazem `temperature_c`, `utilization_pct`, `memory_*` e `power_w`.
- `POST /maintenance/prune` – purga manualmente eventos mais antigos que `max_age_seconds`.

## Testes
Execute na raiz do repositório:
```bash
poetry lock --check
poetry run pytest -q
```
> Alternativa com `pip`: `python -m pip install pytest httpx` seguido de `python -m pytest -q`.

## Licenças e créditos obrigatórios
- **Llama 3 8B Instruct (Meta)** – modelos e demos que consumirem dados derivados devem citar `licenses/third_party/llama3_license.pdf`.
- **Coqui-TTS** – qualquer asset de voz exposto via telemetria deve seguir `licenses/third_party/coqui_tts_model_card.pdf`.
- **Avatar Live2D “Lumi”** – inclua a referência de `licenses/third_party/live2d_lumi_license.pdf` em dashboards públicos, vídeos ou capturas de tela que exibam o avatar.
