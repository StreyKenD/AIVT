import pytest


@pytest.mark.asyncio
async def test_orchestrator_app_has_title() -> None:
    from apps.orchestrator.main import app

    assert app.title == "Kitsu Orchestrator"
