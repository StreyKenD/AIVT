# Code Review Notes

## Issues Found

1. **Incorrect authentication when publishing telemetry from orchestrator services**  
   `TelemetryClient.publish` sends the key using `Authorization: Bearer`, but the API only validates `X-API-Key`. In protected environments every call will return 401 and no event (including GPU metrics) will be persisted.  
   References: `TelemetryClient`【F:kitsu-vtuber-ai/libs/telemetry/__init__.py†L39-L55】 and API validation【F:kitsu-telemetry/api/main.py†L71-L75】【F:kitsu-telemetry/README.md†L27-L35】.

2. **Orchestrator publisher ignores `TELEMETRY_API_KEY` entirely**  
   The `TelemetryPublisher` used by the `EventBroker` never sets authentication headers when calling `/events`. Enabling the API key therefore causes every orchestrator broadcast to fail even if the variable exists in `.env`.  
   References: current implementation【F:kitsu-vtuber-ai/apps/orchestrator/main.py†L213-L236】 and environment docs requiring the token【F:kitsu-vtuber-ai/README.md†L100-L124】.

3. **Events drop the source identifier**  
   The API expects the optional `source` field, but the Python clients send `service`, which is discarded by Pydantic (`extra="allow"` is not configured). As a result the `source` column always receives an empty string, making it harder to filter dashboards by component.  
   References: API schema【F:kitsu-telemetry/api/main.py†L19-L31】 versus generated payloads【F:kitsu-vtuber-ai/libs/telemetry/__init__.py†L39-L55】【F:kitsu-vtuber-ai/apps/orchestrator/main.py†L229-L236】.

## Recommendations

- Align the authentication headers (`X-API-Key`) for both `TelemetryClient` and `TelemetryPublisher`, reusing the already documented variables.
- Populate the service identifier under `source` (or allow extra fields in the API model) to keep telemetry data segmented by component.
- Add tests covering scenarios with the API key enabled to ensure authentication regressions are caught early.
