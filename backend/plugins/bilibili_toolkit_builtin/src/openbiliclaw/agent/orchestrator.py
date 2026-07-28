"""Agent 编排器 —— 协调所有模块的大脑。

职责：
- 任务调度与策略决策
- 多步推理与自我反思
- 技能注册、发现与分派
- 协调 Soul Engine、Discovery Engine 与 Recommendation Engine
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openbiliclaw.config import Config
    from openbiliclaw.memory.manager import MemoryManager
    from openbiliclaw.soul.engine import SoulEngine

    from .skill import Skill

logger = logging.getLogger(__name__)


class AgentOrchestrator:
    """协调所有 agent 组件的中央编排器。

    编排器负责：
    1. 管理 agent 生命周期（init → run → shutdown）
    2. 将任务路由到合适的引擎
    3. 维护反馈回路
    4. 自我反思与策略调整
    """

    def __init__(self, config: Config) -> None:
        self.config = config
        self._skills: dict[str, Skill] = {}
        self._soul_engine: SoulEngine | None = None
        self._memory_manager: MemoryManager | None = None
        self._initialized = False

    async def initialize(self) -> None:
        """初始化所有 agent 组件。"""
        logger.info("Initializing Agent Orchestrator...")

        # TODO: 初始化 LLM providers
        # TODO: 初始化 memory manager
        # TODO: 初始化 soul engine
        # TODO: 初始化 discovery engine
        # TODO: 初始化 recommendation engine
        # TODO: 加载内置 skills
        # TODO: 加载自定义 skills

        self._initialized = True
        logger.info("Agent Orchestrator initialized successfully.")

    def register_skill(self, skill: Skill) -> None:
        """注册一个供 agent 使用的技能。

        Args:
            skill: 要注册的技能实例。
        """
        if skill.name in self._skills:
            logger.warning("Skill '%s' already registered, overwriting.", skill.name)
        self._skills[skill.name] = skill
        logger.info("Registered skill: %s", skill.name)

    def get_skill(self, name: str) -> Skill | None:
        """按名称获取已注册的技能。"""
        return self._skills.get(name)

    @property
    def available_skills(self) -> list[str]:
        """已注册技能名称的列表。"""
        return list(self._skills.keys())

    async def run_discovery_cycle(self) -> None:
        """运行一次完整的内容发现周期。

        这是主循环：
        1. 读取当前用户画像
        2. 生成发现策略
        3. 通过技能执行发现
        4. 评估并对发现的内容排序
        5. 生成朋友式的推荐
        """
        if not self._initialized:
            raise RuntimeError("Agent not initialized. Call initialize() first.")

        logger.info("Starting discovery cycle...")
        # TODO: 实现发现周期

    async def process_feedback(self, feedback: dict) -> None:  # type: ignore[type-arg]
        """处理用户反馈并更新所有层。

        Args:
            feedback: 来自用户的反馈数据。
        """
        logger.info("Processing user feedback...")
        # TODO: 将反馈路由到 memory manager 和 soul engine

    async def chat(self, message: str) -> str:
        """处理用户发来的聊天消息（苏格拉底式对话）。

        Args:
            message: 用户的消息。

        Returns:
            Agent 的响应。
        """
        logger.info("Chat message received: %s", message[:50])
        # TODO: 实现苏格拉底式对话
        return "（对话功能开发中...）"

    async def shutdown(self) -> None:
        """优雅关闭 agent。"""
        logger.info("Shutting down Agent Orchestrator...")
        # TODO: 保存状态，关闭连接
        self._initialized = False
