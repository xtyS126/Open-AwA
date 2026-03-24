from typing import Dict, List, Optional, Any, NamedTuple
from loguru import logger
import time
import ast
import threading
import queue


class ExecutionTimeoutException(Exception):
    pass


def execute_with_timeout(code, exec_globals, local_vars, timeout):
    """
    使用线程执行代码并设置超时
    
    使用threading.Event和threading.Lock实现可靠的超时机制，避免竞态条件
    """
    result_queue = queue.Queue()
    timeout_event = threading.Event()
    result_lock = threading.Lock()
    
    def run_code():
        try:
            exec(code, exec_globals, local_vars)
            with result_lock:
                if not timeout_event.is_set():
                    result_queue.put(('success', None))
        except Exception as e:
            with result_lock:
                if not timeout_event.is_set():
                    result_queue.put(('error', e))
    
    thread = threading.Thread(target=run_code)
    thread.daemon = True
    thread.start()
    
    thread.join(timeout=timeout)
    
    if thread.is_alive():
        timeout_event.set()
        raise ExecutionTimeoutException(f"Execution exceeded {timeout} seconds")
    
    with result_lock:
        if not result_queue.empty():
            try:
                status, error = result_queue.get_nowait()
                if status == 'error':
                    raise error
            except queue.Empty:
                # 队列在此期间变空，可能是由于竞态条件
                pass


class CodeValidator(ast.NodeVisitor):
    """
    AST节点访问器，用于验证Python代码安全性
    只允许安全的数学运算、列表、字典、元组等基本操作
    """
    
    def __init__(self):
        self.allowed_node_types = {
            'Module', 'Expr', 'Assign', 'AugAssign', 'AnnAssign',
            'Name', 'Constant', 'Num', 'Str', 'Bytes', 'List', 'Tuple', 'Dict', 'Set',
            'BinOp', 'UnaryOp', 'Compare', 'BoolOp', 'IfExp',
            'Call', 'Subscript', 'Index',
            'ListComp', 'DictComp', 'SetComp', 'GeneratorExp',
            'For', 'While', 'If',
            'Break', 'Continue', 'Pass', 'Return',
            'FunctionDef', 'AsyncFunctionDef', 'Lambda',
            'arguments', 'arg', 'Return', 'Delete',
            'Slice', 'ExtSlice',
            'Load', 'Store', 'Del',
            'Add', 'Sub', 'Mult', 'Div', 'FloorDiv', 'Mod', 'Pow', 'LShift', 'RShift', 'BitOr', 'BitXor', 'BitAnd',
            'Eq', 'NotEq', 'Lt', 'LtE', 'Gt', 'GtE', 'Is', 'IsNot', 'In', 'NotIn',
            'And', 'Or', 'Not', 'UAdd', 'USub', 'Invert',
            'comprehension', 'keyword'
        }
        
        self.dangerous_patterns = [
            'import', 'Import', 'ImportFrom',
            '__import__', 'getattr', 'setattr', 'delattr',
            'open', 'file', 'input', 'exec', 'eval', 'compile',
            'globals', 'locals', 'vars', 'dir', 'help',
            'breakpoint', 'reload', ' memory',
            '__builtins__', '__class__', '__subclasses__',
            '__globals__', '__code__', '__closure__', '__func__',
            'subprocess', 'os.', 'sys.', 'socket', 'urllib', 'requests',
            'http', 'ftplib', 'telnetlib', 'smtplib', 'poplib',
            'pickle', 'marshal', 'shelve', 'anydbm', 'dbm',
            'ctypes', 'threading', 'multiprocessing', 'concurrent',
            'asyncio', 'await',
            'property', 'classmethod', 'staticmethod',
            'lambda', 'lambda:',
        ]
        
        self.errors = []
        self.depth = 0
        self.max_depth = 20
    
    def visit(self, node):
        if self.depth > self.max_depth:
            self.errors.append(f"代码嵌套深度超过限制: {self.max_depth}")
            return
        
        node_type = type(node).__name__
        
        if node_type not in self.allowed_node_types:
            self.errors.append(f"不支持的代码元素: {node_type} at line {getattr(node, 'lineno', '?')}")
            return
        
        self.depth += 1
        super().visit(node)
        self.depth -= 1
    
    def visit_Call(self, node):
        if isinstance(node.func, ast.Name):
            func_name = node.func.id
            if func_name in ['__import__', 'eval', 'exec', 'compile', 'open', 'input', 'breakpoint', 'reload', 'memory', 'exit', 'quit']:
                self.errors.append(f"危险函数调用: {func_name} at line {getattr(node, 'lineno', '?')}")
                return
            
            if func_name in dir(__builtins__) if isinstance(dir(__builtins__), list) else True:
                if not any(safe in func_name for safe in ['abs', 'min', 'max', 'sum', 'len', 'range', 'print', 'str', 'int', 'float', 'bool', 'list', 'dict', 'set', 'tuple', 'type', 'isinstance', 'issubclass', 'hasattr', 'getattr', 'setattr', 'delattr', 'sorted', 'reversed', 'enumerate', 'zip', 'map', 'filter', 'any', 'all', 'round', 'pow', 'divmod', 'format', 'hex', 'oct', 'bin', 'chr', 'ord', 'slice']):
                    self.errors.append(f"不允许的函数调用: {func_name} at line {getattr(node, 'lineno', '?')}")
                    return
        
        self.generic_visit(node)
    
    def visit_Attribute(self, node):
        attr_name = node.attr if hasattr(node, 'attr') else ''
        if isinstance(attr_name, str):
            for pattern in self.dangerous_patterns:
                if pattern in attr_name:
                    self.errors.append(f"危险的属性访问: {attr_name} at line {getattr(node, 'lineno', '?')}")
                    return
        
        self.generic_visit(node)
    
    def visit_Name(self, node):
        name = node.id if hasattr(node, 'id') else ''
        if isinstance(name, str):
            for pattern in self.dangerous_patterns:
                if pattern in name:
                    self.errors.append(f"危险的名称: {name} at line {getattr(node, 'lineno', '?')}")
                    return
        
        self.generic_visit(node)
    
    def visit_Subscript(self, node):
        if isinstance(node.value, ast.Name):
            name = node.value.id if hasattr(node.value, 'id') else ''
            if name in ['__builtins__', '__imports__']:
                self.errors.append(f"不允许访问: {name} at line {getattr(node, 'lineno', '?')}")
                return
        
        self.generic_visit(node)
    
    def validate_code(self, code: str) -> tuple[bool, str]:
        """
        验证代码安全性
        返回: (是否安全, 错误信息)
        """
        try:
            tree = ast.parse(code, mode='exec')
        except SyntaxError as e:
            return False, f"语法错误: {e}"
        
        self.errors = []
        self.visit(tree)
        
        if self.errors:
            return False, "; ".join(self.errors)
        
        return True, ""


class StepResult(NamedTuple):
    action: str
    tool: str
    result: Any
    success: bool
    error: Optional[str] = None


class ExecutionResult(NamedTuple):
    skill_name: str
    steps: List[StepResult]
    success: bool
    outputs: Dict[str, Any]
    error: Optional[str] = None
    execution_time: float = 0.0


class SkillExecutor:
    def __init__(self):
        self.environment_initialized = False
        self.execution_context: Dict[str, Any] = {}
        logger.info("SkillExecutor initialized")

    async def initialize_environment(self, skill_config: Dict, context: Dict) -> bool:
        try:
            logger.info(f"Initializing environment for skill config: {skill_config.get('name', 'unknown')}")

            required_fields = ['name', 'steps']
            for field in required_fields:
                if field not in skill_config:
                    logger.error(f"Missing required field in skill config: {field}")
                    return False

            self.execution_context = {
                'skill_config': skill_config,
                'shared_context': context.copy() if context else {},
                'variables': {},
                'artifacts': {}
            }

            environment_type = skill_config.get('environment', 'default')
            logger.info(f"Setting up {environment_type} environment")

            self.environment_initialized = True
            logger.info("Environment initialization completed successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize environment: {e}")
            return False

    async def execute_step(self, step: Dict, context: Dict) -> StepResult:
        try:
            action = step.get('action', 'unknown')
            tool = step.get('tool', 'default')
            params = step.get('params', {})

            logger.info(f"Executing step: {action} with tool: {tool}")

            if not self.environment_initialized:
                raise RuntimeError("Environment not initialized")

            merged_context = {**self.execution_context, **context}
            params_with_context = {**params, 'context': merged_context}

            result = await self._execute_tool(tool, action, params_with_context)

            logger.info(f"Step {action} completed successfully")
            return StepResult(
                action=action,
                tool=tool,
                result=result,
                success=True,
                error=None
            )

        except Exception as e:
            logger.error(f"Step execution failed: {e}")
            return StepResult(
                action=step.get('action', 'unknown'),
                tool=step.get('tool', 'default'),
                result=None,
                success=False,
                error=str(e)
            )

    async def _execute_tool(self, tool: str, action: str, params: Dict) -> Any:
        if tool == 'code_executor':
            return await self._execute_code_action(action, params)
        elif tool == 'file_operation':
            return await self._execute_file_action(action, params)
        elif tool == 'shell':
            return await self._execute_shell_action(action, params)
        elif tool == 'api_call':
            return await self._execute_api_action(action, params)
        elif tool == 'llm':
            return await self._execute_llm_action(action, params)
        else:
            return await self._execute_default_action(action, params)

    async def _execute_code_action(self, action: str, params: Dict) -> Any:
        code = params.get('code', '')
        language = params.get('language', 'python')
        timeout = params.get('timeout', 30)

        logger.info(f"Executing {language} code: {action}")

        if language == 'python':
            validator = CodeValidator()
            is_safe, error_msg = validator.validate_code(code)
            
            if not is_safe:
                raise RuntimeError(f"代码安全验证失败: {error_msg}")
            
            try:
                local_vars: dict[str, Any] = {}
                exec_globals = {
                    '__builtins__': {
                        'abs': abs, 'min': min, 'max': max, 'sum': sum,
                        'len': len, 'range': range, 'print': print,
                        'str': str, 'int': int, 'float': float, 'bool': bool,
                        'list': list, 'dict': dict, 'set': set, 'tuple': tuple,
                        'type': type, 'isinstance': isinstance, 'issubclass': issubclass,
                        'hasattr': hasattr, 'getattr': getattr, 'setattr': setattr, 'delattr': delattr,
                        'sorted': sorted, 'reversed': reversed, 'enumerate': enumerate,
                        'zip': zip, 'map': map, 'filter': filter, 'any': any, 'all': all,
                        'round': round, 'pow': pow, 'divmod': divmod, 'format': format,
                        'hex': hex, 'oct': oct, 'bin': bin, 'chr': chr, 'ord': ord,
                        'slice': slice, 'True': True, 'False': False, 'None': None
                    }
                }
                
                execute_with_timeout(code, exec_globals, local_vars, timeout)
                
                return local_vars.get('result', {'status': 'executed'})
                
            except ExecutionTimeoutException:
                raise RuntimeError(f"代码执行超时（超过{timeout}秒）")
            except SyntaxError as e:
                raise RuntimeError(f"代码语法错误: {e}")
            except Exception as e:
                raise RuntimeError(f"代码执行错误: {e}")

        return {'status': 'executed', 'action': action}

    async def _execute_file_action(self, action: str, params: Dict) -> Any:
        file_path = params.get('path', '')
        content = params.get('content', '')

        logger.info(f"File operation: {action} on {file_path}")

        if action == 'read':
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    return {'content': f.read()}
            except Exception as e:
                raise RuntimeError(f"Failed to read file: {e}")

        elif action == 'write':
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                return {'status': 'written', 'path': file_path}
            except Exception as e:
                raise RuntimeError(f"Failed to write file: {e}")

        return {'status': 'completed', 'action': action}

    async def _execute_shell_action(self, action: str, params: Dict) -> Any:
        import subprocess
        import shlex

        command = params.get('command', '')
        timeout = params.get('timeout', 30)
        
        logger.info(f"Executing shell command: {command}")

        if not command:
            raise RuntimeError("Shell命令不能为空")

        command_list = params.get('command_list', None)
        
        if command_list is None:
            try:
                command_list = shlex.split(command)
            except ValueError as e:
                raise RuntimeError(f"命令解析失败: {e}")

        if not command_list or len(command_list) == 0:
            raise RuntimeError("命令列表为空")

        allowed_commands = ['ls', 'cat', 'grep', 'find', 'echo', 'pwd', 'mkdir', 'cp', 'mv', 'rm', 'chmod', 'chown', 'tar', 'gzip', 'gunzip', 'zip', 'unzip', 'head', 'tail', 'sort', 'uniq', 'wc', 'awk', 'sed', 'cut', 'tr', 'tee', 'xargs']
        
        if command_list[0] not in allowed_commands:
            raise RuntimeError(f"不允许的命令: {command_list[0]}。允许的命令: {', '.join(allowed_commands)}")
        
        try:
            result = subprocess.run(
                command_list,
                shell=False,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=params.get('cwd', None),
                env=params.get('env', None)
            )

            if result.returncode != 0 and result.stderr:
                logger.warning(f"Shell command returned non-zero: {result.returncode}, stderr: {result.stderr}")

            return {
                'stdout': result.stdout,
                'stderr': result.stderr,
                'returncode': result.returncode
            }
            
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"Shell命令执行超时（超过{timeout}秒）")
        except PermissionError as e:
            raise RuntimeError(f"权限不足: {e}")
        except FileNotFoundError as e:
            raise RuntimeError(f"命令未找到: {e}")
        except Exception as e:
            raise RuntimeError(f"Shell执行错误: {e}")

    async def _execute_api_action(self, action: str, params: Dict) -> Any:
        import httpx

        url = params.get('url', '')
        method = params.get('method', 'GET')
        headers = params.get('headers', {})
        data = params.get('data', {})

        logger.info(f"Making API call: {method} {url}")

        try:
            async with httpx.AsyncClient() as client:
                if method.upper() == 'GET':
                    response = await client.get(url, headers=headers)
                    return {
                        'status': response.status_code,
                        'data': response.json() if response.headers.get('content-type') == 'application/json' else response.text
                    }
                elif method.upper() == 'POST':
                    response = await client.post(url, json=data, headers=headers)
                    return {
                        'status': response.status_code,
                        'data': response.json() if response.headers.get('content-type') == 'application/json' else response.text
                    }

        except Exception as e:
            raise RuntimeError(f"API call error: {e}")

    async def _execute_llm_action(self, action: str, params: Dict) -> Any:
        prompt = params.get('prompt', '')
        model = params.get('model', 'default')

        logger.info(f"Executing LLM action: {action} with model {model}")

        llm_client = self.execution_context.get('llm_client')
        if llm_client:
            try:
                response = await llm_client.generate(prompt)
                return {'response': response, 'model': model}
            except Exception as e:
                raise RuntimeError(f"LLM execution error: {e}")

        return {'response': f"LLM placeholder response for: {action}", 'model': model}

    async def _execute_default_action(self, action: str, params: Dict) -> Any:
        logger.info(f"Executing default action: {action}")
        return {
            'action': action,
            'status': 'completed',
            'params': params
        }

    async def execute_skill(self, skill_name: str, inputs: Dict, context: Dict) -> ExecutionResult:
        start_time = time.time()
        steps_results: List[StepResult] = []
        outputs: Dict[str, Any] = {}
        error_message: Optional[str] = None

        try:
            logger.info(f"Starting skill execution: {skill_name}")

            skill_config = self.execution_context.get('skill_config', {})

            if not skill_config or skill_config.get('name') != skill_name:
                error_message = f"Skill '{skill_name}' not found or not initialized"
                logger.error(error_message)
                return ExecutionResult(
                    skill_name=skill_name,
                    steps=[],
                    success=False,
                    outputs={},
                    error=error_message,
                    execution_time=time.time() - start_time
                )

            if not self.environment_initialized:
                success = await self.initialize_environment(skill_config, context)
                if not success:
                    error_message = "Failed to initialize environment"
                    return ExecutionResult(
                        skill_name=skill_name,
                        steps=[],
                        success=False,
                        outputs={},
                        error=error_message,
                        execution_time=time.time() - start_time
                    )

            skill_steps = skill_config.get('steps', [])

            for idx, step in enumerate(skill_steps):
                logger.info(f"Executing step {idx + 1}/{len(skill_steps)}: {step.get('action', 'unknown')}")

                result = await self.execute_step(step, context)
                steps_results.append(result)

                if result.success:
                    outputs[f"step_{idx}_result"] = result.result
                    self.execution_context['variables'][f"step_{idx}"] = result.result
                else:
                    if skill_config.get('continue_on_error', False):
                        logger.warning(f"Step failed but continuing: {result.error}")
                        continue
                    else:
                        error_message = result.error
                        break

            execution_time = time.time() - start_time
            overall_success = all(step.success for step in steps_results) and not error_message

            final_outputs = {
                'skill_outputs': outputs,
                'context_variables': self.execution_context.get('variables', {}),
                'artifacts': self.execution_context.get('artifacts', {})
            }

            logger.info(f"Skill {skill_name} completed with success={overall_success} in {execution_time:.2f}s")

            return ExecutionResult(
                skill_name=skill_name,
                steps=steps_results,
                success=overall_success,
                outputs=final_outputs,
                error=error_message,
                execution_time=execution_time
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
                execution_time=time.time() - start_time
            )

    async def cleanup(self):
        try:
            logger.info("Starting cleanup process")

            if hasattr(self, 'execution_context'):
                for key, value in self.execution_context.items():
                    if hasattr(value, 'close'):
                        try:
                            await value.close()
                        except AttributeError as e:
                            logger.warning(f"Failed to close {key}: {str(e)}")
                        except Exception as e:
                            logger.error(f"Unexpected error closing {key}: {str(e)}")

            self.execution_context.clear()
            self.environment_initialized = False

            logger.info("Cleanup completed successfully")

        except Exception as e:
            logger.error(f"Cleanup error: {e}")
