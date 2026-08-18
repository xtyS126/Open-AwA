"""ExecutionStepRuntimeMixin 的单一职责实现。"""

from __future__ import annotations

import json
from typing import Any, Dict

from loguru import logger

from core.metrics import record_tool_execution_metric
from memory.experience_manager import ExperienceManager


# 步骤级 action -> 内置工具名 映射。
# 历史计划中 read_files/execute_command 是独立的步骤动作，现在统一收敛到
# builtin_read_file / builtin_run_command 的工具策略分发入口，消除执行层的重复实现。
_STEP_ACTION_TOOL_MAP: Dict[str, str] = {
    "read_files": "builtin_read_file",
    "execute_command": "builtin_run_command",
}


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
            if action in _STEP_ACTION_TOOL_MAP:
                # 工具类动作统一委托到工具策略分发入口，不再为每个动作硬编码独立实现
                result = await self._execute_step_tool_action(action, step, context)
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

    async def _execute_step_tool_action(
        self,
        action: str,
        step: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        工具类步骤动作（read_files/execute_command）的统一委托入口。

        历史计划中这两个动作各自实现了文件读取与命令执行的逻辑，与
        builtin_read_file / builtin_run_command 的工具策略重复。此处统一构造
        工具调用并委托到 _execute_tool_call 的策略分发，保留步骤级返回契约。
        """
        if action == "read_files":
            return await self._execute_read_files_via_tool(step, context)
        if action == "execute_command":
            return await self._execute_command_via_tool(step, context)
        return {"status": "error", "message": f"Unknown action: {action}"}

    async def _execute_read_files_via_tool(
        self,
        step: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        读取文件列表：复用 builtin_read_file 策略逐文件读取。

        保留历史返回契约 {"status": "completed", "results": {path: {...}}}。
        路径穿越防护由 builtin_read_file 内部的 FileManagerSkill.is_path_safe 承担
        （realpath + relative_to/commonpath 白名单校验，等价于原工作区边界约束）。
        """
        files = self._resolve_step_param(step, "files", "targets") or []
        if isinstance(files, str):
            files = [files]
        if not isinstance(files, (list, tuple)):
            return {
                "status": "error",
                "message": f"参数 'files' 应为列表类型，实际为 {type(files).__name__}",
            }

        results: Dict[str, Any] = {}
        for file_path in files:
            tool_call = {
                "id": "",
                "type": "function",
                "function": {
                    "name": "builtin_read_file",
                    "arguments": json.dumps({"path": file_path}, ensure_ascii=False),
                },
            }
            tool_result = await self._execute_tool_call(tool_call, context)
            if tool_result.get("ok"):
                inner = tool_result.get("result") or {}
                if isinstance(inner, dict) and inner.get("success"):
                    results[file_path] = {
                        "status": "success",
                        "content": inner.get("content"),
                    }
                else:
                    results[file_path] = {
                        "status": "error",
                        "message": (inner if isinstance(inner, dict) else {}).get("error") or "读取失败",
                    }
            else:
                results[file_path] = {
                    "status": "error",
                    "message": tool_result.get("error") or "读取失败",
                }

        return {"status": "completed", "results": results}

    async def _execute_command_via_tool(
        self,
        step: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        执行 Shell 命令：复用 builtin_run_command 策略执行。

        安全语义保持不变：命令长度限制（512 字符）与统一命令安全判定
        （validate_command_for_execution，含系统级硬阻断 + 验证器流水线 + 白名单）
        仍作为步骤级前置门禁；底层命令执行委托给 builtin_run_command。
        保留历史返回契约 {"status": "completed", "returncode", "stdout", "stderr"}。
        """
        command = str(step.get("command", "") or "")

        # 命令长度限制，防止超长命令被注入
        if len(command) > 512:
            return {
                "status": "error",
                "message": f"Command too long: {len(command)} characters (max 512)"
            }

        # 命令安全统一到 security.command_validators.validate_command_for_execution：
        # 系统级硬阻断 + 验证器流水线 + 终端黑名单 + 白名单（require_allowlist=True）。
        from security.command_validators import validate_command_for_execution
        is_safe, err_msg = validate_command_for_execution(command, require_allowlist=True)
        if not is_safe:
            return {
                "status": "error",
                "message": err_msg or "Command rejected by security policy"
            }

        timeout_seconds = step.get("timeout_seconds", step.get("timeout", 30))
        try:
            timeout_seconds = float(timeout_seconds)
        except (TypeError, ValueError):
            timeout_seconds = 30.0
        timeout_seconds = min(max(timeout_seconds, 1.0), 300.0)

        tool_call = {
            "id": "",
            "type": "function",
            "function": {
                "name": "builtin_run_command",
                "arguments": json.dumps(
                    {"command": command, "timeout": timeout_seconds},
                    ensure_ascii=False,
                ),
            },
        }
        tool_result = await self._execute_tool_call(tool_call, context)
        if tool_result.get("ok"):
            inner = tool_result.get("result") or {}
            if not isinstance(inner, dict):
                return {"status": "error", "message": "命令执行返回异常结果"}
            return {
                "status": "completed",
                "returncode": inner.get("exit_code"),
                "stdout": inner.get("stdout", ""),
                "stderr": inner.get("stderr", ""),
            }
        return {"status": "error", "message": tool_result.get("error") or "命令执行失败"}

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
