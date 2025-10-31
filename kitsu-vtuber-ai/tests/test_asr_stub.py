def test_asr_config_has_orchestrator_url() -> None:
    from libs.config import get_app_config

    settings = get_app_config()

    assert settings.asr.orchestrator_url is not None
