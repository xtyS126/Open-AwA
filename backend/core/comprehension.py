from typing import Dict, Any
from loguru import logger
import re


class ComprehensionLayer:
    def __init__(self):
        self.intent_patterns = {
            "execute": ["帮我", "执行", "完成", "做", "创建", "修改", "删除"],
            "query": ["查询", "找", "看看", "有什么", "多少"],
            "explain": ["解释", "说明", "为什么", "是什么"],
            "chat": ["聊", "说", "讲", "谈谈"]
        }
        logger.info("ComprehensionLayer initialized")
    
    async def recognize_intent(self, user_input: str) -> str:
        user_input_lower = user_input.lower()
        
        for intent, keywords in self.intent_patterns.items():
            for keyword in keywords:
                if keyword in user_input_lower:
                    logger.debug(f"Recognized intent: {intent} (matched keyword: {keyword})")
                    return intent
        
        logger.debug("Defaulting to 'chat' intent")
        return "chat"
    
    async def extract_entities(self, user_input: str) -> Dict[str, Any]:
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
        params = {}
        
        if intent == "execute":
            params["task"] = user_input
        elif intent == "query":
            params["query"] = user_input
        elif intent == "explain":
            params["target"] = user_input
        
        return params
