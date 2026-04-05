"""
核心执行编排模块，负责 Agent 主流程中的理解、规划、执行、反馈或记录能力。
这些文件决定了用户请求在内部被如何拆解、编排以及最终落地执行。
"""

from typing import Dict, Any
from loguru import logger
import re


class ComprehensionLayer:
    """
    封装与ComprehensionLayer相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    def __init__(self):
        """
        处理init相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        self.intent_patterns = {
            "execute": ["帮我", "执行", "完成", "做", "创建", "修改", "删除"],
            "query": ["查询", "找", "看看", "有什么", "多少"],
            "explain": ["解释", "说明", "为什么", "是什么"],
            "chat": ["聊", "说", "讲", "谈谈"]
        }
        logger.info("ComprehensionLayer initialized")
    
    async def recognize_intent(self, user_input: str) -> str:
        """
        处理recognize、intent相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        user_input_lower = user_input.lower()
        
        for intent, keywords in self.intent_patterns.items():
            for keyword in keywords:
                if keyword in user_input_lower:
                    logger.debug(f"Recognized intent: {intent} (matched keyword: {keyword})")
                    return intent
        
        logger.debug("Defaulting to 'chat' intent")
        return "chat"
    
    async def extract_entities(self, user_input: str) -> Dict[str, Any]:
        """
        处理extract、entities相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        entities = {}
        
        file_pattern = r'([a-zA-Z0-9_\-\.]+\.(?:py|js|ts|md|txt|json|yaml|yml))'
        files = re.findall(file_pattern, user_input)
        if files:
            entities["files"] = files
        
        path_pattern = r'/[\w/\\\-.]+'
        paths = re.findall(path_pattern, user_input)
        if paths:
            entities["paths"] = paths
        
        command_pattern = r'`([^`]+)`'
        commands = re.findall(command_pattern, user_input)
        if commands:
            entities["commands"] = commands
        
        url_pattern = r'https?://[^\s]+'
        urls = re.findall(url_pattern, user_input)
        if urls:
            entities["urls"] = urls
        
        logger.debug(f"Extracted entities: {entities}")
        return entities
    
    async def parse_parameters(self, user_input: str, intent: str) -> Dict[str, Any]:
        """
        解析parameters相关输入内容，并转换为内部可用结构。
        它常用于屏蔽外部协议差异并统一上层业务使用的数据格式。
        """
        params = {}
        
        if intent == "execute":
            params["task"] = user_input
        elif intent == "query":
            params["query"] = user_input
        elif intent == "explain":
            params["target"] = user_input
        
        return params
