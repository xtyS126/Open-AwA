from typing import Dict, List, Any, Optional
from loguru import logger
from .comprehension import ComprehensionLayer
from .planner import PlanningLayer
from .executor import ExecutionLayer
from .feedback import FeedbackLayer


class AIAgent:
    def __init__(self):
        self.comprehension = ComprehensionLayer()
        self.planner = PlanningLayer()
        self.executor = ExecutionLayer()
        self.feedback = FeedbackLayer()
        logger.info("AI Agent initialized")
    
    async def process(self, user_input: str, context: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(f"Processing user input: {user_input}")
        
        intent = await self.comprehension.recognize_intent(user_input)
        logger.debug(f"Recognized intent: {intent}")
        
        entities = await self.comprehension.extract_entities(user_input)
        logger.debug(f"Extracted entities: {entities}")
        
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
        
        return {
            "status": "completed",
            "response": final_response,
            "results": results
        }
    
    async def handle_confirmation(self, confirmed: bool, step: Dict, context: Dict) -> Dict[str, Any]:
        if confirmed:
            result = await self.executor.execute_step(step, context)
            return {"status": "executed", "result": result}
        else:
            return {"status": "cancelled", "message": "User cancelled the operation"}
