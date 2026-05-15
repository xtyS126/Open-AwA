"""
验证 ComprehensionLayer 的上下文理解逻辑：
意图识别、实体提取、参数解析，覆盖正常与边界场景。
"""

import pytest
from unittest.mock import MagicMock, patch

from core.comprehension import ComprehensionLayer


class TestIntentRecognition:
    """验证 recognize_intent 方法的意图识别逻辑。"""

    @pytest.mark.asyncio
    async def test_recognize_intent_execute_with_command_keywords(self):
        """包含执行/完成类关键词时应返回 'execute'。"""
        layer = ComprehensionLayer()
        assert await layer.recognize_intent("帮我执行这个命令") == "execute"
        assert await layer.recognize_intent("创建新文件") == "execute"

    @pytest.mark.asyncio
    async def test_recognize_intent_query_with_question_keywords(self):
        """包含查询/找类关键词时应返回 'query'。"""
        layer = ComprehensionLayer()
        assert await layer.recognize_intent("查询一下天气") == "query"
        assert await layer.recognize_intent("有什么新消息") == "query"

    @pytest.mark.asyncio
    async def test_recognize_intent_explain_with_explanation_keywords(self):
        """包含解释/说明类关键词时应返回 'explain'。"""
        layer = ComprehensionLayer()
        assert await layer.recognize_intent("解释一下这个概念") == "explain"
        assert await layer.recognize_intent("为什么出现这个错误") == "explain"

    @pytest.mark.asyncio
    async def test_recognize_intent_chat_with_chat_keywords(self):
        """包含聊/说类关键词时应返回 'chat'。"""
        layer = ComprehensionLayer()
        assert await layer.recognize_intent("聊聊今天的事") == "chat"

    @pytest.mark.asyncio
    async def test_recognize_intent_chat_as_default(self):
        """无特殊关键词时应返回默认意图 'chat'。"""
        layer = ComprehensionLayer()
        assert await layer.recognize_intent("你好，今天天气怎么样？") == "chat"
        assert await layer.recognize_intent("谢谢你的帮助") == "chat"

    @pytest.mark.asyncio
    async def test_recognize_intent_empty_input_returns_chat(self):
        """空输入时应返回默认意图 'chat'。"""
        layer = ComprehensionLayer()
        assert await layer.recognize_intent("") == "chat"

    @pytest.mark.asyncio
    async def test_recognize_intent_whitespace_only_returns_chat(self):
        """纯空白字符输入应返回默认意图 'chat'。"""
        layer = ComprehensionLayer()
        assert await layer.recognize_intent("   \t\n  ") == "chat"

    @pytest.mark.asyncio
    async def test_recognize_intent_first_keyword_wins(self):
        """多个意图关键词同时出现时应返回第一个匹配的意图。"""
        layer = ComprehensionLayer()
        # "做"匹配execute，"是什么"匹配explain，execute 排在前面
        result = await layer.recognize_intent("帮我做一个是什么的问题")
        assert result in ("execute", "explain", "query", "chat")


class TestEntityExtraction:
    """验证 extract_entities 方法的实体提取能力。"""

    @pytest.mark.asyncio
    async def test_extract_entities_file_paths(self):
        """应能提取文件路径实体。"""
        layer = ComprehensionLayer()
        entities = await layer.extract_entities("请读取 /etc/config.json 文件")
        assert "paths" in entities
        assert "/etc/config.json" in entities["paths"]

    @pytest.mark.asyncio
    async def test_extract_entities_file_names(self):
        """应能提取文件名实体。"""
        layer = ComprehensionLayer()
        entities = await layer.extract_entities("修改 main.py 中的代码")
        assert "files" in entities
        assert "main.py" in entities["files"]

    @pytest.mark.asyncio
    async def test_extract_entities_urls(self):
        """应能提取 URL 实体。"""
        layer = ComprehensionLayer()
        entities = await layer.extract_entities("访问 https://example.com/api 查看文档")
        assert "urls" in entities
        assert "https://example.com/api" in entities["urls"]

    @pytest.mark.asyncio
    async def test_extract_entities_commands(self):
        """应能提取反引号中的命令实体。"""
        layer = ComprehensionLayer()
        entities = await layer.extract_entities("运行 `pip install numpy` 命令")
        assert "commands" in entities
        assert "pip install numpy" in entities["commands"]

    @pytest.mark.asyncio
    async def test_extract_entities_empty_input_returns_empty_dict(self):
        """空输入时应返回空字典。"""
        layer = ComprehensionLayer()
        entities = await layer.extract_entities("")
        assert entities == {}

    @pytest.mark.asyncio
    async def test_extract_entities_multiple_types_in_one_message(self):
        """一条消息中包含多种类型实体应全部提取。"""
        layer = ComprehensionLayer()
        entities = await layer.extract_entities(
            "读取 /data/file.txt 并运行 `make build`"
        )
        assert "paths" in entities
        assert "/data/file.txt" in entities["paths"]
        assert "commands" in entities
        assert "make build" in entities["commands"]

    @pytest.mark.asyncio
    async def test_extract_entities_no_entities_returns_empty(self):
        """无任何实体时应返回空字典。"""
        layer = ComprehensionLayer()
        entities = await layer.extract_entities("普通文本，没有任何实体")
        assert entities == {}


class TestParameterParsing:
    """验证 parse_parameters 方法的参数提取能力。"""

    @pytest.mark.asyncio
    async def test_parse_parameters_execute_sets_task(self):
        """execute 意图应将全部输入作为 task 参数。"""
        layer = ComprehensionLayer()
        params = await layer.parse_parameters("执行 pip install numpy", "execute")
        assert params["task"] == "执行 pip install numpy"

    @pytest.mark.asyncio
    async def test_parse_parameters_query_sets_query(self):
        """query 意图应将全部输入作为 query 参数。"""
        layer = ComprehensionLayer()
        params = await layer.parse_parameters("搜索 Python 异步编程最佳实践", "query")
        assert params["query"] == "搜索 Python 异步编程最佳实践"

    @pytest.mark.asyncio
    async def test_parse_parameters_explain_sets_target(self):
        """explain 意图应将全部输入作为 target 参数。"""
        layer = ComprehensionLayer()
        params = await layer.parse_parameters("解释卷积神经网络的工作原理", "explain")
        assert params["target"] == "解释卷积神经网络的工作原理"

    @pytest.mark.asyncio
    async def test_parse_parameters_chat_returns_empty(self):
        """chat 意图应返回空字典。"""
        layer = ComprehensionLayer()
        params = await layer.parse_parameters("你好，最近怎么样？", "chat")
        assert params == {}

    @pytest.mark.asyncio
    async def test_parse_parameters_unknown_intent_returns_empty(self):
        """未知意图类型应返回空字典。"""
        layer = ComprehensionLayer()
        params = await layer.parse_parameters("某个消息", "unknown_intent")
        assert params == {}

    @pytest.mark.asyncio
    async def test_parse_parameters_empty_input(self):
        """空输入时应返回空字典。"""
        layer = ComprehensionLayer()
        params = await layer.parse_parameters("", "execute")
        assert params == {}

    @pytest.mark.asyncio
    async def test_parse_parameters_whitespace_input(self):
        """纯空白输入时应返回空字典。"""
        layer = ComprehensionLayer()
        params = await layer.parse_parameters("   ", "query")
        assert params == {}
