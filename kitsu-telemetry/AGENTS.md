# AGENTS.md

## Escopo
Arquivos neste diretório descrevem a API e UI de telemetria do projeto Kitsu.exe. Siga as diretrizes abaixo ao modificar qualquer arquivo sob `kitsu-telemetry/`.

## Estilo geral
- Prefira código assíncrono e digitado (type hints explícitos em Python e TypeScript).
- Utilize nomes autoexplicativos e comentários curtos apenas quando necessário.
- Mantenha a documentação em português.

## Backend (Python)
- Use FastAPI com rotas claras (`/health`, `/events`, `/events/export`).
- Persistência via SQLite usando `aiosqlite`; inicialize a base na inicialização do app.
- Exporte CSV em streaming (`text/csv`) para evitar carregar tudo em memória.

## Frontend (SvelteKit)
- UI baseada em Tailwind CSS.
- Crie componentes acessíveis (atributos `aria-*` quando fizer sentido).
- Mock de WebSocket deve permitir testes locais sem backend em tempo real.

## Testes
- Garanta que os testes possam rodar com `pytest -q` na raiz do repositório.
- Inclua smoke tests para a importação do app pelo Uvicorn e para a exportação CSV.
