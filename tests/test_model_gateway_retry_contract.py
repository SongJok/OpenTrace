from model.model_gateway.gateway import ModelGateway


def test_provider_quota_errors_are_non_retryable():
    gateway = ModelGateway()
    classification = gateway._classify_exception(
        RuntimeError("403 AllocationQuota.FreeTierOnly: free quota has been exhausted")
    )
    assert classification == "auth"
    assert gateway._retry_policy(RuntimeError("403 forbidden")) == (False, 0.0)
