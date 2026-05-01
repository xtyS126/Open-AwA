"""
核心执行编排模块，负责 Agent 主流程中的理解、规划、执行、反馈或记录能力。
这些文件决定了用户请求在内部被如何拆解、编排以及最终落地执行。
"""

import asyncio
import json
import time
from typing import Any, Dict, List, Optional
from loguru import logger
from .comprehension import ComprehensionLayer
from .planner import PlanningLayer
from .executor import ExecutionLayer
from .feedback import FeedbackLayer
from .metrics import record_tool_execution_metric
from memory.experience_manager import ExperienceManager
from skills.experience_extractor import ExperienceExtractor
from skills.skill_engine import SkillEngine
from plugins.plugin_manager import PluginManager
from plugins import plugin_instance
from mcp.manager import MCPManager
from workflow.engine import WorkflowEngine
from .behavior_logger import behavior_logger
from .conversation_recorder import conversation_recorder
from api.services.chat_protocol import emit_task_event, emit_tool_event


from sqlalchemy.orm import Session

class AIAgent:
    """
    封装与AIAgent相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    def __init__(self, db_session: Session = None):
        """
        初始化 AI Agent，包含理解层、规划层、执行层、反馈层以及记忆管理。
        """
        self.comprehension = ComprehensionLayer()
        self.planner = PlanningLayer()
        self.executor = ExecutionLayer()
        self.feedback = FeedbackLayer()
        self.experience_extractor = ExperienceExtractor()
        
        self._db_session = db_session
        self.skill_engine = SkillEngine(self._db_session)
        self.plugin_manager = plugin_instance.get()
        self._closed = False
        
        self.skill_results: List[Dict[str, Any]] = []
        self.plugin_results: List[Dict[str, Any]] = []

        # 初始化记忆管理器，并注入到反馈层
        self.memory_manager = None
        self.workflow_engine = None
        if self._db_session:
            from memory.manager import MemoryManager
            self.memory_manager = MemoryManager(self._db_session)
            self.feedback.set_memory_manager(self.memory_manager)
            self.workflow_engine = WorkflowEngine(db_session=self._db_session, skill_engine=self.skill_engine)
        
        logger.info("AI Agent initialized with SkillEngine and PluginManager integration")
    
    def _handle_record_task_result(self, task: asyncio.Task) -> None:
        """
        处理handle、record、task、result相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
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

    @staticmethod
    def _is_final_only_mode(context: Dict[str, Any]) -> bool:
        """
        判断当前请求是否要求只返回最终答案。

        `output_mode=final_only` 是显式协议约定，`suppress_reasoning`
        则作为兼容旧调用方的兜底开关。
        """
        output_mode = str(context.get("output_mode", "")).strip().lower()
        return output_mode == "final_only" or bool(context.get("suppress_reasoning"))

    def _strip_reasoning_content(self, payload: Any) -> Any:
        """
        递归移除对外响应中的思维链字段，避免 final_only 只在顶层生效。
        """
        if isinstance(payload, dict):
            return {
                key: self._strip_reasoning_content(value)
                for key, value in payload.items()
                if key != "reasoning_content"
            }
        if isinstance(payload, list):
            return [self._strip_reasoning_content(item) for item in payload]
        return payload

    def _apply_output_mode(self, payload: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """
        根据上下文裁剪对外响应，确保渠道级输出模式真正落到返回值上。
        """
        if not self._is_final_only_mode(context):
            return payload
        return self._strip_reasoning_content(payload)

    def _apply_scheduled_execution_defaults(self, context: Dict[str, Any]) -> None:
        """
        为定时任务执行场景补齐隔离开关，避免污染聊天记录、记忆与经验链路。
        """
        if not context.get("scheduled_execution_isolated"):
            return

        context.setdefault("disable_behavior_logging", True)
        context.setdefault("disable_conversation_record", True)
        context.setdefault("disable_memory_update", True)
        context.setdefault("retrieve_experiences", False)
        context.setdefault("retrieve_long_term_memory", False)
        context.setdefault("enable_skill_plugin", False)
        context.setdefault("extract_experience", False)
        context.setdefault("output_mode", "final_only")

    def _prepare_context(self, user_input: str, context: Dict[str, Any]) -> None:
        """
        统一补齐执行上下文，保证数据库会话与隔离开关能够透传到执行层。
        """
        self._apply_scheduled_execution_defaults(context)

        if "message" not in context:
            context["message"] = user_input

        if self._db_session and context.get("db") is None:
            context["db"] = self._db_session

        context["_record_hook"] = self._schedule_record

    def _build_multimodal_context(self, user_input: str, context: Dict[str, Any]) -> None:
        """
        根据上下文中的 attachments 构建多模态消息内容。
        若存在附件且 provider 支持多模态，则生成 content parts 数组；
        否则保持纯文本格式以保证向后兼容。
        """
        attachments = context.get("attachments")
        if not attachments:
            return
        provider = context.get("provider", "")
        model = context.get("model", "")
        from core.model_service import build_multimodal_message
        multimodal_content = build_multimodal_message(user_input, attachments, provider)
        context["_multimodal_content"] = multimodal_content

    def _build_thinking_context(self, context: Dict[str, Any]) -> None:
        """
        根据上下文中的 thinking_enabled 和 thinking_depth 构建思考参数。
        仅当 thinking_enabled 为 True 时才生成参数。
        """
        if not context.get("thinking_enabled"):
            return
        thinking_depth = context.get("thinking_depth", 0)
        if not thinking_depth or thinking_depth < 1:
            return
        provider = context.get("provider", "")
        model = context.get("model", "")
        from core.model_service import build_thinking_params
        thinking_params = build_thinking_params(provider, model, thinking_depth)
        if thinking_params:
            context["_thinking_params"] = thinking_params

    @staticmethod
    def _build_status_event(phase: str, message: str, **extra: Any) -> Dict[str, Any]:
        """
        构造统一的流式阶段状态事件，便于前端在首包前显示当前进度。
        """
        payload: Dict[str, Any] = {
            "type": "status",
            "phase": phase,
            "message": message,
        }
        payload.update(extra)
        return payload

    @staticmethod
    def _get_stream_tool_kind(tool_name: str) -> str:
        """
        根据原生 function name 推断工具类别，便于前端展示正确的分组标签。
        """
        normalized = str(tool_name or "").strip()
        if normalized.startswith("plugin_"):
            return "plugin"
        if normalized.startswith("mcp_"):
            return "mcp"
        return "tool"

    @staticmethod
    def _summarize_stream_tool_result(exec_result: Dict[str, Any]) -> str:
        """
        为流式工具事件生成简短摘要，避免前端只能看到空的占位节点。
        """
        if not isinstance(exec_result, dict):
            return ""

        if not exec_result.get("ok"):
            return str(exec_result.get("error") or "工具调用失败")

        payload = exec_result.get("result")
        if isinstance(payload, dict):
            for key in ("message", "response", "stdout", "status"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return "工具调用完成"

    @staticmethod
    def _summarize_skill_capabilities(skills: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        将技能列表收敛为适合注入模型上下文的轻量摘要，避免把统计和配置细节全部暴露给提示词。
        """
        summarized_skills: List[Dict[str, Any]] = []
        for skill in skills:
            if not isinstance(skill, dict):
                continue
            if not skill.get("enabled"):
                continue

            summarized_skills.append({
                "name": skill.get("name", ""),
                "description": skill.get("description", ""),
            })

        return summarized_skills

    @staticmethod
    def _summarize_plugin_capabilities(plugins: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        仅保留插件名称、描述和工具摘要，用于让模型理解当前会话有哪些插件可被平台调度。
        """
        summarized_plugins: List[Dict[str, Any]] = []
        for plugin in plugins:
            if not isinstance(plugin, dict):
                continue

            raw_tools = plugin.get("tools") if isinstance(plugin.get("tools"), list) else []
            summarized_tools = []
            for tool in raw_tools:
                if not isinstance(tool, dict):
                    continue
                summarized_tools.append({
                    "name": tool.get("name", ""),
                    "description": tool.get("description", ""),
                    "method": tool.get("method", ""),
                    "parameters": tool.get("parameters"),
                    "default_params": tool.get("default_params"),
                })

            summarized_plugins.append({
                "name": plugin.get("name", ""),
                "description": plugin.get("description", ""),
                "loaded": bool(plugin.get("loaded", False)),
                "tools": summarized_tools,
            })

        return summarized_plugins

    async def _collect_mcp_capabilities(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        采集 MCP 连接态信息，用于提示模型平台是否已接入 MCP Server 以及当前有哪些已连接工具。
        这里只描述能力边界，不直接触发 MCP 调用。
        """
        chat_dispatch_enabled = bool(context.get("enable_mcp_tool_dispatch", False))
        default_payload = {
            "platform_supported": True,
            "chat_dispatch_enabled": chat_dispatch_enabled,
            "connected_servers": [],
            "tools": [],
        }

        try:
            manager = MCPManager()
            servers = manager.get_all_servers()
            tools = await manager.get_all_tools()

            default_payload["connected_servers"] = [
                {
                    "server_id": item.get("server_id", ""),
                    "name": item.get("name", ""),
                    "transport_type": item.get("transport_type", ""),
                    "connected": bool(item.get("connected", False)),
                    "tools_count": int(item.get("tools_count", 0) or 0),
                }
                for item in servers
                if isinstance(item, dict)
            ]
            default_payload["tools"] = [
                {
                    "server_id": item.get("server_id", ""),
                    "server_name": item.get("server_name", ""),
                    "name": item.get("tool", {}).get("name", "") if isinstance(item.get("tool"), dict) else "",
                    "description": item.get("tool", {}).get("description", "") if isinstance(item.get("tool"), dict) else "",
                }
                for item in tools
                if isinstance(item, dict)
            ]
            return default_payload
        except Exception as e:
            logger.bind(
                event="get_mcp_capabilities_error",
                module="agent",
                error_type=type(e).__name__,
            ).warning(f"获取 MCP 能力摘要失败: {e}")
            default_payload["error"] = str(e)
            return default_payload

    async def _inject_runtime_capabilities(self, context: Dict[str, Any]) -> None:
        """
        在进入最终模型回答前，把当前会话可用的技能、插件和 MCP 连接态写入上下文。
        这样模型在回答“我能不能调用某能力”时能基于真实运行态，而不是凭空猜测。
        """
        if isinstance(context.get("agent_capabilities"), dict):
            return

        skill_plugin_enabled = bool(context.get("enable_skill_plugin", True))
        skills: List[Dict[str, Any]] = []
        plugins: List[Dict[str, Any]] = []

        if skill_plugin_enabled:
            skills = self._summarize_skill_capabilities(await self.get_available_skills())
            plugins = self._summarize_plugin_capabilities(await self.get_available_plugins())

        context["agent_capabilities"] = {
            "skills_enabled": skill_plugin_enabled,
            "plugins_enabled": skill_plugin_enabled,
            "tool_dispatch_mode": "platform_managed",
            "skills": skills,
            "plugins": plugins,
            "mcp": await self._collect_mcp_capabilities(context),
        }

        # 从运行态能力摘要构建原生 tool_calls 定义，使 LLM 能通过 function calling 协议触发工具
        if not context.get("_tools"):
            context["_tools"] = self._build_native_tools(context["agent_capabilities"])

    @staticmethod
    def _build_native_tools(capabilities: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        将 agent_capabilities 中的插件/MCP 工具转换为 OpenAI 兼容的 tools 参数格式，
        使 LLM 能通过原生 function calling 协议触发工具调用，而不是在文本中模拟。
        """
        tools: List[Dict[str, Any]] = []
        seen_names: set = set()

        plugins = (
            capabilities.get("plugins")
            if isinstance(capabilities.get("plugins"), list)
            else []
        )
        for plugin in plugins:
            if not isinstance(plugin, dict):
                continue
            plugin_name = str(plugin.get("name", "")).strip()
            if not plugin_name:
                continue
            plugin_tools = plugin.get("tools") if isinstance(plugin.get("tools"), list) else []
            for tool_def in plugin_tools:
                if not isinstance(tool_def, dict):
                    continue
                tool_name = str(tool_def.get("name", "")).strip()
                if not tool_name:
                    continue

                func_name = f"plugin_{plugin_name}__{tool_name}"
                if func_name in seen_names:
                    continue
                seen_names.add(func_name)

                params = tool_def.get("parameters")
                if not isinstance(params, dict) or not params:
                    params = {"type": "object", "properties": {}}

                tool_entry = {
                    "type": "function",
                    "function": {
                        "name": func_name,
                        "description": str(tool_def.get("description", "")),
                        "parameters": params,
                    },
                }
                tools.append(tool_entry)

        # MCP 工具也转换为原生 tool_calls
        mcp = capabilities.get("mcp") if isinstance(capabilities.get("mcp"), dict) else {}
        if mcp.get("chat_dispatch_enabled", False):
            mcp_tools = mcp.get("tools") if isinstance(mcp.get("tools"), list) else []
            for mcp_tool in mcp_tools:
                if not isinstance(mcp_tool, dict):
                    continue
                server_name = str(mcp_tool.get("server_name", mcp_tool.get("server_id", ""))).strip()
                tool_name = str(mcp_tool.get("name", "")).strip()
                if not server_name or not tool_name:
                    continue

                func_name = f"mcp_{server_name}__{tool_name}"
                if func_name in seen_names:
                    continue
                seen_names.add(func_name)

                mcP_params = mcp_tool.get("parameters")
                if not isinstance(mcP_params, dict) or not mcP_params:
                    mcP_params = {"type": "object", "properties": {}}

                tool_entry = {
                    "type": "function",
                    "function": {
                        "name": func_name,
                        "description": str(mcp_tool.get("description", "")),
                        "parameters": mcP_params,
                    },
                }
                tools.append(tool_entry)

        if tools:
            logger.bind(
                event="native_tools_built",
                module="agent",
                tool_count=len(tools),
            ).debug(f"已构建 {len(tools)} 个原生工具定义")

        return tools

    def _schedule_record(
        self,
        *,
        node_type: str,
        user_message: str,
        context: Dict[str, Any],
        status: str = "success",
        error_message: str | None = None,
        llm_input: Any = None,
        llm_output: Any = None,
        llm_tokens_used: int | None = None,
        execution_duration_ms: int | None = None,
        metadata: Any = None,
    ) -> None:
        """
        处理schedule、record相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        user_id = context.get("user_id")
        session_id = context.get("session_id", "default")
        if not user_id:
            return

        disable_behavior_logging = bool(
            context.get("scheduled_execution_isolated") or context.get("disable_behavior_logging")
        )
        disable_conversation_record = bool(
            context.get("scheduled_execution_isolated") or context.get("disable_conversation_record")
        )

        if not disable_behavior_logging:
            behavior_entries = self._build_behavior_entries(
                user_id=user_id,
                node_type=node_type,
                status=status,
                error_message=error_message,
                llm_output=llm_output,
                llm_tokens_used=llm_tokens_used,
                execution_duration_ms=execution_duration_ms,
                metadata=metadata,
            )
            for entry in behavior_entries:
                task = asyncio.create_task(behavior_logger.record(entry))
                task.add_done_callback(lambda t: self._handle_record_task_result(t))

        if disable_conversation_record:
            return

        task = asyncio.create_task(
            conversation_recorder.record(
                node_type=node_type,
                session_id=session_id,
                user_message=user_message,
                user_id=user_id,
                provider=context.get("provider"),
                model=context.get("model"),
                llm_input=llm_input,
                llm_output=llm_output,
                llm_tokens_used=llm_tokens_used,
                execution_duration_ms=execution_duration_ms,
                status=status,
                error_message=error_message,
                metadata=metadata,
            )
        )
        task.add_done_callback(lambda t: self._handle_record_task_result(t))

    def _build_behavior_entries(
        self,
        *,
        user_id: str,
        node_type: str,
        status: str,
        error_message: str | None,
        llm_output: Any,
        llm_tokens_used: int | None,
        execution_duration_ms: int | None,
        metadata: Any,
    ) -> List[Dict[str, Any]]:
        """
        将运行态信息整理成轻量埋点结构，交给后台队列统一批量落库。
        这里仅做内存对象拼装，不直接触发数据库操作。
        """
        entries: List[Dict[str, Any]] = []
        action_type = ""
        details_str = ""

        if node_type == "llm_call":
            action_type = "llm_call"

            response_content = None
            if isinstance(llm_output, dict):
                response_content = llm_output.get("response") or llm_output.get("error")

            details_dict = {
                "duration_ms": execution_duration_ms,
                "status": status,
                "provider": metadata.get("provider") if isinstance(metadata, dict) else None,
                "model": metadata.get("model") if isinstance(metadata, dict) else None,
                "tokens_used": llm_tokens_used,
                "response_result": response_content,
            }
            details_str = json.dumps(details_dict, ensure_ascii=False)
        elif node_type == "tool_execution":
            action_type = "tool_usage"
            tool_name = "unknown"
            if isinstance(metadata, dict):
                if metadata.get("execution_type") == "skill":
                    tool_name = metadata.get("skill_name", "unknown")
                elif metadata.get("execution_type") == "plugin":
                    tool_name = metadata.get("plugin_name", "unknown")
            details_str = f"{tool_name}:" + json.dumps({"status": status}, ensure_ascii=False)
        elif node_type == "intent_recognition":
            action_type = "intent"
            details_str = metadata.get("intent", "unknown") if isinstance(metadata, dict) else str(metadata)

        if action_type:
            entries.append({
                "user_id": user_id,
                "action_type": action_type,
                "details": details_str,
            })

        if status == "error":
            entries.append({
                "user_id": user_id,
                "action_type": "error",
                "details": error_message or "Unknown error",
            })

        return entries

    async def execute_skill(self, skill_name: str, inputs: Dict, context: Dict) -> Dict[str, Any]:
        """
        处理execute、skill相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
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
        处理execute、plugin相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
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
            logger.info("No database session available, returning empty skill list")
            return []
        try:
            registry = self.skill_engine.registry
            skills = registry.list_all()
            
            skill_list = []
            for skill in skills:
                stats = self.skill_engine.get_skill_statistics(skill.name)
                skill_config = self.skill_engine.loader.load_from_db(skill.name) or {}
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
            return []
    
    async def get_available_plugins(self) -> List[Dict[str, Any]]:
        """
        获取available、plugins相关数据或当前状态。
        调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
        """
        logger.info("Getting available plugins")
        try:
            discovered_plugins = self.plugin_manager.discover_plugins()
            
            plugin_list = []
            for plugin_info in discovered_plugins:
                plugin_name = plugin_info.get('name')
                if plugin_name and plugin_name not in self.plugin_manager.loaded_plugins:
                    self.plugin_manager.load_plugin(plugin_name)

                tools = self.plugin_manager.get_plugin_tools(plugin_name)
                info = self.plugin_manager.get_plugin_info(plugin_name)
                
                plugin_list.append({
                    'name': plugin_name,
                    'version': plugin_info.get('version'),
                    'description': plugin_info.get('description'),
                    'loaded': info.get('loaded', False) if info else False,
                    'tools': tools
                })
            
            logger.info(f"Found {len(plugin_list)} available plugins")
            return plugin_list
        except Exception as e:
            logger.bind(
                event="get_plugins_error",
                module="agent",
                error_type=type(e).__name__,
            ).opt(exception=True).error(f"获取可用插件列表失败: {e}")
            return []
    
    async def _build_conversation_history(self, session_id: str, max_turns: int = 20) -> list:
        """
        从记忆管理器中构建对话历史消息列表，用于注入到 LLM 调用中。
        返回 [{"role": "user"|"assistant", "content": "..."}] 格式。
        """
        if not self.memory_manager:
            return []
        try:
            memories = await self.memory_manager.get_short_term_memories(
                session_id=session_id, limit=max_turns
            )
            # 按时间正序排列（get_short_term_memories 返回倒序）
            history = []
            for mem in reversed(memories):
                if mem.role in ("user", "assistant"):
                    history.append({"role": mem.role, "content": mem.content})
            return history
        except Exception as e:
            logger.warning(f"构建对话历史失败: {e}")
            return []

    async def process_stream(self, user_input: str, context: Dict[str, Any]):
        """
        流式处理用户输入，注入对话历史后调用大模型并实时 yield 数据块。
        支持 tool_calls 循环：检测到工具调用时自动执行并将结果回传 LLM。
        支持多模态附件和思考模式参数。
        """
        logger.info(f"Processing user input (stream), length={len(user_input)}")

        yield self._build_status_event("starting", "正在准备对话上下文")

        self._prepare_context(user_input, context)
        await self._inject_runtime_capabilities(context)

        # 构建多模态消息内容（若用户上传了附件）
        self._build_multimodal_context(user_input, context)

        # 构建思考模式参数（若用户开启了思考）
        self._build_thinking_context(context)

        # 构建对话历史并注入到上下文中
        session_id = context.get("session_id", "default")
        conversation_history = await self._build_conversation_history(session_id)
        context["conversation_history"] = conversation_history

        intent = await self.comprehension.recognize_intent(user_input)
        entities = await self.comprehension.extract_entities(user_input)

        yield self._build_status_event("planning", "正在生成执行计划")
        plan = await self.planner.create_plan(
            intent=intent,
            entities=entities,
            context=context,
        )
        context["plan"] = plan
        yield {
            "type": "plan",
            "plan": plan,
        }

        full_content = ""
        full_reasoning = ""

        final_only_mode = self._is_final_only_mode(context)

        round_count = 0
        max_rounds = 5

        while round_count < max_rounds:
            round_count += 1
            tool_calls_detected = False

            async for chunk in self.executor._call_llm_api_stream(user_input, context):
                if "error" in chunk:
                    yield {
                        "type": "error",
                        "error": chunk["error"]
                    }
                    return

                # 检测工具调用事件
                if chunk.get("type") == "tool_calls":
                    tool_calls_detected = True
                    tool_calls = chunk.get("tool_calls", [])

                    logger.info(f"Detected {len(tool_calls)} tool_calls in stream mode, executing...")

                    # 发射 task 事件
                    yield emit_task_event({
                        "step_count": len(tool_calls),
                        "steps": [{"name": tc.get("function", {}).get("name", "unknown")} for tc in tool_calls],
                    })

                    # 执行每个工具
                    tool_results = []
                    for tc in tool_calls:
                        tool_name = tc.get("function", {}).get("name", "unknown")
                        tool_id = tc.get("id", "")
                        tool_kind = self._get_stream_tool_kind(tool_name)

                        yield emit_tool_event({
                            "id": tool_id,
                            "kind": tool_kind,
                            "name": tool_name,
                            "status": "running",
                        })

                        result = await self.executor._execute_tool_call(tc, context)

                        yield emit_tool_event({
                            "id": tool_id,
                            "kind": tool_kind,
                            "name": tool_name,
                            "status": "completed" if result.get("ok") else "error",
                            "detail": self._summarize_stream_tool_result(result),
                            "output": result.get("result") if result.get("ok") else result.get("error"),
                        })

                        tool_results.append({"tool_call": tc, "result": result})

                    # 构建工具调用消息并注入到上下文中
                    tool_messages = []
                    tool_messages.append({
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": tc.get("id", ""),
                                "type": "function",
                                "function": {
                                    "name": tc.get("function", {}).get("name", ""),
                                    "arguments": tc.get("function", {}).get("arguments", ""),
                                }
                            }
                            for tc in tool_calls
                        ]
                    })
                    for tr in tool_results:
                        tool_messages.append(self.executor._build_tool_message(tr["tool_call"], tr["result"]))

                    context["_tool_messages"] = tool_messages
                    break  # 跳出 async for 循环，重新进入 while 循环进行下一轮 LLM 调用

                content = chunk.get("content", "")
                reasoning = chunk.get("reasoning_content", "")

                if final_only_mode:
                    reasoning = ""

                if content: full_content += content
                if reasoning: full_reasoning += reasoning

                output_chunk = {
                    "type": "chunk",
                    "content": content,
                }
                if reasoning:
                    output_chunk["reasoning_content"] = reasoning
                yield output_chunk

            if not tool_calls_detected:
                break  # 没有工具调用，退出 while 循环

        # Update memory after stream completes
        if full_content:
            await self.feedback.update_memory(
                user_input=user_input,
                response=full_content,
                context=context
            )

    async def process(self, user_input: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        处理用户输入的完整流程：意图识别、规划、执行、反馈。
        自动注入对话历史以支持多轮对话上下文。
        支持多模态附件和思考模式参数。
        """
        logger.info(f"Processing user input, length={len(user_input)}")

        self._prepare_context(user_input, context)
        await self._inject_runtime_capabilities(context)

        # 构建多模态消息内容（若用户上传了附件）
        self._build_multimodal_context(user_input, context)

        # 构建思考模式参数（若用户开启了思考）
        self._build_thinking_context(context)

        # 构建对话历史并注入到上下文中
        session_id = context.get("session_id", "default")
        conversation_history = await self._build_conversation_history(session_id)
        context["conversation_history"] = conversation_history

        intent_start = time.perf_counter()
        intent = await self.comprehension.recognize_intent(user_input)
        logger.debug(f"Recognized intent: {intent}")

        entities = await self.comprehension.extract_entities(user_input)
        logger.debug(f"Extracted entities: {entities}")
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
        
        experiences = []
        if context.get('retrieve_experiences', True):
            experiences = await self._retrieve_relevant_experiences(
                user_input=user_input,
                context=context
            )
            if experiences:
                context['relevant_experiences'] = experiences
                logger.info(f"Retrieved {len(experiences)} relevant experiences")

        relevant_memories = []
        if context.get('retrieve_long_term_memory', True):
            relevant_memories = await self._retrieve_relevant_memories(
                user_input=user_input,
                context=context,
            )
            if relevant_memories:
                context['vector_retrieved_memories'] = relevant_memories
                logger.info(f"Retrieved {len(relevant_memories)} long-term memories")

        workflow_result = None
        if self.workflow_engine and (context.get('workflow_definition') is not None or context.get('workflow_id') is not None):
            workflow_result = await self._execute_workflow_from_context(context)
            if workflow_result:
                context['workflow_result'] = workflow_result
                if context.get('workflow_only'):
                    return self._apply_output_mode(
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
                            "experiences_used": len(experiences),
                        },
                        context,
                    )
        
        plan = await self.planner.create_plan(
            intent=intent,
            entities=entities,
            context=context
        )
        logger.debug(f"Created plan: {plan}")
        
        auto_results = {"skills": [], "plugins": []}
        if context.get('enable_skill_plugin', True):
            matching_start = time.perf_counter()
            auto_results = await self._auto_execute_skills_and_plugins(
                intent=intent,
                entities=entities,
                context=context
            )
            matching_duration_ms = int((time.perf_counter() - matching_start) * 1000)
            if auto_results:
                context['auto_execution_results'] = auto_results
                logger.info(f"Auto-executed {len(auto_results.get('skills', []))} skills and {len(auto_results.get('plugins', []))} plugins")

            self._schedule_record(
                node_type="skill_plugin_matching",
                user_message=user_input,
                context=context,
                execution_duration_ms=matching_duration_ms,
                metadata={
                    "skills": [item.get('skill_name') for item in auto_results.get('skills', [])],
                    "plugins": [item.get('plugin_name') for item in auto_results.get('plugins', [])],
                    "skills_count": len(auto_results.get('skills', [])),
                    "plugins_count": len(auto_results.get('plugins', []))
                }
            )
        
        results = []
        for step in plan.get("steps", []):
            if context.get('enable_skill_plugin', True) and step.get('use_skill'):
                skill_name = step.get('skill_name')
                if skill_name:
                    skill_result = await self.execute_skill(
                        skill_name=skill_name,
                        inputs=step.get('inputs', {}),
                        context=context
                    )
                    results.append({
                        'type': 'skill',
                        'step': step,
                        'result': skill_result
                    })
                    self._schedule_record(
                        node_type="tool_execution",
                        user_message=user_input,
                        context=context,
                        status="success" if skill_result.get('status') in ('completed', 'success') else "error",
                        error_message=skill_result.get('error'),
                        llm_input=step,
                        llm_output=skill_result,
                        metadata={
                            "execution_type": "skill",
                            "skill_name": skill_name
                        }
                    )
                    record_tool_execution_metric("skill", skill_result.get("status", "unknown"))
                    continue
            
            if context.get('enable_skill_plugin', True) and step.get('use_plugin'):
                plugin_name = step.get('plugin_name')
                plugin_method = step.get('plugin_method')
                if plugin_name and plugin_method:
                    plugin_result = await self.execute_plugin(
                        plugin_name=plugin_name,
                        method=plugin_method,
                        **step.get('kwargs', {})
                    )
                    results.append({
                        'type': 'plugin',
                        'step': step,
                        'result': plugin_result
                    })
                    self._schedule_record(
                        node_type="tool_execution",
                        user_message=user_input,
                        context=context,
                        status="success" if plugin_result.get('status') in ('completed', 'success') else "error",
                        error_message=plugin_result.get('message'),
                        llm_input=step,
                        llm_output=plugin_result,
                        metadata={
                            "execution_type": "plugin",
                            "plugin_name": plugin_name,
                            "plugin_method": plugin_method
                        }
                    )
                    record_tool_execution_metric("plugin", plugin_result.get("status", "unknown"))
                    continue
            
            result = await self.executor.execute_step(step, context)
            results.append({
                'type': 'execution',
                'step': step,
                'result': result
            })
            self._schedule_record(
                node_type="tool_execution",
                user_message=user_input,
                context=context,
                status="success" if isinstance(result, dict) and result.get('status') in ['completed', 'success'] else "error",
                error_message=result.get('message') if isinstance(result, dict) else None,
                llm_input=step,
                llm_output=result,
                metadata={
                    "execution_type": "execution",
                    "action": step.get('action')
                }
            )
            
            if isinstance(result, dict):
                feedback = await self.feedback.evaluate_result(result)
                if feedback.get("needs_confirmation"):
                    return self._apply_output_mode({
                        "status": "awaiting_confirmation",
                        "message": feedback.get("message"),
                        "step": step,
                        "results": results
                    }, context)
                
                if feedback.get("needs_retry"):
                    retry_result = await self.executor.retry_step(step, context)
                    results[-1] = {
                        'type': 'execution',
                        'step': step,
                        'result': retry_result
                    }
        
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
        
        # 从执行结果中聚合推理内容
        reasoning_parts = []
        for item in results:
            result = item.get('result', item)
            if isinstance(result, dict) and result.get('reasoning_content'):
                reasoning_parts.append(result['reasoning_content'])
        
        output = {
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
    
    async def _auto_execute_skills_and_plugins(
        self,
        intent: Dict[str, Any],
        entities: Dict[str, Any],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        处理auto、execute、skills、and、plugins相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        logger.info("Auto-executing skills and plugins based on intent and entities")
        auto_results: dict[str, list[Any]] = {
            'skills': [],
            'plugins': []
        }

        try:
            if isinstance(intent, dict):
                intent_type = str(intent.get('type', ''))
                intent_action = str(intent.get('action', ''))
            else:
                intent_type = str(intent or '')
                intent_action = ''

            intent_keywords = f"{intent_type} {intent_action}".lower().strip()

            entities_list: List[Dict[str, Any]] = []
            if isinstance(entities, dict):
                raw_entities = entities.get('entities')
                if isinstance(raw_entities, list):
                    entities_list = [e for e in raw_entities if isinstance(e, dict)]
                else:
                    for entity_type, entity_values in entities.items():
                        if isinstance(entity_values, list):
                            entities_list.extend(
                                {
                                    'type': entity_type,
                                    'value': value
                                }
                                for value in entity_values
                            )

            available_skills = await self.get_available_skills()
            available_plugins = await self.get_available_plugins()

            for skill in available_skills:
                if not skill.get('enabled'):
                    continue
                if skill.get('config', {}).get('auto_executable') is False:
                    continue

                skill_name = skill.get('name', '')
                skill_description = skill.get('description', '').lower()

                if self._is_skill_relevant(skill_name, skill_description, intent_keywords, entities_list):
                    logger.info(f"Auto-selecting skill: {skill_name}")

                    skill_inputs = {
                        'intent': intent,
                        'entities': entities,
                        'context': context
                    }

                    skill_result = await self.execute_skill(
                        skill_name=skill_name,
                        inputs=skill_inputs,
                        context=context
                    )

                    if skill_result.get('status') in ('completed', 'success'):
                        auto_results['skills'].append({
                            'skill_name': skill_name,
                            'result': skill_result,
                            'reason': 'auto_selected'
                        })

            for plugin in available_plugins:
                plugin_name = plugin.get('name', '')
                plugin_tools = plugin.get('tools', [])

                for tool in plugin_tools:
                    tool_name = tool.get('name', '').lower()
                    tool_description = tool.get('description', '').lower()

                    if self._is_plugin_relevant(tool_name, tool_description, intent_keywords, entities_list):
                        logger.info(f"Auto-selecting plugin '{plugin_name}' tool '{tool.get('name')}'")

                        plugin_kwargs: Dict[str, Any] = {}
                        default_params = tool.get('default_params')
                        if isinstance(default_params, dict):
                            plugin_kwargs.update(default_params)
                        plugin_kwargs.update({
                            'intent': intent,
                            'entities': entities,
                            'context': context,
                        })

                        plugin_result = await self.execute_plugin(
                            plugin_name=plugin_name,
                            method=tool.get('method'),
                            **plugin_kwargs
                        )

                        if plugin_result.get('status') in ('completed', 'success'):
                            auto_results['plugins'].append({
                                'plugin_name': plugin_name,
                                'tool': tool.get('name'),
                                'result': plugin_result,
                                'reason': 'auto_selected'
                            })

            logger.info(f"Auto-execution completed: {len(auto_results['skills'])} skills, {len(auto_results['plugins'])} plugins")
            return auto_results

        except Exception as e:
            logger.bind(
                event="auto_execution_error",
                module="agent",
                error_type=type(e).__name__,
            ).opt(exception=True).error(f"自动执行技能/插件异常: {e}")
            return auto_results
    
    def _is_skill_relevant(
        self,
        skill_name: str,
        skill_description: str,
        intent_keywords: str,
        entities: List[Dict]
    ) -> bool:
        """
        处理is、skill、relevant相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        skill_name_lower = skill_name.lower()
        
        if any(keyword in skill_name_lower or keyword in skill_description 
               for keyword in intent_keywords.split() if len(keyword) > 3):
            return True
        
        entity_types = [entity.get('type', '').lower() for entity in entities]
        if any(entity_type in skill_name_lower or entity_type in skill_description 
               for entity_type in entity_types if entity_type):
            return True
        
        return False
    
    def _is_plugin_relevant(
        self,
        tool_name: str,
        tool_description: str,
        intent_keywords: str,
        entities: List[Dict]
    ) -> bool:
        """
        处理is、plugin、relevant相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        tool_name_lower = tool_name.lower()
        
        if any(keyword in tool_name_lower or keyword in tool_description 
               for keyword in intent_keywords.split() if len(keyword) > 3):
            return True
        
        entity_types = [entity.get('type', '').lower() for entity in entities]
        if any(entity_type in tool_name_lower or entity_type in tool_description 
               for entity_type in entity_types if entity_type):
            return True
        
        return False
    
    async def handle_confirmation(self, confirmed: bool, step: Dict, context: Dict) -> Dict[str, Any]:
        """
        处理handle、confirmation相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
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
        处理retrieve、relevant、experiences相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        try:
            db = context.get('db')
            if not db:
                logger.warning("No database session available for experience retrieval")
                return []
            
            manager = ExperienceManager(db)
            
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
            
        except Exception as e:
            logger.bind(
                event="experience_retrieval_error",
                module="agent",
                error_type=type(e).__name__,
            ).opt(exception=True).error(f"检索相关经验失败: {e}")
            return []

    async def _retrieve_relevant_memories(
        self,
        user_input: str,
        context: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        使用长期记忆的混合检索能力获取相关记忆，并整理为可注入上下文的结构。
        """
        if not self.memory_manager:
            return []

        try:
            memories = await self.memory_manager.search_memories(
                query=user_input,
                limit=5,
                user_id=context.get('user_id'),
                include_archived=False,
                use_vector=True,
            )
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
        except Exception as e:
            logger.bind(
                event="long_term_memory_retrieval_error",
                module="agent",
                error_type=type(e).__name__,
            ).opt(exception=True).error(f"检索长期记忆失败: {e}")
            return []

    async def _execute_workflow_from_context(self, context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        从上下文中提取工作流定义或工作流 ID，并执行对应工作流。
        """
        if not self.workflow_engine:
            return None

        workflow_definition = context.get('workflow_definition')
        workflow_id = context.get('workflow_id')
        workflow_name = context.get('workflow_name')

        if workflow_definition is None and workflow_id is not None and self._db_session is not None:
            from db.models import Workflow

            workflow_record = self._db_session.query(Workflow).filter(Workflow.id == workflow_id).first()
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
        处理extract、and、store、experience相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        try:
            db = context.get('db')
            if not db:
                logger.warning("No database session available for experience extraction")
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
            
        except Exception as e:
            logger.bind(
                event="experience_extraction_error",
                module="agent",
                error_type=type(e).__name__,
            ).opt(exception=True).error(f"经验提取与存储失败: {e}")
    
    def _collect_skill_plugin_results(self) -> Dict[str, Any]:
        """
        处理collect、skill、plugin、results相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
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
        处理generate、skill、plugin、feedback相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
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
        处理clear、results相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        logger.info("Clearing skill and plugin results")
        self.skill_results.clear()
        self.plugin_results.clear()
        logger.info("Results cleared successfully")
