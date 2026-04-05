"""
核心执行编排模块，负责 Agent 主流程中的理解、规划、执行、反馈或记录能力。
这些文件决定了用户请求在内部被如何拆解、编排以及最终落地执行。
"""

import asyncio
import json
import time
from typing import Dict, List, Any
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
from .behavior_logger import behavior_logger
from .conversation_recorder import conversation_recorder


from sqlalchemy.orm import Session

class AIAgent:
    """
    封装与AIAgent相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    def __init__(self, db_session: Session = None):
        """
        处理init相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        self.comprehension = ComprehensionLayer()
        self.planner = PlanningLayer()
        self.executor = ExecutionLayer()
        self.feedback = FeedbackLayer()
        self.experience_extractor = ExperienceExtractor()
        
        self._db_session = db_session
        self.skill_engine = SkillEngine(self._db_session)
        self.plugin_manager = PluginManager()
        self._closed = False
        
        self.skill_results: List[Dict[str, Any]] = []
        self.plugin_results: List[Dict[str, Any]] = []
        
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
                    'status': 'success',
                    'skill_name': skill_name,
                    'outputs': result.get('outputs', {}),
                    'steps': result.get('steps', []),
                    'execution_id': result.get('execution_id'),
                    'metrics': result.get('metrics', {})
                }
            else:
                logger.error(f"Skill '{skill_name}' execution failed: {result.get('error')}")
                return {
                    'status': 'failed',
                    'skill_name': skill_name,
                    'error': result.get('error', 'Unknown error'),
                    'outputs': result.get('outputs', {}),
                    'execution_id': result.get('execution_id')
                }
        except Exception as e:
            logger.error(f"Error executing skill '{skill_name}': {e}")
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
            
            if result.get('status') == 'success':
                logger.info(f"Plugin '{plugin_name}' method '{method}' executed successfully")
                return {
                    'status': 'success',
                    'data': result.get('data'),
                    'message': result.get('message', '')
                }
            else:
                logger.error(f"Plugin '{plugin_name}' method '{method}' failed: {result.get('message')}")
                return {
                    'status': 'failed',
                    'message': result.get('message', 'Unknown error')
                }
        except Exception as e:
            logger.error(f"Error executing plugin '{plugin_name}' method '{method}': {e}")
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
        try:
            registry = self.skill_engine.registry
            skills = registry.list_all()
            
            skill_list = []
            for skill in skills:
                stats = self.skill_engine.get_skill_statistics(skill.name)
                skill_list.append({
                    'name': skill.name,
                    'version': skill.version,
                    'description': skill.description,
                    'enabled': skill.enabled,
                    'usage_count': skill.usage_count,
                    'stats': stats
                })
            
            logger.info(f"Found {len(skill_list)} available skills")
            return skill_list
        except Exception as e:
            logger.error(f"Error getting available skills: {e}")
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
                info = self.plugin_manager.get_plugin_info(plugin_name)
                tools = self.plugin_manager.get_plugin_tools(plugin_name)
                
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
            logger.error(f"Error getting available plugins: {e}")
            return []
    
    async def process_stream(self, user_input: str, context: Dict[str, Any]):
        """
        流式处理用户输入，绕过复杂规划逻辑，直接调用大模型并实时 yield 数据块。
        """
        logger.info(f"Processing user input (stream): {user_input}")

        if "message" not in context:
            context["message"] = user_input
            
        context["_record_hook"] = self._schedule_record
            
        full_content = ""
        full_reasoning = ""
        
        async for chunk in self.executor._call_llm_api_stream(user_input, context):
            if "error" in chunk:
                yield {
                    "type": "error",
                    "error": chunk["error"]
                }
                return
                
            content = chunk.get("content", "")
            reasoning = chunk.get("reasoning_content", "")
            
            if content: full_content += content
            if reasoning: full_reasoning += reasoning
            
            yield {
                "type": "chunk",
                "content": content,
                "reasoning_content": reasoning
            }
            
        # Update memory after stream completes
        if full_content:
            await self.feedback.update_memory(
                user_input=user_input,
                response=full_content,
                context=context
            )

    async def process(self, user_input: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        处理process相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        logger.info(f"Processing user input: {user_input}")

        if "message" not in context:
            context["message"] = user_input
        context["_record_hook"] = self._schedule_record

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
                        status="success" if skill_result.get('status') == 'success' else "error",
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
                        status="success" if plugin_result.get('status') == 'success' else "error",
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
                    return {
                        "status": "awaiting_confirmation",
                        "message": feedback.get("message"),
                        "step": step,
                        "results": results
                    }
                
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
            return {
                "status": "error",
                "response": final_response,
                "results": results,
                "error": first_error
            }
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
        
        return {
            "status": "completed",
            "response": final_response,
            "results": results,
            "experiences_used": len(experiences),
            "skills_executed": skill_count,
            "plugins_executed": plugin_count,
            "skill_results": self.skill_results.copy(),
            "plugin_results": self.plugin_results.copy()
        }
    
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

                    if skill_result.get('status') == 'success':
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

                        plugin_result = await self.execute_plugin(
                            plugin_name=plugin_name,
                            method=tool.get('method'),
                            intent=intent,
                            entities=entities,
                            context=context
                        )

                        if plugin_result.get('status') == 'success':
                            auto_results['plugins'].append({
                                'plugin_name': plugin_name,
                                'tool': tool.get('name'),
                                'result': plugin_result,
                                'reason': 'auto_selected'
                            })

            logger.info(f"Auto-execution completed: {len(auto_results['skills'])} skills, {len(auto_results['plugins'])} plugins")
            return auto_results

        except Exception as e:
            logger.error(f"Error in auto-execution of skills and plugins: {e}")
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
            logger.error(f"Error retrieving experiences: {e}")
            return []
    
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
            logger.error(f"Error extracting and storing experience: {e}")
    
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
