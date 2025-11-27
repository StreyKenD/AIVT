# Kitsu.exe — Documentação Técnica

Este portal reúne informações geradas automaticamente a partir do código para facilitar a manutenção do runtime da Kitsu.exe. Use o menu lateral para navegar entre a arquitetura de alto nível, os endpoints do orquestrador, os workers (ASR, LLM/Policy, TTS) e os contratos de dados compartilhados entre serviços.

Principais objetivos desta documentação:

- **Arquitetura:** visão geral do pipeline e dos componentes que o formam.
- **Observabilidade:** lista dos endpoints expostos pelo orquestrador e seus retornos.
- **Workers:** descrição dos módulos Python responsáveis por ASR, Policy/LLM, TTS e orquestração.
- **Contratos e Schemas:** referência rápida dos `pydantic` models usados para troca de mensagens.

Todas as páginas abaixo são regeneradas a partir do código-fonte durante o `make docs`, garantindo sincronização entre implementação e documentação publicada no GitHub Pages.
