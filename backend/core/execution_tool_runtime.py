"""ExecutionToolRuntimeMixin 的单一职责实现。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from loguru import logger

from core.execution_support import MAX_TOOL_RESULT_CHARS, _handle_audit_task_result
from core.tool_use_context import ToolUseContext, coerce_tool_context
from mcp.manager import MCPManager


class ExecutionToolRuntimeMixin:
    """由 ExecutionLayer 组合的内部协作者。"""

    @staticmethod
    def build_assistant_tool_call_message(
        content: Optional[str],
        reasoning_content: Optional[str] = None,
        tool_calls: Optional[list[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        构造发回模型的 assistant 工具调用消息。

        某些开启思考模式的模型在 tool call 之后继续续写时，
        要求把上一轮 assistant 的 `reasoning_content` 原样回传。
        """
        if tool_calls is not None and not isinstance(tool_calls, list):
            raise ValueError("tool_calls must be a list")

        if reasoning_content is not None and not isinstance(reasoning_content, str):
            reasoning_content = str(reasoning_content)

        assistant_message: Dict[str, Any] = {
            "role": "assistant",
            "content": content or None,
        }
        if reasoning_content:
            assistant_message["reasoning_content"] = reasoning_content
        if tool_calls:
            assistant_message["tool_calls"] = tool_calls
        return assistant_message

    def _validate_step_params(self, action: str, step: Dict[str, Any]) -> Optional[str]:
        """
        校验步骤参数是否完整有效。
        返回 None 表示通过，返回字符串表示错误信息。
        """
        action_schemas = {
            "read_files": {
                "param_key": "files",
                "param_aliases": (),
                "param_type": list,
                "label": "文件路径列表",
            },
            "execute_command": {
                "param_key": "command",
                "param_aliases": (),
                "param_type": str,
                "label": "命令",
            },
            "llm_generate": {
                "param_key": "prompt",
                "param_aliases": ("task",),
                "param_type": str,
                "label": "提示词",
            },
            "llm_query": {
                "param_key": "prompt",
                "param_aliases": ("query",),
                "param_type": str,
                "label": "查询提示词",
            },
            "llm_explain": {
                "param_key": "prompt",
                "param_aliases": ("target",),
                "param_type": str,
                "label": "解释提示词",
            },
            "llm_chat": {
                "param_key": "message",
                "param_aliases": (),
                "param_type": str,
                "label": "聊天消息",
            },
        }

        schema = action_schemas.get(action)
        if not schema:
            return None

        param_key = schema["param_key"]
        param_value = self._resolve_step_param(
            step,
            param_key,
            *schema.get("param_aliases", ()),
        )

        if param_value is None or param_value == "":
            return f"缺少必填参数 '{param_key}' ({schema['label']})"

        if schema["param_type"] is list and not isinstance(param_value, list):
            return f"参数 '{param_key}' 应为 {schema['param_type'].__name__} 类型，实际为 {type(param_value).__name__}"

        if schema["param_type"] is str and not isinstance(param_value, str):
            return f"参数 '{param_key}' 应为 {schema['param_type'].__name__} 类型，实际为 {type(param_value).__name__}"

        return None

    @staticmethod
    def _resolve_step_param(step: Dict[str, Any], *param_keys: str) -> Any:
        """统一从步骤根字段或 parameters 中解析参数，并兼容历史别名。"""
        parameters = step.get("parameters")
        for param_key in param_keys:
            if not param_key:
                continue
            direct_value = step.get(param_key)
            if direct_value is not None and direct_value != "":
                return direct_value
            if isinstance(parameters, dict):
                nested_value = parameters.get(param_key)
                if nested_value is not None and nested_value != "":
                    return nested_value
        return None

    def _build_tool_idempotency_key(self, step: Dict[str, Any], context: Dict[str, Any]) -> str:
        """构建工具执行的幂等键，如果调用方已显式传入幂等键，则优先复用该值。"""

        explicit_key = str(step.get("idempotency_key") or context.get("idempotency_key") or "").strip()
        if explicit_key:
            return explicit_key

        fingerprint_source = {
            "session_id": context.get("session_id"),
            "user_id": context.get("user_id"),
            "action": step.get("action"),
            "step": step,
        }
        serialized = json.dumps(fingerprint_source, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _get_cached_tool_result(self, idempotency_key: str) -> Optional[Dict[str, Any]]:
        """
        读取已缓存的工具执行结果，避免同一幂等键重复触发副作用。
        """

        cached = self._tool_execution_cache.get(idempotency_key)
        if not isinstance(cached, dict):
            return None
        cloned = dict(cached)
        cloned["idempotent_replay"] = True
        return cloned

    def _cache_tool_result(self, idempotency_key: str, result: Dict[str, Any]) -> None:
        """
        缓存工具执行结果，并控制缓存上限，防止内存持续增长。
        使用 OrderedDict 实现 O(1) 的 LRU 淘汰。
        """

        # 若已存在则先移除，重新插入到末尾以标记为最近使用
        if idempotency_key in self._tool_execution_cache:
            self._tool_execution_cache.move_to_end(idempotency_key)
        self._tool_execution_cache[idempotency_key] = dict(result)

        while len(self._tool_execution_cache) > self._max_tool_execution_cache:
            self._tool_execution_cache.popitem(last=False)

    async def _request_user_permission(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        context: Dict[str, Any],
    ) -> str:
        """
        当工具执行因权限不足被拒绝时，通过实时推送队列请求用户授权。
        调用 security 路由的 enqueue_permission_request 将请求推送到前端，
        然后阻塞等待用户回复（once/always/reject）。
        超时后自动返回 "reject"。

        返回:
            str - 用户回复值: "once" / "always" / "reject"
        """
        try:
            from api.routes.security import enqueue_permission_request
        except ImportError:
            logger.bind(
                module="executor",
                event="permission_module_import_failed",
                tool_name=tool_name,
            ).warning("权限请求模块导入失败，默认拒绝")
            return "reject"

        user_id = str(context.get("user_id", ""))
        session_id = str(context.get("session_id", ""))

        if not user_id:
            logger.bind(
                module="executor",
                event="permission_request_no_user",
                tool_name=tool_name,
            ).warning("无法获取用户 ID，默认拒绝权限请求")
            return "reject"

        # 从工具参数中提取资源路径
        resources: list[str] = []
        for key in ("path", "file", "files", "command", "url", "directory"):
            value = tool_args.get(key)
            if isinstance(value, str) and value:
                resources.append(value)
            elif isinstance(value, list):
                resources.extend(str(v) for v in value if v)

        if not resources:
            resources = [tool_name]

        # 构建可持久化的权限规则名
        save_rules: list[str] = []
        # 从工具名推断 action 类型
        if "write" in tool_name or "edit" in tool_name:
            save_rules.append(f"write:{resources[0]}" if resources else "write:*")
        elif "delete" in tool_name:
            save_rules.append(f"delete:{resources[0]}" if resources else "delete:*")
        elif "execute" in tool_name or "bash" in tool_name or "terminal" in tool_name:
            save_rules.append(f"execute:{resources[0]}" if resources else "execute:*")
        elif "read" in tool_name:
            save_rules.append(f"read:{resources[0]}" if resources else "read:*")
        else:
            save_rules.append(f"{tool_name}:*")

        # 推断 action 显示名称
        if "write" in tool_name or "edit" in tool_name:
            action = "write"
        elif "delete" in tool_name:
            action = "delete"
        elif "execute" in tool_name or "bash" in tool_name or "terminal" in tool_name:
            action = "execute"
        elif "read" in tool_name:
            action = "read"
        else:
            action = tool_name

        logger.bind(
            module="executor",
            event="permission_request_sent",
            tool_name=tool_name,
            user_id=user_id,
            session_id=session_id,
            action=action,
            resources=resources,
        ).info(f"权限请求已发送: {tool_name} ({action})")

        # 入队并等待用户回复
        reply_future = enqueue_permission_request(
            user_id=user_id,
            session_id=session_id,
            action=action,
            resources=resources,
            save=save_rules,
            metadata={
                "tool_name": tool_name,
                "tool_args": {
                    k: v for k, v in tool_args.items()
                    if k in ("path", "file", "command", "url", "content")
                },
            },
            agent=context.get("agent_name"),
            timeout=120.0,
        )

        reply = await reply_future
        logger.bind(
            module="executor",
            event="permission_reply_received",
            tool_name=tool_name,
            reply=reply,
        ).info(f"权限请求回复: {tool_name} -> {reply}")
        return reply

    async def _apply_post_tool_use_hooks(
        self,
        result: Dict[str, Any],
        tool_name: str,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        应用 PostToolUse 钩子（hook_manager 系统）。

        处理 MODIFY_OUTPUT 和 PREVENT_CONTINUATION 结果类型：
        - MODIFY_OUTPUT: 使用 hook_updated_output 修改后的输出替换原始结果
        - PREVENT_CONTINUATION: 在结果中设置 prevent_continuation 标志位
        """
        try:
            from core.hook_manager import (
                HookContext as _HookContext,
                HookName as _HookName,
                HookResultType as _HookResultType,
                hook_manager as _hook_manager,
                hook_updated_output as _hook_updated_output,
            )
            _post_results = await _hook_manager.trigger(
                _HookName.TOOL_AFTER_EXECUTE,
                data={
                    "tool_name": tool_name,
                    "result": result,
                    "context": context,
                },
                context=_HookContext(
                    hook_name=_HookName.TOOL_AFTER_EXECUTE.value,
                    session_id=str(context.get("session_id", "") or "") or None,
                    user_id=str(context.get("user_id", "") or "") or None,
                ),
            )
            # 应用 MODIFY_OUTPUT：最后一个非 None 的 modified_output 生效
            result = _hook_updated_output(_post_results, result)
            # 检查 PREVENT_CONTINUATION：设置标志位
            for _post_result in _post_results:
                if _post_result.result_type == _HookResultType.PREVENT_CONTINUATION:
                    if isinstance(result, dict):
                        result["prevent_continuation"] = True
                        if _post_result.reason:
                            result["prevent_continuation_reason"] = _post_result.reason
                    break
        except ImportError:
            logger.warning("[PostToolUse] hook_manager 模块导入失败，跳过 PostToolUse 钩子")
        return result

    def _build_tool_use_context(self, context: Dict[str, Any]) -> ToolUseContext:
        """
        从执行上下文 Dict 构造 ToolUseContext 实例，用于显式依赖注入到工具 execute 函数。

        渐进式迁移：将散乱的 context Dict 中的标识字段、中止控制器、内容替换状态与回调
        集中到 ToolUseContext，工具可通过 coerce_tool_context 适配器获取。

        Args:
            context: 执行上下文 Dict，包含 session_id/user_id/agent_id 等字段

        Returns:
            构造完成的 ToolUseContext 实例
        """
        return ToolUseContext(
            session_id=str(context.get("session_id", "") or ""),
            user_id=str(context.get("user_id", "") or ""),
            agent_id=str(context.get("agent_id", context.get("session_id", "")) or ""),
            abort_controller=context.get("abort_controller"),
            content_replacement_state=context.get("content_replacement_state"),
            record_usage=context.get("record_usage"),
            record_latency=context.get("record_latency"),
            spawn_subagent=context.get("spawn_subagent"),
            metadata={
                k: v for k, v in context.items()
                if k not in {
                    "session_id", "user_id", "agent_id",
                    "abort_controller", "content_replacement_state",
                    "record_usage", "record_latency", "spawn_subagent",
                    "_tool_use_context",
                }
            },
        )

    async def _execute_tool_call(
        self,
        tool_call: Dict[str, Any],
        context: Dict[str, Any],
        on_subagent_event: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
    ) -> Dict[str, Any]:
        """
        执行单个工具调用，根据 function name 分发到对应的处理器。
        """
        _tool_start_time = time.time()
        func_name = tool_call.get("function", {}).get("name", "")
        raw_func_name = func_name
        func_args_str = tool_call.get("function", {}).get("arguments", "{}")

        try:
            func_args = json.loads(func_args_str) if isinstance(func_args_str, str) else func_args_str
        except json.JSONDecodeError:
            return {"ok": False, "error": f"Invalid JSON in tool_call arguments: {func_args_str[:200]}"}

        if not func_name:
            return {"ok": False, "error": "tool_call missing function name"}

        # 构造 ToolUseContext，供工具 execute 函数通过显式依赖注入访问
        # 不直接修改 context，避免污染传入 spawn_agent 等下游调用方的上下文
        _tool_use_context = self._build_tool_use_context(context)

        # 自主模式：四层安全洋葱检查（非阻塞，拒绝即返回）
        try:
            from core.autonomous import get_autonomous_manager
            am = get_autonomous_manager()
            if am and am.is_autonomous:
                # 推断当前 scope
                scope = str(context.get("scope") or context.get("execution_mode") or "chat")
                if am.is_active_for(scope):
                    denial = await am.check_all(func_name, func_args)
                    if denial:
                        # 记录审计日志（fire-and-forget，不阻塞工具拒绝返回）
                        # 添加 done_callback 防止审计证据静默丢失
                        session_id = str(context.get("session_id", "") or "")
                        audit_task = asyncio.create_task(am.record_audit(
                            session_id=session_id,
                            action=func_name,
                            params=func_args,
                            decision="denied",
                            denied_by=denial.get("denied_by", "unknown"),
                            error=denial.get("error"),
                        ))
                        audit_task.add_done_callback(_handle_audit_task_result)
                        return denial
                    # 文件写入/删除操作：自动创建检查点
                    if func_name in ("builtin_write_file", "builtin_delete_file", "write_file", "delete_file"):
                        file_path = str(func_args.get("path") or func_args.get("file") or "")
                        if file_path:
                            cp_id = await am.create_checkpoint(file_path,
                                "delete" if "delete" in func_name else "write")
                            if cp_id:
                                logger.debug(f"[自主模式] 文件操作前检查点已创建: {cp_id}")
                    # 记录允许执行的审计日志（fire-and-forget，不阻塞工具执行）
                    # 添加 done_callback 防止审计证据静默丢失
                    session_id = str(context.get("session_id", "") or "")
                    audit_task = asyncio.create_task(am.record_audit(
                        session_id=session_id,
                        action=func_name,
                        params=func_args,
                        decision="allowed",
                    ))
                    audit_task.add_done_callback(_handle_audit_task_result)
        except ImportError:
            logger.warning("[自主模式] 安全检查模块导入失败，自主模式安全校验已跳过")
        except (TypeError, ValueError, KeyError) as exc:
            # 参数解析异常：安全模块内部数据异常应阻止操作（fail-closed）
            logger.error(f"[自主模式] 安全检查参数异常，拒绝执行: {exc}")
            return {"ok": False, "error": f"安全检查失败: {exc}", "denied_by": "security"}

        # 部分模型会把工具前缀首字母错误大写成 Task_/Plugin_/Builtin_/Mcp_，
        # 这里仅归一化已知前缀，避免破坏后续名称解析。
        if "_" in func_name:
            prefix, remainder = func_name.split("_", 1)
            normalized_prefix = prefix.lower()
            if normalized_prefix in {"plugin", "mcp", "builtin", "task"}:
                func_name = f"{normalized_prefix}_{remainder}"
                if func_name != raw_func_name:
                    logger.bind(
                        module="executor",
                        event="tool_name_prefix_normalized",
                        raw_tool_name=raw_func_name,
                        normalized_tool_name=func_name,
                    ).warning(f"检测到工具名前缀大小写异常，已自动归一化: {raw_func_name} -> {func_name}")

        # PreToolUse 钩子：分发前校验工具调用权限
        try:
            from core.task_runtime.hook_dispatcher import hook_dispatcher, HOOK_PRE_TOOL_USE
            results = await hook_dispatcher.dispatch(HOOK_PRE_TOOL_USE, {
                "tool_name": func_name,
                "tool_args": func_args,
                "context": context,
            })
            deny_result = hook_dispatcher.has_deny(results)
            if deny_result:
                return {"ok": False, "error": deny_result.reason or f"工具调用被阻止: {func_name}",
                        "blocked_by_hook": True}
            # 合并钩子对参数的覆写
            updated_input = hook_dispatcher.get_updated_input(results)
            if updated_input:
                func_args = {**func_args, **updated_input}
        except ImportError:
            logger.warning("[PreToolUse] 钩子调度模块导入失败，工具调用前校验已跳过")

        # PreToolUse 钩子（hook_manager 系统）：支持 APPROVE/DENY/MODIFY_INPUT/REPLACE_RESULT/ERROR
        try:
            from core.hook_manager import (
                HookContext as _HookContext,
                HookName as _HookName,
                HookResultType as _HookResultType,
                hook_manager as _hook_manager,
                hook_updated_input as _hook_updated_input,
            )
            _pre_results = await _hook_manager.trigger(
                _HookName.TOOL_BEFORE_EXECUTE,
                data={
                    "tool_name": func_name,
                    "tool_args": func_args,
                    "context": context,
                },
                context=_HookContext(
                    hook_name=_HookName.TOOL_BEFORE_EXECUTE.value,
                    session_id=str(context.get("session_id", "") or "") or None,
                    user_id=str(context.get("user_id", "") or "") or None,
                ),
            )
            for _pre_result in _pre_results:
                if _pre_result.result_type == _HookResultType.DENY:
                    return {
                        "ok": False,
                        "error": _pre_result.reason or f"工具调用被钩子拒绝: {func_name}",
                        "blocked_by_hook": True,
                        "tool_name": func_name,
                    }
                if _pre_result.result_type == _HookResultType.ERROR:
                    return {
                        "ok": False,
                        "error": _pre_result.error_message or "PreToolUse 钩子执行错误",
                        "blocked_by_hook": True,
                        "tool_name": func_name,
                    }
                if _pre_result.result_type == _HookResultType.REPLACE_RESULT:
                    return {
                        "ok": True,
                        "result": _pre_result.replace_result,
                        "tool_name": func_name,
                        "replaced_by_hook": True,
                    }
            # 合并所有 MODIFY_INPUT 结果到 func_args
            func_args = _hook_updated_input(_pre_results, func_args)
        except ImportError:
            logger.warning("[PreToolUse] hook_manager 模块导入失败，跳过 hook_manager 钩子校验")

        if func_name.startswith("plugin_"):
            remaining = func_name[len("plugin_"):]
            if "__" in remaining:
                plugin_name, plugin_method = remaining.split("__", 1)
            else:
                return {"ok": False, "error": f"plugin tool name missing '__' separator: {func_name}"}
            from plugins import plugin_instance
            try:
                pm = plugin_instance.get()
                candidate_names = []
                for candidate in (
                    plugin_name,
                    plugin_name.replace("_", "-"),
                    plugin_name.replace("-", "_"),
                ):
                    if candidate and candidate not in candidate_names:
                        candidate_names.append(candidate)

                if not any(pm.has_plugin(candidate) for candidate in candidate_names):
                    discovered = pm.discover_plugins()
                    logger.bind(
                        module="executor",
                        event="plugin_metadata_refreshed",
                        requested_plugin=plugin_name,
                        discovered_count=len(discovered) if isinstance(discovered, list) else None,
                    ).debug(f"工具调用前刷新插件元数据: {plugin_name}")

                resolved_plugin_name = next(
                    (
                        candidate
                        for candidate in candidate_names
                        if pm.has_plugin(candidate) or pm.is_plugin_loaded(candidate)
                    ),
                    plugin_name,
                )

                if (
                    resolved_plugin_name not in pm.loaded_plugins
                    and not pm.load_plugin(resolved_plugin_name)
                ):
                    return {"ok": False, "error": f"Failed to load plugin: {resolved_plugin_name}"}
                result = await pm.execute_registered_tool_async(
                    resolved_plugin_name,
                    plugin_method,
                    db=context.get("db"),
                    user_id=context.get("user_id"),
                    **func_args,
                )
                # 检查插件返回结果状态，非成功状态标记为失败
                if isinstance(result, dict) and result.get("status") == "error":
                    return {"ok": False, "error": result.get("message", "Plugin returned error"), "result": result, "tool_name": func_name}
                _plugin_output = {"ok": True, "result": result, "tool_name": func_name}
                return await self._apply_post_tool_use_hooks(_plugin_output, func_name, context)
            except Exception as exc:
                logger.bind(
                    module="executor",
                    event="plugin_execution_error",
                    plugin_name=plugin_name,
                    plugin_method=plugin_method,
                ).error(f"插件执行异常: {exc}")
                return {"ok": False, "error": f"Plugin execution error: {str(exc)}"}

        if func_name.startswith("mcp_"):
            remaining = func_name[len("mcp_"):]
            if "__" in remaining:
                server_id, mcp_tool_name = remaining.split("__", 1)
            else:
                return {"ok": False, "error": f"MCP tool name missing '__' separator: {func_name}"}
            try:
                manager = MCPManager()
                result = await manager.call_tool(server_id, mcp_tool_name, func_args)
                _mcp_output = {"ok": True, "result": result, "tool_name": func_name}
                return await self._apply_post_tool_use_hooks(_mcp_output, func_name, context)
            except Exception as exc:
                logger.bind(
                    module="executor",
                    event="mcp_execution_error",
                    server_id=server_id,
                    tool_name=mcp_tool_name,
                ).error(f"MCP工具执行异常: {exc}")
                return {"ok": False, "error": f"MCP tool execution error: {str(exc)}"}

        if func_name.startswith("builtin_"):
            builtin_name = func_name[len("builtin_"):]
            # ask_user 特殊处理：注入 user_id 和 session_id 到工具参数
            # AskUserTool 需要这些信息创建与用户会话关联的 Future
            if builtin_name == "ask_user":
                func_args.setdefault("user_id", str(context.get("user_id", "") or ""))
                func_args.setdefault("session_id", str(context.get("session_id", "") or ""))
            # 构造包含 ToolUseContext 的工具执行上下文副本，避免污染原 context
            tool_exec_context = {**context, "_tool_use_context": _tool_use_context}
            # 优先通过 ToolRegistry 执行（支持权限检查、截断、统计等）
            _tool_reg = None
            try:
                from core.tool_registry import tool_registry as _tool_reg
            except ImportError:
                pass  # ToolRegistry 不可用时回退到直接执行
            if _tool_reg is not None:
                try:
                    registered_tool = _tool_reg.get(func_name)
                    if registered_tool and registered_tool.execute:
                        exec_result = await _tool_reg.execute(func_name, func_args, tool_exec_context)
                        _builtin_reg_output = {
                            "ok": exec_result.status.value == "completed",
                            "result": exec_result.result,
                            "error": exec_result.error,
                            "tool_name": func_name,
                            "truncated": exec_result.truncated,
                            "output_path": exec_result.output_path,
                            "execution_time_ms": exec_result.execution_time_ms,
                        }
                        return await self._apply_post_tool_use_hooks(_builtin_reg_output, func_name, context)
                except ImportError:
                    pass  # ToolRegistry 模块不可用时回退到直接执行
                except PermissionError:
                    # 权限拒绝：尝试通过实时推送队列请求用户授权
                    reply = await self._request_user_permission(
                        tool_name=func_name,
                        tool_args=func_args,
                        context=context,
                    )
                    if reply == "reject":
                        return {
                            "ok": False,
                            "error": f"用户拒绝权限: {func_name}",
                            "tool_name": func_name,
                            "denied_by": "user",
                        }
                    # 用户允许（once/always），重新执行工具
                    try:
                        exec_result = await _tool_reg.execute(func_name, func_args, tool_exec_context)
                        _builtin_reg_output = {
                            "ok": exec_result.status.value == "completed",
                            "result": exec_result.result,
                            "error": exec_result.error,
                            "tool_name": func_name,
                            "truncated": exec_result.truncated,
                            "output_path": exec_result.output_path,
                            "execution_time_ms": exec_result.execution_time_ms,
                        }
                        return await self._apply_post_tool_use_hooks(_builtin_reg_output, func_name, context)
                    except PermissionError:
                        # 用户授权后仍被拒绝（可能是 always 规则尚未持久化生效）
                        return {
                            "ok": False,
                            "error": f"权限不足: {func_name}",
                            "tool_name": func_name,
                            "denied_by": "security",
                        }
                except Exception:
                    # ToolRegistry 执行意外失败时记录日志并拒绝执行，
                    # 不得回退到未经过权限检查的 builtin_tool_manager 路径
                    logger.bind(
                        module="executor",
                        event="tool_registry_execution_failed",
                        tool_name=func_name,
                    ).exception(f"ToolRegistry 执行异常，已拒绝回退到直接执行: {func_name}")
                    return {
                        "ok": False,
                        "error": f"Tool registry execution failed for {func_name}",
                        "tool_name": func_name,
                    }
            # 回退：直接通过 builtin_tool_manager 执行（仅当 ToolRegistry 完全不可用时）
            from core.builtin_tools.manager import builtin_tool_manager
            try:
                result = await builtin_tool_manager.execute_tool(builtin_name, func_args)
                ok = bool(result.get("success"))
                _builtin_output = {"ok": ok, "result": result, "tool_name": func_name}
                return await self._apply_post_tool_use_hooks(_builtin_output, func_name, context)
            except Exception as exc:
                logger.bind(
                    module="executor",
                    event="builtin_execution_error",
                    tool_name=builtin_name,
                ).error(f"内置工具执行异常: {exc}")
                return {"ok": False, "error": f"Builtin tool execution error: {str(exc)}"}

        # 任务运行时工具（task_spawn_agent / task_send_message / task_stop_agent / task_create_team 等）
        if func_name.startswith("task_"):
            task_action = func_name[len("task_"):]
            from core.task_runtime import task_runtime

            await task_runtime.initialize()

            if task_action == "spawn_agent":
                agent_type = func_args.get("agent_type", "Explore")
                prompt = func_args.get("prompt", "")
                description = func_args.get("description", "")
                provider, model, model_error = self._resolve_subagent_model_selection(
                    context,
                    func_args.get("provider"),
                    func_args.get("model"),
                )
                if model_error:
                    logger.bind(
                        module="executor",
                        event="subagent_model_resolution_failed",
                        agent_type=agent_type,
                    ).warning(model_error)
                    return {"ok": False, "error": model_error, "tool_name": func_name}

                background = func_args.get("background", False)
                logger.bind(
                    module="executor",
                    event="subagent_spawn_requested",
                    agent_type=agent_type,
                    provider=provider,
                    model=model,
                    background=background,
                ).info(f"准备启动子代理: {agent_type}")
                result = await task_runtime.spawn_agent(
                    agent_type=agent_type,
                    prompt=prompt,
                    description=description,
                    provider=provider,
                    model=model,
                    background=background,
                    root_chat_session_id=context.get("session_id"),
                    context=context,
                )
                if isinstance(result, dict):
                    return {"ok": result.get("ok", True), "result": result, "tool_name": func_name}
                return await self._consume_foreground_subagent_stream(
                    result,
                    func_name,
                    on_subagent_event=on_subagent_event,
                )

            elif task_action == "send_message":
                to = func_args.get("to", "")
                message = func_args.get("message", "")
                result = await task_runtime.send_message(to=to, message=message)
                return {"ok": result.get("ok", True), "result": result, "tool_name": func_name}

            elif task_action == "stop_agent":
                agent_id = func_args.get("agent_id", "")
                result = await task_runtime.stop_agent(agent_id)
                return {"ok": result.get("ok", True), "result": result, "tool_name": func_name}

            elif task_action == "list_agents":
                agent_type_filter = func_args.get("agent_type")
                state_filter = func_args.get("state")
                result = await task_runtime.list_agents(state=state_filter)
                return {"ok": True, "result": {"agents": result}, "tool_name": func_name}

            elif task_action == "list_agent_types":
                result = await task_runtime.list_agent_types()
                return {"ok": True, "result": {"agent_types": result}, "tool_name": func_name}

            elif task_action == "create_task":
                result = await task_runtime.create_task_item(
                    list_id=func_args.get("list_id"),
                    subject=func_args.get("subject", ""),
                    description=func_args.get("description"),
                    dependencies=func_args.get("dependencies"),
                    owner_agent_id=func_args.get("owner_agent_id"),
                )
                return {"ok": result.get("ok", True), "result": result, "tool_name": func_name}

            elif task_action == "list_tasks":
                result = await task_runtime.list_task_items(
                    list_id=func_args.get("list_id"),
                    status=func_args.get("status"),
                )
                return {"ok": True, "result": {"tasks": result}, "tool_name": func_name}

            elif task_action == "update_task":
                result = await task_runtime.update_task_item(
                    func_args.get("task_id", ""),
                    status=func_args.get("status"),
                    subject=func_args.get("subject"),
                    owner_agent_id=func_args.get("owner_agent_id"),
                    result_summary=func_args.get("result_summary"),
                )
                return {"ok": result.get("ok", True), "result": result, "tool_name": func_name}

            elif task_action == "claim_task":
                task_id = func_args.get("task_id", "")
                agent_id = context.get("agent_id", context.get("session_id", "unknown"))
                result = await task_runtime.claim_task_item(task_id=task_id, agent_id=agent_id)
                return {"ok": result.get("ok", True), "result": result, "tool_name": func_name}

            elif task_action == "get_task":
                task_id = func_args.get("task_id", "")
                result = await task_runtime.get_task_item(task_id)
                if not result:
                    return {"ok": False, "error": f"任务不存在: {task_id}"}
                return {"ok": True, "result": result, "tool_name": func_name}

            elif task_action == "create_team":
                result = await task_runtime.create_team(
                    lead_agent_id=func_args.get("lead_agent_id", ""),
                    name=func_args.get("name", ""),
                    teammate_agent_ids=func_args.get("teammate_agent_ids"),
                    task_list_id=func_args.get("task_list_id"),
                )
                return {"ok": result.get("ok", True), "result": result, "tool_name": func_name}

            elif task_action == "delete_team":
                result = await task_runtime.delete_team(func_args.get("team_id", ""))
                return {"ok": result.get("ok", True), "result": result, "tool_name": func_name}

            elif task_action == "list_teams":
                result = await task_runtime.list_teams(state=func_args.get("state"))
                return {"ok": True, "result": {"teams": result}, "tool_name": func_name}

            elif task_action == "get_team":
                result = await task_runtime.get_team(func_args.get("team_id", ""))
                if not result:
                    return {"ok": False, "error": f"团队不存在: {func_args.get('team_id')}"}
                return {"ok": True, "result": result, "tool_name": func_name}

            elif task_action == "add_teammate":
                result = await task_runtime.add_teammate(
                    func_args.get("team_id", ""),
                    func_args.get("agent_id", ""),
                    func_args.get("name", ""),
                )
                return {"ok": result.get("ok", True), "result": result, "tool_name": func_name}

            elif task_action == "remove_teammate":
                result = await task_runtime.remove_teammate(
                    func_args.get("team_id", ""),
                    func_args.get("agent_id", ""),
                )
                return {"ok": result.get("ok", True), "result": result, "tool_name": func_name}

            elif task_action == "get_mailbox":
                result = await task_runtime.get_mailbox(
                    agent_id=func_args.get("agent_id", ""),
                    unread_only=func_args.get("unread_only", False),
                )
                return {"ok": True, "result": {"messages": result}, "tool_name": func_name}

            elif task_action == "todo_write":
                result = await task_runtime.sync_todo_snapshot(
                    list_id=func_args.get("list_id"),
                    todos=func_args.get("todos", []),
                )
                return {"ok": result.get("ok", True), "result": result, "tool_name": func_name}

            else:
                return {"ok": False, "error": f"未知任务运行时工具: {task_action}"}

        output = {"ok": False, "error": f"No handler for tool: {func_name}"}

        return output

    async def _execute_tool_calls_concurrent(
        self,
        tool_calls: List[Dict[str, Any]],
        context: Dict[str, Any],
    ) -> List[Tuple[Dict[str, Any], Dict[str, Any]]]:
        """
        使用 StreamingToolExecutor 并发调度工具调用。

        调度策略：
        - 只读且并发安全的工具可同时执行
        - 破坏性工具串行执行
        - 队列中有破坏性工具时阻塞其他工具

        返回结果按原始 tool_calls 顺序排列，保持与同步执行相同的接口契约。

        Args:
            tool_calls: 工具调用列表
            context: 执行上下文

        Returns:
            (tool_call, exec_result) 元组列表，按原始顺序排列
        """
        from core.streaming_tool_executor import StreamingToolExecutor
        from core.tool_registry import tool_registry as global_tool_registry

        streaming_executor = StreamingToolExecutor(
            tool_registry=global_tool_registry,
            max_concurrent=5,
        )

        # 提交所有工具调用到调度队列
        for tc in tool_calls:
            tc_id = tc.get("id", "")
            func_name = tc.get("function", {}).get("name", "")
            func_args_str = tc.get("function", {}).get("arguments", "{}")
            try:
                func_args = json.loads(func_args_str) if isinstance(func_args_str, str) else func_args_str
            except json.JSONDecodeError:
                func_args = {}
            streaming_executor.submit(tc_id, func_name, func_args)

        # 工具执行函数：构造合成 tool_call 并委托给 _execute_tool_call
        async def _execute_fn(tool_name: str, input_params: dict) -> Dict[str, Any]:
            synthetic_tc = {
                "id": "",
                "type": "function",
                "function": {
                    "name": tool_name,
                    "arguments": json.dumps(input_params, ensure_ascii=False),
                },
            }
            return await self._execute_tool_call(synthetic_tc, context)

        # 启动调度循环（后台任务，与 yield_completed 并发运行）
        schedule_task = asyncio.create_task(
            streaming_executor.process_queue(_execute_fn)
        )

        # 收集结果，按 tool_call_id 映射
        results_by_id: Dict[str, Any] = {}
        async for tracked in streaming_executor.yield_completed():
            results_by_id[tracked.tool_call_id] = tracked

        # 确保调度任务完成
        await schedule_task

        # 按原始顺序构建结果列表，保持与同步执行相同的接口契约
        ordered_results: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
        for tc in tool_calls:
            tc_id = tc.get("id", "")
            tracked = results_by_id.get(tc_id)
            if tracked is None:
                # 防御性处理：结果丢失视为失败
                exec_result = {"ok": False, "error": f"工具结果丢失: {tc_id}"}
            elif tracked.error is not None:
                exec_result = {
                    "ok": False,
                    "error": str(tracked.error),
                    "tool_name": tracked.tool_name,
                }
            elif isinstance(tracked.result, dict):
                exec_result = tracked.result
            else:
                exec_result = {
                    "ok": True,
                    "result": tracked.result,
                    "tool_name": tracked.tool_name,
                }
            ordered_results.append((tc, exec_result))

        return ordered_results

    @staticmethod
    def _build_tool_message(tool_call: Dict[str, Any], exec_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        根据工具调用及其执行结果构建 tool role 消息，用于后续 LLM 轮次。
        对过大的工具结果进行截断，防止消息列表无限膨胀导致 OOM 或 token 超限。
        """
        result_str = json.dumps(exec_result, ensure_ascii=False, default=str)
        if len(result_str) > MAX_TOOL_RESULT_CHARS:
            result_str = (
                result_str[:MAX_TOOL_RESULT_CHARS]
                + f"\n[工具输出已截断，原始长度: {len(result_str)} 字符，超出部分已丢弃]"
            )
        return {
            "role": "tool",
            "tool_call_id": tool_call.get("id", ""),
            "content": result_str,
        }
