from typing import Dict, List, Any, Optional
from loguru import logger
from .comprehension import ComprehensionLayer
from .planner import PlanningLayer
from .executor import ExecutionLayer
from .feedback import FeedbackLayer
from memory.experience_manager import ExperienceManager
from skills.experience_extractor import ExperienceExtractor


class AIAgent:
    def __init__(self):
        self.comprehension = ComprehensionLayer()
        self.planner = PlanningLayer()
        self.executor = ExecutionLayer()
        self.feedback = FeedbackLayer()
        self.experience_extractor = ExperienceExtractor()
        logger.info("AI Agent initialized with experience extraction enabled")
    
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
        
        results = []
        for step in plan.get("steps", []):
            result = await self.executor.execute_step(step, context)
            results.append(result)
            
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
                results[-1] = retry_result
        
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
        
        return {
            "status": "completed",
            "response": final_response,
            "results": results,
            "experiences_used": len(experiences)
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
