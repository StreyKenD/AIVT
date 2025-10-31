def test_policy_model_name_defined() -> None:
    from apps.policy_worker.main import MODEL_NAME

    assert MODEL_NAME
