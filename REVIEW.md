# Código revisado

## Problemas encontrados

1. **Autenticação incorreta ao publicar telemetria a partir dos serviços do orquestrador**  
   `TelemetryClient.publish` envia a chave como `Authorization: Bearer`, mas a API valida apenas `X-API-Key`. Em ambientes protegidos, todas as chamadas retornarão 401 e nenhum evento (incluindo métricas de GPU) será persistido.  
   Referências: `TelemetryClient`【F:kitsu-vtuber-ai/libs/telemetry/__init__.py†L39-L55】 e validação da API【F:kitsu-telemetry/api/main.py†L71-L75】【F:kitsu-telemetry/README.md†L27-L35】.

2. **Publicador do orquestrador ignora totalmente a `TELEMETRY_API_KEY`**  
   O `TelemetryPublisher` usado pelo `EventBroker` nunca define cabeçalhos de autenticação ao chamar `/events`. Assim, basta ativar a chave na API para que todos os broadcasts do orquestrador falhem, mesmo que a variável exista no `.env`.  
   Referências: implementação atual【F:kitsu-vtuber-ai/apps/orchestrator/main.py†L213-L236】 e documentação de ambiente que exige o token【F:kitsu-vtuber-ai/README.md†L100-L124】.

3. **Eventos perdem a identificação de origem**  
   A API espera o campo opcional `source`, mas os clientes Python enviam `service`, que é descartado pelo Pydantic (não há configuração `extra="allow"`). Isso faz com que a coluna `source` receba sempre string vazia, dificultando filtros por componente nos dashboards.  
   Referências: schema aceito pela API【F:kitsu-telemetry/api/main.py†L19-L31】 versus payload gerado pelos clientes【F:kitsu-vtuber-ai/libs/telemetry/__init__.py†L39-L55】【F:kitsu-vtuber-ai/apps/orchestrator/main.py†L229-L236】.

## Recomendações

- Alinhar os cabeçalhos de autenticação (`X-API-Key`) tanto no `TelemetryClient` quanto no `TelemetryPublisher`, reaproveitando as variáveis já documentadas.
- Propagar o identificador do serviço em `source` (ou permitir campos extras no modelo da API) para manter os dados diferenciados por componente.
- Adicionar testes que cubram cenários com chave de API habilitada, garantindo que regressões na autenticação sejam detectadas.
