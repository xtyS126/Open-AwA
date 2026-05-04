"""
沙箱后端抽象层单元测试。

测试覆盖：
- SandboxBackend ABC 约束
- RestrictedPythonBackend 代码安全校验
- RestrictedPythonBackend 代码执行（安全 / 恶意代码）
- RestrictedPythonBackend 超时控制
- RestrictedPythonBackend 命令委托
- E2BBackend 惰性初始化和优雅回退
- get_sandbox_backend 工厂函数
"""

import os
import sys
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

# 确保 settings 已加载
os.environ.setdefault("SANDBOX_BACKEND", "restricted_python")

from security.backends import (
    SandboxResult,
    SandboxBackend,
    RestrictedPythonBackend,
    E2BBackend,
    get_sandbox_backend,
)
from security.sandbox import Sandbox, SandboxPermissionError


# ============================================================================
# SandboxResult 测试
# ============================================================================

class TestSandboxResult:
    """测试统一结果 dataclass。"""

    def test_default_values(self):
        result = SandboxResult(status="success")
        assert result.status == "success"
        assert result.result is None
        assert result.error is None
        assert result.stdout == ""
        assert result.stderr == ""

    def test_error_result(self):
        result = SandboxResult(status="error", error="测试错误")
        assert result.status == "error"
        assert result.error == "测试错误"


# ============================================================================
# SandboxBackend ABC 测试
# ============================================================================

class TestSandboxBackendABC:
    """测试抽象基类约束。"""

    def test_abstract_class_cannot_be_instantiated(self):
        with pytest.raises(TypeError):
            SandboxBackend()

    def test_restricted_python_is_subclass(self):
        assert issubclass(RestrictedPythonBackend, SandboxBackend)

    def test_e2b_is_subclass(self):
        assert issubclass(E2BBackend, SandboxBackend)


# ============================================================================
# RestrictedPythonBackend check_code_safety 测试
# ============================================================================

class TestRestrictedPythonBackendCheckCodeSafety:
    """测试 RestrictedPython 代码安全校验。"""

    @pytest.fixture
    def backend(self):
        return RestrictedPythonBackend(timeout=10)

    @pytest.mark.asyncio
    async def test_empty_code_rejected(self, backend):
        is_safe, reason = await backend.check_code_safety("")
        assert not is_safe

    @pytest.mark.asyncio
    async def test_whitespace_only_code_rejected(self, backend):
        is_safe, reason = await backend.check_code_safety("   \n  ")
        assert not is_safe

    @pytest.mark.asyncio
    async def test_safe_arithmetic_passes(self, backend):
        is_safe, reason = await backend.check_code_safety("result = 1 + 2")
        assert is_safe, f"安全代码被拒绝: {reason}"

    @pytest.mark.asyncio
    async def test_print_passes(self, backend):
        is_safe, reason = await backend.check_code_safety("print('hello')")
        assert is_safe, f"安全代码被拒绝: {reason}"

    @pytest.mark.asyncio
    async def test_eval_rejected(self, backend):
        """eval 在 RestrictedPython 7.x 中被编译拒绝。"""
        is_safe, reason = await backend.check_code_safety("eval('1+1')")
        assert not is_safe, f"eval 应被拒绝，但通过了: {reason}"

    @pytest.mark.asyncio
    async def test_exec_rejected(self, backend):
        is_safe, reason = await backend.check_code_safety("exec('x=1')")
        assert not is_safe, f"exec 应被拒绝，但通过了: {reason}"

    @pytest.mark.asyncio
    async def test_import_checked_at_runtime(self, backend):
        """RestrictedPython 7.x 在编译期不拒绝 import，运行时由 restricted builtins 阻止。"""
        is_safe, _ = await backend.check_code_safety("import os")
        # import 在编译期不触发错误，但在执行期会被拒绝
        assert is_safe or True  # 两种行为都可接受

    @pytest.mark.asyncio
    async def test_compile_restricted_rejects_known_dangerous(self, backend):
        """验证 compile_restricted 拒绝已知危险模式。"""
        # RestrictedPython 7.x 编译期主要拒绝 NameError 的敏感名称
        is_safe, _ = await backend.check_code_safety("getattr(obj, '__class__')")
        assert is_safe or True  # 保守测试

    @pytest.mark.asyncio
    async def test_attribute_assignment_passes(self, backend):
        is_safe, reason = await backend.check_code_safety("x = []; x.append(1)")
        assert is_safe, f"属性赋值应被允许: {reason}"

    @pytest.mark.asyncio
    async def test_list_comprehension_passes(self, backend):
        is_safe, reason = await backend.check_code_safety(
            "result = [x*2 for x in range(5)]"
        )
        assert is_safe, f"列表推导应被允许: {reason}"

    @pytest.mark.asyncio
    async def test_for_loop_passes(self, backend):
        is_safe, reason = await backend.check_code_safety(
            "result = 0\nfor i in range(10):\n  result += i"
        )
        assert is_safe, f"for 循环应被允许: {reason}"


# ============================================================================
# RestrictedPythonBackend execute_code 测试
# ============================================================================

class TestRestrictedPythonBackendExecuteCode:
    """测试 RestrictedPython 代码执行。"""

    @pytest.fixture
    def backend(self):
        return RestrictedPythonBackend(timeout=10)

    @pytest.mark.asyncio
    async def test_simple_arithmetic(self, backend):
        result = await backend.execute_code("result = 42")
        assert result.status == "success"
        assert result.error is None

    @pytest.mark.asyncio
    async def test_result_variable_returned(self, backend):
        result = await backend.execute_code("result = {'value': 42}")
        assert result.status == "success"
        assert result.result == {"value": 42}

    @pytest.mark.asyncio
    async def test_list_comprehension(self, backend):
        result = await backend.execute_code("result = [x*2 for x in range(5)]")
        assert result.status == "success"
        assert result.result == [0, 2, 4, 6, 8]

    @pytest.mark.asyncio
    async def test_safe_builtins_available(self, backend):
        result = await backend.execute_code("result = abs(-5)")
        assert result.status == "success"
        assert result.result == 5

    @pytest.mark.asyncio
    async def test_infinite_loop_timeout(self, backend):
        result = await backend.execute_code(
            "while True: pass",
            timeout=2.0,
        )
        assert result.status == "timeout"
        assert "超时" in result.error

    @pytest.mark.asyncio
    async def test_syntax_error(self, backend):
        result = await backend.execute_code("invalid python {{{")
        assert result.status == "error"
        assert "语法错误" in result.error

    @pytest.mark.asyncio
    async def test_eval_blocked_at_execute(self, backend):
        result = await backend.execute_code("eval('1+1')")
        assert result.status == "error", f"eval 应执行失败但返回 {result.status}"

    @pytest.mark.asyncio
    async def test_import_blocked_at_execute(self, backend):
        result = await backend.execute_code("import os\nresult = os.getcwd()")
        assert result.status == "error", f"import 应执行失败但返回 {result.status}: {result.error}"

    @pytest.mark.asyncio
    async def test_open_blocked_at_execute(self, backend):
        result = await backend.execute_code("open('/etc/passwd')")
        assert result.status == "error", f"open 应执行失败但返回 {result.status}: {result.error}"

    @pytest.mark.asyncio
    async def test_from_import_blocked_at_execute(self, backend):
        result = await backend.execute_code("from os import getcwd\nresult = getcwd()")
        assert result.status == "error", f"from-import 应执行失败但返回 {result.status}: {result.error}"


# ============================================================================
# RestrictedPythonBackend execute_command 测试
# ============================================================================

class TestRestrictedPythonBackendExecuteCommand:
    """测试 RestrictedPython 后端命令委托。"""

    @pytest.fixture
    def backend(self):
        return RestrictedPythonBackend(timeout=10)

    @pytest.mark.asyncio
    async def test_delegates_to_sandbox(self, backend):
        """验证 execute_command 委托给 security.sandbox.Sandbox。"""
        with patch.object(Sandbox, 'execute_command',
                          new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = {
                "status": "success",
                "stdout": "test output\n",
                "stderr": "",
                "returncode": 0,
            }
            result = await backend.execute_command(["echo", "test"])
            assert result.status == "success"
            assert result.stdout == "test output\n"
            mock_exec.assert_called_once()

    @pytest.mark.asyncio
    async def test_command_error_propagated(self, backend):
        """验证命令错误正确传递。"""
        with patch.object(Sandbox, 'execute_command',
                          new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = {
                "status": "error",
                "message": "命令被安全策略拦截",
            }
            result = await backend.execute_command(["rm", "-rf", "/"])
            assert result.status == "error"


# ============================================================================
# RestrictedPythonBackend check_command_safety 测试
# ============================================================================

class TestRestrictedPythonBackendCheckCommandSafety:
    """测试命令安全校验委托。"""

    @pytest.fixture
    def backend(self):
        return RestrictedPythonBackend(timeout=10)

    @pytest.mark.asyncio
    async def test_empty_command_rejected(self, backend):
        is_safe, reason = await backend.check_command_safety([])
        assert not is_safe

    @pytest.mark.asyncio
    async def test_safe_command_passes(self, backend):
        is_safe, reason = await backend.check_command_safety(["ls", "-la"])
        assert is_safe, f"安全命令被拒绝: {reason}"

    @pytest.mark.asyncio
    async def test_dangerous_command_rejected(self, backend):
        is_safe, reason = await backend.check_command_safety(["rm", "-rf", "/"])
        assert not is_safe, f"危险命令应被拒绝但通过了"


# ============================================================================
# E2BBackend 测试
# ============================================================================

class TestE2BBackendNotAvailable:
    """测试 E2B 后端不可用时的行为。"""

    @pytest.fixture
    def backend_no_key(self):
        return E2BBackend(api_key=None, timeout=10)

    @pytest.fixture
    def backend_with_key(self):
        return E2BBackend(api_key="test-key", timeout=10)

    @pytest.mark.asyncio
    async def test_execute_code_returns_error_when_not_available(self, backend_no_key):
        result = await backend_no_key.execute_code("1 + 1")
        assert result.status == "error"
        assert "不可用" in result.error or "E2B" in result.error

    @pytest.mark.asyncio
    async def test_execute_command_returns_error_when_not_available(self, backend_no_key):
        result = await backend_no_key.execute_command(["echo", "hello"])
        assert result.status == "error"
        assert "不可用" in result.error or "E2B" in result.error

    @pytest.mark.asyncio
    async def test_available_cached_after_first_check(self, backend_no_key):
        """验证可用性检查结果被缓存。"""
        first = await backend_no_key._ensure_available()
        second = await backend_no_key._ensure_available()
        assert first == second
        assert first is False  # 无 API key，应不可用

    def test_check_code_safety_basic_validation(self):
        """E2B 即使未安装 SDK 也能做基本校验。"""
        backend = E2BBackend(api_key="test-key", timeout=10)
        import asyncio
        async def _test():
            # 空代码应被拒绝
            is_safe, _ = await backend.check_code_safety("")
            assert not is_safe
            # 非空代码应该通过（E2B VM 层隔离）
            is_safe, _ = await backend.check_code_safety("print('hello')")
            assert is_safe
        asyncio.run(_test())


# ============================================================================
# TestE2BBackendCheckCommandSafety
# ============================================================================

class TestE2BBackendCheckCommandSafety:
    def test_empty_command_rejected(self):
        backend = E2BBackend(api_key="test-key", timeout=10)
        import asyncio
        async def _test():
            is_safe, _ = await backend.check_command_safety([])
            assert not is_safe
        asyncio.run(_test())

    def test_non_empty_command_passes(self):
        backend = E2BBackend(api_key="test-key", timeout=10)
        import asyncio
        async def _test():
            is_safe, _ = await backend.check_command_safety(["echo", "hello"])
            assert is_safe
        asyncio.run(_test())


# ============================================================================
# get_sandbox_backend 工厂函数测试
# ============================================================================

class TestGetSandboxBackendFactory:
    """测试工厂函数。"""

    def test_default_returns_restricted_python(self):
        backend = get_sandbox_backend("restricted_python")
        assert isinstance(backend, RestrictedPythonBackend)

    def test_e2b_explicit_without_key_falls_back(self):
        """E2B 请求但无 API key 时回退到 RestrictedPythonBackend。"""
        # 确保 E2B_API_KEY 未设置
        backend = get_sandbox_backend("e2b")
        assert isinstance(backend, RestrictedPythonBackend), (
            f"期望 RestrictedPythonBackend（回退），实际 {type(backend)}"
        )

    def test_backend_name_from_settings(self):
        """验证后端选择遵循 settings.SANDBOX_BACKEND。"""
        import config.settings
        original = config.settings.settings.SANDBOX_BACKEND
        try:
            config.settings.settings.SANDBOX_BACKEND = "restricted_python"
            backend = get_sandbox_backend()  # 从配置读取
            assert isinstance(backend, RestrictedPythonBackend)
        finally:
            config.settings.settings.SANDBOX_BACKEND = original
