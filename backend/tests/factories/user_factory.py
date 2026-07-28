"""
测试用户数据工厂，生成标准化的 User 模型实例或字典。
"""
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any

DEFAULT_TEST_USER_ID = "test-user-001"


def create_test_user(
    user_id: Optional[str] = None,
    username: Optional[str] = None,
    role: str = "user",
    password_hash: Optional[str] = None,
) -> Dict[str, Any]:
    """
    创建测试用户字典，默认返回完整字段。

    参数：
        user_id: 用户 ID，默认自动生成 UUID
        username: 用户名，默认基于 user_id 生成
        role: 角色，默认 "user"
        password_hash: 密码哈希，默认使用安全的测试占位哈希
    """
    uid = user_id or str(uuid.uuid4())
    return {
        "id": uid,
        "username": username or f"test_{uid[:8]}",
        "password_hash": password_hash or "$2b$12$LJ3m4ys3GZfnYMz8kVsKaOTSxJfDwl5V7dP6EJLh0rF3kD1vO.Z7e",
        "role": role,
        "avatar_url": None,
        "nickname": None,
        "email": None,
        "phone": None,
        "profile_data": {},
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }


def create_test_user_dict(
    user_id: Optional[str] = None,
    username: Optional[str] = None,
    role: str = "user",
) -> Dict[str, Any]:
    """创建仅含核心字段的测试用户字典（用于 API 请求体）。"""
    uid = user_id or DEFAULT_TEST_USER_ID
    return {
        "id": uid,
        "username": username or f"testuser_{uid}",
        "role": role,
    }
