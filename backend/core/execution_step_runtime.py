"""ExecutionStepRuntimeMixin 的单一职责实现。"""

from __future__ import annotations

import asyncio
from typing import Any, Dict

from loguru import logger

from core.metrics import record_tool_execution_metric
from memory.experience_manager import ExperienceManager


class ExecutionStepRuntimeMixin:
    """由 ExecutionLayer 组合的内部协作者。"""

    async def execute_step(self, step: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行单个规划步骤：根据 action 类型分发给对应处理函数（read_files/execute_command/llm_* 等）。
        执行前校验参数 Schema，执行后通过幂等键缓存结果防止重复执行。
        """
        action = step.get("action")
        if action is None:
            logger.bind(
                event="execute_step_missing_action",
                module="executor",
                step_keys=list(step.keys()) if isinstance(step, dict) else None,
            ).warning("execute_step 收到 action=None 的步骤，跳过执行")
            return {
                "status": "error",
                "error": "步骤缺少 action 字段",
                "step": step.get("step"),
                "action": None,
            }
        logger.info(f"Executing step: {action}")
        idempotency_key = self._build_tool_idempotency_key(step, context)
        cached_result = self._get_cached_tool_result(idempotency_key)
        if cached_result is not None:
            cached_result["idempotency_key"] = idempotency_key
            record_tool_execution_metric(str(action or "unknown"), "replayed")
            logger.bind(
                event="tool_cache_hit",
                module="executor",
                action=action,
                idempotency_key=idempotency_key[:16],
            ).debug(f"工具执行命中缓存，跳过重复执行: {action}")
            return cached_result

        # 执行前的参数 Schema 校验
        validation_error = self._validate_step_params(action, step)
        if validation_error:
            logger.bind(
                event="tool_param_validation_failed",
                module="executor",
                action=action,
            ).warning(f"步骤参数校验失败: {validation_error}")
            result = {
                "status": "error",
                "error": validation_error,
                "action": action,
                "step": step.get("step"),
                "idempotency_key": idempotency_key,
            }
            record_tool_execution_metric(str(action or "unknown"), "validation_error")
            return result

        try:
            if action == "read_files":
                result = await self._execute_read_files(step)
            elif action == "execute_command":
                result = await self._execute_command(step)
            elif action == "llm_generate":
                result = await self._execute_llm(step, context)
            elif action == "llm_query":
                result = await self._execute_llm_query(step, context)
            elif action == "llm_explain":
                result = await self._execute_llm_explain(step, context)
            elif action == "llm_chat":
                result = await self._execute_llm_chat(step, context)
            else:
                result = {"status": "error", "message": f"Unknown action: {action}"}

            result["step"] = step.get("step")
            result["action"] = action
            result["idempotency_key"] = idempotency_key
            self._cache_tool_result(idempotency_key, result)
            record_tool_execution_metric(str(action or "unknown"), str(result.get("status") or "completed"))

            if context.get('relevant_experiences'):
                logger.info(f"Executed step using {len(context['relevant_experiences'])} experiences")

            return result

        except Exception as e:
            logger.bind(
                event="step_execution_error",
                module="executor",
                error_type=type(e).__name__,
                action=action,
            ).opt(exception=True).error(f"步骤执行异常 [{action}]: {e}")
            record_tool_execution_metric(str(action or "unknown"), "error")
            return {
                "status": "error",
                "message": str(e),
                "step": step.get("step"),
                "action": action,
                "idempotency_key": idempotency_key,
            }

    async def _execute_read_files(self, step: Dict[str, Any]) -> Dict[str, Any]:
        """
        读取指定文件列表的内容。包含路径穿越防护：所有文件路径限制在工作区目录内。
        支持 workspace 环境变量 OPENAWA_WORKSPACE 自定义工作区根路径。
        """
        files = step.get("targets", [])
        results = {}

        from pathlib import Path as _Path
        import os as _os
        _workspace = _Path(_os.environ.get("OPENAWA_WORKSPACE", _os.getcwd())).resolve()
        for file_path in files:
            # 路径穿越防护：使用 Path.resolve() + relative_to() 替代 startswith
            # startswith 可被符号链接或 .. 序列绕过，relative_to 是项目硬约束
            try:
                resolved = (_workspace / str(file_path).lstrip("/\\")).resolve()
                # 触发 relative_to 校验，不在工作区内则抛 ValueError
                resolved.relative_to(_workspace)
            except (ValueError, OSError):
                results[file_path] = {
                    "status": "error",
                    "message": "Path traversal denied"
                }
                continue
            try:
                # 将同步文件读取包装到 asyncio.to_thread，
                # 避免在异步协程中阻塞事件循环。
                def _read_file(path: str) -> str:
                    with open(path, 'r', encoding='utf-8') as _f:
                        return _f.read()
                content = await asyncio.to_thread(_read_file, resolved)
                results[file_path] = {
                    "status": "success",
                    "content": content
                }
            except FileNotFoundError:
                results[file_path] = {
                    "status": "error",
                    "message": f"File not found: {file_path}"
                }
            except Exception as e:
                results[file_path] = {
                    "status": "error",
                    "message": str(e)
                }

        return {
            "status": "completed",
            "results": results
        }

    async def _execute_command(self, step: Dict[str, Any]) -> Dict[str, Any]:
        """
        在沙箱中异步执行 Shell 命令。包含三层安全防护：
        命令长度限制（512 字符）、security.sandbox 白名单校验、30 秒超时自动终止。
        """
        command = step.get("command", "")

        # 命令长度限制，防止超长命令被注入
        if len(command) > 512:
            return {
                "status": "error",
                "message": f"Command too long: {len(command)} characters (max 512)"
            }

        import shlex
        proc = None

        async def _terminate_process() -> None:
            """终止子进程并限制等待时长，避免清理路径本身无限阻塞。"""
            if proc is None or proc.returncode is not None:
                return
            try:
                proc.kill()
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.bind(
                    module="executor",
                    event="process_kill_wait_timeout",
                    pid=proc.pid,
                ).error("子进程终止后未在限定时间内退出")
            except Exception as exc:
                logger.bind(
                    module="executor",
                    event="process_kill_error",
                    pid=proc.pid,
                    error_type=type(exc).__name__,
                ).warning("子进程清理失败")

        try:
            args = shlex.split(command)
            if not args:
                return {
                    "status": "error",
                    "message": "Empty command"
                }

            # 使用白名单校验可执行文件，防止任意命令执行
            from security.sandbox import validate_command_safety
            is_safe, err_msg = validate_command_safety(args[0], args[1:] if len(args) > 1 else [])
            if not is_safe:
                return {
                    "status": "error",
                    "message": err_msg or "Command rejected by security policy"
                }

            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            timeout_seconds = step.get("timeout_seconds", step.get("timeout", 30))
            try:
                timeout_seconds = float(timeout_seconds)
            except (TypeError, ValueError):
                timeout_seconds = 30.0
            timeout_seconds = min(max(timeout_seconds, 1.0), 300.0)

            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout_seconds,
            )

            return {
                "status": "completed",
                "returncode": proc.returncode,
                "stdout": stdout.decode("utf-8", errors="replace") if stdout else "",
                "stderr": stderr.decode("utf-8", errors="replace") if stderr else ""
            }
        except asyncio.TimeoutError:
            await _terminate_process()
            return {
                "status": "error",
                "message": "Command execution timeout"
            }
        except Exception as e:
            await _terminate_process()
            return {
                "status": "error",
                "message": str(e)
            }

    async def _execute_llm(self, step: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """
        通过 LLM 生成内容（llm_generate 动作的处理函数）。
        调用 _call_llm_api 发起非流式请求，返回结果标记 requires_confirmation 用于人工审核。
        """
        prompt = self._resolve_step_param(step, "prompt", "task") or ""
        result = await self._call_llm_api(prompt, context)
        if not result.get("ok"):
            return {
                "status": "error",
                "message": result["error"]["message"],
                "error": result["error"]
            }

        return {
            "status": "completed",
            "response": result["response"],
            "provider": result.get("provider"),
            "model": result.get("model"),
            "requires_confirmation": True
        }

    async def _execute_llm_query(self, step: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """
        通过 LLM 执行查询（llm_query 动作的处理函数）。
        与 _execute_llm 的区别：不标记 requires_confirmation，适用于只读查询场景。
        """
        prompt = self._resolve_step_param(step, "prompt", "query") or ""
        result = await self._call_llm_api(prompt, context)
        if not result.get("ok"):
            return {
                "status": "error",
                "message": result["error"]["message"],
                "error": result["error"]
            }

        return {
            "status": "completed",
            "response": result["response"],
            "provider": result.get("provider"),
            "model": result.get("model")
        }

    async def _execute_llm_explain(self, step: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """
        通过 LLM 解释内容（llm_explain 动作的处理函数）。
        支持 target 参数作为备选输入源，自动构造 "Explain: {target}" 提示词。
        """
        prompt = self._resolve_step_param(step, "prompt")
        if prompt is None or prompt == "":
            target = self._resolve_step_param(step, "target") or ""
            prompt = f"Explain: {target}" if target else ""
        result = await self._call_llm_api(prompt, context)
        if not result.get("ok"):
            return {
                "status": "error",
                "message": result["error"]["message"],
                "error": result["error"]
            }

        return {
            "status": "completed",
            "response": result["response"],
            "provider": result.get("provider"),
            "model": result.get("model")
        }

    async def _execute_llm_chat(self, step: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """
        通过 LLM 进行自由对话（llm_chat 动作的处理函数）。
        与 _execute_llm 的区别：不需要人工确认，适用于对话式交互场景。
        """
        message = step.get("message", "")
        result = await self._call_llm_api(message, context)
        if not result.get("ok"):
            return {
                "status": "error",
                "message": result["error"]["message"],
                "error": result["error"]
            }

        output = {
            "status": "completed",
            "response": result["response"],
            "provider": result.get("provider"),
            "model": result.get("model"),
        }
        # 传递推理内容（如果存在）
        if result.get("reasoning_content"):
            output["reasoning_content"] = result["reasoning_content"]
        return output

    async def retry_step(self, step: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """使用指数退避策略重试失败的执行步骤。"""
        from core.retry import RetryPolicy, execute_with_retry

        policy = RetryPolicy(max_attempts=3)
        # 仅对瞬态 I/O 故障重试；业务校验、权限错误和编程错误必须立即向上返回。
        retryable_exceptions = (TimeoutError, ConnectionError, OSError)
        result = await execute_with_retry(
            self.execute_step,
            step,
            context,
            policy=policy,
            retryable_exceptions=retryable_exceptions,
        )

        if result.success:
            return result.result

        return {
            "status": "failed",
            "response": f"重试 {result.attempts} 次后仍然失败: {result.last_error}",
            "error": str(result.last_error),
        }

    async def record_experience_feedback(
        self,
        experience_id: int,
        success: bool
    ) -> None:
        """
        更新经验条目的质量评分：根据执行成功/失败反馈调整经验的 success_metrics 置信度。
        ExperienceManager 内部通过 asyncio.to_thread 使用独立会话，无需外部传入 db。
        """
        try:
            manager = ExperienceManager(db=None)
            await manager.update_experience_quality(
                experience_id=experience_id,
                success=success
            )
        except Exception as e:
            logger.opt(exception=True).error(f"记录经验反馈失败: {e}")
