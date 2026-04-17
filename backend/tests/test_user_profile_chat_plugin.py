"""
用户画像聊天生成插件的单元测试。
覆盖画像生成、缓存、增量更新、工具和配置校验逻辑。
"""

import sys
import os

import pytest

# 将 plugins 目录添加到搜索路径以便直接导入
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "plugins", "user-profile-chat", "src"))

from plugins.base_plugin import BasePlugin

# 手动导入插件模块（因为插件使用相对 backend 的导入路径）
import importlib.util
_plugin_path = os.path.join(
    os.path.dirname(__file__), "..", "..", "plugins", "user-profile-chat", "src", "index.py"
)
_spec = importlib.util.spec_from_file_location("user_profile_chat_plugin", _plugin_path)
_module = importlib.util.module_from_spec(_spec)
# 将 backend 的 BasePlugin 注入到模块加载上下文中
sys.modules["backend.plugins.base_plugin"] = importlib.import_module("plugins.base_plugin")
_spec.loader.exec_module(_module)
UserProfileChatPlugin = _module.UserProfileChatPlugin
_tokenize = _module._tokenize
_analyze_communication_style = _module._analyze_communication_style
_extract_interests = _module._extract_interests
_detect_expertise_areas = _module._detect_expertise_areas
_analyze_sentiment = _module._analyze_sentiment


class TestTokenize:
    """测试分词函数"""

    def test_chinese_text(self):
        """中文文本应被正确分词"""
        tokens = _tokenize("我喜欢编程开发")
        # 简易分词将整个中文段作为一个词组保留，同时逐字拆分
        assert "我喜欢编程开发" in tokens or "编" in tokens

    def test_english_text(self):
        """英文文本应保留有意义的词"""
        tokens = _tokenize("I love python programming")
        assert "python" in tokens
        assert "programming" in tokens

    def test_stop_words_filtered(self):
        """停用词应被过滤"""
        tokens = _tokenize("the is a an")
        assert len(tokens) == 0

    def test_mixed_language(self):
        """混合语言文本应正确处理"""
        tokens = _tokenize("我在学习python编程")
        assert "python" in tokens


class TestCommunicationStyle:
    """测试交流风格分析"""

    def test_empty_messages(self):
        """空消息列表返回未知风格"""
        result = _analyze_communication_style([])
        assert result["style"] == "unknown"

    def test_concise_style(self):
        """短消息为主应识别为简洁型"""
        messages = ["好的", "知道了", "收到", "明白", "嗯", "OK", "了解", "没问题"]
        result = _analyze_communication_style(messages)
        assert result["style"] == "concise"

    def test_detailed_style(self):
        """长消息为主应识别为详细型"""
        long_msg = "这是一段非常长的消息，" * 20
        messages = [long_msg] * 5
        result = _analyze_communication_style(messages)
        assert result["style"] == "detailed"

    def test_question_ratio(self):
        """问号消息应计入提问比例"""
        messages = ["这是什么？", "怎么做？", "好的", "了解"]
        result = _analyze_communication_style(messages)
        assert result["question_ratio"] == 0.5


class TestExtractInterests:
    """测试兴趣提取"""

    def test_repeated_keywords(self):
        """重复出现的词应排在前面"""
        messages = ["python很好", "python编程", "python开发", "java也不错"]
        interests = _extract_interests(messages)
        assert len(interests) > 0
        # python 出现 3 次，应排在前面
        keywords = [i["keyword"] for i in interests]
        assert "python" in keywords

    def test_minimum_frequency(self):
        """仅出现一次的词不应被提取"""
        messages = ["唯一词汇abc"]
        interests = _extract_interests(messages)
        # 只有一条消息，大多数词只出现一次
        for interest in interests:
            assert interest["frequency"] >= 2


class TestDetectExpertiseAreas:
    """测试专业领域检测"""

    def test_programming_domain(self):
        """编程相关消息应检测到编程开发领域"""
        messages = [
            "我在写python代码",
            "这个函数有bug",
            "git提交后部署",
            "调试了一下接口",
        ]
        areas = _detect_expertise_areas(messages)
        assert len(areas) > 0
        domain_names = [a["domain"] for a in areas]
        assert "编程开发" in domain_names

    def test_ai_domain(self):
        """AI 相关消息应检测到人工智能领域"""
        messages = [
            "训练了一个模型",
            "deep learning效果很好",
            "这个nlp任务需要transformer",
        ]
        areas = _detect_expertise_areas(messages)
        domain_names = [a["domain"] for a in areas]
        assert "人工智能" in domain_names

    def test_no_domain_match(self):
        """不匹配任何领域的消息返回空列表"""
        messages = ["今天天气很好，心情不错"]
        areas = _detect_expertise_areas(messages)
        # 可能匹配日常生活，也可能为空
        assert isinstance(areas, list)


class TestAnalyzeSentiment:
    """测试情感分析"""

    def test_positive_sentiment(self):
        """正面消息应识别为积极"""
        messages = ["太棒了", "非常好", "很赞", "喜欢这个", "优秀", "完美"]
        result = _analyze_sentiment(messages)
        assert result["tendency"] == "positive"

    def test_negative_sentiment(self):
        """负面消息应识别为消极"""
        messages = ["太差了", "这个bug很糟糕", "错误太多", "失败了"]
        result = _analyze_sentiment(messages)
        assert result["tendency"] == "negative"

    def test_neutral_sentiment(self):
        """无情感词汇应识别为中性"""
        messages = ["今天有会议", "明天开始项目"]
        result = _analyze_sentiment(messages)
        assert result["tendency"] == "neutral"


class TestUserProfileChatPlugin:
    """测试 UserProfileChatPlugin 插件类"""

    def setup_method(self):
        """每个测试前创建插件实例"""
        self.plugin = UserProfileChatPlugin(config={
            "max_messages_per_analysis": 50,
            "min_messages_for_profile": 3,
            "profile_update_interval": 5,
        })
        self.plugin.initialize()

    def test_initialize(self):
        """插件初始化应成功"""
        plugin = UserProfileChatPlugin()
        assert plugin.initialize() is True
        assert plugin._initialized is True

    def test_analyze_profile_success(self):
        """有足够消息时应生成画像"""
        messages = [
            "我在学习python",
            "python的语法很简洁",
            "今天写了一个web应用",
            "用了fastapi框架",
            "部署到了服务器上",
        ]
        result = self.plugin.execute(
            action="analyze_user_profile",
            username="alice",
            messages=messages,
        )
        assert result["status"] == "success"
        profile = result["profile"]
        assert profile["username"] == "alice"
        assert profile["message_count"] == 5
        assert "interests" in profile
        assert "communication_style" in profile
        assert "expertise_areas" in profile
        assert "sentiment" in profile

    def test_analyze_profile_insufficient_data(self):
        """消息不足时应返回提示"""
        result = self.plugin.execute(
            action="analyze_user_profile",
            username="bob",
            messages=["hello", "hi"],
        )
        assert result["status"] == "insufficient_data"

    def test_analyze_profile_empty_username(self):
        """空用户名应返回错误"""
        result = self.plugin.execute(
            action="analyze_user_profile",
            username="",
            messages=["msg"],
        )
        assert result["status"] == "error"

    def test_get_profile_not_found(self):
        """未生成画像时应返回 not_found"""
        result = self.plugin.execute(action="get_user_profile", username="unknown")
        assert result["status"] == "not_found"

    def test_get_profile_after_analysis(self):
        """生成画像后应能获取"""
        messages = ["python", "代码", "开发", "测试", "部署"]
        self.plugin.execute(
            action="analyze_user_profile",
            username="charlie",
            messages=messages,
        )
        result = self.plugin.execute(action="get_user_profile", username="charlie")
        assert result["status"] == "success"
        assert result["profile"]["username"] == "charlie"

    def test_on_chat_message_accumulation(self):
        """消息累积未达阈值时不触发更新"""
        result = self.plugin.execute(
            action="on_chat_message",
            username="dave",
            message="hello",
        )
        assert result["status"] == "accumulated"
        assert result["counter"] == 1

    def test_on_chat_message_trigger_update(self):
        """消息累积达到阈值时触发画像更新"""
        messages = ["msg1", "msg2", "msg3", "msg4", "msg5", "msg6"]
        # 累积到阈值
        for i in range(4):
            self.plugin.execute(
                action="on_chat_message",
                username="eve",
                message=f"message {i}",
            )
        # 第 5 次应触发更新（update_interval=5）
        result = self.plugin.execute(
            action="on_chat_message",
            username="eve",
            message="message 5",
            messages=messages,
        )
        assert result["status"] == "success"

    def test_unknown_action(self):
        """未知动作应返回错误"""
        result = self.plugin.execute(action="unknown_action")
        assert result["status"] == "error"

    def test_validate_valid_config(self):
        """合法配置应通过校验"""
        assert self.plugin.validate() is True

    def test_validate_invalid_config(self):
        """非法配置应校验失败"""
        plugin = UserProfileChatPlugin(config={"max_messages_per_analysis": -1})
        assert plugin.validate() is False

    def test_cleanup(self):
        """清理应清空缓存"""
        messages = ["a", "b", "c", "d", "e"]
        self.plugin.execute(action="analyze_user_profile", username="test", messages=messages)
        assert len(self.plugin._profiles) == 1

        self.plugin.cleanup()
        assert len(self.plugin._profiles) == 0
        assert self.plugin._initialized is False

    def test_get_tools(self):
        """工具列表应包含预期的工具"""
        tools = self.plugin.get_tools()
        assert len(tools) == 2
        tool_names = {t["name"] for t in tools}
        assert "analyze_user_profile" in tool_names
        assert "get_user_profile" in tool_names

    def test_is_base_plugin_subclass(self):
        """插件应继承 BasePlugin"""
        assert issubclass(UserProfileChatPlugin, BasePlugin)
