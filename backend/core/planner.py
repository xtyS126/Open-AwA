from typing import Dict, List, Any, Optional
from loguru import logger


class PlanningLayer:
    def __init__(self):
        self.available_tools = []
        logger.info("PlanningLayer initialized")
    
    def register_tool(self, tool: Dict[str, Any]):
        self.available_tools.append(tool)
        logger.debug(f"Registered tool: {tool.get('name')}")
    
    async def create_plan(
        self,
        intent: str,
        entities: Dict[str, Any],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        logger.info(f"Creating plan for intent: {intent}")
        
        if intent == "execute":
            plan = await self._create_execution_plan(entities, context)
        elif intent == "query":
            plan = await self._create_query_plan(entities, context)
        elif intent == "explain":
            plan = await self._create_explain_plan(entities, context)
        else:
            plan = await self._create_chat_plan(entities, context)
        
        logger.debug(f"Created plan with {len(plan.get('steps', []))} steps")
        return plan
    
    async def _create_execution_plan(
        self,
        entities: Dict[str, Any],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        steps = []
        
        if "files" in entities:
            steps.append({
                "step": 1,
                "action": "read_files",
                "targets": entities["files"],
                "purpose": "读取文件内容"
            })
        
        if "commands" in entities:
            steps.append({
                "step": len(steps) + 1,
                "action": "execute_command",
                "command": entities["commands"][0],
                "purpose": "执行命令"
            })
        else:
            steps.append({
                "step": len(steps) + 1,
                "action": "llm_generate",
                "task": context.get("task", ""),
                "purpose": "生成执行计划"
            })
        
        return {
            "intent": "execute",
            "steps": steps,
            "requires_confirmation": True
        }
    
    async def _create_query_plan(
        self,
        entities: Dict[str, Any],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        return {
            "intent": "query",
            "steps": [
                {
                    "step": 1,
                    "action": "llm_query",
                    "query": context.get("query", ""),
                    "purpose": "查询信息"
                }
            ],
            "requires_confirmation": False
        }
    
    async def _create_explain_plan(
        self,
        entities: Dict[str, Any],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        return {
            "intent": "explain",
            "steps": [
                {
                    "step": 1,
                    "action": "llm_explain",
                    "target": context.get("target", ""),
                    "purpose": "解释说明"
                }
            ],
            "requires_confirmation": False
        }
    
    async def _create_chat_plan(
        self,
        entities: Dict[str, Any],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        return {
            "intent": "chat",
            "steps": [
                {
                    "step": 1,
                    "action": "llm_chat",
                    "message": context.get("message", ""),
                    "purpose": "对话交流"
                }
            ],
            "requires_confirmation": False
        }
    
    async def analyze_dependencies(self, steps: List[Dict]) -> Dict[str, Any]:
        dependency_graph = {}
        
        for i, step in enumerate(steps):
            deps = []
            if step.get("action") == "read_files":
                for j, later_step in enumerate(steps[i+1:], i+1):
                    if any(target in str(later_step) for target in step.get("targets", [])):
                        deps.append(j)
            
            dependency_graph[i] = deps
        
        return {
            "graph": dependency_graph,
            "can_parallelize": self._find_parallel_steps(dependency_graph)
        }
    
    def _find_parallel_steps(self, dependency_graph: Dict[int, List[int]]) -> List[List[int]]:
        parallel_groups = []
        processed = set()
        
        for step_id in sorted(dependency_graph.keys()):
            if step_id in processed:
                continue
            
            group = [step_id]
            for other_id in dependency_graph.keys():
                if other_id > step_id and step_id not in dependency_graph.get(other_id, []):
                    if other_id not in processed:
                        group.append(other_id)
                        processed.add(other_id)
            
            parallel_groups.append(group)
            processed.update(group)
        
        return parallel_groups
