from typing import Dict, List, Any, Optional
from loguru import logger
from .comprehension import ComprehensionLayer
from .planner import PlanningLayer
from .executor import ExecutionLayer
from .feedback import FeedbackLayer
from memory.experience_manager import ExperienceManager
from skills.experience_extractor import ExperienceExtractor
from skills.skill_engine import SkillEngine
from plugins.plugin_manager import PluginManager
from skills.skill_registry import SkillRegistry
from plugins.plugin_loader import PluginLoader
from db.models import SessionLocal


class AIAgent:
    def __init__(self):
        self.comprehension = ComprehensionLayer()
        self.planner = PlanningLayer()
        self.executor = ExecutionLayer()
        self.feedback = FeedbackLayer()
        self.experience_extractor = ExperienceExtractor()
        
        db_session = SessionLocal()
        self.skill_engine = SkillEngine(db_session)
        self.plugin_manager = PluginManager()
        
        self.skill_results: List[Dict[str, Any]] = []
        self.plugin_results: List[Dict[str, Any]] = []
        
        logger.info("AI Agent initialized with SkillEngine and PluginManager integration")
    
    async def execute_skill(self, skill_name: str, inputs: Dict, context: Dict) -> Dict[str, Any]:
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
    
    async def process(self, user_input: str, context: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(f"Processing user input: {user_input}")
        
        intent = await self.comprehension.recognize_intent(user_input)
        logger.debug(f"Recognized intent: {intent}")
        
        entities = await self.comprehension.extract_entities(user_input)
        logger.debug(f"Extracted entities: {entities}")
        
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
        
        if context.get('enable_skill_plugin', True):
            auto_results = await self._auto_execute_skills_and_plugins(
                intent=intent,
                entities=entities,
                context=context
            )
            if auto_results:
                context['auto_execution_results'] = auto_results
                logger.info(f"Auto-executed {len(auto_results.get('skills', []))} skills and {len(auto_results.get('plugins', []))} plugins")
        
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
                    continue
            
            result = await self.executor.execute_step(step, context)
            results.append({
                'type': 'execution',
                'step': step,
                'result': result
            })
            
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
        
        final_response = await self.feedback.generate_response(results)
        
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
    
    async def handle_confirmation(self, confirmed: bool, step: Dict, context: Dict) -> Dict[str, Any]:
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
        """检索相关经验"""
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
        """提取并存储经验"""
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
            
            manager = ExperienceManager(db)
            experience = await manager.add_experience(
                experience_type=experience_data['experience_type'],
                title=experience_data['title'],
                content=experience_data['content'],
                trigger_conditions=experience_data['trigger_conditions'],
                confidence=experience_data['confidence'],
                source_task=experience_data.get('source_task', 'general'),
                metadata=experience_data.get('metadata')
            )
            
            logger.info(f"Extracted and stored experience: {experience.title} (ID: {experience.id})")
            
        except Exception as e:
            logger.error(f"Error extracting and storing experience: {e}")
