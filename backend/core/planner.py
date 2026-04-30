"""
核心执行编排模块，负责 Agent 主流程中的理解、规划、执行、反馈或记录能力。
这些文件决定了用户请求在内部被如何拆解、编排以及最终落地执行。
"""

from typing import Dict, List, Any
from loguru import logger


class PlanningLayer:
    """
    封装与PlanningLayer相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    def __init__(self):
        """
        处理init相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        self.available_tools = []
        logger.info("PlanningLayer initialized")
    
    def register_tool(self, tool: Dict[str, Any]):
        """
        处理register、tool相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        self.available_tools.append(tool)
        logger.debug(f"Registered tool: {tool.get('name')}")
    
    async def create_plan(
        self,
        intent: str,
        entities: Dict[str, Any],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        创建plan相关对象、记录或执行结果。
        实现过程中往往会涉及初始化、组装、持久化或返回统一结构。
        """
        logger.info(f"Creating plan for intent: {intent}")
        
        if intent == "execute":
            plan = await self._create_execution_plan(entities, context)
        elif intent == "query":
            plan = await self._create_query_plan(entities, context)
        elif intent == "explain":
            plan = await self._create_explain_plan(entities, context)
        else:
            plan = await self._create_chat_plan(entities, context)
        
        relevant_experiences = context.get('relevant_experiences', [])
        if relevant_experiences:
            plan['relevant_experiences'] = relevant_experiences
            logger.debug(f"Added {len(relevant_experiences)} experiences to plan context")
        
        logger.debug(f"Created plan with {len(plan.get('steps', []))} steps")
        return plan
    
    async def _create_execution_plan(
        self,
        entities: Dict[str, Any],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        处理create、execution、plan相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
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
        """
        处理create、query、plan相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
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
        """
        处理create、explain、plan相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
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
        """
        处理create、chat、plan相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
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
        """
        处理analyze、dependencies相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
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
        """
        处理find、parallel、steps相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
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
    
    def generate_experience_prompt(self, experiences: List[Dict[str, Any]]) -> str:
        """
        处理generate、experience、prompt相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        if not experiences:
            return ""
        
        prompt_parts = ["\n\n## 相关经验提示\n"]
        prompt_parts.append("根据历史经验，以下列方法可能对当前任务有帮助：\n")
        
        for i, exp in enumerate(experiences, 1):
            title = exp.get('title', '无标题')
            confidence = exp.get('confidence', 0)
            content = exp.get('content', '')
            trigger = exp.get('trigger', '通用')
            prompt_parts.append(f"\n{i}. **{title}** (置信度: {confidence:.2f})\n")
            prompt_parts.append(f"   {content}\n")
            prompt_parts.append(f"   适用场景：{trigger}\n")
        
        return "".join(prompt_parts)
