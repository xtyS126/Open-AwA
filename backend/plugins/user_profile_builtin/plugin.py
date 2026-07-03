"""用户画像提取内置插件入口模块。

实现 ``UserProfileBuiltinPlugin(BasePlugin)`` 子类，作为 Open-AwA
插件系统的内置插件入口，将 ``ProfileExtractor`` / ``ProfileLifecycle`` /
``ProfileInjector`` 三个核心组件通过统一的工具定义暴露给 Agent 调用。

关键设计：
- 工具方法名与工具名一致（如 ``extract_user_profile``），让
  ``_normalize_tool_definition`` 自动通过 ``hasattr`` 解析方法。
- 工具方法为 async，由 ``execute_plugin_async`` 调用；
  ``execute_plugin`` (同步) 通过沙箱内的 ``run_coroutine`` 兼容。
- ``user_id`` 由 Agent 调用时显式传入参数（来自认证上下文），不在插件 config 中。
- ``execute()`` 抛 ``NotImplementedError``，与 openbiliclaw-builtin 一致。
- 配置项通过 ``self.config`` 注入，覆盖各组件的类属性默认值。
- 工具定义不含 ``handler`` 字段（不可 pickle），仅声明 ``name``/``description``/``parameters``。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from loguru import logger

from plugins.base_plugin import BasePlugin


class UserProfileBuiltinPlugin(BasePlugin):
    """用户画像提取内置插件入口类。

    通过 ``ProfileExtractor`` / ``ProfileLifecycle`` / ``ProfileInjector``
    对外暴露 4 个工具：
    - ``extract_user_profile``: 从对话历史与行为日志中提取画像事实
    - ``get_user_profile_summary``: 获取当前用户的画像摘要
    - ``refresh_profile_facts``: 刷新所有事实的有效置信度（归档低置信度）
    - ``cleanup_expired_profile_facts``: 永久删除已归档且超期的事实
    """

    name: str = "user-profile-builtin"
    version: str = "1.0.0"
    description: str = (
        "用户画像提取内置插件，基于 LLM 从对话与行为日志中提取结构化用户特征"
    )

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(config)
        # 工具定义列表（initialize 后赋值）
        self._tools: List[Dict[str, Any]] = []

    async def initialize(self) -> bool:
        """初始化插件：构建工具定义列表。

        不在此处创建 db session，由各工具方法按需创建并关闭。

        Returns:
            True 表示初始化成功。
        """
        self._tools = self._build_tool_definitions()
        logger.info(
            f"UserProfileBuiltinPlugin 初始化完成，工具数={len(self._tools)}"
        )
        return True

    def get_tools(self) -> List[Dict[str, Any]]:
        """返回插件暴露的工具定义列表。"""
        return self._tools

    def execute(self, *args: Any, **kwargs: Any) -> Any:
        """BasePlugin 抽象方法实现。

        UserProfileBuiltinPlugin 不通过统一 execute 入口调度，
        工具调用直接走与工具同名的方法（由 _normalize_tool_definition 解析）。
        """
        raise NotImplementedError(
            "UserProfileBuiltinPlugin 不支持统一 execute 入口，"
            "请通过工具名直接调用对应方法"
        )

    def cleanup(self) -> None:
        """清理插件资源：清空工具列表。

        注意：plugin_manager._load_rollback 同步调用 cleanup()，
        因此本方法必须为同步方法（与 BasePlugin.cleanup 基类一致）。
        """
        self._tools = []
        self._initialized = False

    def _build_tool_definitions(self) -> List[Dict[str, Any]]:
        """构建插件暴露的工具定义列表。

        工具定义不含 handler 字段，仅声明 name/description/parameters。
        方法名与工具名一致，由 _normalize_tool_definition 通过 hasattr 自动解析。
        """
        return [
            {
                "name": "extract_user_profile",
                "description": (
                    "从对话历史与行为日志中提取结构化用户画像事实。"
                    "调用 LLM 分析最近的对话内容，识别用户的身份特征、偏好、"
                    "知识水平、行为模式等画像维度，并与已有画像合并（ADD/UPDATE/DELETE/UNCHANGED）。"
                    "建议在对话结束或达到自动触发间隔轮次时调用。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "user_id": {
                            "type": "string",
                            "description": "目标用户 ID（来自认证上下文）",
                        },
                        "session_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "要分析的会话 ID 列表，留空则自动选择最近的会话",
                        },
                        "trigger_type": {
                            "type": "string",
                            "enum": ["auto", "manual", "scheduled"],
                            "description": "触发类型，默认 auto",
                            "default": "auto",
                        },
                        "model_name": {
                            "type": "string",
                            "description": "使用的 LLM 模型名，留空则使用插件配置的默认模型",
                        },
                    },
                    "required": ["user_id"],
                },
            },
            {
                "name": "get_user_profile_summary",
                "description": (
                    "获取指定用户的画像摘要，包含每个类别的高置信度事实列表与统计信息。"
                    "用于 Agent 在对话开始时了解用户背景，或在前端展示用户画像详情。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "user_id": {
                            "type": "string",
                            "description": "目标用户 ID",
                        },
                        "min_confidence": {
                            "type": "number",
                            "description": "最低置信度过滤阈值，仅返回置信度 >= 此值的事实",
                            "default": 0.0,
                        },
                    },
                    "required": ["user_id"],
                },
            },
            {
                "name": "refresh_profile_facts",
                "description": (
                    "刷新所有活跃画像事实的有效置信度（应用衰减模型）。"
                    "将低于归档阈值的事实标记为 inactive（is_active=False）。"
                    "建议按插件配置的 ``lifecycle_refresh_interval_hours`` 周期性调用。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "user_id": {
                            "type": "string",
                            "description": "目标用户 ID",
                        },
                    },
                    "required": ["user_id"],
                },
            },
            {
                "name": "cleanup_expired_profile_facts",
                "description": (
                    "永久删除已归档且超过保留期的画像事实。"
                    "保留期由插件配置的 ``lifecycle_archived_retention_days`` 控制（默认 90 天）。"
                    "建议按 ``lifecycle_cleanup_interval_hours`` 周期性调用。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "user_id": {
                            "type": "string",
                            "description": "目标用户 ID",
                        },
                    },
                    "required": ["user_id"],
                },
            },
        ]

    # ── 工具方法实现 ────────────────────────────────────────────
    #
    # 方法名与工具名一致，让 _normalize_tool_definition 通过 hasattr 自动解析。
    # 每个 async 方法内部按需创建 SessionLocal db 会话，调用原有的
    # ProfileExtractor / ProfileLifecycle / ProfileInjector 组件，并在 finally 中关闭会话。
    # 配置项通过 self.config 注入，覆盖各组件的类属性默认值。

    def _create_db_session(self):
        """创建数据库会话，供工具方法使用。"""
        from db.models import SessionLocal
        return SessionLocal()

    def _apply_config_to_extractor(self, extractor) -> None:
        """将插件配置中的提取参数应用到 ProfileExtractor 实例。"""
        max_turns = self.config.get("extraction_max_turns")
        if isinstance(max_turns, int) and max_turns > 0:
            extractor.MAX_TURNS_PER_EXTRACTION = max_turns
        max_logs = self.config.get("extraction_max_behavior_logs")
        if isinstance(max_logs, int) and max_logs > 0:
            extractor.MAX_BEHAVIOR_LOGS = max_logs
        max_ctx = self.config.get("extraction_max_existing_context_chars")
        if isinstance(max_ctx, int) and max_ctx > 0:
            extractor.MAX_EXISTING_CONTEXT_CHARS = max_ctx

    def _apply_config_to_lifecycle(self, lifecycle) -> None:
        """将插件配置中的生命周期参数应用到 ProfileLifecycle 实例。"""
        retention_days = self.config.get("lifecycle_archived_retention_days")
        if isinstance(retention_days, int) and retention_days > 0:
            lifecycle.ARCHIVED_RETENTION_DAYS = retention_days

    def _apply_config_to_injector(self, injector) -> None:
        """将插件配置中的注入参数应用到 ProfileInjector 实例。"""
        max_chars = self.config.get("injection_max_context_chars")
        if isinstance(max_chars, int) and max_chars > 0:
            injector.MAX_CONTEXT_CHARS = max_chars
        max_facts = self.config.get("injection_max_facts_per_category")
        if isinstance(max_facts, int) and max_facts > 0:
            injector.MAX_FACTS_PER_CATEGORY = max_facts
        min_conf = self.config.get("injection_min_confidence")
        if isinstance(min_conf, (int, float)) and 0.0 <= min_conf <= 1.0:
            injector.MIN_CONFIDENCE = float(min_conf)

    async def extract_user_profile(self, **kwargs: Any) -> Dict[str, Any]:
        """工具方法：提取用户画像。"""
        user_id = kwargs.get("user_id")
        if not user_id:
            return {"status": "error", "message": "user_id 参数必填"}

        session_ids = kwargs.get("session_ids")
        trigger_type = kwargs.get("trigger_type", "auto")
        model_name = kwargs.get("model_name") or self.config.get(
            "extraction_default_model", "gpt-4o-mini"
        )

        db = self._create_db_session()
        try:
            from plugins.user_profile_builtin.profile_extractor import ProfileExtractor
            extractor = ProfileExtractor(db, user_id)
            self._apply_config_to_extractor(extractor)
            result = await extractor.extract(
                session_ids=session_ids,
                trigger_type=trigger_type,
                model_name=model_name,
            )
            return result
        except Exception as exc:
            logger.bind(user_id=user_id).opt(exception=True).error(
                f"画像提取工具调用失败: {exc}"
            )
            return {"status": "error", "message": str(exc)}
        finally:
            db.close()

    async def get_user_profile_summary(self, **kwargs: Any) -> Dict[str, Any]:
        """工具方法：获取用户画像摘要。"""
        user_id = kwargs.get("user_id")
        if not user_id:
            return {"status": "error", "message": "user_id 参数必填"}

        min_confidence = kwargs.get("min_confidence", 0.0)

        db = self._create_db_session()
        try:
            from plugins.user_profile_builtin.profile_injector import ProfileInjector
            injector = ProfileInjector(db, user_id)
            self._apply_config_to_injector(injector)
            summary = injector.build_profile_summary()
            # 按最低置信度过滤
            if min_confidence > 0:
                for cat_data in summary.get("categories", {}).values():
                    cat_data["facts"] = [
                        f for f in cat_data.get("facts", [])
                        if f.get("confidence", 0.0) >= min_confidence
                    ]
            return summary
        except Exception as exc:
            logger.bind(user_id=user_id).opt(exception=True).error(
                f"获取画像摘要工具调用失败: {exc}"
            )
            return {"status": "error", "message": str(exc)}
        finally:
            db.close()

    async def refresh_profile_facts(self, **kwargs: Any) -> Dict[str, Any]:
        """工具方法：刷新画像事实的有效置信度。"""
        user_id = kwargs.get("user_id")
        if not user_id:
            return {"status": "error", "message": "user_id 参数必填"}

        db = self._create_db_session()
        try:
            from plugins.user_profile_builtin.profile_lifecycle import ProfileLifecycle
            lifecycle = ProfileLifecycle(db, user_id)
            self._apply_config_to_lifecycle(lifecycle)
            stats = lifecycle.refresh_all_facts()
            return {
                "status": "success",
                "user_id": user_id,
                "refreshed": stats.get("refreshed", 0),
                "archived": stats.get("archived", 0),
                "unchanged": stats.get("unchanged", 0),
            }
        except Exception as exc:
            logger.bind(user_id=user_id).opt(exception=True).error(
                f"刷新画像事实工具调用失败: {exc}"
            )
            return {"status": "error", "message": str(exc)}
        finally:
            db.close()

    async def cleanup_expired_profile_facts(self, **kwargs: Any) -> Dict[str, Any]:
        """工具方法：清理过期画像事实。"""
        user_id = kwargs.get("user_id")
        if not user_id:
            return {"status": "error", "message": "user_id 参数必填"}

        db = self._create_db_session()
        try:
            from plugins.user_profile_builtin.profile_lifecycle import ProfileLifecycle
            lifecycle = ProfileLifecycle(db, user_id)
            self._apply_config_to_lifecycle(lifecycle)
            purged = lifecycle.purge_expired_archived()
            return {
                "status": "success",
                "user_id": user_id,
                "purged": purged,
            }
        except Exception as exc:
            logger.bind(user_id=user_id).opt(exception=True).error(
                f"清理过期画像事实工具调用失败: {exc}"
            )
            return {"status": "error", "message": str(exc)}
        finally:
            db.close()
