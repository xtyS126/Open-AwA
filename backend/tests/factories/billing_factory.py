"""
测试计费记录数据工厂，生成标准化的计费相关字典。
用于模拟计费引擎的输出和 API 响应。
"""
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any


def create_test_billing_record(
    user_id: str = "test-user-001",
    session_id: Optional[str] = None,
    provider: str = "openai",
    model: str = "gpt-4o",
    prompt_tokens: int = 100,
    completion_tokens: int = 50,
    total_tokens: Optional[int] = None,
    cost: float = 0.0015,
) -> Dict[str, Any]:
    """
    创建测试计费记录字典。

    参数：
        user_id: 用户 ID
        session_id: 会话 ID
        provider: 模型供应商
        model: 模型名称
        prompt_tokens: 输入 Token 数
        completion_tokens: 输出 Token 数
        total_tokens: 总 Token 数，默认自动计算
        cost: 费用（美元）
    """
    total = total_tokens or (prompt_tokens + completion_tokens)
    return {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "session_id": session_id or f"test-session-{uuid.uuid4().hex[:12]}",
        "provider": provider,
        "model": model,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total,
        "cost": cost,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def create_test_billing_record_dict(
    user_id: str = "test-user-001",
    provider: str = "openai",
    model: str = "gpt-4o",
    cost: float = 0.0015,
) -> Dict[str, Any]:
    """创建轻量计费记录字典。"""
    return create_test_billing_record(
        user_id=user_id,
        provider=provider,
        model=model,
        cost=cost,
    )
