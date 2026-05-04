"""
可插拔沙箱后端抽象层。

提供统一的代码执行和命令执行接口，支持多种隔离后端：
- RestrictedPythonBackend: AST 级 Python 代码沙箱（默认）
- E2BBackend: Firecracker microVM 远端沙箱（可选）

所有后端通过 SandboxBackend ABC 定义统一协议，
工厂函数 get_sandbox_backend() 根据配置选择后端。
"""

from __future__ import annotations

import asyncio
import shlex
import types
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger
from config.settings import settings


# ---------------------------------------------------------------------------
# 统一结果类型
# ---------------------------------------------------------------------------


@dataclass
class SandboxResult:
    """沙箱执行统一结果。"""
    status: str                     # success / error / timeout
    result: Any = None
    error: Optional[str] = None
    stdout: str = ""
    stderr: str = ""


# ---------------------------------------------------------------------------
# 抽象基类
# ---------------------------------------------------------------------------


class SandboxBackend(ABC):
    """可插拔沙箱后端抽象基类。"""

    @abstractmethod
    async def execute_code(
        self,
        code: str,
        timeout: float = 30.0,
        context: Optional[Dict[str, Any]] = None,
    ) -> SandboxResult:
        """在受限环境中执行 Python 代码。"""
        ...

    @abstractmethod
    async def execute_command(
        self,
        command: List[str],
        timeout: float = 30.0,
        env: Optional[Dict[str, str]] = None,
        cwd: Optional[str] = None,
    ) -> SandboxResult:
        """在沙箱环境中执行系统命令。"""
        ...

    @abstractmethod
    async def check_code_safety(self, code: str) -> Tuple[bool, str]:
        """静态安全检查：返回 (is_safe, reason)。"""
        ...

    @abstractmethod
    async def check_command_safety(self, command: List[str]) -> Tuple[bool, str]:
        """命令校验：返回 (is_safe, reason)。"""
        ...


# ---------------------------------------------------------------------------
# RestrictedPython 后端
# ---------------------------------------------------------------------------


class RestrictedPythonBackend(SandboxBackend):
    """
    基于 RestrictedPython 的 Python 代码沙箱。

    安全机制：
    - compile_restricted() AST 级编译限制
    - safe_globals + safe_builtins 内置函数白名单
    - 线程级超时控制

    命令执行委托给 security.sandbox.Sandbox，
    因此兼具命令白名单和路径遍历防护。

    纯 Python 实现，Windows / Linux / macOS 全兼容。
    """

    def __init__(
        self,
        timeout: float = 30.0,
        max_memory_mb: Optional[int] = None,
    ) -> None:
        self._timeout = timeout
        self.max_memory_mb = max_memory_mb
        # 延迟导入 RestrictedPython，避免在未安装时阻塞模块加载
        self._restricted_available: Optional[bool] = None

    def _ensure_restricted(self) -> bool:
        """检查 RestrictedPython 是否可用。"""
        if self._restricted_available is not None:
            return self._restricted_available
        try:
            import RestrictedPython  # noqa: F401
            self._restricted_available = True
        except ImportError:
            logger.error("RestrictedPython 未安装，无法使用 RestrictedPythonBackend")
            self._restricted_available = False
        return self._restricted_available

    # ------------------------------------------------------------------
    # 代码安全校验
    # ------------------------------------------------------------------

    async def check_code_safety(self, code: str) -> Tuple[bool, str]:
        """使用 RestrictedPython.compile_restricted 进行 AST 级安全校验。"""
        if not code or not code.strip():
            return False, "代码不能为空"

        if not self._ensure_restricted():
            return False, "RestrictedPython 未安装"

        try:
            from RestrictedPython import compile_restricted
            compile_restricted(code, '<sandbox>', 'exec')
            return True, ""
        except SyntaxError as e:
            return False, f"语法错误: {e}"
        except TypeError as e:
            return False, f"不安全的代码结构: {e}"
        except ValueError as e:
            return False, f"代码校验失败: {e}"
        except Exception as e:
            return False, str(e)

    # ------------------------------------------------------------------
    # 代码执行
    # ------------------------------------------------------------------

    async def execute_code(
        self,
        code: str,
        timeout: float = 30.0,
        context: Optional[Dict[str, Any]] = None,
    ) -> SandboxResult:
        """
        在 RestrictedPython 沙箱中执行 Python 代码。

        执行流程：
        1. compile_restricted() 编译代码（AST 级安全限制）
        2. 构建受限全局命名空间（safe_globals + safe_builtins）
        3. 在线程池中执行，附带超时控制
        """
        if not self._ensure_restricted():
            return SandboxResult(
                status="error",
                error="RestrictedPython 未安装",
            )

        from RestrictedPython import compile_restricted, safe_builtins
        from RestrictedPython.Guards import safer_getattr

        effective_timeout = timeout if timeout else self._timeout

        # Step 1: 编译检查
        try:
            byte_code = compile_restricted(code, '<sandbox>', 'exec')
        except SyntaxError as e:
            return SandboxResult(status="error", error=f"语法错误: {e}")
        except (TypeError, ValueError) as e:
            return SandboxResult(status="error", error=f"代码安全校验失败: {e}")
        except Exception as e:
            return SandboxResult(status="error", error=str(e))

        # Step 2: 构建受限执行命名空间
        # RestrictedPython 7.x 需要以下守卫函数在 globals 中：
        # - _getattr_: 安全属性访问（Guards.safer_getattr）
        # - _getiter_: 迭代器和列表推导的迭代入口
        # - _getitem_: 下标访问 obj[key]
        # - _write_: 列表推导中的写入操作
        restricted_globals: Dict[str, Any] = {
            '__builtins__': dict(safe_builtins),
            '_getattr_': safer_getattr,
            '_getiter_': iter,
            '_getitem_': lambda obj, key: obj[key],
            '_write_': lambda x: x,
        }

        # 注入调用方提供的上下文
        if context:
            restricted_globals.update(context)

        local_vars: Dict[str, Any] = {}

        # Step 3: 在线程池中执行（带超时）
        from skills.skill_executor import execute_with_timeout

        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                _execute_with_timeout_sync,
                byte_code,
                restricted_globals,
                local_vars,
                effective_timeout,
            )
            result = local_vars.get('result', {'status': 'executed'})
            return SandboxResult(status="success", result=result)
        except asyncio.TimeoutError:
            return SandboxResult(
                status="timeout",
                error=f"代码执行超时（超过 {effective_timeout} 秒）",
            )
        except Exception as e:
            # execute_with_timeout 通过线程 join 实现超时，抛出 ExecutionTimeoutException
            error_msg = str(e)
            if "超时" in error_msg or "timeout" in error_msg.lower():
                return SandboxResult(status="timeout", error=error_msg)
            return SandboxResult(status="error", error=str(e))

    # ------------------------------------------------------------------
    # 命令安全校验
    # ------------------------------------------------------------------

    async def check_command_safety(self, command: List[str]) -> Tuple[bool, str]:
        """委托给 security.sandbox.Sandbox 进行命令校验。"""
        if not command:
            return False, "命令列表不能为空"
        try:
            from security.sandbox import Sandbox
            sandbox = Sandbox()
            sandbox._validate_command(command)
            return True, ""
        except Exception as e:
            return False, str(e)

    # ------------------------------------------------------------------
    # 命令执行
    # ------------------------------------------------------------------

    async def execute_command(
        self,
        command: List[str],
        timeout: float = 30.0,
        env: Optional[Dict[str, str]] = None,
        cwd: Optional[str] = None,
    ) -> SandboxResult:
        """
        委托给 security.sandbox.Sandbox 执行系统命令。

        RestrictedPython 后端不直接处理系统命令执行，
        而是复用已有的命令白名单/黑名单/路径校验机制。
        """
        from security.sandbox import Sandbox

        effective_timeout = timeout if timeout else self._timeout
        sandbox = Sandbox(timeout=int(effective_timeout))

        command_str = ' '.join(shlex.quote(c) for c in command)
        result = await sandbox.execute_command(
            command_str,
            working_dir=cwd,
            env=env,
            timeout=int(effective_timeout),
        )

        if result.get("status") == "success":
            return SandboxResult(
                status="success",
                stdout=result.get("stdout", ""),
                stderr=result.get("stderr", ""),
                result={"returncode": result.get("returncode", 0)},
            )
        return SandboxResult(
            status=result.get("status", "error"),
            error=result.get("message", result.get("error", "")),
        )


# ---------------------------------------------------------------------------
# E2B 远端沙箱后端
# ---------------------------------------------------------------------------


class E2BBackend(SandboxBackend):
    """
    基于 E2B Code Interpreter 的远端沙箱后端。

    使用 Firecracker microVM 提供硬件级隔离，
    通过 HTTPS 远程执行，Windows / Linux / macOS 全兼容。

    自动检测可用性：未安装 SDK 或未配置 API Key 时优雅降级。
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        timeout: int = 60,
        template: str = "default",
    ) -> None:
        self.api_key = api_key
        self.timeout = timeout
        self.template = template
        self._available: Optional[bool] = None  # 惰性检测

    async def _ensure_available(self) -> bool:
        """检查 E2B SDK 是否已安装且 API Key 已配置。"""
        if self._available is not None:
            return self._available
        try:
            import e2b_code_interpreter  # noqa: F401
        except ImportError:
            logger.warning("e2b-code-interpreter 未安装，E2B 后端不可用")
            self._available = False
            return False
        if not self.api_key:
            logger.warning("E2B_API_KEY 未配置，E2B 后端不可用")
            self._available = False
            return False
        self._available = True
        return True

    # ------------------------------------------------------------------
    # 代码安全校验
    # ------------------------------------------------------------------

    async def check_code_safety(self, code: str) -> Tuple[bool, str]:
        """E2B 使用 VM 隔离，客户端侧仅做基本语法检查。"""
        if not code or not code.strip():
            return False, "代码不能为空"
        # 尝试用 RestrictedPython 做客户端侧预检（尽早发现语法错误）
        try:
            from RestrictedPython import compile_restricted
            compile_restricted(code, '<sandbox>', 'exec')
            return True, ""
        except ImportError:
            pass  # RestrictedPython 不可用时跳过预检
        except SyntaxError as e:
            return False, f"语法错误: {e}"
        except (TypeError, ValueError) as e:
            return False, f"代码校验失败: {e}"
        return True, ""  # 无 RestrictedPython 时，仅做非空检查即放行

    # ------------------------------------------------------------------
    # 命令安全校验
    # ------------------------------------------------------------------

    async def check_command_safety(self, command: List[str]) -> Tuple[bool, str]:
        """E2B VM 提供进程级隔离，仅做基本校验。"""
        if not command:
            return False, "命令列表不能为空"
        return True, ""

    # ------------------------------------------------------------------
    # 代码执行
    # ------------------------------------------------------------------

    async def execute_code(
        self,
        code: str,
        timeout: float = 30.0,
        context: Optional[Dict[str, Any]] = None,
    ) -> SandboxResult:
        """在 E2B Firecracker microVM 中执行 Python 代码。"""
        if not await self._ensure_available():
            return SandboxResult(
                status="error",
                error="E2B 后端不可用：请安装 e2b-code-interpreter 并配置 E2B_API_KEY",
            )

        effective_timeout = timeout if timeout else float(self.timeout)

        try:
            from e2b_code_interpreter import CodeInterpreter

            def _exec_in_sandbox() -> Any:
                with CodeInterpreter(
                    api_key=self.api_key,
                    timeout=int(effective_timeout),
                ) as sandbox:
                    return sandbox.notebook.exec_cell(
                        code,
                        timeout=int(effective_timeout),
                    )

            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, _exec_in_sandbox)

            if getattr(result, 'error', None):
                error_info = result.error
                return SandboxResult(
                    status="error",
                    error=str(error_info),
                    stdout=getattr(result.logs, 'stdout', [""])[0] if hasattr(result, 'logs') else "",
                    stderr=getattr(result.logs, 'stderr', [""])[0] if hasattr(result, 'logs') else "",
                )

            text_output = ""
            if hasattr(result, 'text'):
                text_output = result.text or ""
            elif hasattr(result, 'logs'):
                text_output = "\n".join(result.logs.stdout) if result.logs.stdout else ""

            return SandboxResult(
                status="success",
                result=text_output,
                stdout=text_output,
            )

        except ImportError:
            return SandboxResult(
                status="error",
                error="e2b-code-interpreter 未安装",
            )
        except Exception as e:
            logger.error(f"E2B 执行异常: {e}")
            return SandboxResult(status="error", error=str(e))

    # ------------------------------------------------------------------
    # 命令执行
    # ------------------------------------------------------------------

    async def execute_command(
        self,
        command: List[str],
        timeout: float = 30.0,
        env: Optional[Dict[str, str]] = None,
        cwd: Optional[str] = None,
    ) -> SandboxResult:
        """在 E2B Firecracker microVM 中执行系统命令。"""
        if not await self._ensure_available():
            return SandboxResult(
                status="error",
                error="E2B 后端不可用：请安装 e2b-code-interpreter 并配置 E2B_API_KEY",
            )

        effective_timeout = timeout if timeout else float(self.timeout)
        command_str = ' '.join(shlex.quote(c) for c in command)

        try:
            from e2b_code_interpreter import CodeInterpreter

            def _exec_in_sandbox() -> Any:
                with CodeInterpreter(
                    api_key=self.api_key,
                    timeout=int(effective_timeout),
                ) as sandbox:
                    return sandbox.commands.run(
                        command_str,
                        timeout=int(effective_timeout),
                        cwd=cwd,
                        envs=env,
                    )

            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, _exec_in_sandbox)

            exit_code = getattr(result, 'exit_code', -1)
            return SandboxResult(
                status="success" if exit_code == 0 else "error",
                stdout=getattr(result, 'stdout', '') or '',
                stderr=getattr(result, 'stderr', '') or '',
                result={"exit_code": exit_code},
            )

        except ImportError:
            return SandboxResult(
                status="error",
                error="e2b-code-interpreter 未安装",
            )
        except Exception as e:
            logger.error(f"E2B 命令执行异常: {e}")
            return SandboxResult(status="error", error=str(e))


# ---------------------------------------------------------------------------
# 辅助函数：同步执行（供 run_in_executor 使用）
# ---------------------------------------------------------------------------


def _execute_with_timeout_sync(
    byte_code: types.CodeType,
    exec_globals: Dict[str, Any],
    local_vars: Dict[str, Any],
    timeout: float,
) -> None:
    """
    同步执行已编译的代码对象，带超时控制。

    复用 skills.skill_executor 的 execute_with_timeout，
    但接受预编译的 code object 而非字符串。
    """
    from skills.skill_executor import execute_with_timeout
    execute_with_timeout(byte_code, exec_globals, local_vars, timeout)


# ---------------------------------------------------------------------------
# 工厂函数
# ---------------------------------------------------------------------------


def get_sandbox_backend(backend_name: Optional[str] = None) -> SandboxBackend:
    """
    根据配置创建沙箱后端实例。

    优先级：
    1. 显式指定的 backend_name 参数
    2. settings.SANDBOX_BACKEND 配置值
    3. 默认 "restricted_python"

    当 E2B 被请求但不可用时，自动回退到 RestrictedPythonBackend。

    Args:
        backend_name: 后端名称 ("restricted_python" 或 "e2b")，为 None 时从配置读取。

    Returns:
        SandboxBackend 实例。
    """
    name = backend_name or getattr(settings, "SANDBOX_BACKEND", "restricted_python")
    logger.info(f"沙箱后端请求: {name!r}")

    if name == "e2b":
        api_key = None
        if hasattr(settings, "E2B_API_KEY") and settings.E2B_API_KEY:
            secret = settings.E2B_API_KEY
            api_key = secret.get_secret_value() if hasattr(secret, 'get_secret_value') else str(secret)

        if not api_key:
            logger.warning(
                "请求 E2B 后端但 E2B_API_KEY 未设置，回退到 RestrictedPythonBackend"
            )
            return RestrictedPythonBackend(timeout=settings.SANDBOX_TIMEOUT)

        logger.info("使用 E2B 远端沙箱后端（Firecracker microVM）")
        return E2BBackend(
            api_key=api_key,
            timeout=getattr(settings, "E2B_TIMEOUT", 60),
        )

    logger.info("使用 RestrictedPython 沙箱后端")
    return RestrictedPythonBackend(
        timeout=settings.SANDBOX_TIMEOUT,
    )
