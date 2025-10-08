# Primeiros Passos (Kitsu.exe Core)

Este guia resume o que precisa ser feito logo após clonar o repositório para rodar o ambiente local de desenvolvimento com segurança e em conformidade com as licenças dos modelos envolvidos.

## 1. Pré-requisitos
- Python 3.11+ instalado.
- [Poetry](https://python-poetry.org/docs/) instalado.
- Dependências de sistema para áudio/WebRTC (`portaudio`, `ffmpeg`, `libsndfile`) quando for executar os serviços de TTS/ASR.

## 2. Instalar dependências do projeto
```bash
poetry install
```

## 3. Configurar variáveis de ambiente
Copie o arquivo `.env.example` para `.env`, preencha as credenciais (Twitch, OBS, Ollama, Coqui-TTS etc.) e inclua as variáveis do orquestrador/telemetria:

```
ORCH_HOST=127.0.0.1
ORCH_PORT=8000
ORCH_CORS_ALLOW_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
TELEMETRY_API_URL=http://localhost:8001/api
```

> Ajuste `ORCH_HOST` para `0.0.0.0` caso o painel/UI rode fora da mesma máquina. O valor de `TELEMETRY_API_URL` deve apontar para a API do repositório `kitsu-telemetry`.

## 4. Validar qualidade local
Execute a suíte mínima antes de subir qualquer alteração:
```bash
poetry run pytest -q
poetry run ruff .
poetry run black --check .
poetry run mypy
```
> Sem Poetry, instale `pytest` e `pytest-asyncio` com `python -m pip install pytest pytest-asyncio` e execute `python -m pytest -q`.

## 5. Ativar hooks de pré-commit
Instale os hooks configurados em `.pre-commit-config.yaml` para garantir lint/format/tipos automaticamente antes dos commits:
```bash
poetry run pre-commit install
```

## 6. Avisos de licença obrigatórios
A utilização dos modelos requer aceitar os termos de terceiros. Leia e mantenha cópias destes documentos em `licenses/third_party/`:
- **Llama 3 8B Instruct (Meta)** – veja `licenses/third_party/llama3_license.pdf` antes de redistribuir ou demonstrar o modelo.
- **Coqui-TTS** (modelo selecionado conforme política do projeto) – restrições detalhadas em `licenses/third_party/coqui_tts_model_card.pdf`.
- **Avatar Live2D “Lumi”** – atribuição obrigatória conforme `licenses/third_party/live2d_lumi_license.pdf`.

> Certifique-se de que qualquer distribuição ou demo pública do projeto inclui as atribuições acima e segue os termos de cada fornecedor.

## 7. Subir os serviços FastAPI
- Backend de controle: `poetry run uvicorn apps.control_panel_backend.main:app --reload`
- Orquestrador (usando as variáveis configuradas):  
  ```bash
  poetry run uvicorn apps.orchestrator.main:app --reload --host ${ORCH_HOST:-127.0.0.1} --port ${ORCH_PORT:-8000}
  ```
- Valide que a API responde: `curl http://${ORCH_HOST:-127.0.0.1}:${ORCH_PORT:-8000}/status`
- (Opcional) Scripts paralelos em PowerShell: `scripts\run_all.ps1 -UsePoetry`

## 8. Validar via UI de telemetria
1. No repositório `../kitsu-telemetry`, configure `.env` (API) e `ui/.env.local` com os mesmos `PUBLIC_ORCH_BASE_URL`/`PUBLIC_ORCH_WS_URL` apontando para `http://{ORCH_HOST}:{ORCH_PORT}`.
2. Inicie a API de telemetria: `poetry run uvicorn api.main:app --reload --port 8001`.
3. Inicie a UI:  
   ```bash
   cd kitsu-telemetry/ui
   pnpm install
   pnpm dev
   ```
4. Abra `http://localhost:5173` e verifique se:
   - O painel mostra o `GET /status` do orquestrador.
   - O gráfico de eventos se atualiza ao gerar ações (chamada a `POST /tts`, toggles etc.).
   - A conexão WebSocket aparece como `connected`.

> Caso veja blocos bloqueados por CORS, confirme se `ORCH_CORS_ALLOW_ORIGINS` inclui a origem exibida no console do navegador.
