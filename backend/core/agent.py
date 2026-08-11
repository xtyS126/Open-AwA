"""
核心执行编排模块，负责 Agent 主流程中的理解、规划、执行、反馈或记录能力。
这些文件决定了用户请求在内部被如何拆解、编排以及最终落地执行。
"""

import asyncio
import json
import time
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional, Tuple
from loguru import logger
from .abort_controller import AbortController
from .rollback import RollbackManager
from .role_engine import RoleEngine
from .magic_commands import get_magic_command_registry
from .compaction_manager import CompactionManager
from .context.token_budget import TokenBudget
from core.agent_capability_builder import (
    summarize_skill_capabilities,
    summarize_plugin_capabilities,
)
from core.agent_context_builder import (
    strip_reasoning_content,
    apply_scheduled_execution_defaults,
    build_multimodal_context,
    build_thinking_context,
)
from core.agent_execution_context import (
    StreamFinalizationContext,
)
from core.agent_helpers import (
    is_final_only_mode,
    build_status_event,
    build_effective_user_input,
    ttft_stage_logger,
    COMPACTION_MESSAGE_THRESHOLD,
    MAX_HISTORY_MESSAGE_CHARS,
)
from core.agent_task_registry import register_agent_task, unregister_agent_task
from core.agent_runtime import initialize_agent_runtime


from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from core.ports.ask_user_port import AskUserPort
from core.ports.workflow_repository_port import WorkflowRepositoryPort

class _StreamEarlyExit(Exception):
    """process_stream 内部信号：流应提前退出（魔法命令、用户取消等场景）。

    子方法通过此异常通知 process_stream 主体立即返回，等价于原代码中
    `yield ...; return` 模式。process_stream 的 finally 块仍会执行清理。
    """

    pass


class AIAgent:
    """
    封装与AIAgent相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    # 能力缓存 TTL：30 秒内复用 skills/plugins/mcp 查询结果
    # 过期后下一次 process_stream 重新构建，保证插件/MCP 状态变化最终可见
    _CAPABILITIES_CACHE_TTL: float = 30.0

    def __init__(
        self,
        db_session: Session = None,
        ask_user_port: Optional[AskUserPort] = None,
        workflow_repository: Optional[WorkflowRepositoryPort] = None,
        memory_session_factory: Optional[Callable[[], Session]] = None,
    ):
        """
        初始化 AI Agent，包含理解层、规划层、执行层、反馈层以及记忆管理。
        """
        init_started_at = time.time()
        timings = initialize_agent_runtime(
            self,
            db_session=db_session,
            ask_user_port=ask_user_port,
            workflow_repository=workflow_repository,
            memory_session_factory=memory_session_factory,
            early_exit_type=_StreamEarlyExit,
            unregister_task=unregister_agent_task,
        )
        self._log_initialization_breakdown(
            init_started_at,
            timings.layers_ms,
            timings.skill_engine_ms,
            timings.plugin_manager_ms,
            timings.memory_engine_ms,
        )
        logger.info("AI Agent initialized with SkillEngine and PluginManager integration")

    @staticmethod
    def _log_initialization_breakdown(
        started_at: float, layers_ms: float, skill_engine_ms: float,
        plugin_manager_ms: float, memory_engine_ms: float,
    ) -> None:
        """记录构造耗时分解，保持 TTFT 诊断字段兼容。"""
        total_ms = round((time.time() - started_at) * 1000, 2)
        logger.bind(
            event="agent_init_breakdown", module="agent", layers_ms=layers_ms,
            skill_engine_ms=skill_engine_ms, plugin_manager_ms=plugin_manager_ms,
            memory_engine_ms=memory_engine_ms, total_ms=total_ms,
        ).info(f"AIAgent 构造耗时分解: layers={layers_ms}ms, skill_engine={skill_engine_ms}ms, plugin_manager={plugin_manager_ms}ms, memory_engine={memory_engine_ms}ms, total={total_ms}ms")

    def bind_db(self, db_session: Session) -> None:
        """绑定新的数据库会话到所有子引擎。

        通过子引擎暴露的公共 bind_db 方法更新，避免直接访问内部 _cache / _list_cache 私有属性。
        子引擎未实现 bind_db 时 AttributeError 自然传播，禁止 setattr 兜底。

        注意：SkillRegistry 内部持有 db 引用与缓存（_cache/_list_cache），
        缓存的 Skill 对象绑定到旧 session，访问属性会触发 DetachedInstanceError。
        SkillEngine.bind_db 内部已委托给 SkillRegistry.bind_db 同步清空缓存，
        因此本方法不再直接读写 registry._cache / _list_cache 私有属性。
        """
        # 委托给 skill_engine 公共方法（内部会同步更新 registry.db 并清空缓存）
        if hasattr(self, 'skill_engine') and self.skill_engine is not None:
            self.skill_engine.bind_db(db_session)

        # 委托给 workflow_engine 公共方法
        if hasattr(self, 'workflow_engine') and self.workflow_engine is not None:
            self.workflow_engine.bind_db(db_session)

        # 更新 agent 自身的请求级 db_session 引用
        self._db_session_request = db_session
        if self._workflow_repository is not None:
            self._workflow_repository.bind_db(db_session)

    @property
    def _db_session(self) -> Optional[Session]:
        """动态返回当前有效的 db session：优先请求级 bind 的 db，回退到 __init__ 的 db。"""
        if self._db_session_request is not None:
            return self._db_session_request
        return self._db_session_bound

    @property
    def _capabilities_cache(self) -> Optional[Dict[str, Any]]:
        """兼容既有调用，返回能力聚合器持有的缓存。"""
        return self._capability_aggregator.capabilities_cache

    @_capabilities_cache.setter
    def _capabilities_cache(self, value: Optional[Dict[str, Any]]) -> None:
        self._capability_aggregator.capabilities_cache = value

    @property
    def _capabilities_cache_ts(self) -> float:
        """兼容既有调用，返回能力缓存时间戳。"""
        return self._capability_aggregator.capabilities_cache_ts

    @_capabilities_cache_ts.setter
    def _capabilities_cache_ts(self, value: float) -> None:
        self._capability_aggregator.capabilities_cache_ts = value

    @property
    def _tools_cache(self) -> Optional[List[Dict[str, Any]]]:
        """兼容既有调用，返回原生工具缓存。"""
        return self._capability_aggregator.tools_cache

    @_tools_cache.setter
    def _tools_cache(self, value: Optional[List[Dict[str, Any]]]) -> None:
        self._capability_aggregator.tools_cache = value

    @property
    def _tools_cache_version(self) -> str:
        """兼容既有调用，返回工具缓存版本。"""
        return self._capability_aggregator.tools_cache_version

    @_tools_cache_version.setter
    def _tools_cache_version(self, value: str) -> None:
        self._capability_aggregator.tools_cache_version = value

    def invalidate_capabilities_cache(self) -> None:
        """
        主动失效实例级 capabilities 与 tools 缓存。

        在插件 load/unload、MCP server connect/disconnect、技能启用/禁用等
        影响能力集合的事件发生后调用，确保下一次 process_stream 重建 capabilities。
        若不调用，TTL（默认 30 秒）到期后也会自动失效重建。
        """
        self._capability_aggregator.invalidate()
        logger.bind(
            event="capabilities_cache_invalidated",
            module="agent",
        ).debug("capabilities 与 tools 实例级缓存已主动失效")

    async def _record_with_backpressure(self, coro) -> Any:
        """
        通过信号量限制并发 fire-and-forget 记录任务数，防止高并发下 Task 堆积。
        """
        async with self._record_semaphore:
            return await coro

    def _handle_record_task_result(self, task: asyncio.Task) -> None:
        """
        检查后台记录任务（行为日志/对话记录）的执行结果，
        对取消和异常情况记录告警日志，避免 fire-and-forget 任务静默失败。
        """
        try:
            if task.cancelled():
                logger.warning("Conversation recorder task was cancelled")
                return

            exc = task.exception()
            if exc is not None:
                logger.warning(f"Conversation recorder task failed: {exc}")
                return

            task.result()
        except Exception as e:
            logger.warning(f"Conversation recorder task failed: {e}")

    def _apply_output_mode(self, payload: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """
        根据上下文裁剪对外响应，确保渠道级输出模式真正落到返回值上。
        """
        if not is_final_only_mode(context):
            return payload
        return strip_reasoning_content(payload)

    def _prepare_context(self, user_input: str, context: Dict[str, Any]) -> None:
        """
        统一补齐执行上下文，保证数据库会话与隔离开关能够透传到执行层。
        """
        apply_scheduled_execution_defaults(context)

        if "message" not in context:
            context["message"] = user_input

        if self._db_session and context.get("db") is None:
            context["db"] = self._db_session

        context["_record_hook"] = self._schedule_record

    def _record_round_budget_usage(
        self,
        *,
        user_input: str,
        context: Dict[str, Any],
        round_content: str,
        round_reasoning: str,
    ) -> None:
        """
        估算并记录本轮 LLM 调用的 token 使用量到预算追踪器。

        流式响应不直接返回 usage 信息，因此基于本轮输入和输出文本进行启发式估算：
        - 输入 token：用户输入 + 对话历史
        - 输出 token：本轮生成的内容 + 推理内容

        参数:
            user_input: 本轮有效的用户输入
            context: 执行上下文，可能包含 conversation_history
            round_content: 本轮 LLM 生成的回复内容
            round_reasoning: 本轮 LLM 生成的推理内容
        """
        token_budget = TokenBudget()

        # 估算输入 token：用户输入 + 对话历史
        input_text = user_input or ""
        conversation_history = context.get("conversation_history", [])
        if isinstance(conversation_history, list):
            for msg in conversation_history:
                if isinstance(msg, dict):
                    content = msg.get("content", "")
                    if isinstance(content, str):
                        input_text += " " + content
        input_tokens = token_budget.estimate_tokens(input_text)

        # 估算输出 token：本轮生成的内容 + 推理内容
        output_text = (round_content or "") + (round_reasoning or "")
        output_tokens = token_budget.estimate_tokens(output_text)

        self.budget_tracker.record_usage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    async def _inject_runtime_capabilities(self, context: Dict[str, Any]) -> None:
        """
        在进入最终模型回答前，把当前会话可用的技能、插件和 MCP 连接态写入上下文。
        这样模型在回答“我能不能调用某能力”时能基于真实运行态，而不是凭空猜测。
        """
        await self._capability_aggregator.inject(
            context,
            get_available_skills=self.get_available_skills,
            get_available_plugins=self.get_available_plugins,
            summarize_skills=summarize_skill_capabilities,
            summarize_plugins=summarize_plugin_capabilities,
            build_native_tools=self.native_tool_builder,
        )

    def _schedule_record(
        self,
        *,
        node_type: str,
        user_message: str,
        context: Dict[str, Any],
        **record_fields: Any,
    ) -> None:
        """
        将对话节点（LLM调用/工具执行/意图识别）通过后台任务异步记录到行为日志和对话记录表。
        受 scheduled_execution_isolated 开关控制，定时任务执行时不写入记录以避免污染。

        token 计数来源优先级：
        1. token_breakdown 非 None 时直接使用（携带 input/output/cache 等明细）
        2. 否则从 llm_tokens_used 构造简单 breakdown（向后兼容旧调用方）
        最终 llm_tokens_used 从 breakdown.total_tokens 派生，保证下游记录器一致。
        """
        self._behavior_recorder.schedule(
            node_type=node_type,
            user_message=user_message,
            context=context,
            db_session=self._db_session,
            **record_fields,
        )

    async def execute_skill(self, skill_name: str, inputs: Dict, context: Dict) -> Dict[str, Any]:
        """
        通过 SkillEngine 执行指定技能，收集执行结果并记录到 skill_results 列表。
        成功时返回包含 outputs 和 steps 的结构化结果，失败时返回错误信息。
        """
        logger.info(f"Executing skill: {skill_name}")
        try:
            result = await self.skill_engine.execute_skill(skill_name, inputs, context)
            
            self.skill_results.append({
                'skill_name': skill_name,
                'result': result,
                'success': result.get('success', False)
            })
            
            if result.get('success'):
                logger.info(f"Skill '{skill_name}' executed successfully")
                return {
                    'status': 'completed',
                    'skill_name': skill_name,
                    'outputs': result.get('outputs', {}),
                    'steps': result.get('steps', []),
                    'execution_id': result.get('execution_id'),
                    'metrics': result.get('metrics', {})
                }
            else:
                logger.error(f"Skill '{skill_name}' execution failed: {result.get('error')}")
                return {
                    'status': 'error',
                    'skill_name': skill_name,
                    'error': result.get('error', 'Unknown error'),
                    'outputs': result.get('outputs', {}),
                    'execution_id': result.get('execution_id')
                }
        except Exception as e:
            logger.bind(
                event="skill_execution_error",
                module="agent",
                error_type=type(e).__name__,
                skill_name=skill_name,
            ).opt(exception=True).error(f"技能 '{skill_name}' 执行异常: {e}")
            return {
                'status': 'error',
                'skill_name': skill_name,
                'error': str(e)
            }
    
    async def execute_plugin(self, plugin_name: str, method: str, **kwargs) -> Any:
        """
        加载并异步执行指定插件的目标方法。若插件未加载则自动加载。
        将执行结果（成功/失败）记录到 plugin_results 列表，用于后续汇总统计。
        """
        logger.info(f"Executing plugin '{plugin_name}' method '{method}'")
        try:
            if plugin_name not in self.plugin_manager.loaded_plugins:
                load_result = self.plugin_manager.load_plugin(plugin_name)
                if not load_result:
                    logger.error(f"Failed to load plugin '{plugin_name}'")
                    return {
                        'status': 'error',
                        'message': f"Plugin '{plugin_name}' not found or failed to load"
                    }
            
            result = await self.plugin_manager.execute_plugin_async(plugin_name, method, **kwargs)
            
            self.plugin_results.append({
                'plugin_name': plugin_name,
                'method': method,
                'result': result,
                'success': result.get('status') == 'success'
            })
            
            status = result.get('status', 'error')

            if status == 'success':
                logger.info(f"Plugin '{plugin_name}' method '{method}' executed successfully")
                return {
                    'status': 'completed',
                    'data': result.get('data') if result.get('data') is not None else result.get('result'),
                    'message': result.get('message', '')
                }

            logger.error(f"Plugin '{plugin_name}' method '{method}' failed: {result.get('message')}")
            response = {
                'status': 'error' if status == 'error' else status,
                'message': result.get('message', 'Unknown error')
            }
            if result.get('data') is not None:
                response['data'] = result.get('data')
            if result.get('required_permissions') is not None:
                response['required_permissions'] = result.get('required_permissions')
            return response
        except Exception as e:
            logger.bind(
                event="plugin_execution_error",
                module="agent",
                error_type=type(e).__name__,
                plugin_name=plugin_name,
                method=method,
            ).opt(exception=True).error(f"插件 '{plugin_name}' 方法 '{method}' 执行异常: {e}")
            return {
                'status': 'error',
                'message': str(e)
            }
    
    async def get_available_skills(self) -> List[Dict[str, Any]]:
        """
        获取available、skills相关数据或当前状态。
        调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
        """
        logger.info("Getting available skills")
        if self._db_session is None:
            # 技能列表是能力注入的必需输入，DB 不可用时必须失败，禁止静默返回空列表
            raise RuntimeError("数据库会话不可用，无法获取技能列表")
        try:
            registry = self.skill_engine.registry
            skills = registry.list_all()

            skill_list = []
            for skill in skills:
                stats = self.skill_engine.get_skill_statistics(skill.name)
                # 直接从 list_all 返回的 ORM 对象读取 config，
                # 避免 load_from_db 的额外数据库查询。config 字段是 JSON 类型，SQLAlchemy 已自动反序列化为 dict。
                skill_config = skill.config if isinstance(skill.config, dict) else {}
                skill_list.append({
                    'name': skill.name,
                    'version': skill.version,
                    'description': skill.description,
                    'enabled': skill.enabled,
                    'usage_count': skill.usage_count,
                    'stats': stats,
                    'config': skill_config,
                })

            logger.info(f"Found {len(skill_list)} available skills")
            return skill_list
        except Exception as e:
            logger.bind(
                event="get_skills_error",
                module="agent",
                error_type=type(e).__name__,
            ).opt(exception=True).error(f"获取可用技能列表失败: {e}")
            raise
    
    async def get_available_plugins(self) -> List[Dict[str, Any]]:
        """
        获取available、plugins相关数据或当前状态。
        未 loaded 的插件返回 loaded=False, tools=[]，不再触发 lazy load。
        """
        logger.info("Getting available plugins")
        try:
            discovered_plugins = self.plugin_manager.discover_plugins()

            plugin_list = []
            for plugin_info in discovered_plugins:
                plugin_name = plugin_info.get('name')
                if not plugin_name:
                    continue

                if plugin_name not in self.plugin_manager.loaded_plugins:
                    # 未 loaded 的插件不再 lazy load，直接返回空 tools
                    # lifespan startup 已加载所有 enabled 插件，未 loaded 意味着用户禁用或加载失败
                    plugin_list.append({
                        'name': plugin_name,
                        'version': plugin_info.get('version'),
                        'description': plugin_info.get('description'),
                        'loaded': False,
                        'tools': [],
                    })
                    continue

                # 已 loaded 的插件正常读取 tools 与 info
                tools = self.plugin_manager.get_plugin_tools(plugin_name)
                info = self.plugin_manager.get_plugin_info(plugin_name)

                plugin_list.append({
                    'name': plugin_name,
                    'version': plugin_info.get('version'),
                    'description': plugin_info.get('description'),
                    'loaded': info.get('loaded', False) if info else False,
                    'tools': tools,
                })

            logger.info(f"Found {len(plugin_list)} available plugins (loaded: {len(self.plugin_manager.loaded_plugins)})")
            return plugin_list
        except Exception as e:
            logger.bind(
                event="get_plugins_error",
                module="agent",
                error_type=type(e).__name__,
            ).opt(exception=True).error(f"获取可用插件列表失败: {e}")
            raise
    
    async def _build_conversation_history(self, session_id: str, max_turns: int = 20) -> list:
        """
        从记忆管理器中构建对话历史消息列表，用于注入到 LLM 调用中。
        返回 [{"role": "user"|"assistant", "content": "..."}] 格式。
        对单条消息内容做字符截断，防止超大消息撑爆上下文窗口。
        """
        if not self.memory_manager:
            # 记忆管理器未注入属于构造配置错误，必须显式失败，
            # 禁止 LLM 在零历史下继续对话（与构建失败传播原则一致）
            raise RuntimeError("记忆管理器未注入，无法构建对话历史")
        try:
            memories = await self.memory_manager.get_short_term_memories(
                session_id=session_id, limit=max_turns
            )
            history = []
            for mem in reversed(memories):
                if mem.role in ("user", "assistant"):
                    content = mem.content or ""
                    original_len = len(content)
                    if original_len > MAX_HISTORY_MESSAGE_CHARS:
                        content = content[:MAX_HISTORY_MESSAGE_CHARS] + (
                            f"\n[消息已截断，原始长度: {original_len} 字符]"
                        )
                    history.append({"role": mem.role, "content": content})
            return history
        except Exception as e:
            # 对话历史是 LLM 上下文的核心输入，构建失败必须传播，
            # 禁止 LLM 在零历史下继续对话
            logger.warning(f"构建对话历史失败: {e}")
            raise

    async def _check_and_handle_magic_command(
        self, user_input: str, context: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        检测用户输入是否包含魔法命令，如果匹配则执行对应处理程序。
        返回命令执行结果字典，如果不是命令则返回 None。
        """
        registry = get_magic_command_registry()
        cmd_name, cmd_args, remaining = registry.parse_message(user_input)
        if cmd_name is None:
            return None

        command = registry.get_command(cmd_name)
        if command is None:
            return {
                "is_command": True,
                "command_name": cmd_name,
                "success": False,
                "message": f"未知命令: /{cmd_name}，输入 /help 查看可用命令",
            }

        logger.bind(
            event="magic_command_detected",
            command=cmd_name,
            session_id=context.get("session_id", ""),
        ).info(f"检测到魔法命令: /{cmd_name}")

        try:
            ctx = {
                "session_id": context.get("session_id", "default"),
                "workspace_id": context.get("workspace_id", "default"),
                "user_id": context.get("user_id", ""),
                "model_name": context.get("model", "default"),
                "db": context.get("db"),
            }
            result = await command.handler(ctx)
            result["is_command"] = True
            result["command_name"] = cmd_name
            return result
        except Exception as exc:
            logger.bind(
                event="magic_command_error",
                command=cmd_name,
            ).error(f"魔法命令执行失败: {exc}")
            return {
                "is_command": True,
                "command_name": cmd_name,
                "success": False,
                "message": f"命令执行失败: {str(exc)}",
            }

    async def _auto_compress_context(
        self, context: Dict[str, Any], messages: list
    ) -> list:
        """
        自动检测并压缩对话上下文。
        当 token 使用量超过阈值时触发压缩，返回压缩后的消息列表。
        使用 CompactionManager 进行结构化摘要压缩，断路器保护避免反复失败。
        """
        model_name = context.get("model", "default")
        budget = TokenBudget(model_name=model_name)
        current_tokens = budget.count_messages(messages)
        # 更新计数器后检查压缩阈值
        budget.track(current_tokens)

        if (
            not budget.should_compress()
            and len(messages) <= COMPACTION_MESSAGE_THRESHOLD
        ):
            return messages

        # 使用 CompactionManager 进行压缩，窗口大小取自 TokenBudget
        compaction = CompactionManager(model_context_window=budget.max_tokens)

        # 设置 LLM 调用函数：复用 executor 的 LLM 配置解析与调用能力
        # 构建最小化上下文，仅包含配置解析所需字段，避免注入对话历史
        async def _compaction_llm_call(prompt: str, **kwargs) -> str:
            summary_ctx: Dict[str, Any] = {
                "provider": context.get("provider"),
                "model": context.get("model"),
                "db": context.get("db"),
                "request_id": context.get("request_id"),
            }
            result = await self.executor._call_llm_api(prompt, summary_ctx)
            if isinstance(result, dict) and result.get("ok"):
                return result.get("response", "") or ""
            # 摘要 LLM 调用失败必须显式抛出，由 CompactionManager 记录失败状态
            error_message = "未知错误"
            if isinstance(result, dict):
                error_obj = result.get("error") or {}
                if isinstance(error_obj, dict):
                    error_message = str(error_obj.get("message") or "未知错误")
                else:
                    error_message = str(error_obj)
            else:
                error_message = str(result)
            raise RuntimeError(f"压缩摘要 LLM 调用失败: {error_message}")

        compaction.set_llm_call(_compaction_llm_call)

        result = await compaction.compact(messages=messages)
        compressed_messages = result["messages"]
        if result.get("error"):
            # 压缩失败必须可见：记录错误事件，但保留原始历史继续对话（历史不能丢）
            logger.bind(
                event="auto_context_compression_failed",
                module="agent",
                original_count=len(messages),
                error=str(result.get("error")),
            ).error(f"上下文压缩失败，继续使用原始历史: {result.get('error')}")

        logger.bind(
            event="auto_context_compressed",
            original_count=len(messages),
            compressed_count=len(compressed_messages),
            tokens_before=current_tokens,
            tokens_after=budget.count_messages(compressed_messages),
            compacted=result.get("compacted", False),
        ).info("对话上下文已自动压缩")
        return compressed_messages

    async def _handle_magic_command_or_yield(
        self, user_input: str, context: Dict[str, Any]
    ) -> AsyncGenerator[Any, None]:
        """检测魔法命令，匹配时 yield 命令事件并触发提前退出。

        非魔法命令时不 yield 任何事件，正常返回；魔法命令时 yield
        magic_command（与可选 context_cleared）事件后 raise _StreamEarlyExit。
        """
        cmd_result = await self._check_and_handle_magic_command(user_input, context)
        if cmd_result is None:
            return
        yield {
            "type": "magic_command",
            "command_name": cmd_result.get("command_name", ""),
            "content": json.dumps(cmd_result, ensure_ascii=False, default=str),
        }
        if cmd_result.get("clears_context"):
            yield {"type": "context_cleared", "content": ""}
        raise _StreamEarlyExit()

    async def _prepare_role_and_capabilities(
        self,
        user_input: str,
        context: Dict[str, Any],
        _ttft_session_id: str,
        _ttft_t0: float,
    ) -> None:
        """流式入口兼容 façade，启用角色引擎后执行统一准备管线。"""
        await self._prepare_execution_context(
            user_input,
            context,
            _ttft_session_id,
            _ttft_t0,
            enable_role_engine=True,
        )

    async def _prepare_execution_context(
        self,
        user_input: str,
        context: Dict[str, Any],
        ttft_session_id: str = "",
        ttft_started_at: float = 0.0,
        *,
        enable_role_engine: bool,
    ) -> None:
        """统一上下文准备管线，通过参数显式声明是否加载角色引擎。"""
        stage_started_at = ttft_started_at or time.time()
        self._prepare_context(user_input, context)
        role_id = context.get("role_id") if enable_role_engine else None
        soul_injection_enabled = True
        if role_id and hasattr(self, 'soul_state_manager') and self.soul_state_manager is not None:
            soul_injection_enabled = self.soul_state_manager.is_injection_enabled()
            if not soul_injection_enabled:
                logger.bind(event="soul_injection_skipped", module="agent").info(
                    f"灵魂注入已禁用，跳过角色引擎加载 (workspace_id={context.get('workspace_id', 'unknown')})"
                )
        if role_id and soul_injection_enabled:
            request_db = context.get("db")
            if request_db is None:
                # 角色注入被启用但 DB 不可用，属于配置不一致，必须失败而非静默跳过
                raise RuntimeError("启用角色引擎但 context['db'] 不可用，无法加载角色")
            with ttft_stage_logger("role_engine", ttft_session_id, stage_started_at):
                role_engine = RoleEngine(db=request_db)
                role = role_engine.load_role(role_id)
                if role:
                    context = role_engine.apply_role_to_context(role, context)
                    if hasattr(self, 'soul_state_manager') and self.soul_state_manager is not None:
                        self.soul_state_manager.mark_injection_completed()
        with ttft_stage_logger("inject_capabilities", ttft_session_id, stage_started_at):
            await self._inject_runtime_capabilities(context)
        build_multimodal_context(user_input, context)
        build_thinking_context(context)

    async def _build_session_history(
        self,
        user_input: str,
        context: Dict[str, Any],
        session_id: str,
        _ttft_session_id: str,
        _ttft_t0: float,
        state: Dict[str, Any],
    ) -> AsyncGenerator[Any, None]:
        """构建对话历史、自动压缩、检索长期记忆。

        yield 压缩状态事件（若历史超过统一阈值）；通过 state["effective_user_input"]
        返回构建后的有效用户输入，供后续意图识别与工具循环使用。
        """
        with ttft_stage_logger("build_history", _ttft_session_id, _ttft_t0):
            conversation_history = await self._build_conversation_history(session_id)
        # 与自动压缩共用阈值，避免进度事件和实际压缩条件漂移。
        if len(conversation_history) > COMPACTION_MESSAGE_THRESHOLD:
            yield build_status_event("compressing", "正在压缩对话上下文")
        with ttft_stage_logger("auto_compress", _ttft_session_id, _ttft_t0, min_elapsed_ms=50):
            context["conversation_history"] = await self._auto_compress_context(
                context, conversation_history
            )
        effective_user_input = build_effective_user_input(user_input, context)
        # 自动检索相关长期记忆（stream 路径）
        if context.get("retrieve_long_term_memory", True) and self.memory_manager:
            _memory_extra: Dict[str, Any] = {}
            # 记忆检索失败必须传播，禁止 LLM 在缺失记忆的情况下继续对话
            with ttft_stage_logger("retrieve_memories", _ttft_session_id, _ttft_t0, extra_fields=_memory_extra):
                relevant_memories = await self._retrieve_relevant_memories(
                    user_input=effective_user_input,
                    context=context,
                )
                _memory_extra["memory_count"] = len(relevant_memories) if relevant_memories else 0
                if relevant_memories:
                    context["vector_retrieved_memories"] = relevant_memories
                    logger.info(f"Stream: 检索到 {len(relevant_memories)} 条相关长期记忆")
        state["effective_user_input"] = effective_user_input

    async def process_stream(self, user_input: str, context: Dict[str, Any]):
        """流式处理输入，编排上下文、计划、工具回环与最终清理。"""
        _ttft_t0 = time.time()
        _ttft_session_id = context.get("session_id", "")
        logger.info(f"Processing user input (stream), length={len(user_input)}")
        self.skill_results = []
        self.plugin_results = []
        self.root_abort_controller = AbortController()
        yield build_status_event("starting", "正在准备对话上下文")
        # TTFT 诊断：首个 SSE 事件已发出，记录从入口到此处的耗时
        logger.bind(
            event="ttft_first_event", module="agent", session_id=_ttft_session_id,
            elapsed_ms=round((time.time() - _ttft_t0) * 1000, 2),
        ).info("首个 SSE 事件已发送（TTFT 基准点）")
        # 共享状态字典：在子方法间传递需要跨方法共享的变量
        state: Dict[str, Any] = {
            "full_content": "", "full_reasoning": "",
            "accumulated_tool_events": [], "round_count": 0,
            "user_input": user_input, "main_completed": False,
        }
        current_task = asyncio.current_task()
        session_id = context.get("session_id", "default")
        task_user_id = str(context.get("user_id", ""))
        _stream_start_time = time.time()
        # 将当前协程注册为活跃任务，供取消端点查找
        if current_task is not None and session_id:
            register_agent_task(task_user_id, session_id, current_task)
        try:
            # 1. 魔法命令处理：匹配时 yield 命令事件并 raise _StreamEarlyExit
            async for event in self._handle_magic_command_or_yield(user_input, context):
                yield event
            # 2. 角色与能力准备（含灵魂注入检查、角色引擎、能力注入、多模态/思考上下文）
            await self._prepare_role_and_capabilities(user_input, context, _ttft_session_id, _ttft_t0)
            # 3. 会话历史构建（含压缩、长期记忆检索），结果写入 state["effective_user_input"]
            async for event in self._build_session_history(
                user_input, context, session_id, _ttft_session_id, _ttft_t0, state
            ):
                yield event
            # 4. 单一轮次协调器准备模型原生执行步骤
            yield build_status_event("planning", "正在生成执行计划")
            with ttft_stage_logger("prepare_turn", _ttft_session_id, _ttft_t0):
                intent, entities, plan = await self.turn_coordinator.prepare_turn(
                    state["effective_user_input"],
                    context,
                )
            context["plan"] = plan
            context["intent"] = intent
            context["entities"] = entities
            yield {"type": "plan", "plan": plan}
            # 5. 初始化工具调用循环相关状态
            state["final_only_mode"] = is_final_only_mode(context)
            if not context.get("_rollback_manager"):
                context["_rollback_manager"] = RollbackManager()
            # 6. 工具调用主循环：状态机推进 + 取消传播 + 预算追踪
            async for event in self._stream_orchestrator.run_tool_calls_loop(
                context,
                current_task,
                session_id,
                state,
            ):
                yield event
            state["main_completed"] = True
        except _StreamEarlyExit:
            pass
        finally:
            # 7. 流结束清理：TaskCompleted 钩子 + update_memory + 数据收集 + abort 清理
            abort_controller = self.root_abort_controller
            self.root_abort_controller = None
            await self._stream_orchestrator.finalize(
                StreamFinalizationContext(
                    user_input=user_input,
                    context=context,
                    state=state,
                    started_at=_stream_start_time,
                    task_user_id=task_user_id,
                    session_id=session_id,
                    current_task=current_task,
                    abort_controller=abort_controller,
                )
            )

    async def process(self, user_input: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        处理用户输入的完整流程：意图识别、规划、执行、反馈。
        自动注入对话历史以支持多轮对话上下文。
        支持多模态附件和思考模式参数。
        优先检测魔法命令，匹配时跳过 LLM 处理。
        """
        logger.info(f"Processing user input, length={len(user_input)}")

        # 魔法命令分发 + 上下文准备 + 能力注入 + 多模态/思考
        early = await self._prepare_process_context(user_input, context)
        if early is not None:
            return early

        # 注册活跃任务，供取消端点查找
        session_id = context.get("session_id", "default")
        task_user_id = str(context.get("user_id", ""))
        current_task = asyncio.current_task()
        if current_task is not None and session_id:
            register_agent_task(task_user_id, session_id, current_task)

        try:
            conversation_history = await self._build_conversation_history(session_id)
            # 自动检测并压缩上下文
            context["conversation_history"] = await self._auto_compress_context(
                context, conversation_history
            )
            effective_user_input = build_effective_user_input(user_input, context)

            intent, entities, plan = await self._prepare_turn(
                effective_user_input, user_input, context
            )
            experiences, relevant_memories = await self._retrieve_experiences_and_memories(
                effective_user_input, context
            )

            workflow_result, workflow_early = await self._execute_workflow_if_present(
                context, len(experiences)
            )
            if workflow_early is not None:
                return workflow_early

            results, plan_early = await self._plan_executor.execute_plan(
                plan, intent, entities, user_input, context
            )
            if plan_early is not None:
                return plan_early

            return await self._finalize_process_response(
                user_input, context, results, experiences, relevant_memories, workflow_result
            )
        except asyncio.CancelledError:
            logger.info(f"Agent task cancelled for session {session_id}")
            return self._build_cancelled_response()
        finally:
            unregister_agent_task(task_user_id, session_id, current_task)

    async def _prepare_process_context(
        self, user_input: str, context: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """魔法命令分发 + 上下文准备 + 能力注入 + 多模态/思考上下文构建。

        命中魔法命令时返回响应字典，process 应立即返回；否则返回 None 继续
        后续意图识别、规划、执行流程。
        """
        # 检测魔法命令
        cmd_result = await self._check_and_handle_magic_command(user_input, context)
        if cmd_result is not None:
            response_text = cmd_result.get("message", "")
            if cmd_result.get("success"):
                return {
                    "status": "success",
                    "response": response_text,
                    "is_magic_command": True,
                    "command_name": cmd_result.get("command_name", ""),
                    "command_result": cmd_result,
                }
            return {
                "status": "error",
                "response": response_text,
                "error": cmd_result.get("message", "命令执行失败"),
                "is_magic_command": True,
                "command_name": cmd_result.get("command_name", ""),
            }

        await self._prepare_execution_context(
            user_input,
            context,
            enable_role_engine=True,
        )
        return None

    async def _prepare_turn(
        self,
        effective_user_input: str,
        user_input: str,
        context: Dict[str, Any],
    ) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
        """准备单一模型执行轮次并记录结构化指标。"""
        intent_start = time.perf_counter()
        intent, entities, plan = await self.turn_coordinator.prepare_turn(
            effective_user_input,
            context,
        )
        context["intent"] = intent
        context["entities"] = entities
        context["plan"] = plan
        intent_duration_ms = int((time.perf_counter() - intent_start) * 1000)
        self._schedule_record(
            node_type="intent_recognition",
            user_message=user_input,
            context=context,
            execution_duration_ms=intent_duration_ms,
            metadata={
                "intent": intent,
                "entities": entities
            }
        )
        return intent, entities, plan

    async def _retrieve_experiences_and_memories(
        self,
        effective_user_input: str,
        context: Dict[str, Any],
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """检索相关经验与长期记忆，命中时写入 context 并返回列表。"""
        experiences: List[Dict[str, Any]] = []
        if context.get('retrieve_experiences', True):
            experiences = await self._retrieve_relevant_experiences(
                user_input=effective_user_input,
                context=context
            )
            if experiences:
                context['relevant_experiences'] = experiences
                logger.info(f"Retrieved {len(experiences)} relevant experiences")

        relevant_memories: List[Dict[str, Any]] = []
        if context.get('retrieve_long_term_memory', True):
            relevant_memories = await self._retrieve_relevant_memories(
                user_input=effective_user_input,
                context=context,
            )
            if relevant_memories:
                context['vector_retrieved_memories'] = relevant_memories
                logger.info(f"Retrieved {len(relevant_memories)} long-term memories")

        return experiences, relevant_memories

    async def _execute_workflow_if_present(
        self,
        context: Dict[str, Any],
        experiences_count: int,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        """若上下文携带工作流定义或 ID，执行工作流；workflow_only 时构建提前返回响应。

        返回 (workflow_result, early_return)。early_return 非 None 时 process 应立即返回。
        """
        workflow_result: Optional[Dict[str, Any]] = None
        if self.workflow_engine and (
            context.get('workflow_definition') is not None
            or context.get('workflow_id') is not None
        ):
            workflow_result = await self._execute_workflow_from_context(context)
            if workflow_result:
                context['workflow_result'] = workflow_result
                if context.get('workflow_only'):
                    early_return = self._apply_output_mode(
                        {
                            "status": workflow_result.get("status", "completed"),
                            "response": workflow_result.get("last_result", workflow_result),
                            "results": [
                                {
                                    "type": "workflow",
                                    "step": {"action": "workflow_execution"},
                                    "result": workflow_result,
                                }
                            ],
                            "workflows_executed": 1,
                            "experiences_used": experiences_count,
                        },
                        context,
                    )
                    return workflow_result, early_return
        return workflow_result, None

    async def _finalize_process_response(
        self,
        user_input: str,
        context: Dict[str, Any],
        results: List[Dict[str, Any]],
        experiences: List[Dict[str, Any]],
        relevant_memories: List[Dict[str, Any]],
        workflow_result: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """生成最终响应 + 错误汇总 + 更新记忆 + 经验提取 + 输出装配。"""
        final_response = await self.feedback.generate_response(results, context)

        first_error = None
        for item in results:
            result = item.get('result', item)
            if isinstance(result, dict) and result.get('error'):
                first_error = result.get('error')
                break

        if first_error:
            return self._apply_output_mode({
                "status": "error",
                "response": final_response,
                "results": results,
                "error": first_error
            }, context)

        await self.feedback.update_memory(
            user_input=user_input,
            response=final_response,
            context=context
        )

        if context.get('extract_experience', False):
            await self._extract_and_store_experience(
                user_input=user_input,
                context=context,
                results=results,
                status='success' if final_response else 'failed'
            )

        skill_count = sum(1 for r in results if r.get('type') == 'skill')
        plugin_count = sum(1 for r in results if r.get('type') == 'plugin')

        reasoning_parts: List[str] = []
        for item in results:
            result = item.get('result', item)
            if isinstance(result, dict) and result.get('reasoning_content'):
                reasoning_parts.append(result['reasoning_content'])

        output: Dict[str, Any] = {
            "status": "completed",
            "response": final_response,
            "results": results,
            "experiences_used": len(experiences),
            "memories_used": len(relevant_memories),
            "skills_executed": skill_count,
            "plugins_executed": plugin_count,
            "skill_results": self.skill_results.copy(),
            "plugin_results": self.plugin_results.copy()
        }
        if workflow_result:
            output["workflow_result"] = workflow_result
        if reasoning_parts:
            output["reasoning_content"] = "\n".join(reasoning_parts)
        return self._apply_output_mode(output, context)

    def _build_cancelled_response(self) -> Dict[str, Any]:
        """构建任务取消时的统一响应字典。"""
        return {
            "status": "cancelled",
            "response": "",
            "results": [],
            "experiences_used": 0,
            "memories_used": 0,
            "skills_executed": 0,
            "plugins_executed": 0,
            "skill_results": [],
            "plugin_results": [],
        }
    async def handle_confirmation(self, confirmed: bool, step: Dict, context: Dict) -> Dict[str, Any]:
        """
        处理用户对操作步骤的确认或取消：确认时执行步骤，取消时返回 cancelled 状态。
        用于需要用户二次确认的危险操作流程（如文件删除、命令执行等）。
        """
        self._prepare_context(context.get("message", ""), context)

        if confirmed:
            result = await self.executor.execute_step(step, context)
            return {"status": "executed", "result": result}
        else:
            return {"status": "cancelled", "message": "User cancelled the operation"}
    
    async def _retrieve_relevant_experiences(
        self,
        user_input: str,
        context: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        从经验记忆中检索与当前用户输入相关的历史经验。
        通过 ExperienceManager 进行语义匹配，最多返回 3 条相关经验，
        每条包含类型、标题、内容、置信度和触发条件。
        """
        try:
            db = context.get('db')
            if not db:
                logger.debug("无可用数据库会话，跳过经验检索")
                return []
            
            manager = self._experience_manager_factory(db)
            
            task_context = {
                'description': user_input,
                'task_type': context.get('task_type', 'general'),
                'intent': context.get('intent', {})
            }
            
            experiences = await manager.retrieve_relevant_experiences(
                task_context=task_context,
                max_experiences=3
            )
            
            formatted_experiences = []
            for exp in experiences:
                formatted_experiences.append({
                    'type': exp.experience_type,
                    'title': exp.title,
                    'content': exp.content,
                    'confidence': exp.confidence,
                    'trigger': exp.trigger_conditions
                })
            
            return formatted_experiences

        except (SQLAlchemyError, asyncio.TimeoutError, ValueError) as e:
            logger.bind(
                event="experience_retrieval_error",
                module="agent",
                error_type=type(e).__name__,
            ).opt(exception=True).error(f"检索相关经验失败: {e}")
            raise

    async def _retrieve_relevant_memories(
        self,
        user_input: str,
        context: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        使用长期记忆的混合检索能力获取相关记忆，并整理为可注入上下文的结构。
        """
        if not self.memory_manager:
            # 记忆管理器未注入属于构造配置错误，必须显式失败，
            # 禁止在缺失记忆检索能力的情况下继续对话
            raise RuntimeError("记忆管理器未注入，无法检索长期记忆")

        try:
            selected_memory_ids = context.get("selected_memory_ids") or []
            selected_memories = []
            if selected_memory_ids:
                selected_memories = await self.memory_manager.get_memories_by_ids(
                    selected_memory_ids,
                    user_id=context.get("user_id"),
                    workspace_id=context.get("workspace_id", "default"),
                )
            related_memories = await self.memory_manager.search_memories(
                query=user_input,
                limit=5,
                user_id=context.get('user_id'),
                include_archived=False,
                use_vector=True,
                workspace_id=context.get("workspace_id", "default"),
            )
            memories = []
            seen_memory_ids = set()
            for memory in [*selected_memories, *related_memories]:
                if memory.id in seen_memory_ids:
                    continue
                seen_memory_ids.add(memory.id)
                memories.append(memory)
            return [
                {
                    'id': memory.id,
                    'content': memory.content,
                    'importance': memory.importance,
                    'confidence': memory.confidence,
                    'quality_score': memory.quality_score,
                }
                for memory in memories
            ]
        except (SQLAlchemyError, asyncio.TimeoutError, ValueError) as e:
            logger.bind(
                event="long_term_memory_retrieval_error",
                module="agent",
                error_type=type(e).__name__,
            ).opt(exception=True).error(f"检索长期记忆失败: {e}")
            raise

    async def _execute_workflow_from_context(self, context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        从上下文中提取工作流定义或工作流 ID，并执行对应工作流。
        """
        if not self.workflow_engine:
            return None

        workflow_definition = context.get('workflow_definition')
        workflow_id = context.get('workflow_id')
        workflow_name = context.get('workflow_name')

        if workflow_definition is None and workflow_id is not None:
            if self._workflow_repository is None:
                return {
                    'status': 'failed',
                    'error': 'Workflow repository is not configured',
                }
            workflow_record = await self._workflow_repository.find_by_id(workflow_id)
            if workflow_record is None:
                return {
                    'status': 'failed',
                    'error': f'Workflow {workflow_id} not found',
                }
            workflow_definition = workflow_record.definition
            workflow_name = workflow_record.name

        if workflow_definition is None:
            return None

        return await self.workflow_engine.execute_definition(
            workflow_definition,
            workflow_id=workflow_id,
            workflow_name=workflow_name,
            user_id=context.get('user_id'),
            input_context=context.get('workflow_input_context', {}),
            format_hint=context.get('workflow_format'),
        )
    
    async def _extract_and_store_experience(
        self,
        user_input: str,
        context: Dict[str, Any],
        results: List[Dict],
        status: str
    ) -> None:
        """
        从会话执行结果中提取可复用的经验并持久化存储。
        通过 ExperienceExtractor 分析用户目标、执行步骤和最终结果，
        提取有价值的经验模式保存到经验文件。
        """
        try:
            db = context.get('db')
            if not db:
                logger.debug("无可用数据库会话，跳过经验提取")
                return
            
            execution_steps = []
            for i, result in enumerate(results, 1):
                step = {
                    'action': result.get('action', f'Step {i}'),
                    'result': result.get('message', result.get('status', 'Unknown')),
                    'success': result.get('status') == 'success'
                }
                execution_steps.append(step)
            
            experience_data = await self.experience_extractor.extract_from_session(
                user_goal=user_input,
                execution_steps=execution_steps,
                final_result=context.get('final_result', ''),
                status=status,
                session_id=context.get('session_id', '')
            )

            if not experience_data:
                logger.info("No experience extracted from session")
                return

            logger.info(
                f"Extracted experience and saved to file: {experience_data.get('save_result', {}).get('file_name', '')}"
            )
            
        except (SQLAlchemyError, asyncio.TimeoutError, ValueError, json.JSONDecodeError) as e:
            logger.bind(
                event="experience_extraction_error",
                module="agent",
                error_type=type(e).__name__,
            ).opt(exception=True).error(f"经验提取与存储失败: {e}")
    
    def _collect_skill_plugin_results(self) -> Dict[str, Any]:
        """
        汇总当前会话中所有技能和插件的执行统计。
        返回包含技能/插件各自的总数、成功数、失败数和详细结果的字典。
        """
        logger.info("Collecting skill and plugin execution results")
        
        skill_results_summary: dict[str, Any] = {
            'total': len(self.skill_results),
            'successful': sum(1 for r in self.skill_results if r.get('success', False)),
            'failed': sum(1 for r in self.skill_results if not r.get('success', False)),
            'details': self.skill_results.copy()
        }

        plugin_results_summary: dict[str, Any] = {
            'total': len(self.plugin_results),
            'successful': sum(1 for r in self.plugin_results if r.get('success', False)),
            'failed': sum(1 for r in self.plugin_results if not r.get('success', False)),
            'details': self.plugin_results.copy()
        }
        
        logger.info(f"Collected {skill_results_summary['total']} skill results, {plugin_results_summary['total']} plugin results")
        
        return {
            'skills': skill_results_summary,
            'plugins': plugin_results_summary,
            'overall_success': skill_results_summary['successful'] > 0 or plugin_results_summary['successful'] > 0
        }
    
    def _generate_skill_plugin_feedback(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """
        根据技能和插件执行统计生成反馈摘要。
        计算各自的成功率，成功率低于 50% 时标记 needs_attention 告警。
        """
        logger.info("Generating feedback for skill and plugin executions")
        
        skills = results.get('skills', {})
        plugins = results.get('plugins', {})
        
        skill_success_rate = 0
        if skills.get('total', 0) > 0:
            skill_success_rate = skills['successful'] / skills['total']
        
        plugin_success_rate = 0
        if plugins.get('total', 0) > 0:
            plugin_success_rate = plugins['successful'] / plugins['total']
        
        feedback_messages = []
        
        if skills['total'] > 0:
            feedback_messages.append(f"Executed {skills['total']} skills with {skills['successful']} successful")
            if skill_success_rate < 0.5:
                feedback_messages.append(f"Warning: Low skill success rate ({skill_success_rate:.1%})")
        
        if plugins['total'] > 0:
            feedback_messages.append(f"Executed {plugins['total']} plugins with {plugins['successful']} successful")
            if plugin_success_rate < 0.5:
                feedback_messages.append(f"Warning: Low plugin success rate ({plugin_success_rate:.1%})")
        
        if not feedback_messages:
            feedback_messages.append("No skills or plugins were executed")
        
        logger.info(f"Generated feedback: {'; '.join(feedback_messages)}")
        
        return {
            'skill_success_rate': skill_success_rate,
            'plugin_success_rate': plugin_success_rate,
            'messages': feedback_messages,
            'needs_attention': skill_success_rate < 0.5 or plugin_success_rate < 0.5
        }
    
    def clear_results(self) -> None:
        """
        清空当前会话中累积的技能和插件执行结果列表。
        通常在新轮对话开始时调用，避免历史执行结果干扰后续判断。
        """
        logger.info("Clearing skill and plugin results")
        self.skill_results.clear()
        self.plugin_results.clear()
        logger.info("Results cleared successfully")

    async def _self_correction_loop(
        self,
        step: Dict[str, Any],
        context: Dict[str, Any],
        error: Exception,
    ) -> Dict[str, Any]:
        """
        自主纠错循环：诊断错误 -> 生成修复计划 -> 回滚 -> 重新执行。
        最多执行 AGENT_SELF_CORRECTION_MAX_ROUNDS 轮纠错，超出则请求人工介入。
        """
        max_rounds = self._max_self_correction_rounds
        rollback_manager = context.get("_rollback_manager")

        for correction_round in range(1, max_rounds + 1):
            logger.bind(
                event="self_correction_round",
                module="agent",
                round=correction_round,
                max_rounds=max_rounds,
            ).info(f"自主纠错第 {correction_round}/{max_rounds} 轮")

            # 1. 诊断错误
            diagnosis = await self.feedback.diagnose_error(error, context)

            # 2. 生成修复计划
            fix_plan = self.turn_coordinator.build_recovery_step(diagnosis)

            # 3. 回滚到上一个稳定状态
            if rollback_manager:
                restored_context = rollback_manager.get_context_after_rollback()
                if restored_context:
                    # 只更新非内部键的上下文
                    for key, value in restored_context.items():
                        if not key.startswith("_"):
                            context[key] = value

            # 4. 执行修复计划
            try:
                result = await self.executor.execute_step(fix_plan, context)
                if result.get("status") != "failed":
                    logger.bind(
                        event="self_correction_success",
                        module="agent",
                        round=correction_round,
                    ).info(f"自主纠错第 {correction_round} 轮成功")
                    return result
                error = Exception(result.get("response", "修复计划执行失败"))
            except Exception as e:
                error = e

        # 超出最大纠错轮数，请求人工介入
        logger.bind(
            event="self_correction_exhausted",
            module="agent",
            max_rounds=max_rounds,
        ).warning(f"自主纠错 {max_rounds} 轮后仍失败，需要人工介入")

        return {
            "status": "needs_human_intervention",
            "response": f"自主纠错 {max_rounds} 轮后仍失败，需要人工介入",
            "error": str(error),
        }
