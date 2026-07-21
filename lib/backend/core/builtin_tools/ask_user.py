"""
ask_user 提问工具，让 Agent 能主动向用户提问以补充信息。

当现有上下文不足以完成任务时，Agent 调用此工具向用户下发问题卡片，
执行流同步阻塞等待回答，回答作为 tool result 回填 LLM 继续思考。

实现要点：
- 工具通过 enqueue_ask_user_request 创建 asyncio.Future 并阻塞等待
- 用户通过 POST /api/chat/ask-user/reply 提交回答后 Future 完成
- 超时后 Future 返回 [TIMEOUT] 占位字符串

注意：在 agent.py 的 process_stream 中，builtin_ask_user 会被特殊处理，
事件下发由 agent.py 直接 yield emit_ask_user_event 完成。
此工具类的 execute 方法作为通用执行入口，用于非 agent.py 路径的调用（如测试）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from loguru import logger


class AskUserTool:
    """ask_user 提问工具。

    让 Agent 能主动向用户提问，支持单选/多选/自由输入。
    执行流同步阻塞等待用户回答。
    """

    def __init__(self) -> None:
        self._initialized = True
        # 工具元信息，与现有工具模式保持一致
        self.name = "ask_user"
        self.description = "向用户提问以补充信息，支持单选/多选/自由输入"
        self.version = "1.0.0"

    async def initialize(self) -> bool:
        """异步初始化（兼容现有工具接口）。

        Returns:
            始终返回 True，因为该工具无异步初始化需求
        """
        return True

    def get_tools(self) -> List[str]:
        """返回工具支持的操作列表。"""
        return ["ask"]

    async def execute(self, action: str = "ask", **kwargs: Any) -> Dict[str, Any]:
        """执行提问操作。

        Args:
            action: 操作名称，目前仅支持 "ask"
            **kwargs: 提问参数（question, options, allow_multiple, allow_free_text,
                      placeholder, timeout, user_id, session_id）

        Returns:
            Dict 包含 success 和 answer 字段
        """
        if action == "ask":
            return await self._ask(kwargs)
        return {"success": False, "error": f"未知 ask_user 操作: {action}"}

    async def _ask(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """向用户提问并阻塞等待回答。

        Args:
            params: 提问参数字典

        Returns:
            Dict 包含 success 和 answer 字段
        """
        question = params.get("question", "")
        options = params.get("options", [])
        allow_multiple = params.get("allow_multiple", False)
        allow_free_text = params.get("allow_free_text", True)
        placeholder = params.get("placeholder", "")
        timeout = params.get("timeout", 300)
        user_id = str(params.get("user_id", "") or "")
        session_id = str(params.get("session_id", "") or "")

        # 参数校验
        if not question or not question.strip():
            return {"success": False, "error": "question 参数不能为空"}

        if not user_id or not session_id:
            return {"success": False, "error": "user_id 和 session_id 不能为空"}

        # 延迟导入避免循环依赖
        from api.routes.ask_user import enqueue_ask_user_request

        # 创建 Future 并阻塞等待用户回答
        request_id, future = enqueue_ask_user_request(
            user_id=user_id,
            session_id=session_id,
            question=question,
            options=options if isinstance(options, list) else [],
            allow_multiple=bool(allow_multiple),
            allow_free_text=bool(allow_free_text),
            placeholder=placeholder or "",
            timeout=int(timeout) if timeout else 300,
        )

        logger.bind(
            event="ask_user_tool_waiting",
            request_id=request_id,
            session_id=session_id,
        ).debug(f"ask_user 工具等待用户回答: {request_id}")

        # 阻塞等待用户回答或超时
        result = await future

        answer = result.get("answer", "")
        selected_options = result.get("selected_options", [])

        # 构造返回给 LLM 的文本
        if selected_options and answer and answer not in selected_options:
            # 既有选项又有自由文本
            text_answer = f"选项: {', '.join(selected_options)}\n补充: {answer}"
        elif selected_options:
            text_answer = "\n".join(selected_options)
        else:
            text_answer = answer

        return {
            "success": True,
            "answer": text_answer,
            "request_id": request_id,
            "message": f"用户回答: {text_answer[:200]}",
        }
