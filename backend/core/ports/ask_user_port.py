"""ask_user 端口抽象。

领域核心层（core/*）通过此端口与 API 层解耦，避免直接 import api.routes.ask_user。
由 api/adapters/ask_user_adapter.py 提供具体实现，main.py 在 lifespan 启动时注入。
"""
from __future__ import annotations

import asyncio
from typing import Any, List, Optional, Protocol, Tuple, runtime_checkable


@runtime_checkable
class AskUserPort(Protocol):
    """ask_user 请求入队端口。

    抽象自 api.routes.ask_user.enqueue_ask_user_request 的调用契约，
    领域核心层通过此端口将 ask_user 请求委托给 API 层处理，避免反向依赖。
    """

    async def enqueue(
        self,
        *,
        user_id: str,
        session_id: str,
        question: str,
        options: Optional[List[str]] = None,
        allow_multiple: bool = False,
        allow_free_text: bool = True,
        placeholder: str = "",
        timeout: int = 300,
    ) -> Tuple[str, "asyncio.Future[Any]"]:
        """入队 ask_user 请求。

        Args:
            user_id: 用户 ID
            session_id: 会话 ID
            question: 向用户展示的问题文本
            options: 选项列表（None 表示自由输入）
            allow_multiple: 是否允许多选
            allow_free_text: 是否允许自由文本输入
            placeholder: 输入框占位符
            timeout: 超时秒数

        Returns:
            (request_id, answer_future)：请求 ID 与答案 Future
        """
        ...
