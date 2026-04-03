from datetime import datetime, timezone, timedelta

from loguru import logger

from config.logging import init_logging, query_log_buffer, sanitize_for_logging, set_request_id


def test_sanitize_for_logging_masks_sensitive_fields():
    payload = {
        "token": "abc123",
        "password": "pwd",
        "user_id": "user_123456",
        "nested": {"authorization": "Bearer testtoken"},
    }
    sanitized = sanitize_for_logging(payload)
    assert sanitized["token"] == "***"
    assert sanitized["password"] == "***"
    assert sanitized["nested"]["authorization"] == "***"
    assert sanitized["user_id"] != "user_123456"


def test_query_log_buffer_filters_by_level_and_keyword():
    init_logging(log_level="DEBUG", service_name="test-service", log_serialize=False)
    request_id = "req-test-001"
    set_request_id(request_id)
    logger.bind(event="unit_test_log_event", module="test").info("query buffer target message")

    start_time = datetime.now(timezone.utc) - timedelta(minutes=1)
    result = query_log_buffer(
        start_time=start_time,
        level="INFO",
        keyword="target",
        limit=20,
        offset=0,
    )

    assert result["total"] >= 1
    assert any(item.get("request_id") == request_id for item in result["records"])
