"""Bilibili Toolkit 适配层：包装 vendored 的 OpenClawAdapter 并转换为 Open-AwA 工具定义。

适配策略：
- 通过 ``importlib.import_module`` 动态加载 vendored 的
  ``openbiliclaw.integrations.openclaw.bootstrap`` 模块。
- 调用工厂函数 ``build_openclaw_adapter()`` 构造上游 ``OpenClawAdapter`` 实例，
  再通过 ``build_openclaw_skills(adapter)`` 获取 10 个 ``OpenClawSkillDescriptor``。
- 将每个 descriptor 转换为 Open-AwA 工具定义（``name``/``description``/``parameters``/``handler``）。

降级策略：
- vendored 包导入失败或 ``OpenClawAdapter`` 构造失败时，仅记录 WARNING，
  ``self._skills`` 保持空列表，不抛异常，让插件以 ``loaded_with_warnings`` 状态加载。
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger


# vendored 包在文件系统上的根目录（adapter.py 同级的 src/openbiliclaw/）
_ADAPTER_DIR = Path(__file__).resolve().parent
_VENDORED_SRC_DIR = _ADAPTER_DIR / "src"
_VENDORED_PACKAGE_NAME = "openbiliclaw"
_BOOTSTRAP_MODULE = f"{_VENDORED_PACKAGE_NAME}.integrations.openclaw.bootstrap"
_SKILL_MODULE = f"{_VENDORED_PACKAGE_NAME}.integrations.openclaw.skill"


class BilibiliToolkitAdapter:
    """Bilibili Toolkit 上游 ``OpenClawAdapter`` 的 Open-AwA 侧包装器。"""

    def __init__(self) -> None:
        # 上游 OpenClawAdapter 实例（成功加载后赋值）
        self._inner: Any = None
        # 转换后的 Open-AwA 工具定义列表
        self._skills: List[Dict[str, Any]] = []
        # 加载过程中的告警信息（供 plugin.py 收集到 _dependency_warnings）
        self._warnings: List[str] = []

    async def initialize(self) -> None:
        """加载 vendored 包并构造上游 adapter，捕获异常以降级加载。"""
        bootstrap_module = self._load_vendored_module(_BOOTSTRAP_MODULE)
        if bootstrap_module is None:
            # 导入失败时已记录 WARNING，这里直接返回保持空 skills 列表
            return

        # 上游 bootstrap.py 提供 build_openclaw_adapter() 工厂函数
        build_adapter = getattr(bootstrap_module, "build_openclaw_adapter", None)
        if not callable(build_adapter):
            warning = (
                "vendored openbiliclaw.bootstrap 缺少 build_openclaw_adapter 工厂函数，"
                "Bilibili Toolkit 工具集将不可用"
            )
            logger.warning(warning)
            self._warnings.append(warning)
            return

        try:
            # 上游工厂函数会调用 load_config()、build_llm_registry() 等完整初始化链路，
            # 可能因缺少 Bilibili Toolkit 配置文件或 LLM provider 而抛异常
            self._inner = build_adapter()
        except Exception as exc:  # noqa: BLE001 - 适配层边界，统一降级
            warning = (
                f"OpenClawAdapter 构造失败，Bilibili Toolkit 工具集将降级为空: {exc}"
            )
            logger.warning(warning)
            self._warnings.append(warning)
            self._inner = None
            return

        # 通过 build_openclaw_skills() 拿到 10 个 OpenClawSkillDescriptor
        skill_module = self._load_vendored_module(_SKILL_MODULE)
        if skill_module is None:
            return
        build_skills = getattr(skill_module, "build_openclaw_skills", None)
        if not callable(build_skills):
            warning = "vendored openbiliclaw.skill 缺少 build_openclaw_skills 函数"
            logger.warning(warning)
            self._warnings.append(warning)
            return

        try:
            descriptors = build_skills(self._inner)
        except Exception as exc:  # noqa: BLE001 - 适配层边界
            warning = f"build_openclaw_skills 调用失败: {exc}"
            logger.warning(warning)
            self._warnings.append(warning)
            return

        if not isinstance(descriptors, list):
            warning = "build_openclaw_skills 返回值非列表，跳过技能注册"
            logger.warning(warning)
            self._warnings.append(warning)
            return

        for descriptor in descriptors:
            try:
                tool_def = self._skill_to_tool_def(descriptor)
            except Exception as exc:  # noqa: BLE001 - 单个 descriptor 转换失败不影响其他
                logger.warning(
                    f"Bilibili Toolkit 技能转换失败，跳过: {getattr(descriptor, 'name', '<unknown>')} - {exc}"
                )
                continue
            self._skills.append(tool_def)

        logger.info(
            f"Bilibili Toolkit 适配层加载完成，注册 {len(self._skills)} 个工具"
        )

    def get_tools(self) -> List[Dict[str, Any]]:
        """返回转换后的 Open-AwA 工具定义列表。"""
        return self._skills

    def get_warnings(self) -> List[str]:
        """返回加载过程中收集到的告警信息。"""
        return list(self._warnings)

    def _skill_to_tool_def(self, descriptor: Any) -> Dict[str, Any]:
        """将 OpenClawSkillDescriptor 转换为 Open-AwA 工具定义。

        保留 descriptor.handler 作为异步可调用对象，由 PluginManager 在调用工具时
        传入参数字典并 await。
        """
        name = getattr(descriptor, "name", None)
        if not isinstance(name, str) or not name.strip():
            raise ValueError("descriptor.name 缺失或非字符串")

        description = getattr(descriptor, "description", "") or ""
        input_schema = getattr(descriptor, "input_schema", None)
        if not isinstance(input_schema, dict):
            input_schema = {"type": "object", "properties": {}}

        handler = getattr(descriptor, "handler", None)
        if handler is not None and not callable(handler):
            raise ValueError(f"descriptor.handler 不可调用: {handler!r}")

        return {
            "name": name,
            "description": description,
            "parameters": input_schema,
            "handler": handler,
        }

    def _load_vendored_module(self, module_name: str) -> Optional[Any]:
        """加载 vendored 包的指定子模块。

        通过临时将 ``src`` 目录插入 ``sys.path`` 实现 vendored 包导入，
        加载完成后立即移除该路径项，避免污染全局 ``sys.path``。
        已加载到 ``sys.modules`` 的 ``openbiliclaw.*`` 模块保留（避免重复加载）。
        """
        src_dir = str(_VENDORED_SRC_DIR)
        path_injected = False
        if src_dir not in sys.path:
            sys.path.insert(0, src_dir)
            path_injected = True

        try:
            return importlib.import_module(module_name)
        except Exception as exc:  # noqa: BLE001 - 适配层边界，统一降级
            warning = (
                f"vendored 模块 {module_name} 导入失败，"
                f"Bilibili Toolkit 工具集将降级为空: {exc}"
            )
            logger.warning(warning)
            self._warnings.append(warning)
            return None
        finally:
            if path_injected:
                try:
                    sys.path.remove(src_dir)
                except ValueError:
                    # 路径已被其他逻辑移除，忽略
                    pass

    def cleanup(self) -> None:
        """清理适配层持有的上游引用。"""
        self._inner = None
        self._skills = []
        self._warnings = []
        # 上游 vendored 模块一旦加载会常驻 sys.modules，这里不强制卸载，
        # 避免在热更新场景下破坏其他已注册工具的引用。


# 模块自检：当直接运行此文件时打印路径信息（仅用于调试）
if __name__ == "__main__":  # pragma: no cover
    print(f"_VENDORED_SRC_DIR = {_VENDORED_SRC_DIR}")
    print(f"_VENDORED_SRC_DIR exists = {_VENDORED_SRC_DIR.exists()}")
    print(f"os.getcwd() = {os.getcwd()}")
