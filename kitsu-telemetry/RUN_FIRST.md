# Primeiros Passos (Kitsu Telemetry)

Guia rápido para configurar e validar o módulo de telemetria (API + UI) após clonar o repositório.

## 1. Pré-requisitos
- Python 3.11+ com [Poetry](https://python-poetry.org/)
- Node.js 18+ com `pnpm`
- Banco SQLite disponível (já bundlado com Python)

## 2. Instalar dependências
```bash
poetry install
cd ui
pnpm install
cd ..
```

## 3. Configurar variáveis de ambiente

Crie o arquivo `.env` (API) a partir de `.env.example` e ajuste os valores conforme o ambiente:

```
API_HOST=127.0.0.1
API_PORT=8001
TELEMETRY_ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
```

Para a UI, copie `ui/.env.example` para `ui/.env.local` mantendo alinhamento com o orquestrador (`kitsu-vtuber-ai`):

```
PUBLIC_ORCH_BASE_URL=http://127.0.0.1:8000
PUBLIC_ORCH_WS_URL=ws://127.0.0.1:8000
```

> Garanta que `ORCH_HOST`, `ORCH_PORT` e `ORCH_CORS_ALLOW_ORIGINS` estejam configurados no repositório `kitsu-vtuber-ai` com valores compatíveis. O cliente adiciona `/stream` automaticamente ao `PUBLIC_ORCH_WS_URL`.

## 4. Rodar API e UI
Abra dois terminais ou sessões:

```bash
# Terminal 1
poetry run uvicorn api.main:app --reload --host ${API_HOST:-127.0.0.1} --port ${API_PORT:-8001}

# Terminal 2
cd ui
pnpm dev -- --host 127.0.0.1 --port 5173
```

Acesse `http://localhost:5173` e confirme:
- Indicador de status do orquestrador em **verde** (requisição `GET /status` bem-sucedida).
- Eventos em tempo real fluindo no painel após ações (WebSocket conectado).
- Roteamento de métricas para `POST /events` funcionando (verifique os dados na aba de histórico).

## 5. Testes rápidos
Valide os endpoints periodicamente:
```bash
poetry run pytest -q
```
> Alternativa com `pip`: `python -m pip install pytest httpx` seguido de `python -m pytest -q`.

## 6. Licenças e créditos
- **Llama 3 8B Instruct (Meta)** – consulte `licenses/third_party/llama3_license.pdf`.
- **Coqui-TTS** – requisitos em `licenses/third_party/coqui_tts_model_card.pdf`.
- **Avatar Live2D “Lumi”** – atribuição obrigatória detalhada em `licenses/third_party/live2d_lumi_license.pdf`.

> Ao expor o painel publicamente (dashboards, capturas ou demonstrações), inclua as referências acima junto ao material.
