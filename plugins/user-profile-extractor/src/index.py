"""
用户画像提取插件 — 基于 LLM 的智能用户画像引擎。
"""

import sys
import os
from typing import Any, Dict, List, Optional

from loguru import logger

# 确保 backend 目录在 sys.path 中
_backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "backend"))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from backend.plugins.base_plugin import BasePlugin


class UserProfileExtractorPlugin(BasePlugin):
    """
    用户画像提取插件。
    基于 LLM 从对话历史和用户行为中提取多维画像：身份特征、偏好、知识水平、
    沟通风格、行为模式、目标意图、情感状态等。支持置信度模型和生命周期管理。
    """

    name: str = "user-profile-extractor"
    version: str = "1.0.0"
    description: str = (
        "基于LLM的智能用户画像提取插件，从对话历史中自动识别身份特征、偏好、"
        "知识水平、沟通风格、行为模式等多维画像信息"
    )

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)

    # ── 生命周期 ──────────────────────────────────────────────

    def initialize(self) -> bool:
        """初始化画像提取引擎。"""
        logger.info(
            f"[{self.name}] 画像提取插件初始化完成 "
            f"(model={self.config.get('extraction_model', 'gpt-4o-mini')})"
        )
        self._initialized = True
        return True

    def validate(self) -> bool:
        """校验插件配置参数。"""
        try:
            cooldown = int(self.config.get("extraction_cooldown_minutes", 30))
            if cooldown < 1:
                logger.error(f"[{self.name}] extraction_cooldown_minutes 必须 >= 1")
                return False
            min_turns = int(self.config.get("min_conversation_turns", 10))
            if min_turns < 1:
                logger.error(f"[{self.name}] min_conversation_turns 必须 >= 1")
                return False
        except (TypeError, ValueError) as e:
            logger.error(f"[{self.name}] 配置校验失败: {e}")
            return False
        return True

    def cleanup(self) -> None:
        """清理资源。"""
        logger.info(f"[{self.name}] 画像提取插件已清理")
        super().cleanup()

    # ── 内部引擎工厂（每次调用创建新实例，绑定 db 和 user_id） ──

    def _create_extractor(self, db, user_id: str):
        """创建画像提取器实例。"""
        from plugins.user_profile_builtin.profile_extractor import ProfileExtractor
        return ProfileExtractor(db, user_id)

    def _create_lifecycle(self, db, user_id: str):
        """创建画像生命周期管理器实例。"""
        from plugins.user_profile_builtin.profile_lifecycle import ProfileLifecycle
        return ProfileLifecycle(db, user_id)

    def _create_injector(self, db, user_id: str):
        """创建画像上下文注入器实例。"""
        from plugins.user_profile_builtin.profile_injector import ProfileInjector
        return ProfileInjector(db, user_id)

    def _get_db_and_requester(self, kwargs: Dict[str, Any]):
        """
        从 kwargs 或插件上下文中提取 db session 和请求者 user_id。
        请求者 user_id 仅从 PluginContext 获取（已认证用户），不从 kwargs 推断。
        """
        db = kwargs.get("db")
        if db is None:
            context = getattr(self, "_context", None)
            if context and context.db_session_factory:
                db = context.get_db_session()
        requester_id = self._get_requester_id()
        return db, requester_id

    def _get_requester_id(self) -> str:
        """从插件上下文中提取已认证的请求者 user_id。"""
        context = getattr(self, "_context", None)
        if context:
            return context.get_user_id() or ""
        return ""

    def _authorize(self, requester_id: str, target_user_id: str) -> bool:
        """
        校验请求者是否有权访问目标用户的画像数据。
        仅允许访问自己的画像（self-only），管理员可突破此限制。
        """
        if not requester_id or not target_user_id:
            return False
        if requester_id == target_user_id:
            return True
        # 管理员可访问任意用户的画像
        context = getattr(self, "_context", None)
        if context and context.get_user_role() == "admin":
            return True
        return False

    # ── 插件执行入口 ────────────────────────────────────────

    def execute(self, *args, **kwargs) -> Dict[str, Any]:
        """
        执行插件动作。

        支持的 action:
        - extract_user_profile: 触发 LLM 画像提取
        - get_profile_facts: 获取画像事实列表
        - get_profile_summary: 获取画像摘要
        - refresh_profile: 刷新置信度评分
        """
        action = kwargs.get("action", "extract_user_profile")
        logger.debug(f"[{self.name}] 执行动作: {action}")

        # 透传 db 给各动作方法（user_id 由显式参数传递，避免重复）
        extra = {"db": kwargs.get("db")}

        if action == "extract_user_profile":
            return self._do_extract(
                user_id=kwargs.get("user_id", ""),
                session_ids=kwargs.get("session_ids"),
                model_name=kwargs.get(
                    "model_name",
                    self.config.get("extraction_model", "gpt-4o-mini"),
                ),
                **extra,
            )
        if action == "get_profile_facts":
            return self._do_get_facts(
                user_id=kwargs.get("user_id", ""),
                category=kwargs.get("category"),
                min_confidence=kwargs.get("min_confidence"),
                active_only=kwargs.get("active_only", True),
                **extra,
            )
        if action == "get_profile_summary":
            return self._do_get_summary(user_id=kwargs.get("user_id", ""), **extra)
        if action == "refresh_profile":
            return self._do_refresh(user_id=kwargs.get("user_id", ""), **extra)

        logger.warning(f"[{self.name}] 未知动作: {action}")
        return {"success": False, "error": f"未知动作: {action}"}

    # ── 动作实现 ────────────────────────────────────────────

    def _do_extract(
        self, user_id: str, session_ids=None, model_name: str = "gpt-4o-mini",
        **kwargs
    ) -> Dict[str, Any]:
        """触发 LLM 画像提取。"""
        if not user_id:
            return {"success": False, "error": "user_id 不能为空"}

        # 授权检查（在任何数据操作之前）
        db, requester_id = self._get_db_and_requester(kwargs)
        target_id = user_id
        if requester_id and not self._authorize(requester_id, target_id):
            return {"success": False, "error": "无权访问该用户的画像数据"}
        if db is None:
            return {"success": False, "error": "数据库会话不可用"}
        try:
            extractor = self._create_extractor(db, target_id)
            result = extractor.extract(
                session_ids=session_ids,
                model_name=model_name,
            )
            logger.bind(
                event="profile_extract_plugin",
                user_id=target_id,
                facts_added=result.get("facts_added", 0),
            ).info(f"[{self.name}] 画像提取完成")
            return {"success": True, **result}
        except Exception as e:
            logger.bind(
                event="profile_extract_error",
                user_id=target_id,
                error=str(e),
            ).error(f"[{self.name}] 画像提取失败")
            return {"success": False, "error": f"画像提取失败: {str(e)}"}

    def _do_get_facts(
        self, user_id: str, category=None, min_confidence=None, active_only: bool = True,
        **kwargs
    ) -> Dict[str, Any]:
        """获取用户的画像事实列表。"""
        if not user_id:
            return {"success": False, "error": "user_id 不能为空"}

        db, requester_id = self._get_db_and_requester(kwargs)
        target_id = user_id
        if requester_id and not self._authorize(requester_id, target_id):
            return {"success": False, "error": "无权访问该用户的画像数据"}
        if db is None:
            return {"success": False, "error": "数据库会话不可用"}
        try:
            lifecycle = self._create_lifecycle(db, target_id)
            facts = lifecycle.list_facts(
                user_id=target_id,
                category=category,
                min_confidence=min_confidence,
                active_only=active_only,
            )
            return {"success": True, "user_id": target_id, "facts": facts, "total": len(facts)}
        except Exception as e:
            logger.bind(
                event="profile_facts_error", user_id=target_id, error=str(e)
            ).error(f"[{self.name}] 获取画像事实失败")
            return {"success": False, "error": f"获取画像事实失败: {str(e)}"}

    def _do_get_summary(self, user_id: str, **kwargs) -> Dict[str, Any]:
        """获取用户画像摘要。"""
        if not user_id:
            return {"success": False, "error": "user_id 不能为空"}

        db, requester_id = self._get_db_and_requester(kwargs)
        target_id = user_id
        if requester_id and not self._authorize(requester_id, target_id):
            return {"success": False, "error": "无权访问该用户的画像数据"}
        if db is None:
            return {"success": False, "error": "数据库会话不可用"}
        try:
            injector = self._create_injector(db, target_id)
            summary = injector.build_profile_summary(user_id=target_id)
            return {"success": True, "user_id": target_id, **summary}
        except Exception as e:
            logger.bind(
                event="profile_summary_error", user_id=target_id, error=str(e)
            ).error(f"[{self.name}] 获取画像摘要失败")
            return {"success": False, "error": f"获取画像摘要失败: {str(e)}"}

    def _do_refresh(self, user_id: str, **kwargs) -> Dict[str, Any]:
        """刷新画像置信度评分，归档低质量事实。"""
        if not user_id:
            return {"success": False, "error": "user_id 不能为空"}

        db, requester_id = self._get_db_and_requester(kwargs)
        target_id = user_id
        if requester_id and not self._authorize(requester_id, target_id):
            return {"success": False, "error": "无权访问该用户的画像数据"}
        if db is None:
            return {"success": False, "error": "数据库会话不可用"}
        try:
            lifecycle = self._create_lifecycle(db, target_id)
            result = lifecycle.refresh_all_facts(user_id=target_id)
            logger.bind(
                event="profile_refresh_plugin",
                user_id=target_id,
                archived=result.get("archived", 0),
            ).info(f"[{self.name}] 画像刷新完成")
            return {"success": True, **result}
        except Exception as e:
            logger.bind(
                event="profile_refresh_error", user_id=target_id, error=str(e)
            ).error(f"[{self.name}] 画像刷新失败")
            return {"success": False, "error": f"画像刷新失败: {str(e)}"}

    # ── 工具注册 ────────────────────────────────────────────

    def get_tools(self) -> List[Dict[str, Any]]:
        """返回插件提供的 Agent 工具列表。"""
        return [
            {
                "name": "extract_user_profile",
                "description": (
                    "从用户对话历史中提取多维画像信息。分析对话内容，"
                    "识别用户的身份特征、偏好、知识水平、沟通风格、行为模式、"
                    "目标意图、情感状态等。使用LLM进行深度语义分析。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "user_id": {
                            "type": "string",
                            "description": "目标用户的唯一标识",
                        },
                        "session_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "要分析的会话ID列表，不传则分析最近会话",
                        },
                    },
                    "required": ["user_id"],
                },
            },
            {
                "name": "get_profile_facts",
                "description": (
                    "获取指定用户的画像事实列表。支持按类别和置信度阈值筛选。"
                    "类别包括：identity(身份)、preference(偏好)、expertise(知识水平)、"
                    "communication(沟通风格)、behavior(行为)、goal(目标)、emotion(情感)、context(环境)"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "user_id": {"type": "string", "description": "目标用户的唯一标识"},
                        "category": {
                            "type": "string",
                            "description": "画像维度类别",
                            "enum": [
                                "identity", "preference", "expertise", "communication",
                                "behavior", "goal", "emotion", "context",
                            ],
                        },
                        "min_confidence": {
                            "type": "number",
                            "description": "最低置信度阈值(0.0-1.0)，默认0.4",
                        },
                    },
                    "required": ["user_id"],
                },
            },
            {
                "name": "get_profile_summary",
                "description": (
                    "获取用户画像摘要，按维度聚合展示用户的综合特征。"
                    "包含各维度事实统计和置信度分布，用于快速了解用户全貌。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "user_id": {"type": "string", "description": "目标用户的唯一标识"},
                    },
                    "required": ["user_id"],
                },
            },
            {
                "name": "refresh_profile",
                "description": (
                    "刷新用户画像的置信度评分，重新计算所有事实的有效置信度，"
                    "归档低于阈值(0.15)的低质量事实，保持画像库的时效性和准确性。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "user_id": {"type": "string", "description": "目标用户的唯一标识"},
                    },
                    "required": ["user_id"],
                },
            },
        ]
