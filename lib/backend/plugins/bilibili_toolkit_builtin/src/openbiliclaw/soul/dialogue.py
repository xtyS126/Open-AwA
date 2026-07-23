"""苏格拉底式对话模块。

处理与用户的深度、探询式对话，以更好地理解他们。
对话风格受苏格拉底法启发：
- 用「为什么」挖掘动机
- 提出假设并验证
- 调整前先确认理解
- 根据回应动态调整
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

    from openbiliclaw.llm.service import LLMService, ModuleOverride, SupportsComplete
    from openbiliclaw.soul.engine import SoulEngine

logger = logging.getLogger(__name__)


@dataclass
class DialogueTurn:
    """对话中的一轮。"""

    role: str  # "user" | "agent"
    content: str
    timestamp: str = ""
    extracted_insights: list[str] | None = None


class SocraticDialogue:
    """管理与用户的苏格拉底式对话。

    对话模块不仅记录用户说了什么 —— 还主动深挖以理解动机、
    验证假设，并精细化 agent 对用户真实面貌的理解。

    对话策略：
    1. 追问 Why —— 不止于偏好，深挖动机
    2. 提出假设 —— 基于当前理解主动假设
    3. 确认验证 —— 用推荐来验证假设
    4. 动态调整 —— 根据对话精细化灵魂画像
    """

    def __init__(
        self,
        llm: SupportsComplete | None,
        soul_engine: SoulEngine,
        llm_service: LLMService | None = None,
        session: str = "cli",
        tools: list[dict[str, Any]] | None = None,
        tool_dispatcher: Any | None = None,
        module_overrides: Mapping[str, ModuleOverride] | None = None,
    ) -> None:
        self._llm = llm
        self._soul_engine = soul_engine
        self._llm_service = llm_service
        self._session = session
        self._history: list[DialogueTurn] = []
        self._tools = tools or []
        self._tool_dispatcher = tool_dispatcher
        self._module_overrides = dict(module_overrides) if module_overrides is not None else None

    async def respond(self, user_message: str) -> str:
        """对用户消息生成苏格拉底式回复。

        回复应当：
        - 确认用户所说
        - 适时深挖（「为什么？」）
        - 提出假设（「我猜你可能...」）
        - 确认理解（「所以你的意思是...」）
        - 自然温暖，像朋友交谈

        参数：
            user_message: 用户的消息。

        返回：
            Agent 的回复。
        """
        from openbiliclaw.llm.service import LLMServiceError

        self._history.append(DialogueTurn(role="user", content=user_message))

        try:
            service = self._llm_service or self._build_service()

            # 若配置了工具，优先尝试工具调用路径
            if self._tools and self._tool_dispatcher:
                reply = await self._respond_with_tools(service, user_message)
            else:
                response = await service.complete_socratic_dialogue(
                    user_message=user_message,
                    history=self._history_to_messages(),
                    caller="soul.dialogue",
                )
                reply = response.content
        except (LLMServiceError, RuntimeError):
            logger.exception("Failed to generate Socratic dialogue response.")
            reply = "我刚刚思路断了一下，你可以换个说法再告诉我一次吗？"

        self._history.append(DialogueTurn(role="agent", content=reply))
        learn_fn = getattr(self._soul_engine, "learn_from_dialogue", None)
        if callable(learn_fn):

            async def _background_learn() -> None:
                try:
                    await learn_fn(
                        user_message=user_message,
                        assistant_reply=reply,
                        session=self._session,
                    )
                except Exception:
                    logger.exception("Failed to learn from dialogue turn.")

            asyncio.create_task(_background_learn())
        return reply

    async def _respond_with_tools(self, service: Any, user_message: str) -> str:
        """尝试工具调用回复，失败时回退到普通对话。

        流程：
        1. 带工具定义询问 LLM —— 它可能返回 tool_call 或文本。
        2. 若 tool_call：通过 dispatcher 执行，把结果回喂，得到最终回复。
        3. 若文本：原样返回。
        """
        from openbiliclaw.llm.prompts import build_socratic_dialogue_prompt

        core_memory = ""
        build_block = getattr(service, "_build_core_memory_block", None)
        if callable(build_block):
            core_memory = build_block()
        tone_profile = None
        build_tone = getattr(service, "_build_dialogue_tone_profile", None)
        if callable(build_tone):
            tone_profile = build_tone()
        prompt_messages = build_socratic_dialogue_prompt(
            user_message=user_message,
            history=self._history_to_messages(),
            core_memory_text=core_memory,
            tone_profile=tone_profile,
        )
        system = prompt_messages[0]["content"] if prompt_messages else ""

        response = await service.complete_with_tools(
            system_instruction=system,
            user_input=user_message,
            tools=self._tools,
            history=self._history_to_messages(),
            caller="soul.dialogue.tools",
            bypass_semaphore=True,
        )

        # 若 LLM 返回了工具调用，执行并继续
        if response.tool_calls:
            tool_call = response.tool_calls[0]
            logger.info("Dialogue tool call: %s", tool_call.get("name"))
            if self._tool_dispatcher is None:
                return str(response.content)
            tool_result = self._tool_dispatcher.dispatch(tool_call)

            # 把工具结果回喂以得到自然回复
            followup = await service.complete_socratic_dialogue(
                user_message=f"[工具执行结果] {tool_result}",
                history=self._history_to_messages()
                + [
                    {"role": "user", "content": user_message},
                    {"role": "assistant", "content": f"（调用了工具 {tool_call.get('name')}）"},
                ],
                caller="soul.dialogue.tool_followup",
            )
            return str(followup.content)

        return str(response.content)

    async def extract_insights(self, turns: list[DialogueTurn]) -> list[dict[str, Any]]:
        """从对话轮次中提取关于用户的洞察。

        参数：
            turns: 待分析的近期对话轮次。

        返回：
            提取出的洞察字典列表。
        """
        # TODO: 用 LLM 从对话中识别偏好信号、动机、人格特质
        return []

    @property
    def history(self) -> list[DialogueTurn]:
        """对话历史。"""
        return self._history.copy()

    def clear_history(self) -> None:
        """清空对话历史。"""
        self._history.clear()

    def _history_to_messages(self) -> list[dict[str, str]]:
        """把先前的对话轮次转成 LLM 的聊天消息。"""
        return [
            {
                "role": "assistant" if turn.role == "agent" else turn.role,
                "content": turn.content,
            }
            for turn in self._history[:-1]
        ]

    def _build_service(self) -> LLMService:
        """在未注入时创建共享的 LLM 服务。"""
        from openbiliclaw.llm.service import LLMService

        memory = getattr(self._soul_engine, "_memory", None)
        if self._llm is None or memory is None:
            raise RuntimeError("Dialogue service is not configured.")
        module_overrides = self._module_overrides
        if module_overrides is None:
            module_overrides = getattr(self._soul_engine, "_module_overrides", {})
        return LLMService(
            registry=self._llm,
            memory=memory,
            module_overrides=module_overrides or {},
            concurrency=int(getattr(self._soul_engine, "_llm_concurrency", 3)),
        )
