"""意图分类器测试：验证关键词匹配和置信度计算。"""

import pytest

from core.intent_classifier import IntentClassifier, IntentType


class TestIntentClassifier:
    """意图分类器单元测试"""

    def setup_method(self):
        self.classifier = IntentClassifier()

    def test_empty_message_returns_chat(self):
        """空消息应返回 chat 意图"""
        assert self.classifier.classify("") == IntentType.CHAT
        assert self.classifier.classify("   ") == IntentType.CHAT

    def test_none_message_returns_chat(self):
        """None 消息应返回 chat 意图"""
        assert self.classifier.classify(None) == IntentType.CHAT

    def test_chat_message_returns_chat(self):
        """普通闲聊消息应返回 chat 意图"""
        assert self.classifier.classify("你好") == IntentType.CHAT
        assert self.classifier.classify("今天天气怎么样") == IntentType.CHAT
        assert self.classifier.classify("hello world") == IntentType.CHAT

    def test_code_keyword_returns_code(self):
        """编程关键词应识别为 code 意图"""
        assert self.classifier.classify("帮我写代码") == IntentType.CODE
        assert self.classifier.classify("修改代码重构一下") == IntentType.CODE
        assert self.classifier.classify("修复bug") == IntentType.CODE
        assert self.classifier.classify("implement a function") == IntentType.CODE

    def test_search_keyword_returns_search(self):
        """搜索关键词应识别为 search 意图"""
        assert self.classifier.classify("搜索一下") == IntentType.SEARCH
        assert self.classifier.classify("帮我查一下资料") == IntentType.SEARCH
        assert self.classifier.classify("search for python") == IntentType.SEARCH

    def test_task_keyword_returns_task(self):
        """任务关键词应识别为 task 意图"""
        assert self.classifier.classify("执行任务") == IntentType.TASK
        assert self.classifier.classify("批量处理") == IntentType.TASK
        assert self.classifier.classify("automate the process") == IntentType.TASK

    def test_manage_keyword_returns_manage(self):
        """管理关键词应识别为 manage 意图"""
        assert self.classifier.classify("修改设置") == IntentType.MANAGE
        assert self.classifier.classify("添加插件") == IntentType.MANAGE
        assert self.classifier.classify("config update") == IntentType.MANAGE

    def test_code_priority_over_search(self):
        """编程关键词应优先于搜索关键词（因为 code 在枚举中先于 search）"""
        # "重构" 匹配 CODE，"搜索" 匹配 SEARCH，但 CODE 枚举顺序靠前
        assert self.classifier.classify("重构搜索功能") == IntentType.CODE

    def test_classify_with_confidence_high(self):
        """关键词匹配应返回高置信度"""
        intent, confidence = self.classifier.classify_with_confidence("帮我写代码")
        assert intent == IntentType.CODE
        assert confidence == 0.8

    def test_classify_with_confidence_low(self):
        """默认 chat 意图应返回低置信度"""
        intent, confidence = self.classifier.classify_with_confidence("你好")
        assert intent == IntentType.CHAT
        assert confidence == 0.5

    def test_case_insensitive_matching(self):
        """关键词匹配应不区分大小写"""
        assert self.classifier.classify("IMPLEMENT") == IntentType.CODE
        assert self.classifier.classify("Search") == IntentType.SEARCH
        assert self.classifier.classify("CONFIG") == IntentType.MANAGE