"""
技能系统模块，负责技能注册、加载、校验、执行或适配外部能力。

当 Agent 需要调用外部能力时，通常会经过这一层完成查找、验证与执行。
每种工具类型（code_executor、file_operation、shell、api_call、llm）
都有独立的执行路径和安全校验。
"""

import os
import re
import ast
import shlex
import subprocess
import threading
import queue
import time
from pathlib import Path
from typing import Dict, List, Optional, Any, NamedTuple
from loguru import logger


# ---------------------------------------------------------------------------
# 安全常量
# ---------------------------------------------------------------------------

# Shell 命令白名单（仅保留低风险命令，移除 rm/chmod/chown/xargs 等高危命令）
_ALLOWED_SHELL_COMMANDS = frozenset([
    'ls', 'cat', 'grep', 'find', 'echo', 'pwd',
    'head', 'tail', 'sort', 'uniq', 'wc', 'cut', 'tr', 'tee',
    'mkdir', 'cp', 'mv',
    'tar', 'gzip', 'gunzip', 'zip', 'unzip',
])

# 危险参数模式（防止参数级注入）
_DANGEROUS_ARG_PATTERNS = [
    re.compile(r'\.\.[\\/]'),          # 路径遍历
    re.compile(r'^[\\/]etc[\\/]'),     # /etc/ 目录
    re.compile(r'^[\\/]root'),         # /root 目录
    re.compile(r'^[\\/]proc'),         # /proc 目录
    re.compile(r'^[\\/]sys'),          # /sys 目录
    re.compile(r'[;&|`]'),             # Shell 特殊字符
    re.compile(r'\$\('),               # 命令替换
]


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
    code: str,
    exec_globals: Dict[str, Any],
    local_vars: Dict[str, Any],
    timeout: float,
) -> None:
    """
    在独立线程中执行代码，并通过 join 实现超时控制。

    注意：线程级超时无法强制中止正在运行的 C 扩展，
    对于更严格的隔离需求应使用进程级沙箱。

    Args:
        code: 已通过安全校验的 Python 代码字符串。
        exec_globals: exec 使用的全局命名空间（已限制 __builtins__）。
        local_vars: exec 使用的局部命名空间，执行结果写入此处。
        timeout: 超时秒数。

    Raises:
        ExecutionTimeoutException: 执行超时。
        Exception: 代码执行过程中抛出的异常。
    """
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
# 代码安全校验器
# ---------------------------------------------------------------------------

class CodeValidator(ast.NodeVisitor):
    """
    基于 AST 的 Python 代码安全校验器。

    通过白名单方式限制允许的 AST 节点类型，
    并拦截危险函数调用和属性访问，防止代码执行逃逸。
    """

    # 允许的 AST 节点类型白名单
    _ALLOWED_NODE_TYPES = frozenset({
        'Module', 'Expr', 'Assign', 'AugAssign', 'AnnAssign',
        'Name', 'Constant', 'Num', 'Str', 'Bytes',
        'List', 'Tuple', 'Dict', 'Set',
        'BinOp', 'UnaryOp', 'Compare', 'BoolOp', 'IfExp',
        'Call', 'Subscript', 'Index',
        'ListComp', 'DictComp', 'SetComp', 'GeneratorExp',
        'For', 'While', 'If',
        'Break', 'Continue', 'Pass', 'Return',
        # 注意：移除 FunctionDef/AsyncFunctionDef 以防止嵌套函数调用危险操作
        # 如业务确实需要，可谨慎地加回并增加嵌套深度限制
        'arguments', 'arg', 'Delete',
        'Slice',
        'Load', 'Store', 'Del',
        'Add', 'Sub', 'Mult', 'Div', 'FloorDiv', 'Mod', 'Pow',
        'LShift', 'RShift', 'BitOr', 'BitXor', 'BitAnd',
        'Eq', 'NotEq', 'Lt', 'LtE', 'Gt', 'GtE', 'Is', 'IsNot', 'In', 'NotIn',
        'And', 'Or', 'Not', 'UAdd', 'USub', 'Invert',
        'comprehension', 'keyword',
    })

    # 明确禁止调用的内置函数
    _FORBIDDEN_BUILTINS = frozenset({
        '__import__', 'eval', 'exec', 'compile',
        'open', 'input', 'breakpoint', 'exit', 'quit',
        'reload', 'memoryview',
        'globals', 'locals', 'vars', 'dir',
        # 移除 getattr/setattr/delattr，防止通过属性访问绕过限制
        'getattr', 'setattr', 'delattr',
    })

    # 安全内置函数白名单
    _SAFE_BUILTINS = frozenset({
        'abs', 'min', 'max', 'sum', 'len', 'range', 'print',
        'str', 'int', 'float', 'bool',
        'list', 'dict', 'set', 'tuple',
        'type', 'isinstance', 'issubclass', 'hasattr',
        'sorted', 'reversed', 'enumerate',
        'zip', 'map', 'filter', 'any', 'all',
        'round', 'pow', 'divmod', 'format',
        'hex', 'oct', 'bin', 'chr', 'ord', 'slice',
    })

    # 危险属性/名称模式（字符串子串匹配）
    _DANGEROUS_PATTERNS = frozenset({
        '__import__', '__builtins__', '__class__', '__subclasses__',
        '__globals__', '__code__', '__closure__', '__func__',
        'subprocess', 'os.', 'sys.', 'socket', 'urllib', 'requests',
        'pickle', 'marshal', 'shelve', 'ctypes',
        'threading', 'multiprocessing', 'concurrent',
        'asyncio', 'getattr', 'setattr', 'delattr',
    })

    def __init__(self) -> None:
        self.errors: List[str] = []
        self.depth = 0
        self.max_depth = 10  # 降低最大嵌套深度

    def visit(self, node: ast.AST) -> None:
        """访问 AST 节点，检查节点类型是否在白名单内。"""
        if self.depth > self.max_depth:
            self.errors.append(f"代码嵌套深度超过限制 ({self.max_depth})")
            return

        node_type = type(node).__name__
        if node_type not in self._ALLOWED_NODE_TYPES:
            self.errors.append(
                f"不支持的代码结构: {node_type} (第 {getattr(node, 'lineno', '?')} 行)"
            )
            return

        self.depth += 1
        super().visit(node)
        self.depth -= 1

    def visit_Call(self, node: ast.Call) -> None:
        """拦截危险函数调用。"""
        if isinstance(node.func, ast.Name):
            func_name = node.func.id
            if func_name in self._FORBIDDEN_BUILTINS:
                self.errors.append(
                    f"禁止调用函数: {func_name!r} (第 {getattr(node, 'lineno', '?')} 行)"
                )
                return
            if func_name not in self._SAFE_BUILTINS:
                self.errors.append(
                    f"不在安全函数列表中: {func_name!r} (第 {getattr(node, 'lineno', '?')} 行)"
                )
                return
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        """拦截危险属性访问。"""
        attr_name = getattr(node, 'attr', '')
        if isinstance(attr_name, str):
            for pattern in self._DANGEROUS_PATTERNS:
                if pattern in attr_name:
                    self.errors.append(
                        f"危险属性访问: {attr_name!r} (第 {getattr(node, 'lineno', '?')} 行)"
                    )
                    return
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        """拦截危险名称引用。"""
        name = getattr(node, 'id', '')
        if isinstance(name, str):
            for pattern in self._DANGEROUS_PATTERNS:
                if pattern in name:
                    self.errors.append(
                        f"危险名称引用: {name!r} (第 {getattr(node, 'lineno', '?')} 行)"
                    )
                    return
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        """拦截对 __builtins__ 等敏感对象的下标访问。"""
        if isinstance(node.value, ast.Name):
            name = getattr(node.value, 'id', '')
            if name in ('__builtins__', '__imports__', '__globals__'):
                self.errors.append(
                    f"禁止访问: {name!r} (第 {getattr(node, 'lineno', '?')} 行)"
                )
                return
        self.generic_visit(node)

    def validate_code(self, code: str) -> tuple[bool, str]:
        """
        对代码字符串进行完整的安全校验。

        Args:
            code: 待校验的 Python 代码字符串。

        Returns:
            (is_safe, error_message) 元组。
            is_safe 为 True 表示代码通过校验；
            error_message 在校验失败时包含具体原因。
        """
        try:
            tree = ast.parse(code, mode='exec')
        except SyntaxError as e:
            return False, f"语法错误: {e}"

        self.errors = []
        self.depth = 0
        self.visit(tree)

        if self.errors:
            return False, "; ".join(self.errors)

        return True, ""


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
        base = Path(base_dir).resolve()
        try:
            resolved.relative_to(base)
        except ValueError:
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
        在受限沙箱内执行 Python 代码。

        代码在执行前经过 AST 静态分析校验，执行时使用受限的
        __builtins__ 命名空间，防止访问危险模块和函数。

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

        # AST 安全校验
        validator = CodeValidator()
        is_safe, error_msg = validator.validate_code(code)
        if not is_safe:
            raise RuntimeError(f"代码安全校验失败: {error_msg}")

        # 构建受限执行环境（不包含 getattr/setattr/delattr）
        safe_builtins: Dict[str, Any] = {
            'abs': abs, 'min': min, 'max': max, 'sum': sum,
            'len': len, 'range': range, 'print': print,
            'str': str, 'int': int, 'float': float, 'bool': bool,
            'list': list, 'dict': dict, 'set': set, 'tuple': tuple,
            'type': type, 'isinstance': isinstance, 'issubclass': issubclass,
            'hasattr': hasattr,
            'sorted': sorted, 'reversed': reversed, 'enumerate': enumerate,
            'zip': zip, 'map': map, 'filter': filter, 'any': any, 'all': all,
            'round': round, 'pow': pow, 'divmod': divmod, 'format': format,
            'hex': hex, 'oct': oct, 'bin': bin, 'chr': chr, 'ord': ord,
            'slice': slice, 'True': True, 'False': False, 'None': None,
        }
        exec_globals: Dict[str, Any] = {'__builtins__': safe_builtins}
        local_vars: Dict[str, Any] = {}

        try:
            execute_with_timeout(code, exec_globals, local_vars, timeout)
            return local_vars.get('result', {'status': 'executed'})
        except ExecutionTimeoutException:
            raise RuntimeError(f"代码执行超时（超过 {timeout} 秒）")
        except SyntaxError as e:
            raise RuntimeError(f"代码语法错误: {e}")
        except Exception as e:
            raise RuntimeError(f"代码执行错误: {e}")

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

        命令必须在 _ALLOWED_SHELL_COMMANDS 白名单内，
        参数中不允许包含危险字符（;、|、& 等），
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

        # 白名单校验
        if executable not in _ALLOWED_SHELL_COMMANDS:
            raise RuntimeError(
                f"命令 '{executable}' 不在允许列表中。"
                f"允许的命令: {', '.join(sorted(_ALLOWED_SHELL_COMMANDS))}"
            )

        # 参数安全校验（防止参数级注入）
        for arg in command_list[1:]:
            for pattern in _DANGEROUS_ARG_PATTERNS:
                if pattern.search(arg):
                    raise RuntimeError(
                        f"命令参数包含不允许的字符或模式: {arg!r}"
                    )

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

        # 无 LLM 客户端时返回占位响应（用于测试）
        logger.warning("No LLM client configured, returning placeholder response")
        return {'response': f"[占位响应] action={action!r}", 'model': model}

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
