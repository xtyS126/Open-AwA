"""ask_user 端口的 API 层适配器。

实现 core.ports.ask_user_port.AskUserPort，内部委托给 api.routes.ask_user.enqueue_ask_user_request。
由 main.py 在 lifespan 启动时构造并注入到 AIAgent。
"""
from __future__ import annotations

import asyncio
from typing import Any, List, Optional, Tuple

from api.routes.ask_user import enqueue_ask_user_request


class AskUserPortAdapter:
    """AskUserPort 的 API 层实现，委托给 api.routes.ask_user.enqueue_ask_user_request。"""

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
        """入队 ask_user 请求，委托给 api.routes.ask_user。

        注意：enqueue_ask_user_request 本身是同步函数，返回 (request_id, Future)，
        此处直接返回其结果，无需 await（Future 由调用方自行 await）。
        """
        return enqueue_ask_user_request(
            user_id=user_id,
            session_id=session_id,
            question=question,
            options=options,
            allow_multiple=allow_multiple,
            allow_free_text=allow_free_text,
            placeholder=placeholder,
            timeout=timeout,
        )
