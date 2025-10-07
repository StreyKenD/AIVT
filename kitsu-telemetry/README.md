# Kitsu Telemetry

Módulo de telemetria para o ecossistema Kitsu.exe, composto por uma API FastAPI e uma interface SvelteKit com Tailwind CSS.

## Pré-requisitos
- Python 3.11+
- Poetry ou `pip` para instalar dependências
- Node.js 18+ com `pnpm`

## Configuração rápida
1. Copie `.env.example` para `.env` e ajuste as variáveis conforme necessário.
2. Instale as dependências Python:
   ```bash
   poetry install
   ```
3. Inicialize a UI:
   ```bash
   cd kitsu-telemetry/ui
   pnpm install
   pnpm dev
   ```

## Executando a API
```bash
uvicorn api.main:app --reload --port ${API_PORT:-8001}
```

## Estrutura
- `api/`: código da API de telemetria (FastAPI + SQLite).
- `ui/`: front-end SvelteKit com Tailwind e mock de WebSocket para prototipagem.
- `tests/`: testes de fumaça para endpoints e exportação CSV.

## Testes
Execute na raiz do repositório:
```bash
pytest -q
```
