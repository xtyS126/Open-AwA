"""
测试数据工厂模块，提供便捷的测试数据生成函数。
所有工厂函数均返回未持久化的模型实例或字典，由调用方决定是否写入数据库。
"""

from .user_factory import create_test_user, create_test_user_dict, DEFAULT_TEST_USER_ID
from .conversation_factory import create_test_conversation, create_test_conversation_dict
from .message_factory import create_test_message, create_test_message_dict
from .provider_factory import create_test_provider_config, create_test_provider_config_dict
from .billing_factory import create_test_billing_record, create_test_billing_record_dict

__all__ = [
    "create_test_user",
    "create_test_user_dict",
    "DEFAULT_TEST_USER_ID",
    "create_test_conversation",
    "create_test_conversation_dict",
    "create_test_message",
    "create_test_message_dict",
    "create_test_provider_config",
    "create_test_provider_config_dict",
    "create_test_billing_record",
    "create_test_billing_record_dict",
]
