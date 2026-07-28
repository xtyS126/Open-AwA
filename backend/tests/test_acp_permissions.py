# -*- coding: utf-8 -*-
"""
ACP permissions 模块单元测试。

覆盖 ACPPermissionAdapter 的命令黑名单硬阻断、路径越权检测、
SuspendedPermission 载荷构建、选项解析与权限响应生成等行为。
测试不依赖外部 acp SDK，全部以 dict 形式构造 mock tool_call。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from acp_host.core import SuspendedPermission
from acp_host.permissions import ACPPermissionAdapter, BLOCKED_COMMAND_PATTERNS, _ACP_AVAILABLE


def _make_shell_tool_call(command: str, **extra: Any) -> dict[str, Any]:
    """构造 shell 类工具调用的 mock dict。

    Args:
        command: 命令字符串。
        **extra: 附加字段，合并到 tool_call 顶层。

    Returns:
        形如 ACP 协议 tool_call 的字典。
    """
    payload: dict[str, Any] = {
        "title": "Shell Command",
        "kind": "shell",
        "rawInput": {"command": command},
    }
    payload.update(extra)
    return payload


class TestBlockedCommandPatternsConstant:
    """BLOCKED_COMMAND_PATTERNS 常量定义一致性测试。"""

    def test_blocked_patterns_includes_expected_entries(self) -> None:
        """验证硬阻断命令子串列表包含四类危险命令模式。"""
        assert "rm -rf /" in BLOCKED_COMMAND_PATTERNS
        assert "sudo rm -rf" in BLOCKED_COMMAND_PATTERNS
        assert "mkfs" in BLOCKED_COMMAND_PATTERNS
        assert "dd if=" in BLOCKED_COMMAND_PATTERNS


class TestHardBlockedCommands:
    """命中 BLOCKED_COMMAND_PATTERNS 的命令应被硬阻断。"""

    @pytest.mark.parametrize(
        "command",
        [
            "rm -rf /",
            "rm -rf / home",
            "sudo rm -rf /tmp",
            "mkfs.ext4 /dev/sda",
            "dd if=/dev/zero of=/dev/sda bs=1M",
        ],
    )
    def test_dangerous_command_is_hard_blocked(self, command: str) -> None:
        """验证危险命令字符串被 is_hard_blocked 判定为 True。"""
        adapter = ACPPermissionAdapter(cwd=".")
        tool_call = _make_shell_tool_call(command)

        assert adapter.is_hard_blocked(tool_call) is True

    def test_rm_rf_root_is_hard_blocked(self) -> None:
        """验证 'rm -rf /' 命令被硬阻断（SubTask 用例 1）。"""
        adapter = ACPPermissionAdapter(cwd=".")
        tool_call = _make_shell_tool_call("rm -rf /")

        assert adapter.is_hard_blocked(tool_call) is True

    def test_sudo_rm_rf_is_hard_blocked(self) -> None:
        """验证 'sudo rm -rf xxx' 命令被硬阻断（SubTask 用例 2）。"""
        adapter = ACPPermissionAdapter(cwd=".")
        tool_call = _make_shell_tool_call("sudo rm -rf /var/log")

        assert adapter.is_hard_blocked(tool_call) is True

    def test_mkfs_is_hard_blocked(self) -> None:
        """验证 'mkfs.ext4 /dev/sda' 命令被硬阻断（SubTask 用例 3）。"""
        adapter = ACPPermissionAdapter(cwd=".")
        tool_call = _make_shell_tool_call("mkfs.ext4 /dev/sda")

        assert adapter.is_hard_blocked(tool_call) is True

    def test_dd_if_is_hard_blocked(self) -> None:
        """验证 'dd if=/dev/zero of=/dev/sda' 命令被硬阻断（SubTask 用例 4）。"""
        adapter = ACPPermissionAdapter(cwd=".")
        tool_call = _make_shell_tool_call("dd if=/dev/zero of=/dev/sda")

        assert adapter.is_hard_blocked(tool_call) is True


class TestPathEscapeHardBlocked:
    """路径越权检测：locations 中包含 cwd 之外绝对路径应被硬阻断。"""

    def test_location_outside_cwd_is_hard_blocked(
        self,
        tmp_path: Path,
        tmp_path_factory: pytest.TempPathFactory,
    ) -> None:
        """验证 locations 中的绝对路径位于 cwd 之外时被硬阻断（SubTask 用例 5）。"""
        # 用 tmp_path 作为 cwd，另起一个兄弟目录作为越权路径
        cwd_dir = tmp_path
        outside_dir = tmp_path_factory.mktemp("escape_target")

        adapter = ACPPermissionAdapter(cwd=str(cwd_dir))
        tool_call = {
            "title": "Edit File",
            "kind": "file",
            "locations": [{"path": str(outside_dir / "secret.txt")}],
        }

        assert adapter.is_hard_blocked(tool_call) is True

    def test_location_inside_cwd_is_not_hard_blocked(self, tmp_path: Path) -> None:
        """验证 locations 中的相对路径解析后位于 cwd 内时未被硬阻断。"""
        adapter = ACPPermissionAdapter(cwd=str(tmp_path))
        tool_call = {
            "title": "Edit File",
            "kind": "file",
            "locations": [{"path": "src/main.py"}],
        }

        assert adapter.is_hard_blocked(tool_call) is False


class TestSafeCommands:
    """安全命令不应被硬阻断。"""

    def test_safe_command_is_not_hard_blocked(self) -> None:
        """验证 'ls -la' 等安全命令不被硬阻断（SubTask 用例 6）。"""
        adapter = ACPPermissionAdapter(cwd=".")
        tool_call = _make_shell_tool_call("ls -la")

        assert adapter.is_hard_blocked(tool_call) is False

    def test_empty_command_is_not_hard_blocked(self) -> None:
        """验证无命令信息的 tool_call 不被硬阻断。"""
        adapter = ACPPermissionAdapter(cwd=".")
        tool_call = {"title": "Read File", "kind": "file"}

        assert adapter.is_hard_blocked(tool_call) is False


class TestBuildSuspendedPermission:
    """build_suspended_permission 字段填充正确性测试（SubTask 用例 7）。"""

    def test_build_suspended_permission_populates_all_fields(self) -> None:
        """验证返回的 SuspendedPermission 字段被正确填充。"""
        adapter = ACPPermissionAdapter(cwd=".")
        tool_call = {
            "title": "Shell Command",
            "kind": "shell",
            "rawInput": {"command": "ls -la src/"},
            "locations": [{"path": "src/"}],
        }
        options = [
            {"optionId": "allow_once", "label": "允许一次"},
            {"optionId": "deny", "label": "拒绝"},
        ]

        permission = adapter.build_suspended_permission(
            agent="test-agent",
            tool_call=tool_call,
            options=options,
        )

        # 类型校验
        assert isinstance(permission, SuspendedPermission)

        # 核心字段
        assert permission.agent == "test-agent"
        assert permission.tool_name == "Shell Command"
        assert permission.tool_kind == "shell"
        assert permission.action == "shell"
        assert permission.summary == "Shell Command"
        assert permission.command == "ls -la src/"
        assert permission.paths == ["src/"]
        assert permission.requires_user_confirmation is True

        # 单路径情况下 target 应为相对路径原样（位于 cwd 内）
        assert permission.target == "src/"

        # payload 结构
        assert permission.payload["toolCall"]["kind"] == "shell"
        assert permission.payload["toolCall"]["rawInput"]["command"] == "ls -la src/"
        assert len(permission.payload["options"]) == 2
        assert permission.payload["options"][0]["optionId"] == "allow_once"

        # options 字段为 dict 副本列表
        assert permission.options == options
        assert permission.options is not options  # 应为副本而非原引用

    def test_build_suspended_permission_skips_invalid_options(self) -> None:
        """验证非 dict、非模型对象的 option 被跳过。"""
        adapter = ACPPermissionAdapter(cwd=".")
        tool_call = {"title": "Tool", "kind": "file"}
        options: list[Any] = [
            {"optionId": "valid"},
            "invalid_string",
            12345,
            None,
            {"optionId": "valid2"},
        ]

        permission = adapter.build_suspended_permission(
            agent="agent",
            tool_call=tool_call,
            options=options,
        )

        assert len(permission.options) == 2
        assert permission.options[0]["optionId"] == "valid"
        assert permission.options[1]["optionId"] == "valid2"

    def test_build_suspended_permission_multiple_paths_target_shows_count(self) -> None:
        """验证多路径场景下 target 显示为 'N files'。"""
        adapter = ACPPermissionAdapter(cwd=".")
        tool_call = {
            "title": "Edit Files",
            "kind": "file",
            "locations": [
                {"path": "src/a.py"},
                {"path": "src/b.py"},
                {"path": "src/c.py"},
            ],
        }

        permission = adapter.build_suspended_permission(
            agent="agent",
            tool_call=tool_call,
            options=[],
        )

        assert permission.target == "3 files"
        assert len(permission.paths) == 3

    def test_build_suspended_permission_falls_back_to_command_as_target(self) -> None:
        """验证无路径场景下 target 回退为命令字符串。"""
        adapter = ACPPermissionAdapter(cwd=".")
        tool_call = _make_shell_tool_call("git status")

        permission = adapter.build_suspended_permission(
            agent="agent",
            tool_call=tool_call,
            options=[],
        )

        assert permission.target == "git status"


class TestResolveOptionById:
    """resolve_option_by_id 选项查找测试。"""

    def test_resolve_option_by_id_finds_match(self) -> None:
        """验证按 optionId 在选项列表中找到匹配项（SubTask 用例 8）。"""
        adapter = ACPPermissionAdapter(cwd=".")
        options = [
            {"optionId": "allow_once", "label": "允许一次"},
            {"optionId": "deny", "label": "拒绝"},
        ]

        result = adapter.resolve_option_by_id(options, "deny")

        assert result is not None
        assert result["optionId"] == "deny"
        assert result["label"] == "拒绝"

    def test_resolve_option_by_id_supports_snake_case_field(self) -> None:
        """验证兼容 snake_case 字段 option_id。"""
        adapter = ACPPermissionAdapter(cwd=".")
        options = [{"option_id": "allow_always"}]

        result = adapter.resolve_option_by_id(options, "allow_always")

        assert result is not None
        assert result["option_id"] == "allow_always"

    def test_resolve_option_by_id_returns_none_when_not_found(self) -> None:
        """验证未找到匹配项时返回 None（SubTask 用例 9）。"""
        adapter = ACPPermissionAdapter(cwd=".")
        options = [{"optionId": "allow_once"}, {"optionId": "deny"}]

        result = adapter.resolve_option_by_id(options, "nonexistent")

        assert result is None

    def test_resolve_option_by_id_returns_none_for_empty_id(self) -> None:
        """验证 option_id 为空字符串或纯空白时返回 None。"""
        adapter = ACPPermissionAdapter(cwd=".")
        options = [{"optionId": "allow_once"}]

        assert adapter.resolve_option_by_id(options, "") is None
        assert adapter.resolve_option_by_id(options, "   ") is None

    def test_resolve_option_by_id_strips_whitespace(self) -> None:
        """验证 option_id 首尾空白会被去除后再比较。"""
        adapter = ACPPermissionAdapter(cwd=".")
        options = [{"optionId": "allow_once"}]

        result = adapter.resolve_option_by_id(options, "  allow_once  ")

        assert result is not None
        assert result["optionId"] == "allow_once"

    def test_resolve_option_by_id_skips_non_dict_entries(self) -> None:
        """验证列表中的非 dict 元素被跳过，不抛异常。"""
        adapter = ACPPermissionAdapter(cwd=".")
        options: list[Any] = ["invalid", 123, {"optionId": "valid"}]

        result = adapter.resolve_option_by_id(options, "valid")

        assert result is not None
        assert result["optionId"] == "valid"


class TestSelectedResponse:
    """selected_response 响应生成测试。"""

    def test_selected_response_with_none_returns_cancelled(self) -> None:
        """验证 option 为 None 时返回与 cancelled_response 等价的结构（SubTask 用例 10）。"""
        adapter = ACPPermissionAdapter(cwd=".")

        selected = adapter.selected_response(None)
        cancelled = adapter.cancelled_response()

        # SDK 可用：两者均为 RequestPermissionResponse 实例且 outcome 类型一致
        # SDK 缺失：两者均为 dict 占位结构
        if _ACP_AVAILABLE:
            assert type(selected).__name__ == "RequestPermissionResponse"
            assert type(selected) is type(cancelled)
        else:
            assert isinstance(selected, dict)
            assert isinstance(cancelled, dict)
            assert selected == cancelled

    def test_selected_response_with_option_returns_selected_outcome(self) -> None:
        """验证传入有效选项时返回 selected outcome。"""
        adapter = ACPPermissionAdapter(cwd=".")
        option = {"optionId": "allow_once", "label": "允许一次"}

        response = adapter.selected_response(option)

        if _ACP_AVAILABLE:
            assert type(response).__name__ == "RequestPermissionResponse"
            # outcome 应为 AllowedOutcome 且 outcome 字段为 selected
            outcome = response.outcome
            assert getattr(outcome, "outcome", None) == "selected"
            assert getattr(outcome, "optionId", None) == "allow_once"
        else:
            assert isinstance(response, dict)
            assert response["outcome"]["outcome"] == "selected"
            assert response["outcome"]["optionId"] == "allow_once"

    def test_selected_response_falls_back_when_no_option_id(self) -> None:
        """验证 option 缺失 optionId 字段时回退为 'selected'。"""
        adapter = ACPPermissionAdapter(cwd=".")
        option = {"label": "允许"}

        response = adapter.selected_response(option)

        if _ACP_AVAILABLE:
            outcome = response.outcome
            assert getattr(outcome, "optionId", None) == "selected"
        else:
            assert response["outcome"]["optionId"] == "selected"


class TestCancelledResponse:
    """cancelled_response 响应生成测试（SubTask 用例 11）。"""

    def test_cancelled_response_returns_denied_outcome_when_sdk_available(self) -> None:
        """验证 acp SDK 可用时返回 DeniedOutcome 类型的响应。"""
        adapter = ACPPermissionAdapter(cwd=".")

        response = adapter.cancelled_response()

        if _ACP_AVAILABLE:
            # SDK 可用：应为 RequestPermissionResponse 实例
            assert type(response).__name__ == "RequestPermissionResponse"
            outcome = response.outcome
            # outcome 应为 DeniedOutcome 且 outcome 字段为 cancelled
            assert type(outcome).__name__ == "DeniedOutcome"
            assert getattr(outcome, "outcome", None) == "cancelled"
        else:
            # SDK 缺失：返回 dict 占位结构
            assert isinstance(response, dict)
            assert response["outcome"]["outcome"] == "cancelled"


class TestCwdResolution:
    """__init__ cwd 解析行为测试。"""

    def test_cwd_is_resolved_to_absolute_path(self, tmp_path: Path) -> None:
        """验证传入的 cwd 被展开并 resolve 为绝对路径字符串。"""
        relative_path = "."
        adapter = ACPPermissionAdapter(cwd=relative_path)

        cwd_path = Path(adapter.cwd)
        assert cwd_path.is_absolute()
        assert adapter.cwd == str(cwd_path)

    def test_cwd_expands_user_home(self) -> None:
        """验证 cwd 中的 ~ 被展开为用户家目录。"""
        adapter = ACPPermissionAdapter(cwd="~")

        assert "~" not in adapter.cwd
        assert Path(adapter.cwd).is_absolute()
