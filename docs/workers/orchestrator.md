# Orchestrator Worker Stack

## Estado e Health Snapshot

::: apps.orchestrator.state_manager.OrchestratorState
    handler: python
    selection:
      members:
        - snapshot
        - health_snapshot
        - handle_asr_partial
        - handle_asr_final

## Decision Engine

::: apps.orchestrator.decision_engine.DecisionEngine
    handler: python

## Event Dispatcher

::: apps.orchestrator.event_dispatcher.EventDispatcher
    handler: python
