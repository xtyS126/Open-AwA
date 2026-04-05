"""
后端测试模块，负责验证对应功能在正常、边界或异常场景下的行为是否符合预期。
保持测试注释清晰，有助于快速分辨各个用例所覆盖的场景。
"""

from datetime import datetime, timezone, timedelta

from loguru import logger

from config.logging import init_logging, query_log_buffer, sanitize_for_logging, set_request_id


def test_sanitize_for_logging_masks_sensitive_fields():
    """
    验证sanitize、for、logging、masks、sensitive、fields相关场景的行为是否符合预期。
    通过断言结果可以帮助定位实现与预期行为之间的偏差。
    """
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
    """
    验证query、log、buffer、filters、by、level、and、keyword相关场景的行为是否符合预期。
    通过断言结果可以帮助定位实现与预期行为之间的偏差。
    """
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
