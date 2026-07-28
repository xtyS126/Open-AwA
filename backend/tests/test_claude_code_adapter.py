# -*- coding: utf-8 -*-
"""
ClaudeCodeAdapter 双模回归测试。

覆盖 ACP 优先/subprocess 回退两条执行路径，验证：
1. prefer_acp=False 走 subprocess
2. prefer_acp=True ACP 不可用时降级到 subprocess（含 cc_fallback_to_subprocess 日志）
3. prefer_acp=True ACP 可用时调用 ACPService.run_turn
4. ACP 模式 output 字段拼接所有 text 事件
5. ACP 模式 changed_files 从 tool_end 事件的 locations 提取
6. ACP 模式 success=True 当 status="completed"
7. ACP 模式 success=False 当 status="error"
8. ACP 模式抛异常时降级到 subprocess
9. 接口签名兼容：run_task/run_with_mode/is_available/enable_worktree/cleanup_worktree
"""

from __future__ import annotations

from types import ModuleType
from typing import Any
from unittest.mock import MagicMock, patch

from loguru import logger

from config.logging import sanitize_for_logging
from core.coding.claude_code import ClaudeCodeAdapter


# ==================== 辅助函数 ====================


def _make_fake_acp_module() -> ModuleType:
    """构造一个假的 acp 模块，使 `import acp` 在测试中成功。"""
    return ModuleType("acp")


def _make_mock_service(
    events: list[dict[str, Any]] | None = None,
    status: str = "completed",
    exc: Exception | None = None,
) -> MagicMock:
    """构造 mock ACPService。

    Args:
        events: run_turn 执行过程中通过 on_message 推送的事件列表。
        status: run_turn 返回的最终 status。
        exc: 若不为 None，run_turn 抛出该异常。

    Returns:
        MagicMock 实例，run_turn 为 async 函数，按 events 推送事件后返回。
    """
    service = MagicMock()
    events = events or []

    async def _run_turn(**kwargs: Any) -> dict[str, Any]:
        if exc is not None:
            raise exc
        on_message = kwargs.get("on_message")
        for event in events:
            if on_message is not None:
                await on_message(event, False)
        return {"status": status}

    service.run_turn = _run_turn
    return service


def _make_subprocess_result(
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> MagicMock:
    """构造 mock subprocess.run 返回值。"""
    result = MagicMock()
    result.returncode = returncode
    result.stdout = stdout
    result.stderr = stderr
    return result


def _setup_subprocess_adapter(tmp_path: Any) -> ClaudeCodeAdapter:
    """构造走 subprocess 路径的适配器：预置 _available=True 与空文件快照。

    Args:
        tmp_path: pytest 临时目录 fixture。

    Returns:
        已就绪的 ClaudeCodeAdapter 实例。
    """
    adapter = ClaudeCodeAdapter(project_dir=str(tmp_path), prefer_acp=False)
    # 预置可用性缓存，跳过 claude --version 探测
    adapter._available = True
    return adapter


def _extra_matches(actual: Any, expected: str) -> bool:
    """匹配日志 extra 字段值，兼容 init_logging 全局 patcher 脱敏前后的值。

    main.py 导入时会调用 init_logging()，其全局 patcher 会对 extra 字典中的
    字符串值调用 sanitize_for_logging 脱敏（如 "cc_fallback_to_subprocess"
    被掩码为 "cc***ss"）。本函数同时匹配原始值与脱敏值，使测试在隔离运行
    与全套运行下均能通过。

    Args:
        actual: 日志记录中 extra 字段的实际值。
        expected: 期望的原始值。

    Returns:
        实际值等于原始值或脱敏值时返回 True。
    """
    return actual == expected or actual == sanitize_for_logging(expected)


# ==================== 测试用例 ====================


class TestSubprocessPath:
    """prefer_acp=False 时走 subprocess 路径测试。"""

    def test_prefer_acp_false_goes_subprocess(self, tmp_path: Any) -> None:
        """prefer_acp=False 时 run_task 走 subprocess 路径（用例 1）。"""
        adapter = _setup_subprocess_adapter(tmp_path)

        with patch(
            "core.coding.claude_code.subprocess.run",
            return_value=_make_subprocess_result(
                returncode=0, stdout="task done", stderr="",
            ),
        ), patch.object(
            adapter, "_get_file_snapshot", return_value={},
        ):
            result = adapter.run_task(prompt="hello")

        assert result["success"] is True
        assert result["output"] == "task done"
        assert result["exit_code"] == 0
        assert result["changed_files"] == []


class TestAcpUnavailableFallback:
    """prefer_acp=True 但 ACP 不可用时降级到 subprocess 测试。"""

    def test_acp_unavailable_falls_back_to_subprocess(
        self, tmp_path: Any,
    ) -> None:
        """prefer_acp=True 且 ACP SDK 未安装时降级到 subprocess（用例 2）。"""
        adapter = ClaudeCodeAdapter(project_dir=str(tmp_path), prefer_acp=True)
        adapter._available = True

        # 收集 loguru 日志记录
        log_records: list[dict[str, Any]] = []

        def log_sink(message: Any) -> None:
            log_records.append(message.record)

        sink_id = logger.add(log_sink, level="WARNING")

        try:
            # 将 sys.modules["acp"] 置为 None 使 `import acp` 抛 ImportError
            with patch.dict("sys.modules", {"acp": None}), patch(
                "core.coding.claude_code.subprocess.run",
                return_value=_make_subprocess_result(
                    returncode=0, stdout="fallback output", stderr="",
                ),
            ), patch.object(
                adapter, "_get_file_snapshot", return_value={},
            ):
                result = adapter.run_task(prompt="hello")

            # 验证降级日志被记录
            fallback_records = [
                r for r in log_records
                if _extra_matches(r["extra"].get("event"), "cc_fallback_to_subprocess")
            ]
            assert len(fallback_records) >= 1
            assert _extra_matches(
                fallback_records[0]["extra"].get("reason"),
                "acp_sdk_not_installed",
            )

            # 验证回退到 subprocess 后返回成功
            assert result["success"] is True
            assert result["output"] == "fallback output"
        finally:
            logger.remove(sink_id)


class TestAcpAvailableExecution:
    """prefer_acp=True 且 ACP 可用时调用 ACPService.run_turn 测试。"""

    def test_acp_available_calls_run_turn(self, tmp_path: Any) -> None:
        """prefer_acp=True 且 ACP 可用时调用 ACPService.run_turn（用例 3）。"""
        adapter = ClaudeCodeAdapter(project_dir=str(tmp_path), prefer_acp=True)
        mock_service = _make_mock_service(
            events=[{"type": "text", "text": "hi"}],
            status="completed",
        )

        fake_acp = _make_fake_acp_module()
        with patch.dict("sys.modules", {"acp": fake_acp}), patch(
            "acp_host.get_acp_service", return_value=mock_service,
        ):
            result = adapter.run_task(prompt="hello")

        assert result["success"] is True
        assert result["output"] == "hi"
        assert result["status"] == "completed"

    def test_acp_output_concatenates_text_events(
        self, tmp_path: Any,
    ) -> None:
        """ACP 模式 output 字段拼接所有 text 事件（用例 4）。"""
        adapter = ClaudeCodeAdapter(project_dir=str(tmp_path), prefer_acp=True)
        mock_service = _make_mock_service(
            events=[
                {"type": "text", "text": "hello "},
                {"type": "status", "status": "agent_thinking"},
                {"type": "text", "text": "world"},
            ],
            status="completed",
        )

        fake_acp = _make_fake_acp_module()
        with patch.dict("sys.modules", {"acp": fake_acp}), patch(
            "acp_host.get_acp_service", return_value=mock_service,
        ):
            result = adapter.run_task(prompt="hello")

        # 拼接所有 text 事件，跳过 status 事件
        assert result["output"] == "hello world"

    def test_acp_changed_files_from_tool_end_locations(
        self, tmp_path: Any,
    ) -> None:
        """ACP 模式 changed_files 从 tool_end 事件的 locations 提取（用例 5）。"""
        adapter = ClaudeCodeAdapter(project_dir=str(tmp_path), prefer_acp=True)
        mock_service = _make_mock_service(
            events=[
                # locations 列表形式
                {
                    "type": "tool_end",
                    "locations": [
                        {"path": "/tmp/a.py"},
                        {"path": "/tmp/b.py"},
                    ],
                },
                # target 字符串形式
                {"type": "tool_end", "target": "/tmp/c.py"},
                # 重复路径应去重
                {"type": "tool_end", "target": "/tmp/a.py"},
                # locations 中字符串元素
                {"type": "tool_end", "locations": ["/tmp/d.py"]},
            ],
            status="completed",
        )

        fake_acp = _make_fake_acp_module()
        with patch.dict("sys.modules", {"acp": fake_acp}), patch(
            "acp_host.get_acp_service", return_value=mock_service,
        ):
            result = adapter.run_task(prompt="hello")

        # 4 个不重复路径
        assert result["changed_files"] == [
            "/tmp/a.py", "/tmp/b.py", "/tmp/c.py", "/tmp/d.py",
        ]
        assert result["changed_count"] == 4

    def test_acp_success_true_when_completed(self, tmp_path: Any) -> None:
        """ACP 模式 success=True 当 status="completed"（用例 6）。"""
        adapter = ClaudeCodeAdapter(project_dir=str(tmp_path), prefer_acp=True)
        mock_service = _make_mock_service(
            events=[{"type": "text", "text": "done"}],
            status="completed",
        )

        fake_acp = _make_fake_acp_module()
        with patch.dict("sys.modules", {"acp": fake_acp}), patch(
            "acp_host.get_acp_service", return_value=mock_service,
        ):
            result = adapter.run_task(prompt="hello")

        assert result["success"] is True
        assert result["error"] is None

    def test_acp_success_false_when_error(self, tmp_path: Any) -> None:
        """ACP 模式 success=False 当 status="error"（用例 7）。"""
        adapter = ClaudeCodeAdapter(project_dir=str(tmp_path), prefer_acp=True)
        mock_service = _make_mock_service(
            events=[],
            status="error",
        )

        fake_acp = _make_fake_acp_module()
        with patch.dict("sys.modules", {"acp": fake_acp}), patch(
            "acp_host.get_acp_service", return_value=mock_service,
        ):
            result = adapter.run_task(prompt="hello")

        assert result["success"] is False
        assert result["error"] is not None
        assert result["status"] == "error"


class TestAcpExceptionFallback:
    """ACP 模式抛异常时降级到 subprocess 测试。"""

    def test_acp_exception_falls_back_to_subprocess(
        self, tmp_path: Any,
    ) -> None:
        """ACP 模式抛异常时降级到 subprocess（用例 8）。"""
        adapter = ClaudeCodeAdapter(project_dir=str(tmp_path), prefer_acp=True)
        adapter._available = True
        mock_service = _make_mock_service(
            exc=RuntimeError("acp boom"),
        )

        fake_acp = _make_fake_acp_module()
        with patch.dict("sys.modules", {"acp": fake_acp}), patch(
            "acp_host.get_acp_service", return_value=mock_service,
        ), patch(
            "core.coding.claude_code.subprocess.run",
            return_value=_make_subprocess_result(
                returncode=0, stdout="subprocess output", stderr="",
            ),
        ), patch.object(
            adapter, "_get_file_snapshot", return_value={},
        ):
            result = adapter.run_task(prompt="hello")

        # 验证降级到 subprocess
        assert result["success"] is True
        assert result["output"] == "subprocess output"


class TestInterfaceCompatibility:
    """接口签名兼容性测试（用例 9）。"""

    def test_all_methods_exist(self, tmp_path: Any) -> None:
        """验证 run_task/run_with_mode/is_available/enable_worktree/cleanup_worktree 都存在。"""
        adapter = ClaudeCodeAdapter(project_dir=str(tmp_path), prefer_acp=True)

        assert callable(getattr(adapter, "run_task", None))
        assert callable(getattr(adapter, "run_with_mode", None))
        assert callable(getattr(adapter, "is_available", None))
        assert callable(getattr(adapter, "enable_worktree", None))
        assert callable(getattr(adapter, "cleanup_worktree", None))
        # 内部方法
        assert callable(getattr(adapter, "_run_via_acp", None))
        assert callable(getattr(adapter, "_run_via_subprocess", None))

    def test_prefer_acp_default_true(self, tmp_path: Any) -> None:
        """验证 prefer_acp 默认为 True。"""
        adapter = ClaudeCodeAdapter(project_dir=str(tmp_path))
        assert adapter.prefer_acp is True
        assert adapter._acp_available is False

    def test_prefer_acp_false_explicit(self, tmp_path: Any) -> None:
        """验证 prefer_acp=False 可显式设置。"""
        adapter = ClaudeCodeAdapter(project_dir=str(tmp_path), prefer_acp=False)
        assert adapter.prefer_acp is False


class TestRunTurnCallArguments:
    """验证 run_turn 调用参数测试。"""

    def test_run_turn_called_with_correct_args(
        self, tmp_path: Any,
    ) -> None:
        """验证 run_turn 使用 chat_id/agent/prompt_blocks/cwd/on_message 调用。"""
        adapter = ClaudeCodeAdapter(project_dir=str(tmp_path), prefer_acp=True)

        captured_kwargs: dict[str, Any] = {}

        async def _capture_run_turn(**kwargs: Any) -> dict[str, Any]:
            captured_kwargs.update(kwargs)
            return {"status": "completed"}

        mock_service = MagicMock()
        mock_service.run_turn = _capture_run_turn

        fake_acp = _make_fake_acp_module()
        with patch.dict("sys.modules", {"acp": fake_acp}), patch(
            "acp_host.get_acp_service", return_value=mock_service,
        ):
            adapter.run_task(prompt="test prompt", cwd="/custom/cwd")

        assert captured_kwargs["chat_id"] == "claude_code_adapter"
        assert captured_kwargs["agent"] == "claude_code"
        assert captured_kwargs["cwd"] == "/custom/cwd"
        assert captured_kwargs["prompt_blocks"] == [
            {"type": "text", "text": "test prompt"},
        ]
        assert callable(captured_kwargs["on_message"])

    def test_run_turn_cwd_defaults_to_project_dir(
        self, tmp_path: Any,
    ) -> None:
        """验证 cwd 为 None 时使用 project_dir。"""
        adapter = ClaudeCodeAdapter(project_dir=str(tmp_path), prefer_acp=True)

        captured_kwargs: dict[str, Any] = {}

        async def _capture_run_turn(**kwargs: Any) -> dict[str, Any]:
            captured_kwargs.update(kwargs)
            return {"status": "completed"}

        mock_service = MagicMock()
        mock_service.run_turn = _capture_run_turn

        fake_acp = _make_fake_acp_module()
        with patch.dict("sys.modules", {"acp": fake_acp}), patch(
            "acp_host.get_acp_service", return_value=mock_service,
        ):
            adapter.run_task(prompt="hello")

        assert captured_kwargs["cwd"] == str(tmp_path)

    def test_acp_service_none_falls_back_to_subprocess(
        self, tmp_path: Any,
    ) -> None:
        """ACP service 为 None 时降级到 subprocess（用例 2 变体）。"""
        adapter = ClaudeCodeAdapter(project_dir=str(tmp_path), prefer_acp=True)
        adapter._available = True

        log_records: list[dict[str, Any]] = []

        def log_sink(message: Any) -> None:
            log_records.append(message.record)

        sink_id = logger.add(log_sink, level="WARNING")

        try:
            fake_acp = _make_fake_acp_module()
            with patch.dict("sys.modules", {"acp": fake_acp}), patch(
                "acp_host.get_acp_service", return_value=None,
            ), patch(
                "core.coding.claude_code.subprocess.run",
                return_value=_make_subprocess_result(
                    returncode=0, stdout="ok", stderr="",
                ),
            ), patch.object(
                adapter, "_get_file_snapshot", return_value={},
            ):
                result = adapter.run_task(prompt="hello")

            # 验证降级日志（service 未初始化）
            fallback_records = [
                r for r in log_records
                if _extra_matches(r["extra"].get("event"), "cc_fallback_to_subprocess")
            ]
            assert len(fallback_records) >= 1
            assert _extra_matches(
                fallback_records[0]["extra"].get("reason"),
                "acp_service_not_initialized",
            )

            assert result["success"] is True
            assert result["output"] == "ok"
        finally:
            logger.remove(sink_id)
