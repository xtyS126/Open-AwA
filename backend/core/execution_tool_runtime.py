"""ExecutionToolRuntimeMixin 的单一职责实现。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from loguru import logger

from core.execution_support import MAX_TOOL_RESULT_CHARS, _handle_audit_task_result
from core.tool_use_context import ToolUseContext
from core.tool_execution import (
    ToolExecutionContext,
    ToolExecutionStrategyRegistry,
    BuiltinToolStrategy,
    PluginToolStrategy,
    MCPToolStrategy,
    TaskToolStrategy,
)


def _safe_int(value: Any, default: int = 0) -> int:
    """安全地将值转换为 int，字符串 ID 等非数值回退到 default。"""
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


# 工具名到权限 action 类别的精确映射（与 PermissionManager 规则 action 对齐：
# read/glob/grep/web_search/web_fetch/skill/write/edit/delete/command:execute 等）。
# 命令类工具（execute_command/run_command/run_shell）统一为 command:execute，
# 与 core/task_runtime/permission_guard.py 及 core/tool_entries.py 保持一致。
_TOOL_ACTION_EXACT_MAP: Dict[str, str] = {
    "read_file": "read",
    "list_files": "read",
    "file_exists": "read",
    "local_search": "read",
    "glob": "glob",
    "grep": "grep",
    "web_search": "web_search",
    "web_fetch": "web_fetch",
    "write_file": "write",
    "create_file": "write",
    "edit_file": "edit",
    "apply_patch": "edit",
    "delete_file": "delete",
    "execute_command": "command:execute",
    "run_command": "command:execute",
    "run_shell": "command:execute",
}

# 只读工具名前缀
_READ_TOOL_PREFIXES = ("read_", "list_", "search_", "get_", "find_", "query_", "check_", "fetch_")
# 写入工具名前缀
_WRITE_TOOL_PREFIXES = ("write_", "create_", "save_", "upload_")
# 编辑工具名前缀
_EDIT_TOOL_PREFIXES = ("edit_", "patch_", "update_", "modify_")
# 删除工具名前缀
_DELETE_TOOL_PREFIXES = ("delete_", "remove_", "drop_", "truncate_", "purge_")
# 命令执行工具名前缀（映射到统一权限 action command:execute）
_COMMAND_TOOL_PREFIXES = ("execute_", "run_", "bash", "shell_", "terminal")


def _infer_permission_action(tool_name: str) -> str:
    """
    根据工具名推断权限 action 类别（read/write/edit/delete/command:execute 等）。

    供 PermissionManager 规则评估使用，与 _get_agent_rules 中的规则 action 对齐。
    命令类工具统一映射为 command:execute，与 _request_user_permission 的 action
    及 core/task_runtime/permission_guard.py 的 _TOOL_OPERATION_MAP 保持一致。
    未识别时返回工具名本身，保证未知工具至少可被 catch-all 规则约束。
    """
    name = tool_name
    if name.startswith("builtin_"):
        name = name[len("builtin_"):]

    if name in _TOOL_ACTION_EXACT_MAP:
        return _TOOL_ACTION_EXACT_MAP[name]

    if name.startswith("install_"):
        return "skill"
    if name.startswith(_READ_TOOL_PREFIXES):
        return "read"
    if name.startswith(_WRITE_TOOL_PREFIXES):
        return "write"
    if name.startswith(_EDIT_TOOL_PREFIXES):
        return "edit"
    if name.startswith(_DELETE_TOOL_PREFIXES):
        return "delete"
    if name.startswith(_COMMAND_TOOL_PREFIXES):
        return "command:execute"
    if name.startswith("plugin_"):
        return "plugin"
    if name.startswith("task_"):
        return "system"
    if name.startswith("mcp_"):
        return "network"
    return name


def _extract_permission_resources(tool_args: Dict[str, Any], tool_name: str) -> List[str]:
    """
    从工具参数中提取权限检查所需的资源列表（路径/命令/URL 等）。

    与 _request_user_permission 的资源提取逻辑保持一致；
    无可用参数时回退为工具名本身，保证资源列表非空。
    """
    resources: List[str] = []
    for key in ("path", "file", "files", "command", "url", "directory"):
        value = tool_args.get(key)
        if isinstance(value, str) and value:
            resources.append(value)
        elif isinstance(value, list):
            resources.extend(str(v) for v in value if v)
    if not resources:
        resources = [tool_name]
    return resources


def _tool_rbac_permission(tool_name: str) -> str:
    """
    将工具名映射为用户级 RBAC 的 resource:action 权限字符串。

    与 core/tool_entries._BUILTIN_PERMISSION_MAP 的 resource 字段保持一致
    （命令工具统一为 command:execute，读文件统一为 file:read 等）。
    未收录的工具回退到 _infer_permission_action 的 action 值，保证 RBAC
    仍能对未知工具施加最小约束。
    """
    name = tool_name
    if name.startswith("builtin_"):
        name = name[len("builtin_"):]

    try:
        from core.tool_entries import _BUILTIN_PERMISSION_MAP as _builtin_permission_map
    except ImportError:
        _builtin_permission_map = {}

    entry = _builtin_permission_map.get(name)
    if entry:
        # entry 为 (permission_action, permission_resource)，resource 即 resource:action 字符串
        return entry[1]
    return _infer_permission_action(tool_name)


def _has_explicit_user_role(db: Any, user_id: str) -> bool:
    """判断用户是否被显式分配过角色（存在 UserRole 记录）。"""
    from db.models import UserRole

    return db.query(UserRole).filter(UserRole.user_id == user_id).first() is not None


class ExecutionToolRuntimeMixin:
    """由 ExecutionLayer 组合的内部协作者。"""

    def _ensure_tool_strategy_registry(self) -> ToolExecutionStrategyRegistry:
        """延迟初始化工具执行策略注册表（首次调用时创建）。"""
        if not hasattr(self, "_tool_strategy_registry") or self._tool_strategy_registry is None:
            from core.task_runtime import task_runtime as _task_runtime
            from core.tool_registry import tool_registry as _tool_reg

            registry = ToolExecutionStrategyRegistry()
            # 注册四种策略：内置工具作为兜底（can_handle 同时匹配 builtin_ 和无前缀工具）
            registry.register("builtin_", BuiltinToolStrategy(tool_registry=_tool_reg, mixin=self))
            registry.register("plugin_", PluginToolStrategy(mixin=self))
            registry.register("mcp_", MCPToolStrategy(mixin=self))
            registry.register("task_", TaskToolStrategy(task_runtime=_task_runtime, mixin=self))
            self._tool_strategy_registry = registry
        return self._tool_strategy_registry

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
            save_rules.append(f"command:execute:{resources[0]}" if resources else "command:execute:*")
        elif "read" in tool_name:
            save_rules.append(f"read:{resources[0]}" if resources else "read:*")
        else:
            save_rules.append(f"{tool_name}:*")

        # 推断 action 显示名称（命令类工具统一为 command:execute）
        if "write" in tool_name or "edit" in tool_name:
            action = "write"
        elif "delete" in tool_name:
            action = "delete"
        elif "execute" in tool_name or "bash" in tool_name or "terminal" in tool_name:
            action = "command:execute"
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

    async def _check_user_rbac_permission(
        self,
        tool_name: str,
        context: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """
        用户级 RBAC / 细粒度权限检查（安全加严，独立于代理级权限规则）。

        仅在用户被显式分配角色（存在 UserRole 记录）时启用，保证默认
        （无 RBAC 配置）下工具权限决策行为完全不变；命中后按 resource:action
        权限字符串（如 command:execute）校验，用户无该权限则拒绝。
        RBAC 模块缺失时按默认放行（与无配置语义一致）；权限数据损坏时
        fine_grained 校验内部 fail-closed 返回拒绝，不降级放行。

        返回 None 表示放行（无显式角色 / 拥有权限 / 模块缺失），
        dict 表示拒绝结果。
        """
        db = context.get("db")
        user_id = str(context.get("user_id", "") or "")
        if db is None or not user_id:
            # 无数据库会话或无用户标识：无法做用户级校验，按默认放行保持行为不变
            return None

        try:
            from db.models import UserRole
            from security.fine_grained_permissions import (
                FineGrainedPermissionManager,
            )
        except ImportError:
            logger.bind(
                module="executor",
                event="rbac_module_missing",
                tool_name=tool_name,
            ).warning("用户级 RBAC 模块缺失，工具权限检查按默认放行")
            return None

        # 仅当管理员显式分配过角色时才施加用户级 RBAC 约束
        has_explicit_role = await asyncio.to_thread(
            _has_explicit_user_role, db, user_id,
        )
        if not has_explicit_role:
            return None

        permission = _tool_rbac_permission(tool_name)
        try:
            allowed = await FineGrainedPermissionManager(db).check_permission(
                user_id, permission,
            )
        except Exception as exc:  # noqa: BLE001 - RBAC 校验异常需 fail-closed
            logger.bind(
                module="executor",
                event="rbac_check_failed",
                tool_name=tool_name,
                permission=permission,
                error=str(exc),
            ).warning(f"用户级 RBAC 校验异常，拒绝工具调用: {tool_name}")
            return {
                "ok": False,
                "error": f"用户级 RBAC 校验失败，拒绝工具调用: {tool_name}",
                "tool_name": tool_name,
                "denied_by": "rbac",
            }

        if allowed:
            return None

        logger.bind(
            module="executor",
            event="rbac_permission_denied",
            tool_name=tool_name,
            permission=permission,
            user_id=user_id,
        ).warning(f"用户级 RBAC 拒绝工具调用: {tool_name} 缺少权限 {permission}")
        return {
            "ok": False,
            "error": f"用户缺少权限 {permission}，工具调用被拒绝: {tool_name}",
            "tool_name": tool_name,
            "denied_by": "rbac",
        }

    async def _check_tool_permission(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """
        工具分发前的权限检查链（用户级 RBAC + PermissionGuard 模式检查 + PermissionManager 规则评估 + 拒绝追踪）。

        检查顺序：
        1. 用户级 RBAC / 细粒度权限检查，仅在用户存在显式角色分配时启用，
           无 RBAC 配置时默认放行，保持既有行为不变
        2. PermissionGuard 模式检查（plan/accept_edits/dont_ask），仅在 context 配置了
           非 default 的 permission_mode 时启用，避免破坏默认行为
        3. PermissionManager 规则评估（deny > allow > ask），仅在存在生效规则时启用，
           无规则时默认放行，避免默认 ASK 破坏既有行为
        4. 需要确认时触发 enqueue_permission_request（经 _request_user_permission），
           用户回复 once/always 继续执行，reject 拒绝执行
        5. 拒绝追踪：deny/拒绝时 record_denial，放行时 record_success，
           auto 模式下连续拒绝超限自动回退到人工确认模式

        返回 None 表示放行，返回 dict 表示拦截结果（直接作为工具执行结果返回）。
        """
        # 用户交互类工具无需权限门禁（本身需要用户参与确认）
        if tool_name in ("ask_user", "builtin_ask_user"):
            return None

        permission_mode = context.get("permission_mode")
        user_id = str(context.get("user_id", "") or "")
        agent_id = context.get("agent_id") or context.get("agent_name")
        work_dir = context.get("work_dir")

        # 第一层：PermissionGuard 模式检查。
        # 仅对非 default 的强制模式启用；bypass_permissions 全部放行（直接跳过整个检查链）。
        if permission_mode == "bypass_permissions":
            return None

        # 用户级 RBAC / 细粒度权限检查（安全加严）。
        # 仅在用户被显式分配角色时启用，无 RBAC 配置（无 db 或无 UserRole 记录）时
        # 默认放行，保持既有行为不变；命中无权限时拒绝。
        rbac_result = await self._check_user_rbac_permission(tool_name, context)
        if rbac_result is not None:
            return rbac_result

        if permission_mode in ("plan", "accept_edits", "dont_ask"):
            try:
                from core.task_runtime.permission_guard import permission_guard as _guard
            except ImportError:
                _guard = None
            if _guard is not None:
                decision = _guard.evaluate(
                    tool_name,
                    tool_args,
                    permission_mode=str(permission_mode),
                    work_dir=work_dir,
                )
                if not decision.allowed:
                    logger.bind(
                        module="executor",
                        event="permission_mode_denied",
                        tool_name=tool_name,
                        permission_mode=permission_mode,
                        reason=decision.reason,
                    ).warning(f"权限模式拒绝工具调用: {tool_name} ({permission_mode})")
                    return {
                        "ok": False,
                        "error": decision.reason or f"权限模式拒绝工具调用: {tool_name}",
                        "tool_name": tool_name,
                        "denied_by": "permission_mode",
                    }
                if decision.require_user_confirm:
                    # 模式级确认：写操作等需要用户确认
                    reply = await self._request_user_permission(tool_name, tool_args, context)
                    if reply == "reject":
                        return {
                            "ok": False,
                            "error": f"用户拒绝权限: {tool_name}",
                            "tool_name": tool_name,
                            "denied_by": "user",
                        }

        # 第二层：PermissionManager 规则评估（deny > allow > ask）。
        try:
            from core.denial_tracking import record_denial as _record_denial
            from core.denial_tracking import record_success as _record_success
            from core.permission_manager import (
                PermissionEffect as _PE,
                get_permission_manager,
            )
        except ImportError:
            logger.warning("[权限检查] permission_manager 模块导入失败，规则评估已跳过")
            return None

        try:
            _pm = get_permission_manager(context.get("db"))
        except TypeError:
            # 传入的 db 无法被 PermissionManager 接受时回退到无会话实例
            _pm = get_permission_manager()

        # 无任何生效规则时默认放行（防止默认 ASK 改变既有行为）
        _agent_rules = _pm._get_agent_rules(agent_id)
        _global_rules = list(_pm._global_rules)
        _saved_rules = await _pm._get_saved_rules(user_id)
        if not _agent_rules and not _global_rules and not _saved_rules:
            return None

        action = _infer_permission_action(tool_name)
        resources = _extract_permission_resources(tool_args, tool_name)

        # 评估所有资源，deny 优先、ask 其次（与 PermissionManager.ask 语义一致）
        effects = set()
        for resource in resources:
            effect = await _pm.evaluate(action, resource, agent_id=agent_id, user_id=user_id)
            effects.add(effect)

        if _PE.DENY in effects:
            # 记录拒绝并检查 auto 模式是否需要回退人工
            _new_state = _record_denial(_pm.denial_state)
            _pm._update_denial_state(_new_state, None)
            _pm._check_and_fallback(_new_state, None)
            logger.bind(
                module="executor",
                event="permission_rule_denied",
                tool_name=tool_name,
                action=action,
                resources=resources,
            ).warning(f"权限规则拒绝工具调用: {tool_name} ({action})")
            return {
                "ok": False,
                "error": f"操作 {action} 被权限规则拒绝: {resources}",
                "tool_name": tool_name,
                "denied_by": "permission",
            }

        if _PE.ASK in effects:
            # 需要用户确认：经 enqueue_permission_request 推送前端并阻塞等待回复
            reply = await self._request_user_permission(tool_name, tool_args, context)
            if reply == "reject":
                _new_state = _record_denial(_pm.denial_state)
                _pm._update_denial_state(_new_state, None)
                _pm._check_and_fallback(_new_state, None)
                return {
                    "ok": False,
                    "error": f"用户拒绝权限: {tool_name}",
                    "tool_name": tool_name,
                    "denied_by": "user",
                }
            # once/always：放行并记录成功（重置连续拒绝）
            _pm._update_denial_state(_record_success(_pm.denial_state), None)
            return None

        # allow：记录成功以重置连续拒绝
        _pm._update_denial_state(_record_success(_pm.denial_state), None)
        return None

    async def _check_mcp_permission(
        self,
        full_tool_name: str,
        server_id: str,
        context: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """
        MCP 工具调用的服务级权限门禁。

        在 mcp 分支调用 manager.call_tool 前评估 (action=工具全限定名, resource=server_id)：
        - 服务级规则 mcp__<server> 可匹配该服务下所有工具（matches_mcp_server 语义）
        - 工具级规则 mcp__<server>__<tool> 精确匹配（wildcard_match 语义）
        - 无规则命中时默认放行（向后兼容，未配置权限规则的 MCP Server 工具保持可用）
        - 命中 DENY 规则时拒绝执行并返回错误结果
        - ALLOW / ASK 均放行（ASK 的用户确认已由前置 _check_tool_permission 处理，
          此处避免重复弹窗阻塞 Agent 执行流程）

        返回 None 表示放行；返回 dict 表示拒绝结果（直接作为工具执行结果返回）。
        """
        try:
            from core.permission_manager import (
                PermissionEffect,
                get_permission_manager,
                matches_mcp_server,
                wildcard_match,
            )
        except ImportError:
            # 权限模块不可用：默认放行，避免阻断已连接 MCP Server 的工具调用
            logger.bind(
                module="executor",
                event="mcp_permission_module_missing",
                tool_name=full_tool_name,
            ).warning("权限管理模块导入失败，MCP 工具调用默认放行")
            return None

        try:
            _pm = get_permission_manager(context.get("db"))
        except TypeError:
            # 传入的 db 无法被 PermissionManager 接受时回退到无会话实例
            _pm = get_permission_manager()

        user_id = str(context.get("user_id", "") or "")
        agent_id = context.get("agent_id") or context.get("agent_name")

        # 与 _check_tool_permission 一致：无任何生效规则时默认放行
        _agent_rules = _pm._get_agent_rules(agent_id)
        _global_rules = list(_pm._global_rules)
        _saved_rules = await _pm._get_saved_rules(user_id)
        if not _agent_rules and not _global_rules and not _saved_rules:
            return None

        # 遍历规则（last-match-wins）：action 支持 matches_mcp_server 服务级匹配，
        # resource 匹配 server_id（wildcard_match 语义）
        matched_rule = None
        for ruleset in (_agent_rules, _global_rules, _saved_rules):
            for rule in ruleset:
                action_matched = wildcard_match(rule.action, full_tool_name) or (
                    rule.action.startswith("mcp__")
                    and matches_mcp_server(rule.action, full_tool_name)
                )
                resource_matched = wildcard_match(rule.resource, server_id)
                if action_matched and resource_matched:
                    matched_rule = rule

        if matched_rule is None:
            # 无规则命中：默认放行（避免破坏现有未配置权限的 MCP 调用）
            logger.bind(
                module="executor",
                event="mcp_permission_no_rule",
                tool_name=full_tool_name,
                server_id=server_id,
            ).debug(f"MCP 工具无权限规则命中，默认放行: {full_tool_name}")
            return None

        if matched_rule.effect == PermissionEffect.DENY:
            logger.bind(
                module="executor",
                event="mcp_permission_denied",
                tool_name=full_tool_name,
                server_id=server_id,
            ).warning(f"MCP 工具调用被权限规则拒绝: {full_tool_name}")
            return {
                "ok": False,
                "error": f"MCP 工具调用被权限规则拒绝: {full_tool_name}",
                "tool_name": full_tool_name,
                "denied_by": "permission",
            }

        # ALLOW 或显式 ASK：放行
        return None

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

        # PreToolUse 钩子（hook_manager 插件系统）：统一的工具执行前钩子。
        # 职责边界：hook_manager（core）负责所有 Hook 事件，包括插件级工具钩子（APPROVE/DENY/MODIFY_INPUT/REPLACE_RESULT/ERROR）
        # 和子代理生命周期事件（SUBAGENT_START/STOP/ERROR/COMPLETE、TASK_CREATED/COMPLETED、STOP 等），
        # 不在通用工具执行路径中触发，避免 PreToolUse 双触发。
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
                if _pre_result.result_type == _HookResultType.ASK:
                    # ASK 语义：需要用户确认才能继续执行，经 _request_user_permission 推送前端
                    reply = await self._request_user_permission(func_name, func_args, context)
                    if reply == "reject":
                        return {
                            "ok": False,
                            "error": _pre_result.reason or f"用户拒绝钩子确认: {func_name}",
                            "blocked_by_hook": True,
                            "tool_name": func_name,
                        }
            # 合并所有 MODIFY_INPUT 结果到 func_args
            func_args = _hook_updated_input(_pre_results, func_args)
        except ImportError:
            logger.warning("[PreToolUse] hook_manager 模块导入失败，跳过 hook_manager 钩子校验")

        # 权限检查链：PermissionGuard 模式检查 + PermissionManager 规则评估 + 拒绝追踪。
        # 仅在配置了 permission_mode 或存在权限规则时拦截，默认放行以保持既有行为。
        # 拦截结果直接作为工具执行结果返回，不再进入 plugin_/mcp_/builtin_/task_ 分发。
        _permission_result = await self._check_tool_permission(func_name, func_args, context)
        if _permission_result is not None:
            return _permission_result

        # 策略模式分发：根据工具名前缀查找匹配的执行策略并委托执行
        _strategy_context = ToolExecutionContext(
            session_id=str(context.get("session_id", "") or ""),
            user_id=_safe_int(context.get("user_id"), 0),
            tool_name=func_name,
            tool_input=func_args,
            tool_call_id=tool_call.get("id", ""),
            abort_controller=context.get("abort_controller"),
            content_replacement_state=context.get("content_replacement_state"),
            permission_mode=str(context.get("permission_mode", "auto") or "auto"),
            record_usage=context.get("record_usage"),
            record_latency=context.get("record_latency"),
            raw_context=context,
            extra={
                "on_subagent_event": on_subagent_event,
                "_tool_use_context": _tool_use_context,
            },
        )

        _strategy_result = await self._ensure_tool_strategy_registry().execute(_strategy_context)

        # 将 ToolExecutionResult 转换回 Dict 格式
        if _strategy_result.error is not None:
            return {"ok": False, "error": _strategy_result.error, "tool_name": func_name}

        if isinstance(_strategy_result.output, dict):
            return _strategy_result.output

        return {"ok": False, "error": f"No handler for tool: {func_name}"}

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
            tool_concurrency=context.get("_tool_concurrency"),
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
        async def _execute_fn(
            tool_name: str,
            input_params: dict,
            abort_controller=None,
        ) -> Dict[str, Any]:
            # 将工具级 abort_controller 注入 context，使 _build_tool_use_context
            # 能取到非 None 的中止控制器（级联中止信号贯通工具执行链）
            exec_context = dict(context)
            if abort_controller is not None:
                exec_context["abort_controller"] = abort_controller
            synthetic_tc = {
                "id": "",
                "type": "function",
                "function": {
                    "name": tool_name,
                    "arguments": json.dumps(input_params, ensure_ascii=False),
                },
            }
            return await self._execute_tool_call(synthetic_tc, exec_context)

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
