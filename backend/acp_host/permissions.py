# -*- coding: utf-8 -*-
"""
ACP 权限审批适配器模块。

负责将外部 ACP Agent 发起的工具调用转换为可挂起的权限审批请求，并在用户确认后
构造符合 ACP 协议的响应。本模块不直接调用外部 `acp` SDK，对 SDK 的依赖通过
try/except 优雅降级：SDK 缺失时返回 dict 等价的占位对象，避免运行时 NameError。

模块包含：
- BLOCKED_COMMAND_PATTERNS：硬阻断命令子串黑名单
- ACPPermissionAdapter：权限审批适配器，封装工具调用解析、路径越权检测、
  挂起审批载体构建与响应生成等职责

注意：路径越权检测仅校验单个 cwd 根目录。调用方（service.py）应负责进一步校验
cwd 是否在 Open-AwA 允许的工作区根目录列表内（见 backend/api/routes/terminal.py
的 _ALLOWED_WORKSPACE_ROOTS），ACP 模块保持解耦不依赖 terminal 路由。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from security.command_hard_block import (
    HARD_BLOCKED_COMMAND_SUBSTRINGS,
    is_hard_blocked_command,
)

try:
    from acp.schema import AllowedOutcome, DeniedOutcome, RequestPermissionResponse

    _ACP_AVAILABLE = True
except ImportError:
    _ACP_AVAILABLE = False

    class _DummyModel:  # type: ignore[no-redef]
        """SDK 缺失时的占位类型，仅用于类型注解兼容，不应被实例化使用。"""

    AllowedOutcome = _DummyModel  # type: ignore[assignment, misc]
    DeniedOutcome = _DummyModel  # type: ignore[assignment, misc]
    RequestPermissionResponse = _DummyModel  # type: ignore[assignment, misc]


from .core import SuspendedPermission


__all__ = [
    "ACPPermissionAdapter",
    "BLOCKED_COMMAND_PATTERNS",
]


# 向后兼容：旧调用方仍可读取原常量名，实际定义由共享策略统一维护。
BLOCKED_COMMAND_PATTERNS = HARD_BLOCKED_COMMAND_SUBSTRINGS


class ACPPermissionAdapter:
    """ACP 权限审批适配器。

    将外部 ACP Agent 的工具调用请求转换为可挂起的权限审批载体，并提供命令黑名单
    与路径越权的硬阻断检测。当 SDK 可用时生成符合 acp.schema 协议的响应对象，
    SDK 缺失时回退为等价的 dict 占位结构。

    Attributes:
        cwd: 适配器绑定的当前工作目录绝对路径，用于路径越权检测基准。
    """

    def __init__(self, cwd: str) -> None:
        """初始化权限审批适配器。

        Args:
            cwd: 当前工作目录字符串，将展开 ~ 并 resolve 为绝对路径。
        """
        self.cwd = str(Path(cwd).expanduser().resolve())

    def build_suspended_permission(
        self,
        *,
        agent: str,
        tool_call: Any,
        options: list[Any],
    ) -> SuspendedPermission:
        """构建被挂起的权限审批请求载体。

        将原始 tool_call 与 options 序列化为 dict 载荷，并提取工具名、类别、
        目标、动作、摘要、命令、路径等元信息填充到 SuspendedPermission 中。

        Args:
            agent: 触发该权限请求的 Agent 标识。
            tool_call: 原始工具调用对象（dict 或具备 model_dump 方法的模型）。
            options: 可选的审批选项列表，元素可为 dict 或模型对象。

        Returns:
            填充完整字段的 SuspendedPermission 实例。
        """
        tool_call_payload = self._tool_call_payload(tool_call)
        option_payloads: list[dict[str, Any]] = []
        for option in options:
            payload = self._option_payload(option)
            if payload is not None:
                option_payloads.append(payload)
        return SuspendedPermission(
            payload={
                "toolCall": tool_call_payload,
                "options": option_payloads,
            },
            options=option_payloads,
            agent=agent,
            tool_name=self._tool_name(tool_call_payload),
            tool_kind=self._tool_kind(tool_call_payload),
            target=self._target(tool_call_payload),
            action=self._action(tool_call_payload),
            summary=self._summary(tool_call_payload),
            command=self._command(tool_call_payload),
            paths=self._paths(tool_call_payload),
            requires_user_confirmation=True,
        )

    def resolve_option_by_id(
        self,
        options: list[dict[str, Any]],
        option_id: str,
    ) -> Optional[dict[str, Any]]:
        """按 optionId 在选项列表中查找匹配的选项。

        支持兼容 camelCase（optionId）与 snake_case（option_id）两种字段命名。

        Args:
            options: 选项字典列表。
            option_id: 目标选项 ID 字符串，首尾空白会被去除。

        Returns:
            匹配的选项字典；未找到或 option_id 为空时返回 None。
        """
        key = option_id.strip()
        if not key:
            return None
        for opt in options:
            if not isinstance(opt, dict):
                continue
            candidate = str(
                opt.get("optionId") or opt.get("option_id") or "",
            ).strip()
            if candidate == key:
                return opt
        return None

    def selected_response(
        self,
        option: Optional[dict[str, Any]],
    ) -> Any:
        """构造"用户已选择某选项"的权限响应。

        Args:
            option: 用户选中的选项字典；为 None 时等价于取消。

        Returns:
            acp.schema.RequestPermissionResponse 实例（SDK 可用时），
            或等价的 dict 占位结构（SDK 缺失时）。
        """
        if option is None:
            return self.cancelled_response()
        option_id = str(
            option.get("optionId") or option.get("option_id") or "selected",
        )
        if _ACP_AVAILABLE:
            return RequestPermissionResponse(
                outcome=AllowedOutcome(option_id=option_id, outcome="selected"),
            )
        # SDK 缺失时的占位等价结构
        return {
            "outcome": {
                "optionId": option_id,
                "outcome": "selected",
            },
        }

    def cancelled_response(self) -> Any:
        """构造"用户取消"的权限响应。

        Returns:
            acp.schema.RequestPermissionResponse 实例（SDK 可用时），
            或等价的 dict 占位结构（SDK 缺失时）。
        """
        if _ACP_AVAILABLE:
            return RequestPermissionResponse(
                outcome=DeniedOutcome(outcome="cancelled"),
            )
        # SDK 缺失时的占位等价结构
        return {
            "outcome": {
                "outcome": "cancelled",
            },
        }

    def is_hard_blocked(self, tool_call: Any) -> bool:
        """判断工具调用是否命中硬阻断规则。

        命中条件：
        1. 命令字符串包含 BLOCKED_COMMAND_PATTERNS 中任一子串；或
        2. 涉及的路径解析后位于 cwd 之外（路径越权）。

        Args:
            tool_call: 原始工具调用对象。

        Returns:
            True 表示应直接拒绝该工具调用，不进入用户审批流程。
        """
        return self._is_hard_blocked(self._tool_call_payload(tool_call))

    def _tool_call_payload(self, tool_call: Any) -> dict[str, Any]:
        """将 tool_call 转换为 dict 载荷。

        dict 直接拷贝；具备 model_dump 方法的 Pydantic 模型则调用其序列化；
        其他类型返回空 dict。

        Args:
            tool_call: 原始工具调用对象。

        Returns:
            工具调用的 dict 表示。
        """
        if isinstance(tool_call, dict):
            return dict(tool_call)
        model_dump = getattr(tool_call, "model_dump", None)
        if callable(model_dump):
            data = model_dump(by_alias=True, exclude_none=True)
            if isinstance(data, dict):
                return data
        return {}

    def _option_payload(self, option: Any) -> Optional[dict[str, Any]]:
        """将单个 option 转换为 dict 载荷。

        与 _tool_call_payload 类似，但 option 为非 dict/非模型对象时返回 None
        表示跳过该选项。

        Args:
            option: 原始选项对象。

        Returns:
            选项的 dict 表示，或 None 表示无效跳过。
        """
        if isinstance(option, dict):
            return dict(option)
        model_dump = getattr(option, "model_dump", None)
        if callable(model_dump):
            data = model_dump(by_alias=True, exclude_none=True)
            if isinstance(data, dict):
                return data
        return None

    def _tool_name(self, tool_call: dict[str, Any]) -> str:
        """提取工具名称，缺失时回退为 'external-agent'。"""
        title = tool_call.get("title")
        if isinstance(title, str) and title.strip():
            return title.strip()
        return "external-agent"

    def _tool_kind(self, tool_call: dict[str, Any]) -> str:
        """提取工具类别，缺失时回退为 'other'。"""
        kind = tool_call.get("kind")
        if isinstance(kind, str) and kind.strip():
            return kind.strip().lower()
        return "other"

    def _action(self, tool_call: dict[str, Any]) -> Optional[str]:
        """提取具体动作（与 tool_kind 同义但可选）。"""
        kind = tool_call.get("kind")
        if isinstance(kind, str) and kind.strip():
            return kind.strip().lower()
        return None

    def _summary(self, tool_call: dict[str, Any]) -> Optional[str]:
        """提取人类可读的操作摘要，优先取 title 字段。"""
        title = tool_call.get("title")
        if isinstance(title, str) and title.strip():
            return title.strip()
        return None

    def _command(self, tool_call: dict[str, Any]) -> Optional[str]:
        """从 rawInput 中提取命令字符串。

        支持两种命令字段：
        1. rawInput.command：直接字符串命令
        2. rawInput.args / rawInput.argv：参数列表，空格拼接为命令字符串

        Args:
            tool_call: 工具调用 dict 载荷。

        Returns:
            命令字符串，或 None 表示未携带命令信息。
        """
        raw_input = tool_call.get("rawInput") or tool_call.get("raw_input")
        if isinstance(raw_input, dict):
            command = raw_input.get("command")
            if isinstance(command, str) and command.strip():
                return command.strip()
            argv = raw_input.get("args") or raw_input.get("argv")
            if isinstance(argv, list):
                parts = [
                    str(item).strip() for item in argv if str(item).strip()
                ]
                if parts:
                    return " ".join(parts)
        return None

    def _paths(self, tool_call: dict[str, Any]) -> list[str]:
        """从工具调用中提取涉及的文件路径列表（去重，最多 5 个）。

        提取来源：
        1. locations[*].path：位置声明中的路径
        2. content[*].path：当 content 类型为 diff 时的目标路径
        3. rawInput.path / raw_input.path：命令行附带的路径参数

        Args:
            tool_call: 工具调用 dict 载荷。

        Returns:
            去重后的路径列表，最多 5 项。
        """
        paths: list[str] = []
        seen: set[str] = set()

        def add_path(value: Any) -> None:
            """添加路径到列表，跳过非字符串、空值与重复项。"""
            if not isinstance(value, str):
                return
            text = value.strip()
            if not text or text in seen:
                return
            seen.add(text)
            paths.append(text)

        for location in tool_call.get("locations") or []:
            if isinstance(location, dict):
                add_path(location.get("path"))

        for content in tool_call.get("content") or []:
            if isinstance(content, dict) and content.get("type") == "diff":
                add_path(content.get("path"))

        raw_input = tool_call.get("rawInput")
        if raw_input is None:
            raw_input = tool_call.get("raw_input")
        if isinstance(raw_input, dict):
            add_path(raw_input.get("path"))

        return paths[:5]

    def _target(self, tool_call: dict[str, Any]) -> Optional[str]:
        """提取操作目标资源标识。

        优先级：
        1. 单个路径：显示为相对 cwd 的路径
        2. 多个路径：显示为 "N files"
        3. 命令字符串
        4. 摘要

        Args:
            tool_call: 工具调用 dict 载荷。

        Returns:
            目标资源标识字符串，或 None。
        """
        paths = self._paths(tool_call)
        if len(paths) == 1:
            return self._display_path(paths[0])
        if len(paths) > 1:
            return f"{len(paths)} files"
        command = self._command(tool_call)
        if command:
            return command
        return self._summary(tool_call)

    def _display_path(self, value: str) -> str:
        """将路径转换为相对 cwd 的展示形式。

        绝对路径若位于 cwd 内则返回相对路径，否则返回原始绝对路径字符串；
        相对路径原样返回。任何解析异常均回退为原始输入。

        Args:
            value: 原始路径字符串。

        Returns:
            展示用路径字符串。
        """
        try:
            path = Path(value).expanduser()
            cwd_path = Path(self.cwd)
            if path.is_absolute():
                try:
                    return str(path.resolve().relative_to(cwd_path))
                except ValueError:
                    return str(path)
            return value
        except (OSError, RuntimeError, ValueError):
            return value

    def _is_hard_blocked(self, tool_call: dict[str, Any]) -> bool:
        """硬阻断判定核心逻辑。

        命中规则：
        1. 命令字符串包含 BLOCKED_COMMAND_PATTERNS 任一子串；
        2. 任一涉及路径解析失败（OSError）或解析后位于 cwd 之外。

        注意：本方法仅校验单个 cwd 根目录。调用方应负责进一步校验 cwd 在
        Open-AwA 允许的工作区根目录列表内（见 terminal.py 的
        _ALLOWED_WORKSPACE_ROOTS），ACP 模块保持与 terminal 路由解耦。

        Args:
            tool_call: 工具调用 dict 载荷。

        Returns:
            True 表示命中硬阻断规则。
        """
        command = str(self._command(tool_call) or "")
        if is_hard_blocked_command(command):
            return True

        for path_value in self._paths(tool_call):
            candidate = Path(path_value).expanduser()
            if not candidate.is_absolute():
                candidate = Path(self.cwd) / candidate
            try:
                resolved = candidate.resolve()
            except OSError:
                return True
            # 使用 relative_to 替代裸字符串前缀匹配，防止 /home/user 误匹配 /home/userevil
            try:
                resolved.relative_to(Path(self.cwd))
            except ValueError:
                return True
        return False
