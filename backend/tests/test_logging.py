from app.core.logging import redact_sensitive_values


def test_redact_sensitive_values_masks_credentials() -> None:
    event = {
        "event": "request",
        "authorization": "Bearer private-token",
        "qwen_api_key": "sk-private",
        "user_id": 7,
    }

    result = redact_sensitive_values(None, "info", event)

    assert result["authorization"] == "[REDACTED]"
    assert result["qwen_api_key"] == "[REDACTED]"
    assert result["user_id"] == 7
