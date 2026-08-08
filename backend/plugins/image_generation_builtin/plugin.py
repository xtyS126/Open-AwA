"""生图内置插件入口模块。

实现 ``ImageGenerationPlugin(BasePlugin)`` 子类，作为 Open-AwA
插件系统中 ``image-generation-builtin`` 内置插件的入口。

关键设计：
- 生图能力由 ``core/image_generation.py`` 提供（三种协议族：OpenAI 兼容
  images/generations、DashScope 原生 multimodal-generation、SD WebUI 原生
  txt2img），本插件通过 ``get_tools()`` 暴露 ``image_generate`` 工具供 Agent 调度。
- 生图模型配置（是否生图模型、用途/限制描述、API Key）在模型设置页管理，
  插件不持有模型配置。
- ``execute()`` 走 handler 调度降级路径，与 ``bilibili-toolkit-builtin`` 一致。
- ``cleanup()`` 为同步方法（被 ``_load_rollback`` 同步调用）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from loguru import logger

from plugins.base_plugin import BasePlugin


class ImageGenerationPlugin(BasePlugin):
    """生图内置插件入口类。

    将 ``core/image_generation.py`` 的生图能力以 ``image_generate`` 工具
    形式暴露给 Agent；生图模型由用户在模型设置页标记并配置。
    """

    name: str = "image-generation-builtin"
    version: str = "1.0.0"
    description: str = (
        "生图内置插件：通过已标记为生图模型的配置（SD / GPT-Image / Qwen-Image 系列）"
        "生成图片，支持 OpenAI 兼容、DashScope 原生与 SD WebUI 原生三种协议"
    )

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(config)
        # 工具定义缓存（get_tools 返回）
        self._tools: List[Dict[str, Any]] = []

    async def initialize(self) -> bool:
        """初始化插件：加载工具定义注册表。

        Returns:
            True 表示初始化成功。
        """
        from plugins.image_generation_builtin.tools import IMAGE_GENERATION_TOOLS

        self._tools = list(IMAGE_GENERATION_TOOLS)
        logger.info(
            f"ImageGenerationPlugin 初始化完成，工具数={len(self._tools)}"
        )
        return True

    def get_tools(self) -> List[Dict[str, Any]]:
        """返回插件暴露的工具定义列表（含 handler 调用契约）。"""
        return self._tools

    def execute(self, *args: Any, **kwargs: Any) -> Any:
        """BasePlugin 抽象方法实现的降级路径。

        plugin_manager 的 ``execute_registered_tool_async`` 已识别工具定义中的
        ``handler`` 并直接调用；当调用方仍走旧版 ``execute(action=...)`` 入口时，
        从 ``self._tools`` 中查找匹配工具并调用其 handler。
        """
        action = kwargs.get("action") or (args[0] if args else "")
        if not action:
            raise ValueError(
                "ImageGenerationPlugin.execute 需要 action 参数指定要调用的工具"
            )
        action_name = str(action)
        for tool_def in self._tools:
            if str(tool_def.get("name") or "") != action_name:
                continue
            handler = tool_def.get("handler")
            if not callable(handler):
                raise RuntimeError(
                    f"ImageGenerationPlugin tool '{action_name}' handler not callable"
                )
            handler_kwargs = {k: v for k, v in kwargs.items() if k != "action"}
            return handler(**handler_kwargs)
        raise NotImplementedError(
            f"ImageGenerationPlugin 不支持未知 action '{action_name}'，"
            f"可用工具: {sorted(t.get('name', '') for t in self._tools)}"
        )

    def cleanup(self) -> None:
        """清理插件资源：清空工具定义缓存。

        注意：plugin_manager._load_rollback 同步调用 cleanup()，
        因此本方法必须为同步方法（与 BasePlugin.cleanup 基类一致）。
        """
        self._tools = []
        self._initialized = False
