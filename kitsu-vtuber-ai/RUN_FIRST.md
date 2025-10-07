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
Copie o arquivo `.env.example` para `.env` e preencha as credenciais (Twitch, OBS, Ollama, Coqui-TTS etc.).

## 4. Validar qualidade local
Execute a suíte mínima antes de subir qualquer alteração:
```bash
poetry run pytest -q
poetry run ruff .
poetry run black --check .
poetry run mypy
```

## 5. Ativar hooks de pré-commit
Instale os hooks configurados em `.pre-commit-config.yaml` para garantir lint/format/tipos automaticamente antes dos commits:
```bash
poetry run pre-commit install
```

## 6. Avisos de licença obrigatórios
A utilização dos modelos requer aceitar os termos de terceiros. Leia e mantenha cópias destes documentos em `licenses/third_party/`:
- **Meta Llama 3** (modelo LLM servido via Ollama) – veja `licenses/third_party/llama3_license.pdf`.
- **Coqui-TTS** (modelo selecionado conforme política do projeto) – veja `licenses/third_party/coqui_tts_model_card.pdf`.
- **Live2D Avatar “Lumi”** (arte/rig disponibilizado para o projeto) – veja `licenses/third_party/live2d_lumi_license.pdf`.

> Certifique-se de que qualquer distribuição ou demo pública do projeto inclui as atribuições acima e segue os termos de cada fornecedor.

## 7. Próximos passos sugeridos
- Inicie os serviços FastAPI com `poetry run uvicorn apps.control_panel_backend.main:app --reload` e, se necessário, o orquestrador em `apps.orchestrator`.
- Consulte o `README.md` para fluxos completos, arquitetura e comandos adicionais.
