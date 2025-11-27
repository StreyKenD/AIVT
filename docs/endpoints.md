# Endpoints do Orchestrator

O módulo `apps.orchestrator.routes.system` concentra os endpoints de saúde, status e métricas usados pelo painel.

## Sistema / Health

::: apps.orchestrator.routes.system.health
    handler: python

## Status completo

::: apps.orchestrator.routes.system.get_status
    handler: python

## Métricas Prometheus

::: apps.orchestrator.routes.system.metrics
    handler: python
