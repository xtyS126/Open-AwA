"""
测试消息数据工厂，生成标准化的 ShortTermMemory 模型实例或字典。
"""
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List


def create_test_message(
    session_id: Optional[str] = None,
    role: str = "user",
    content: Optional[str] = None,
    reasoning_content: Optional[str] = None,
    tool_events: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    创建测试消息字典。

    参数：
        session_id: 所属会话 ID
        role: 消息角色（user/assistant/system/tool）
        content: 消息内容
        reasoning_content: 思维链推理内容
        tool_events: 工具调用事件列表
    """
    sid = session_id or f"test-session-{uuid.uuid4().hex[:12]}"
    default_content = {
        "user": "你好，请帮我分析一下这个问题",
        "assistant": "好的，我来帮你分析。根据你提供的信息...",
        "system": "你是一个有用的AI助手",
        "tool": '{"result": "工具执行成功"}',
    }
    return {
        "session_id": sid,
        "role": role,
        "content": content or default_content.get(role, "测试消息内容"),
        "reasoning_content": reasoning_content,
        "tool_events": tool_events or [],
        "timestamp": datetime.now(timezone.utc),
    }


def create_test_message_dict(
    session_id: Optional[str] = None,
    role: str = "user",
    content: Optional[str] = None,
) -> Dict[str, Any]:
    """创建轻量测试消息字典（用于 API 请求体）。"""
    sid = session_id or f"test-session-{uuid.uuid4().hex[:12]}"
    return {
        "session_id": sid,
        "role": role,
        "content": content or f"测试{role}消息",
    }
