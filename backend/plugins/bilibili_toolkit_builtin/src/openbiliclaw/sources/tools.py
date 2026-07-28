"""内容源管理工具，供 Agent 函数调用使用。

这些工具可被对话 Agent 调用，以代表用户创建、列出和管理内容源订阅
（SourceRecipe）。
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

# ── 工具定义（供 LLM 使用）─────────────────────────────────────────

SOURCE_TOOLS: list[dict[str, Any]] = [
    {
        "name": "create_source",
        "description": ("创建新的内容源订阅。当用户说想关注某个平台的某类内容时调用。"),
        "parameters": {
            "source_type": "平台类型，如 xiaohongshu / web / v2ex / zhihu",
            "name": "人类可读的订阅名，如 '小红书-机械键盘'",
            "strategy": "search 或 feed",
            "query": "搜索关键词（strategy=search 时必填）",
            "url": "直接 URL（strategy=feed 时必填）",
        },
    },
    {
        "name": "list_sources",
        "description": "列出用户当前的所有内容源订阅。",
    },
    {
        "name": "toggle_source",
        "description": "启用或禁用某个内容源订阅。",
        "parameters": {
            "id": "订阅 ID",
            "enabled": "true 或 false",
        },
    },
]


# ── 工具分发器 ────────────────────────────────────────────────────


class SourceToolDispatcher:
    """针对数据库执行内容源管理工具调用。"""

    def __init__(self, database: Any) -> None:
        self._db = database

    def dispatch(self, tool_call: dict[str, Any]) -> str:
        """执行工具调用并返回人类可读的结果字符串。

        Args:
            tool_call: 包含 ``name`` 和可选 ``arguments`` 键的字典。

        Returns:
            适合反馈给 LLM 的结果消息。
        """
        name = tool_call.get("name", "")
        args = tool_call.get("arguments", {})
        if not isinstance(args, dict):
            args = {}

        handlers = {
            "create_source": self._create_source,
            "list_sources": self._list_sources,
            "toggle_source": self._toggle_source,
        }

        handler = handlers.get(name)
        if handler is None:
            return f"未知工具: {name}"

        try:
            return handler(args)
        except Exception as exc:
            logger.exception("Tool dispatch error: %s", name)
            return f"工具执行出错: {exc}"

    def _create_source(self, args: dict[str, Any]) -> str:
        source_type = str(args.get("source_type", "web"))
        name = str(args.get("name", ""))
        strategy = str(args.get("strategy", "search"))
        query = str(args.get("query", ""))
        url = str(args.get("url", ""))

        if not name:
            name = f"{source_type}-{query or url or '未命名'}"

        config: dict[str, str] = {}
        if query:
            config["query"] = query
        if url:
            config["url"] = url

        recipe = {
            "id": str(uuid.uuid4()),
            "source_type": source_type,
            "name": name,
            "strategy": strategy,
            "config": config,
            "target_share": 4,
            "enabled": True,
            "created_by": "agent",
            "created_at": datetime.now(UTC).isoformat(),
        }
        self._db.save_source_recipe(recipe)

        logger.info("Agent created source recipe: %s (%s)", name, recipe["id"])
        return f"已创建内容源订阅「{name}」(类型: {source_type}, 策略: {strategy})"

    def _list_sources(self, _args: dict[str, Any]) -> str:
        recipes = self._db.get_all_recipes()
        if not recipes:
            return "当前没有任何内容源订阅。"

        lines = []
        for r in recipes:
            status = "[OK]" if r["enabled"] else "[ICON]"
            lines.append(f"{status} {r['name']} ({r['source_type']}/{r['strategy']})")
        return "当前内容源订阅：\n" + "\n".join(lines)

    def _toggle_source(self, args: dict[str, Any]) -> str:
        recipe_id = str(args.get("id", ""))
        enabled = args.get("enabled", True)
        if isinstance(enabled, str):
            enabled = enabled.lower() in ("true", "1", "yes")

        if not recipe_id:
            return "缺少订阅 ID。"

        updated = self._db.update_recipe(recipe_id, enabled=bool(enabled))
        if not updated:
            return f"未找到 ID 为 {recipe_id} 的订阅。"

        action = "启用" if enabled else "禁用"
        return f"已{action}订阅 {recipe_id}。"
