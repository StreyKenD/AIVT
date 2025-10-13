# Primeiros Passos (Kitsu.exe Core)

Este guia resume o que precisa ser feito logo após clonar o repositório para rodar o ambiente local de desenvolvimento com segurança e em conformidade com as licenças dos modelos envolvidos.

## 1. Pré-requisitos
- Python 3.11+ instalado.
- [Poetry](https://python-poetry.org/docs/) instalado.
- Dependências de sistema para áudio/WebRTC (`portaudio`, `ffmpeg`, `libsndfile`) quando for executar os serviços de TTS/ASR.

### 1.1 Instalar os binários de áudio/vídeo (Windows)
- Com [Chocolatey](https://chocolatey.org/install):
  ```powershell
  choco install ffmpeg portaudio libsndfile
  ```
- Sem Chocolatey, baixe os binários pré-compilados:
  1. **FFmpeg**: baixe o pacote "release full" em <https://www.gyan.dev/ffmpeg/builds/> e extraia em `C:\ffmpeg`.
  2. **libsndfile**: obtenha o instalador `.exe` em <https://github.com/libsndfile/libsndfile/releases> (adicione `bin\\` ao `PATH`).
  3. **PortAudio**: utilize o pacote pré-compilado em <http://files.portaudio.com/download.html> (copie `portaudio_x64.dll` para uma pasta no `PATH`).
- Após instalar, valide no PowerShell (ajuste o caminho conforme onde extraiu as DLLs):
  ```powershell
  ffmpeg -version
  Get-Command ffmpeg
  Get-ChildItem "C:\\AudioSDK" -Filter "*sndfile*.dll"
  Get-ChildItem "C:\\AudioSDK" -Filter "*portaudio*.dll"
  ```

## 2. Instalar dependências do projeto
```bash
poetry install
```

## 3. Configurar variáveis de ambiente
Copie o arquivo `.env.example` para `.env`, preencha as credenciais (Twitch, OBS, VTube Studio, Ollama, Coqui-TTS etc.) e inclua as variáveis do orquestrador/telemetria:

```
ORCH_HOST=127.0.0.1
ORCH_PORT=8000
ORCH_CORS_ALLOW_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
TELEMETRY_API_URL=http://localhost:8001/api
TELEMETRY_API_KEY=dev-secret
ORCHESTRATOR_URL=http://127.0.0.1:8000
ORCHESTRATOR_API_KEY=
TWITCH_CHANNEL=seu_canal
TWITCH_OAUTH_TOKEN=oauth:xxxxxxx
TWITCH_BOT_NICK=kitsu-bot
OBS_WS_URL=ws://127.0.0.1:4455
OBS_WS_PASSWORD=
VTS_URL=ws://127.0.0.1:8001
VTS_AUTH_TOKEN=
KITSU_LOG_ROOT=C:\\kitsu\\logs
GPU_METRICS_INTERVAL_SECONDS=30
```

> Ajuste `ORCH_HOST` para `0.0.0.0` caso o painel/UI rode fora da mesma máquina. O valor de `TELEMETRY_API_URL` deve apontar para a API do repositório `kitsu-telemetry`.
>
> Para o VTube Studio, abra o menu de plugins e autorize "Kitsu.exe Controller"; copie o token gerado para `VTS_AUTH_TOKEN`. Gere o OAuth da Twitch com scopes `chat:read chat:edit` e preencha `TWITCH_OAUTH_TOKEN`.
>
> Para encontrar o microfone correto, execute `poetry run python -m kitsu_vtuber_ai.apps.asr_worker.devices`. O comando indica o nome (sounddevice) e o índice (PyAudio) que podem ser usados em `ASR_INPUT_DEVICE`. Use `ASR_FAKE_AUDIO=1` para testes sem hardware.

## 4. Validar qualidade local
Execute a suíte mínima antes de subir qualquer alteração:
```bash
poetry lock --check
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
- Automação Windows (sem Docker):
  - Inicie tudo: `pwsh scripts/run_all_no_docker.ps1 -Action start`
  - Verifique o estado: `pwsh scripts/run_all_no_docker.ps1 -Action status`
  - Encerrar serviços: `pwsh scripts/run_all_no_docker.ps1 -Action stop`
- Logs estruturados (JSON) ficam em `KITSU_LOG_ROOT`, um arquivo por serviço, rotacionados diariamente.
- (Opcional) Scripts paralelos em PowerShell: `scripts\run_all.ps1 -UsePoetry`

## 8. Validar via UI de telemetria
1. No repositório `../kitsu-telemetry`, configure `.env` (API) e `ui/.env.local` com `PUBLIC_ORCH_BASE_URL`, `PUBLIC_ORCH_WS_URL` **e** `PUBLIC_CONTROL_BASE_URL` apontando para `http://{ORCH_HOST}:{ORCH_PORT}` e `http://{CONTROL_PANEL_HOST}:{CONTROL_PANEL_PORT}`.
2. Inicie a API de telemetria: `poetry run uvicorn api.main:app --reload --port 8001`.
3. Inicie a UI:  
   ```bash
   cd kitsu-telemetry/ui
   pnpm install
   pnpm dev
   ```
4. Abra `http://localhost:5173` e verifique se:
   - O painel mostra o `GET /status` do orquestrador (via backend de controle).
   - Cartões e gráficos de latência respondem conforme os workers processam eventos.
   - Botões de pânico/mute/preset retornam feedback e refletem no snapshot.
   - Exportar CSV baixa o arquivo `telemetry-*.csv` e a tabela de soak tests lista os resultados recentes.
   - A conexão WebSocket aparece como `connected`.

> Caso veja blocos bloqueados por CORS, confirme se `ORCH_CORS_ALLOW_ORIGINS` inclui a origem exibida no console do navegador.

## 9. Executar o soak harness (QA)
- Configure `SOAK_POLICY_URL`, `SOAK_TELEMETRY_URL` e `SOAK_DURATION_MINUTES` no `.env` se desejar sobrescrever os padrões.
- Inicie todos os serviços (`pwsh scripts/run_all_no_docker.ps1 -Action start`).
- Execute o harness por 2h (ou use `--max-turns` para uma verificação rápida):
  ```bash
  poetry run python -m kitsu_vtuber_ai.apps.soak_harness.main --duration-minutes 120 --output artifacts/soak/summary.json
  ```
- O resumo final é salvo no arquivo indicado e também enviado como evento `soak.result` para a telemetria. Monitore o painel em `http://localhost:5173` para acompanhar a tabela de resultados.

> Para publicar métricas de GPU, instale o [pynvml](https://pypi.org/project/pynvml/) (já incluso no `pyproject.toml`). Se o driver NVIDIA não estiver disponível, o coletor é desativado automaticamente.

## 10. Checklist do piloto de transmissão
### Antes do go-live
- Validar áudio/vídeo com um `recording test` local (OBS + VTS).
- Garantir que o soak harness mais recente concluiu sem falhas (<24h).
- Revisar `.env` e tokens (Twitch, OBS, VTS, Ollama, Telemetria) e renovar os que expiram em <48h.
- Confirmar que o preset de persona e os assets (modelos Coqui/Piper) estão sincronizados com a versão do README.
- Preparar mensagem de boas-vindas e macro de pânico em OBS.

### Durante a transmissão
- Deixar o painel de telemetria aberto (dashboard + latência) para observar spikes.
- Registrar incidentes em tempo real no canal interno (`#kitsu-ops`).
- Validar a cada bloco (30 min) se os módulos seguem online via `/status`.

### Pós-show
- Exportar o CSV de telemetria e anexar ao log diário.
- Rodar novamente o soak harness curto (`--max-turns 5`) para detectar regressões imediatas.
- Arquivar clipes e incidentes no runbook de operações.

## 11. Plano de rollback e resposta a incidentes
1. Acione o macro de pânico (`/control/panic`) pelo painel e mute o TTS.
2. Troque a cena do OBS para o "BRB" ou "Starting Soon".
3. Reinicie o serviço problemático via `pwsh scripts/service_manager.ps1 -Service <nome> -Action restart`.
4. Se o incidente persistir, aplique `pwsh scripts/run_all_no_docker.ps1 -Action stop` e comunique o público.
5. Registre o incidente em `docs/incidents/<data>.md` com horário, causa suspeita e mitigação.

## 12. Empacotamento da release
- Atualize `poetry.lock`/`pyproject.toml` e confirme que `poetry lock --check` passa.
- Gere o pacote Windows-only com:
  ```powershell
  pwsh scripts/package_release.ps1 -OutputPath artifacts/release -Zip
  ```
- O script cria uma pasta com `README.md`, `RUN_FIRST.md`, `.env.example`, scripts PowerShell e licenças em `licenses/third_party/`.
- Valide o ZIP resultante, execute o checklist do item 10 e publique no canal interno antes de distribuir a build.
