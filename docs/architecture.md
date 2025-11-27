# Arquitetura

O runtime da Kitsu.exe segue um desenho orientado a serviços async:

1. **Orchestrator (FastAPI)** concentra controle de estado, roteamento entre ASR/LLM/TTS e exposição de eventos via WebSocket.
2. **Workers especializados**
   - `asr_worker`: captura microfone, aplica VAD e envia `asr_partial`/`asr_final` para o orchestrator.
   - `policy_worker`: mantém a sessão com o backend LLM (Ollama/OpenAI/local) e devolve respostas em streaming.
   - `tts_worker`: realiza síntese de voz aplicando cache em disco + memória.
3. **Serviços auxiliares** como `pipeline_runner`, `obs_controller`, `avatar_controller` e `twitch_ingest` orbitam o orquestrador.

Os módulos abaixo detalham cada peça relevante:

- [Workers](workers/orchestrator.md) — implementação da lógica.
- [Contratos](contracts.md) — modelos `pydantic` compartilhados.
- [Endpoints](endpoints.md) — interface HTTP exposta.
