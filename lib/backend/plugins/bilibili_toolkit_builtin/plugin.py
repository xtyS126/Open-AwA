"""bilibili-toolkit-builtin 内置插件入口模块。

实现 ``BilibiliToolkitBuiltinPlugin(BasePlugin)`` 子类，作为 Open-AwA
插件系统的内置插件入口，将 vendored 的 OpenBiliClaw v0.3.147 通过
``adapter.BilibiliToolkitAdapter`` 暴露给 Agent 工具调用。

关键设计：
- 依赖检测：``initialize()`` 开头用 ``importlib.util.find_spec()`` 检测关键依赖
  (httpx/pydantic/loguru/bilibili_api 等)，缺失时抛
  ``BuiltinPluginDependencyError``(携带 ``missing_packages``)，由
  ``main.py`` 捕获后仅记录 WARNING，不阻塞启动。
- 降级加载：vendored 包导入失败或 ``OpenClawAdapter`` 构造失败时，
  adapter 层捕获异常并以空工具列表返回，插件仍以 ``loaded_with_warnings``
  状态加载。
"""

from __future__ import annotations

import importlib.util
from typing import Any, Dict, List, Optional

from loguru import logger

from plugins.base_plugin import BasePlugin
from plugins.bilibili_toolkit_builtin.adapter import BilibiliToolkitAdapter


class BuiltinPluginDependencyError(Exception):
    """内置插件关键依赖缺失异常。

    携带 ``missing_packages`` 列表，供 ``main.py`` 捕获后向用户展示
    需要安装的包名（与 ``requirements.txt`` 中声明的包名一致）。
    """

    def __init__(self, message: str, missing_packages: Optional[List[str]] = None) -> None:
        super().__init__(message)
        # 缺失的包名列表（pip install 名，非 import 名）
        self.missing_packages: List[str] = list(missing_packages or [])


# 关键依赖映射：{import_name: pip_package_name}
# 仅检测 Bilibili Toolkit OpenClaw 适配层运行所必需的依赖；
# 缺失任一项均视为不可用，抛 BuiltinPluginDependencyError。
# bilibili-api-python 的 import 名是 bilibili_api（带下划线），
# google-genai 的 import 名是 google.genai（带点），需特殊处理。
_REQUIRED_DEPENDENCIES: Dict[str, str] = {
    "httpx": "httpx",
    "pydantic": "pydantic",
    "loguru": "loguru",
    "bilibili_api": "bilibili-api-python",
}

# 可选依赖：缺失时仅记录 WARNING，不阻塞加载
_OPTIONAL_DEPENDENCIES: Dict[str, str] = {
    "openai": "openai",
    "anthropic": "anthropic",
    "ollama": "ollama",
}


class BilibiliToolkitBuiltinPlugin(BasePlugin):
    """bilibili-toolkit-builtin 内置插件入口类。

    通过 ``adapter.BilibiliToolkitAdapter`` 包装 vendored 的上游
    ``OpenClawAdapter``，对外暴露 10 个技能作为 Open-AwA 工具。
    """

    name: str = "bilibili-toolkit-builtin"
    version: str = "0.3.147"
    description: str = (
        "兼顾 B 站信息获取与视频下载双能力的 B 站工具箱插件 - "
        "为 OpenAwA AI 提供 B 站/X/抖音/小红书等"
        "多平台内容数据采集渠道（仅接入数据，AI 能力由主平台提供）"
    )

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(config)
        # Bilibili Toolkit 适配层实例（成功 initialize 后赋值）
        self._adapter: Optional[BilibiliToolkitAdapter] = None
        # 已转换为 Open-AwA 格式的工具定义列表
        self._tools: List[Dict[str, Any]] = []
        # 加载过程中收集到的依赖告警（可选依赖缺失、vendored 导入失败等）
        self._dependency_warnings: List[str] = []

    async def initialize(self) -> bool:
        """初始化插件：依赖检测 + 构造适配层 + 加载工具。

        Returns:
            True 表示初始化成功（可能以降级模式加载，工具列表为空）。

        Raises:
            BuiltinPluginDependencyError: 关键依赖缺失时抛出，由 main.py 捕获。
        """
        missing = self._check_dependencies()
        if missing:
            # 关键依赖缺失，直接抛异常让上层决定是否降级
            missing_display = ", ".join(missing)
            raise BuiltinPluginDependencyError(
                f"bilibili-toolkit-builtin 内置插件关键依赖缺失: {missing_display}",
                missing_packages=missing,
            )

        self._adapter = BilibiliToolkitAdapter()
        try:
            await self._adapter.initialize()
        except Exception as exc:  # noqa: BLE001 - 适配层异常统一降级
            # adapter 内部已捕获大部分异常，这里兜底防止插件初始化崩溃
            warning = (
                f"BilibiliToolkitAdapter.initialize 抛出未预期异常，工具集降级为空: {exc}"
            )
            logger.warning(warning)
            self._dependency_warnings.append(warning)
            self._adapter = None
            self._tools = []
            return True

        self._dependency_warnings.extend(self._adapter.get_warnings())
        self._tools = self._adapter.get_tools()

        if self._dependency_warnings:
            logger.warning(
                f"bilibili-toolkit-builtin 内置插件以降级模式加载，"
                f"warnings={len(self._dependency_warnings)}, tools={len(self._tools)}"
            )
        else:
            logger.info(
                f"bilibili-toolkit-builtin 内置插件初始化完成，工具数={len(self._tools)}"
            )

        return True

    def get_tools(self) -> List[Dict[str, Any]]:
        """返回插件暴露的工具定义列表。"""
        return self._tools

    def execute(self, *args: Any, **kwargs: Any) -> Any:
        """BasePlugin 抽象方法实现。

        bilibili-toolkit-builtin 内置插件不通过统一 execute 入口调度，
        工具调用直接走 ``get_tools()`` 返回的 handler。
        """
        raise NotImplementedError(
            "BilibiliToolkitBuiltinPlugin 不支持统一 execute 入口，"
            "请通过 get_tools() 返回的 handler 调用具体工具"
        )

    async def cleanup(self) -> None:
        """清理插件资源：清空工具列表与适配层引用。"""
        if self._adapter is not None:
            try:
                self._adapter.cleanup()
            except Exception as exc:  # noqa: BLE001 - cleanup 不抛异常
                logger.warning(f"BilibiliToolkitAdapter cleanup 失败: {exc}")
        self._adapter = None
        self._tools = []
        # 保留 _dependency_warnings 供后续审计/日志查看
        self._initialized = False

    def _check_dependencies(self) -> List[str]:
        """检测关键依赖是否已安装。

        Returns:
            缺失的包名列表（pip install 名），空列表表示全部就绪。
            缺失的包名与 requirements.txt 中的声明保持一致，
            便于上层直接拼装 ``pip install`` 命令。
        """
        missing: List[str] = []

        for import_name, pip_name in _REQUIRED_DEPENDENCIES.items():
            spec = importlib.util.find_spec(import_name)
            if spec is None:
                missing.append(pip_name)
                logger.warning(
                    f"bilibili-toolkit-builtin 内置插件关键依赖缺失: "
                    f"import={import_name}, pip={pip_name}"
                )

        # 可选依赖缺失仅记录 WARNING，不加入 missing 列表
        for import_name, pip_name in _OPTIONAL_DEPENDENCIES.items():
            spec = importlib.util.find_spec(import_name)
            if spec is None:
                self._dependency_warnings.append(
                    f"可选依赖缺失: import={import_name}, pip={pip_name}"
                )
                logger.info(
                    f"bilibili-toolkit-builtin 可选依赖缺失（不影响加载）: "
                    f"import={import_name}, pip={pip_name}"
                )

        return missing

    def get_dependency_warnings(self) -> List[str]:
        """返回加载过程中收集到的所有告警信息。"""
        return list(self._dependency_warnings)
