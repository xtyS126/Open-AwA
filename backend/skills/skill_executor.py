"""
技能系统模块，负责技能注册、加载、校验、执行或适配外部能力。

当 Agent 需要调用外部能力时，通常会经过这一层完成查找、验证与执行。
每种工具类型（code_executor、file_operation、shell、api_call、llm）
都有独立的执行路径和安全校验。

代码安全校验已迁移至 security.backends.RestrictedPythonBackend（基于 RestrictedPython 的
compile_restricted 进行 AST 级安全编译）。本模块的 execute_with_timeout 仅在 RestrictedPython
已验证并编译字节码后执行，不直接接受用户提供的代码字符串。

命令白名单、危险命令黑名单、危险参数模式等常量已迁移至
security.command_whitelist 模块作为单一真相源，本模块通过 re-export
保持向后兼容（_ALLOWED_SHELL_COMMANDS / _DANGEROUS_ARG_PATTERNS）。
"""

import os
import re
import shlex
import subprocess
import threading
import queue
import time
from pathlib import Path
from typing import Dict, List, Optional, Any, NamedTuple
from loguru import logger

from security.command_whitelist import (
    ALLOWED_COMMANDS,
    DANGEROUS_ARG_PATTERNS,
    is_path_allowed as _is_path_in_workspace,
    validate_command_safety_detailed as _validate_command_safety_detailed,
)


# ---------------------------------------------------------------------------
# 安全常量（向后兼容 re-export，实际定义已迁移至 security.command_whitelist）
# ---------------------------------------------------------------------------

# Shell 命令白名单（与 sandbox.py / command_executor.py 共用同一真相源）
_ALLOWED_SHELL_COMMANDS = ALLOWED_COMMANDS

# 危险参数模式（与 sandbox.py / command_executor.py 共用同一真相源）
_DANGEROUS_ARG_PATTERNS = DANGEROUS_ARG_PATTERNS


# ---------------------------------------------------------------------------
# 异常类型
# ---------------------------------------------------------------------------

class ExecutionTimeoutException(Exception):
    """代码或命令执行超时异常。"""
    pass


class SecurityValidationError(Exception):
    """安全校验失败异常。"""
    pass


# ---------------------------------------------------------------------------
# 线程级代码执行（带超时）
# ---------------------------------------------------------------------------

def execute_with_timeout(
    code: Any,
    exec_globals: Dict[str, Any],
    local_vars: Dict[str, Any],
    timeout: float,
) -> None:
    """
    在独立线程中执行代码，并通过 join 实现超时控制。

    重要：此函数仅在 RestrictedPythonBackend（security/backends.py）通过
    compile_restricted() 成功验证并编译代码为字节码后调用。
    调用方负责确保传入的 code 已经过安全校验——此函数不执行额外验证。

    注意：线程级超时无法强制中止正在运行的 C 扩展，
    对于更严格的隔离需求应使用进程级沙箱。

    Args:
        code: 已通过 RestrictedPython compile_restricted() 安全校验的 Python 代码字符串或预编译的 code object。
        exec_globals: exec 使用的全局命名空间（已限制 __builtins__）。
        local_vars: exec 使用的局部命名空间，执行结果写入此处。
        timeout: 超时秒数。

    Raises:
        ExecutionTimeoutException: 执行超时。
        ValueError: __builtins__ 未正确限制（防御性检查）。
        Exception: 代码执行过程中抛出的异常。
    """
    # 防御性检查：确保 __builtins__ 已正确限制
    _builtins = exec_globals.get("__builtins__", {})
    if isinstance(_builtins, dict):
        _dangerous = {"__import__", "open", "eval", "exec", "compile", "input"}
        _present_dangerous = _dangerous & set(_builtins.keys())
        if _present_dangerous:
            raise ValueError(
                f"沙箱配置错误: exec_globals 包含禁止的内置函数 {_present_dangerous}"
            )
    elif not isinstance(_builtins, dict):
        # 如果 __builtins__ 不是字典（例如是模块对象），说明未正确限制
        raise ValueError("沙箱配置错误: exec_globals 使用了未限制的 __builtins__")

    result_queue: queue.Queue = queue.Queue()
    timeout_event = threading.Event()
    result_lock = threading.Lock()

    def run_code() -> None:
        try:
            exec(code, exec_globals, local_vars)  # noqa: S102
            with result_lock:
                if not timeout_event.is_set():
                    result_queue.put(('success', None))
        except Exception as e:
            with result_lock:
                if not timeout_event.is_set():
                    result_queue.put(('error', e))

    thread = threading.Thread(target=run_code, daemon=True)
    thread.start()
    thread.join(timeout=timeout)

    if thread.is_alive():
        timeout_event.set()
        raise ExecutionTimeoutException(f"代码执行超时（超过 {timeout} 秒）")

    with result_lock:
        try:
            status, error = result_queue.get_nowait()
            if status == 'error':
                raise error
        except queue.Empty:
            # 极端竞态条件下队列可能为空，视为正常完成
            pass


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

class StepResult(NamedTuple):
    """单个执行步骤的结果。"""
    action: str
    tool: str
    result: Any
    success: bool
    error: Optional[str] = None


class ExecutionResult(NamedTuple):
    """技能整体执行结果。"""
    skill_name: str
    steps: List[StepResult]
    success: bool
    outputs: Dict[str, Any]
    error: Optional[str] = None
    execution_time: float = 0.0


# ---------------------------------------------------------------------------
# 路径安全工具函数
# ---------------------------------------------------------------------------

def _validate_file_path(file_path: str, base_dir: Optional[str] = None) -> Path:
    """
    校验文件路径，防止路径遍历攻击。

    Args:
        file_path: 待校验的文件路径。
        base_dir: 允许的根目录，若提供则路径必须在其内部。

    Returns:
        解析后的安全路径。

    Raises:
        SecurityValidationError: 路径不合法。
    """
    if not file_path or not file_path.strip():
        raise SecurityValidationError("文件路径不能为空")

    # 拒绝包含危险模式的路径
    for pattern in _DANGEROUS_ARG_PATTERNS:
        if pattern.search(file_path):
            raise SecurityValidationError(f"文件路径包含不允许的字符或模式: {file_path!r}")

    try:
        resolved = Path(file_path).resolve()
    except (ValueError, OSError) as e:
        raise SecurityValidationError(f"无法解析文件路径: {e}")

    if base_dir:
        # 委托给 command_whitelist.is_path_allowed 进行 Path.resolve() + relative_to() 校验
        # 禁止使用 str.startswith()——可被 ../ 符号链接绕过
        if not _is_path_in_workspace(resolved, Path(base_dir)):
            base = Path(base_dir).resolve()
            raise SecurityValidationError(
                f"文件路径超出允许范围: {resolved!r} 不在 {base!r} 内"
            )

    return resolved


# ---------------------------------------------------------------------------
# SkillExecutor 主类
# ---------------------------------------------------------------------------

class SkillExecutor:
    """
    技能执行器，负责解析技能配置并按步骤执行各类工具动作。

    支持的工具类型：
    - code_executor: 在受限沙箱内执行 Python 代码
    - file_operation: 受路径校验保护的文件读写
    - shell: 白名单限制的 Shell 命令执行
    - api_call: 外部 HTTP API 调用
    - llm: LLM 推理调用
    """

    def __init__(self, work_dir: Optional[str] = None) -> None:
        """
        初始化技能执行器。

        Args:
            work_dir: 文件操作允许的根目录，默认为当前工作目录。
        """
        self.environment_initialized = False
        self.execution_context: Dict[str, Any] = {}
        self.work_dir = Path(work_dir).resolve() if work_dir else Path.cwd()
        logger.info(f"SkillExecutor initialized with work_dir={self.work_dir}")

    async def initialize_environment(self, skill_config: Dict, context: Dict) -> bool:
        """
        初始化技能执行环境，校验必要字段并构建执行上下文。

        Args:
            skill_config: 技能配置字典，必须包含 'name' 和 'steps' 字段。
            context: 来自调用方的共享上下文。

        Returns:
            True 表示初始化成功，False 表示失败。
        """
        try:
            skill_name = skill_config.get('name', 'unknown')
            logger.info(f"Initializing environment for skill: {skill_name!r}")

            required_fields = ['name', 'steps']
            for field in required_fields:
                if field not in skill_config:
                    logger.error(f"Missing required field in skill config: {field!r}")
                    return False

            self.execution_context = {
                'skill_config': skill_config,
                'shared_context': context.copy() if context else {},
                'variables': {},
                'artifacts': {},
            }

            environment_type = skill_config.get('environment', 'default')
            logger.info(f"Environment type: {environment_type!r}")

            self.environment_initialized = True
            logger.info(f"Environment initialized for skill: {skill_name!r}")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize environment: {e}")
            return False

    async def execute_step(self, step: Dict, context: Dict) -> StepResult:
        """
        执行单个技能步骤。

        Args:
            step: 步骤配置字典，包含 action、tool、params 等字段。
            context: 当前执行上下文。

        Returns:
            StepResult 实例，包含执行结果和成功/失败状态。
        """
        action = step.get('action', 'unknown')
        tool = step.get('tool', 'default')
        params = step.get('params', {})

        logger.info(f"Executing step: action={action!r}, tool={tool!r}")

        try:
            if not self.environment_initialized:
                raise RuntimeError("执行环境尚未初始化，请先调用 initialize_environment()")

            merged_context = {**self.execution_context, **context}
            params_with_context = {**params, 'context': merged_context}

            result = await self._execute_tool(tool, action, params_with_context)

            logger.info(f"Step completed: action={action!r}")
            return StepResult(action=action, tool=tool, result=result, success=True)

        except Exception as e:
            logger.error(f"Step failed: action={action!r}, error={e}")
            return StepResult(action=action, tool=tool, result=None, success=False, error=str(e))

    async def _execute_tool(self, tool: str, action: str, params: Dict) -> Any:
        """根据工具类型分发到对应的执行方法。"""
        dispatch: Dict[str, Any] = {
            'code_executor': self._execute_code_action,
            'file_operation': self._execute_file_action,
            'shell': self._execute_shell_action,
            'api_call': self._execute_api_action,
            'llm': self._execute_llm_action,
        }
        handler = dispatch.get(tool, self._execute_default_action)
        return await handler(action, params)

    async def _execute_code_action(self, action: str, params: Dict) -> Any:
        """
        在沙箱后端中执行 Python 代码。

        使用 get_sandbox_backend() 获取当前配置的沙箱后端，
        支持 RestrictedPython（默认）和 E2B（可选）两种后端。

        Args:
            action: 动作名称（用于日志记录）。
            params: 参数字典，包含 code、language、timeout。

        Returns:
            local_vars 中的 'result' 键值，或 {'status': 'executed'}。
        """
        code = params.get('code', '')
        language = params.get('language', 'python')
        timeout = min(float(params.get('timeout', 30)), 60.0)  # 最大超时 60 秒

        logger.info(f"Executing {language!r} code: action={action!r}")

        if language != 'python':
            # 非 Python 语言目前仅记录日志，不实际执行
            logger.warning(f"Unsupported code language: {language!r}, skipping execution")
            return {'status': 'skipped', 'reason': f'不支持的语言: {language}'}

        # 使用统一沙箱后端执行
        from security.backends import get_sandbox_backend
        backend = get_sandbox_backend()
        result = await backend.execute_code(code, timeout=timeout)

        if result.status == 'error':
            raise RuntimeError(f"代码执行失败: {result.error}")
        if result.status == 'timeout':
            raise RuntimeError(f"代码执行超时（超过 {timeout} 秒）")

        return result.result if result.result is not None else {'status': 'executed'}

    async def _execute_file_action(self, action: str, params: Dict) -> Any:
        """
        执行受路径校验保护的文件操作。

        所有路径在操作前经过安全校验，确保文件操作限制在
        允许的工作目录内，防止路径遍历攻击。

        Args:
            action: 操作类型，支持 'read' 和 'write'。
            params: 参数字典，包含 path 和 content（写操作）。

        Returns:
            操作结果字典。
        """
        file_path = params.get('path', '')
        content = params.get('content', '')

        logger.info(f"File operation: action={action!r}, path={file_path!r}")

        # 路径安全校验
        try:
            safe_path = _validate_file_path(file_path, base_dir=str(self.work_dir))
        except SecurityValidationError as e:
            raise RuntimeError(f"文件路径校验失败: {e}")

        if action == 'read':
            try:
                if not safe_path.exists():
                    raise RuntimeError(f"文件不存在: {file_path!r}")
                if not safe_path.is_file():
                    raise RuntimeError(f"路径不是文件: {file_path!r}")
                return {'content': safe_path.read_text(encoding='utf-8')}
            except OSError as e:
                raise RuntimeError(f"文件读取失败: {e}")

        elif action == 'write':
            try:
                safe_path.parent.mkdir(parents=True, exist_ok=True)
                safe_path.write_text(content, encoding='utf-8')
                return {'status': 'written', 'path': str(safe_path)}
            except OSError as e:
                raise RuntimeError(f"文件写入失败: {e}")

        else:
            raise RuntimeError(f"不支持的文件操作类型: {action!r}")

    async def _execute_shell_action(self, action: str, params: Dict) -> Any:
        """
        执行白名单限制的 Shell 命令。

        命令安全校验委托给 security.command_whitelist.validate_command_safety_detailed，
        统一三处（sandbox.py / command_executor.py / skill_executor.py）的安全基线：
        - 危险命令黑名单（rm/sudo/mkfs/dd 等）直接拒绝
        - 必须在 ALLOWED_COMMANDS 白名单内
        - 参数不允许匹配 DANGEROUS_ARG_PATTERNS（路径遍历、Shell 特殊字符等）
        - ACP 硬阻断模式（rm -rf / / sudo rm -rf / / mkfs / dd if=）直接拒绝
        使用 shell=False 模式防止 Shell 注入。

        Args:
            action: 动作名称（用于日志记录）。
            params: 参数字典，包含 command、timeout、cwd 等。

        Returns:
            包含 stdout、stderr、returncode 的字典。
        """
        command = params.get('command', '').strip()
        timeout = min(float(params.get('timeout', 30)), 120.0)  # 最大超时 120 秒

        logger.info(f"Shell action: {action!r}, command={command!r}")

        if not command:
            raise RuntimeError("Shell 命令不能为空")

        # 解析命令字符串为列表
        command_list = params.get('command_list', None)
        if command_list is None:
            try:
                command_list = shlex.split(command)
            except ValueError as e:
                raise RuntimeError(f"命令解析失败: {e}")

        if not command_list:
            raise RuntimeError("命令列表解析结果为空")

        executable = command_list[0]

        # 委托给 command_whitelist.validate_command_safety_detailed 进行统一校验
        # 包括：危险命令黑名单 + 白名单 + 参数危险模式 + ACP 硬阻断模式（rm -rf / 等）
        is_safe, err_msg = _validate_command_safety_detailed(
            executable, command_list[1:]
        )
        if not is_safe:
            raise RuntimeError(err_msg or "命令被安全策略拒绝")

        # 校验工作目录
        cwd = params.get('cwd', None)
        if cwd:
            try:
                safe_cwd = _validate_file_path(cwd, base_dir=str(self.work_dir))
                cwd = str(safe_cwd)
            except SecurityValidationError as e:
                raise RuntimeError(f"工作目录校验失败: {e}")

        try:
            result = subprocess.run(
                command_list,
                shell=False,          # 明确禁用 shell 模式，防止 Shell 注入
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
                env=params.get('env', None),
            )

            if result.returncode != 0 and result.stderr:
                logger.warning(
                    f"Shell command exited with code {result.returncode}: {result.stderr[:200]}"
                )

            return {
                'stdout': result.stdout,
                'stderr': result.stderr,
                'returncode': result.returncode,
            }

        except subprocess.TimeoutExpired:
            raise RuntimeError(f"Shell 命令执行超时（超过 {timeout} 秒）")
        except PermissionError as e:
            raise RuntimeError(f"权限不足: {e}")
        except FileNotFoundError:
            raise RuntimeError(f"命令未找到: {executable!r}")
        except Exception as e:
            raise RuntimeError(f"Shell 执行错误: {e}")

    async def _execute_api_action(self, action: str, params: Dict) -> Any:
        """
        执行外部 HTTP API 调用。

        Args:
            action: 动作名称（用于日志记录）。
            params: 参数字典，包含 url、method、headers、data。

        Returns:
            包含 status 和 data 的响应字典。
        """
        import httpx

        url = params.get('url', '')
        method = params.get('method', 'GET').upper()
        headers = params.get('headers', {})
        data = params.get('data', {})

        if not url:
            raise RuntimeError("API 调用的 URL 不能为空")

        logger.info(f"API call: {method} {url!r}")

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                if method == 'GET':
                    response = await client.get(url, headers=headers)
                elif method == 'POST':
                    response = await client.post(url, json=data, headers=headers)
                elif method == 'PUT':
                    response = await client.put(url, json=data, headers=headers)
                elif method == 'DELETE':
                    response = await client.delete(url, headers=headers)
                else:
                    raise RuntimeError(f"不支持的 HTTP 方法: {method!r}")

                content_type = response.headers.get('content-type', '')
                body = response.json() if 'application/json' in content_type else response.text
                return {'status': response.status_code, 'data': body}

        except httpx.TimeoutException:
            raise RuntimeError(f"API 调用超时: {url!r}")
        except httpx.RequestError as e:
            raise RuntimeError(f"API 请求错误: {e}")

    async def _execute_llm_action(self, action: str, params: Dict) -> Any:
        """
        调用 LLM 进行推理。

        Args:
            action: 动作名称（用于日志记录）。
            params: 参数字典，包含 prompt 和 model。

        Returns:
            包含 response 和 model 的字典。
        """
        prompt = params.get('prompt', '')
        model = params.get('model', 'default')

        logger.info(f"LLM action: {action!r}, model={model!r}")

        llm_client = self.execution_context.get('llm_client')
        if llm_client:
            try:
                response = await llm_client.generate(prompt)
                return {'response': response, 'model': model}
            except Exception as e:
                raise RuntimeError(f"LLM 调用错误: {e}")

        # 无 LLM 客户端时直接抛错，避免占位字符串流入业务流程
        logger.warning("No LLM client configured for skill execution")
        raise RuntimeError("LLM client not configured for skill execution")

    async def _execute_default_action(self, action: str, params: Dict) -> Any:
        """
        默认动作处理器，直接返回参数（用于未知工具类型）。

        Args:
            action: 动作名称。
            params: 参数字典。

        Returns:
            包含 action、status、params 的字典。
        """
        logger.info(f"Default action: {action!r}")
        return {'action': action, 'status': 'completed', 'params': params}

    async def execute_skill(
        self,
        skill_name: str,
        inputs: Dict,
        context: Dict,
    ) -> ExecutionResult:
        """
        按配置顺序执行技能的全部步骤。

        Args:
            skill_name: 技能名称，必须与 execution_context 中的配置匹配。
            inputs: 调用方传入的输入参数。
            context: 共享上下文。

        Returns:
            ExecutionResult 实例，包含每步结果和整体执行状态。
        """
        start_time = time.time()
        steps_results: List[StepResult] = []
        outputs: Dict[str, Any] = {}
        error_message: Optional[str] = None

        try:
            logger.info(f"Starting skill execution: {skill_name!r}")

            skill_config = self.execution_context.get('skill_config', {})
            if not skill_config or skill_config.get('name') != skill_name:
                error_message = f"技能 '{skill_name}' 未找到或未初始化"
                logger.error(error_message)
                return ExecutionResult(
                    skill_name=skill_name,
                    steps=[],
                    success=False,
                    outputs={},
                    error=error_message,
                    execution_time=time.time() - start_time,
                )

            if not self.environment_initialized:
                success = await self.initialize_environment(skill_config, context)
                if not success:
                    error_message = "执行环境初始化失败"
                    return ExecutionResult(
                        skill_name=skill_name,
                        steps=[],
                        success=False,
                        outputs={},
                        error=error_message,
                        execution_time=time.time() - start_time,
                    )

            skill_steps = skill_config.get('steps', [])
            continue_on_error = skill_config.get('continue_on_error', False)

            for idx, step in enumerate(skill_steps):
                logger.info(
                    f"Step {idx + 1}/{len(skill_steps)}: {step.get('action', 'unknown')!r}"
                )

                result = await self.execute_step(step, context)
                steps_results.append(result)

                if result.success:
                    outputs[f"step_{idx}_result"] = result.result
                    self.execution_context['variables'][f"step_{idx}"] = result.result
                else:
                    if continue_on_error:
                        logger.warning(f"Step failed, continuing: {result.error}")
                    else:
                        error_message = result.error
                        break

            execution_time = time.time() - start_time
            overall_success = (
                all(s.success for s in steps_results) and error_message is None
            )

            final_outputs = {
                'skill_outputs': outputs,
                'context_variables': self.execution_context.get('variables', {}),
                'artifacts': self.execution_context.get('artifacts', {}),
            }

            logger.info(
                f"Skill {skill_name!r} finished: success={overall_success}, "
                f"time={execution_time:.2f}s"
            )

            return ExecutionResult(
                skill_name=skill_name,
                steps=steps_results,
                success=overall_success,
                outputs=final_outputs,
                error=error_message,
                execution_time=execution_time,
            )

        except Exception as e:
            error_message = str(e)
            logger.error(f"Skill execution error: {error_message}")
            return ExecutionResult(
                skill_name=skill_name,
                steps=steps_results,
                success=False,
                outputs=outputs,
                error=error_message,
                execution_time=time.time() - start_time,
            )

    async def cleanup(self) -> None:
        """
        清理执行环境，关闭所有可关闭的资源并重置状态。
        """
        try:
            logger.info("Starting cleanup")

            if hasattr(self, 'execution_context'):
                for key, value in self.execution_context.items():
                    if hasattr(value, 'close'):
                        try:
                            await value.close()
                        except AttributeError as e:
                            logger.warning(f"Failed to close {key!r}: {e}")
                        except Exception as e:
                            logger.error(f"Unexpected error closing {key!r}: {e}")

            self.execution_context.clear()
            self.environment_initialized = False
            logger.info("Cleanup completed")

        except Exception as e:
            logger.error(f"Cleanup error: {e}")
