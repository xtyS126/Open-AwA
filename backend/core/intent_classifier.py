"""
意图分类器：基于关键词匹配 + LLM fallback 的轻量级意图识别。
支持五种意图类型：chat（闲聊）、code（编程）、search（搜索）、task（任务）、manage（管理）。
"""
import re
from typing import Optional
from enum import Enum


class IntentType(Enum):
    CHAT = "chat"
    CODE = "code"
    SEARCH = "search"
    TASK = "task"
    MANAGE = "manage"


# 关键词到意图的映射表，优先级从高到低
INTENT_KEYWORDS: dict[IntentType, list[str]] = {
    IntentType.CODE: [
        "写代码", "编程", "实现", "修改代码", "重构", "修复bug", "修bug",
        "创建文件", "新建文件", "添加功能", "新增功能", "改代码", "写函数",
        "实现功能", "修复", "修改文件", "改文件", "重写", "优化代码",
        "code", "implement", "refactor", "fix bug", "create file",
    ],
    IntentType.SEARCH: [
        "搜索", "查", "查找", "找一下", "搜索一下", "帮我查", "查询",
        "搜一下", "找找", "搜索资料", "查资料", "调研", "搜索文档",
        "search", "find", "look up", "research",
    ],
    IntentType.TASK: [
        "任务", "执行", "运行", "批量", "自动", "定时", "计划",
        "预约", "编排", "工作流", "多步骤", "复杂任务",
        "task", "execute", "batch", "automate", "schedule",
    ],
    IntentType.MANAGE: [
        "设置", "配置", "管理", "修改设置", "添加插件", "安装插件",
        "启用", "禁用", "删除插件", "插件管理", "技能管理",
        "记忆管理", "角色管理", "模型管理", "计费", "账单",
        "settings", "config", "manage", "plugin", "billing",
    ],
}


class IntentClassifier:
    """意图分类器：先关键词匹配，失败时返回默认 chat（未来可接入 LLM fallback）"""

    def classify(self, message: str) -> IntentType:
        """根据消息内容分类意图"""
        if not message or not message.strip():
            return IntentType.CHAT

        message_lower = message.lower()

        # 按关键词匹配（优先级从高到低遍历）
        for intent_type in IntentType:
            if intent_type == IntentType.CHAT:
                continue  # chat 是默认兜底
            keywords = INTENT_KEYWORDS.get(intent_type, [])
            for keyword in keywords:
                if keyword.lower() in message_lower:
                    return intent_type

        # 默认返回 chat
        return IntentType.CHAT

    def classify_with_confidence(self, message: str) -> tuple[IntentType, float]:
        """带置信度的分类，用于未来 LLM fallback 的触发判断"""
        intent = self.classify(message)
        if intent == IntentType.CHAT:
            return intent, 0.5  # 默认 chat 置信度较低
        return intent, 0.8  # 关键词匹配置信度较高