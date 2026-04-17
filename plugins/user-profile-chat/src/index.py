"""
用户画像聊天生成插件。
通过分析用户的聊天记录，提取兴趣偏好、交流风格、专业领域等多维画像信息。
支持实时增量更新，可配合事件总线监听聊天消息事件。
"""

import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from loguru import logger

from backend.plugins.base_plugin import BasePlugin


# 中文停用词（高频但无语义价值的词汇）
_STOP_WORDS = frozenset({
    "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一", "一个",
    "上", "也", "很", "到", "说", "要", "去", "你", "会", "着", "没有", "看", "好",
    "自己", "这", "他", "她", "它", "们", "那", "被", "从", "把", "让", "用", "对",
    "可以", "什么", "这个", "那个", "还", "能", "吗", "吧", "呢", "啊", "嗯", "哦",
    "哈", "呀", "嘛", "嗯嗯", "好的", "可以", "没问题", "谢谢", "感谢", "请", "请问",
    "怎么", "如何", "为什么", "哪个", "哪些", "多少", "是否", "能否", "是不是",
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "shall",
    "should", "may", "might", "must", "can", "could", "i", "you", "he",
    "she", "it", "we", "they", "me", "him", "her", "us", "them", "my",
    "your", "his", "its", "our", "their", "this", "that", "these", "those",
    "what", "which", "who", "whom", "how", "where", "when", "why",
    "and", "or", "but", "not", "no", "if", "then", "so", "as", "at",
    "by", "for", "from", "in", "into", "of", "on", "to", "with",
})

# 通信风格判定阈值
_SHORT_MESSAGE_THRESHOLD = 20
_LONG_MESSAGE_THRESHOLD = 200

# 领域关键词映射表
_DOMAIN_KEYWORDS: Dict[str, List[str]] = {
    "编程开发": ["python", "java", "javascript", "代码", "编程", "开发", "函数", "类", "接口",
                "api", "bug", "调试", "git", "数据库", "sql", "前端", "后端", "框架"],
    "人工智能": ["ai", "机器学习", "深度学习", "模型", "训练", "神经网络", "nlp", "自然语言",
                "gpt", "llm", "transformer", "算法", "数据集", "推理", "agent"],
    "数据分析": ["数据", "分析", "统计", "图表", "报表", "可视化", "excel", "pandas",
                "数据库", "查询", "指标", "kpi"],
    "产品设计": ["产品", "设计", "用户体验", "ux", "ui", "交互", "原型", "需求",
                "功能", "迭代", "版本"],
    "运维部署": ["部署", "服务器", "docker", "kubernetes", "k8s", "ci", "cd", "运维",
                "监控", "日志", "nginx", "linux"],
    "日常生活": ["天气", "美食", "旅游", "电影", "音乐", "运动", "健身", "学习",
                "工作", "生活"],
}


def _tokenize(text: str) -> List[str]:
    """
    简易分词：按空格和标点分割，过滤停用词和短词。
    中文单字保留，英文保留 2 字符以上的词。
    """
    # 使用正则拆分为词元
    tokens = re.findall(r'[\u4e00-\u9fff]+|[a-zA-Z_][a-zA-Z0-9_]*', text.lower())
    # 中文进一步按单字拆分（简易方式）
    expanded: List[str] = []
    for token in tokens:
        if re.match(r'^[\u4e00-\u9fff]+$', token):
            # 中文词组保留 2 字以上的组合
            if len(token) >= 2:
                expanded.append(token)
            # 也逐字加入（用于关键词匹配）
            for char in token:
                expanded.append(char)
        else:
            if len(token) >= 2:
                expanded.append(token)
    # 过滤停用词
    return [t for t in expanded if t not in _STOP_WORDS]


def _analyze_communication_style(messages: List[str]) -> Dict[str, Any]:
    """
    分析用户的交流风格。

    Returns:
        包含风格维度的字典。
    """
    if not messages:
        return {"style": "unknown", "detail": {}}

    lengths = [len(m) for m in messages]
    avg_length = sum(lengths) / len(lengths)
    short_ratio = sum(1 for l in lengths if l <= _SHORT_MESSAGE_THRESHOLD) / len(lengths)
    long_ratio = sum(1 for l in lengths if l >= _LONG_MESSAGE_THRESHOLD) / len(lengths)
    question_ratio = sum(1 for m in messages if m.rstrip().endswith("?") or m.rstrip().endswith("？")) / len(messages)

    if short_ratio > 0.7:
        style = "concise"
        style_label = "简洁型"
    elif long_ratio > 0.3:
        style = "detailed"
        style_label = "详细型"
    else:
        style = "balanced"
        style_label = "均衡型"

    return {
        "style": style,
        "style_label": style_label,
        "avg_message_length": round(avg_length, 1),
        "question_ratio": round(question_ratio, 3),
        "short_message_ratio": round(short_ratio, 3),
        "long_message_ratio": round(long_ratio, 3),
    }


def _extract_interests(messages: List[str], top_n: int = 10) -> List[Dict[str, Any]]:
    """
    从消息中提取兴趣关键词。

    Returns:
        按频率排序的兴趣标签列表。
    """
    all_tokens: List[str] = []
    for message in messages:
        all_tokens.extend(_tokenize(message))

    counter = Counter(all_tokens)
    # 过滤出现次数过少的词（至少出现 2 次）
    significant = [(word, count) for word, count in counter.most_common(top_n * 3) if count >= 2]

    return [
        {"keyword": word, "frequency": count}
        for word, count in significant[:top_n]
    ]


def _detect_expertise_areas(messages: List[str]) -> List[Dict[str, Any]]:
    """
    基于领域关键词匹配检测用户的专业领域。

    Returns:
        按匹配度排序的领域列表。
    """
    text = " ".join(messages).lower()
    domain_scores: Dict[str, int] = {}

    for domain, keywords in _DOMAIN_KEYWORDS.items():
        score = sum(text.count(kw) for kw in keywords)
        if score > 0:
            domain_scores[domain] = score

    sorted_domains = sorted(domain_scores.items(), key=lambda x: x[1], reverse=True)
    return [
        {"domain": domain, "relevance_score": score}
        for domain, score in sorted_domains
    ]


def _analyze_sentiment(messages: List[str]) -> Dict[str, Any]:
    """
    简易情感分析：基于正面/负面词汇频率估算整体情感倾向。

    Returns:
        情感分析结果字典。
    """
    positive_words = {"好", "棒", "优秀", "不错", "喜欢", "感谢", "谢谢", "完美", "赞",
                      "cool", "great", "good", "nice", "love", "thanks", "awesome", "excellent"}
    negative_words = {"差", "糟糕", "问题", "错误", "失败", "bug", "坏", "难", "烦",
                      "bad", "error", "fail", "wrong", "terrible", "awful", "hate"}

    text = " ".join(messages).lower()
    positive_count = sum(text.count(w) for w in positive_words)
    negative_count = sum(text.count(w) for w in negative_words)
    total = positive_count + negative_count

    if total == 0:
        return {"tendency": "neutral", "tendency_label": "中性", "positive_ratio": 0.5}

    positive_ratio = positive_count / total
    if positive_ratio > 0.65:
        tendency = "positive"
        label = "积极"
    elif positive_ratio < 0.35:
        tendency = "negative"
        label = "消极"
    else:
        tendency = "neutral"
        label = "中性"

    return {
        "tendency": tendency,
        "tendency_label": label,
        "positive_ratio": round(positive_ratio, 3),
    }


class UserProfileChatPlugin(BasePlugin):
    """
    用户画像聊天生成插件。
    分析聊天记录，生成包含兴趣偏好、交流风格、专业领域等维度的用户画像。
    """
    name: str = "user-profile-chat"
    version: str = "1.0.0"
    description: str = "基于聊天记录分析并生成用户画像的插件"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._max_messages: int = int(self.config.get("max_messages_per_analysis", 100))
        self._min_messages: int = int(self.config.get("min_messages_for_profile", 5))
        self._update_interval: int = int(self.config.get("profile_update_interval", 10))
        # 内存缓存：username -> 画像数据
        self._profiles: Dict[str, Dict[str, Any]] = {}
        # 消息计数器：username -> 自上次更新以来的新消息数
        self._message_counters: Dict[str, int] = defaultdict(int)

    def initialize(self) -> bool:
        """初始化插件。"""
        logger.info(
            f"[{self.name}] 初始化用户画像插件，"
            f"最大分析消息数: {self._max_messages}，"
            f"最少画像消息数: {self._min_messages}，"
            f"更新间隔: {self._update_interval}"
        )
        self._initialized = True
        return True

    def execute(self, *args, **kwargs) -> Dict[str, Any]:
        """
        执行插件动作。

        支持的 action:
        - analyze_user_profile: 分析消息列表并生成画像
        - get_user_profile: 获取已缓存的画像
        - on_chat_message: 处理单条新消息（增量更新）
        """
        action = kwargs.get("action", "analyze_user_profile")
        logger.debug(f"[{self.name}] 执行动作: {action}")

        if action == "analyze_user_profile":
            return self._analyze_profile(
                username=kwargs.get("username", ""),
                messages=kwargs.get("messages", []),
            )
        if action == "get_user_profile":
            return self._get_profile(
                username=kwargs.get("username", ""),
            )
        if action == "on_chat_message":
            return self._handle_chat_message(
                username=kwargs.get("username", ""),
                message=kwargs.get("message", ""),
                messages=kwargs.get("messages"),
            )

        logger.warning(f"[{self.name}] 未知动作: {action}")
        return {"status": "error", "message": f"未知动作: {action}"}

    def _analyze_profile(self, username: str, messages: List[str]) -> Dict[str, Any]:
        """
        根据消息列表生成用户画像。

        Args:
            username: 用户名。
            messages: 用户消息列表。

        Returns:
            包含画像数据的结果字典。
        """
        if not username:
            return {"status": "error", "message": "username 不能为空"}

        if len(messages) < self._min_messages:
            return {
                "status": "insufficient_data",
                "message": f"消息数量不足，需要至少 {self._min_messages} 条，当前 {len(messages)} 条",
                "username": username,
            }

        # 截取最近的消息
        recent_messages = messages[-self._max_messages:]

        profile = {
            "username": username,
            "message_count": len(messages),
            "analyzed_count": len(recent_messages),
            "interests": _extract_interests(recent_messages),
            "communication_style": _analyze_communication_style(recent_messages),
            "expertise_areas": _detect_expertise_areas(recent_messages),
            "sentiment": _analyze_sentiment(recent_messages),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        # 缓存画像
        self._profiles[username] = profile
        self._message_counters[username] = 0

        logger.info(f"[{self.name}] 已生成用户 '{username}' 的画像（分析 {len(recent_messages)} 条消息）")
        return {"status": "success", "profile": profile}

    def _get_profile(self, username: str) -> Dict[str, Any]:
        """获取已缓存的用户画像。"""
        if not username:
            return {"status": "error", "message": "username 不能为空"}

        profile = self._profiles.get(username)
        if profile is None:
            return {
                "status": "not_found",
                "message": f"用户 '{username}' 尚无画像数据，请先调用 analyze_user_profile",
                "username": username,
            }

        return {"status": "success", "profile": profile}

    def _handle_chat_message(
        self,
        username: str,
        message: str,
        messages: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        处理单条新消息，根据配置的更新间隔决定是否触发画像更新。

        Args:
            username: 用户名。
            message: 新消息内容。
            messages: 完整消息列表（用于重新分析，可选）。

        Returns:
            处理结果。
        """
        if not username or not message:
            return {"status": "skipped", "message": "username 或 message 为空"}

        self._message_counters[username] += 1
        counter = self._message_counters[username]

        if counter >= self._update_interval and messages is not None:
            logger.info(f"[{self.name}] 用户 '{username}' 累计 {counter} 条新消息，触发画像更新")
            return self._analyze_profile(username, messages)

        return {
            "status": "accumulated",
            "username": username,
            "counter": counter,
            "update_threshold": self._update_interval,
        }

    def validate(self) -> bool:
        """校验插件配置。"""
        try:
            max_msg = int(self.config.get("max_messages_per_analysis", 100))
            if max_msg <= 0:
                logger.error(f"[{self.name}] max_messages_per_analysis 必须大于 0")
                return False
        except (TypeError, ValueError):
            logger.error(f"[{self.name}] max_messages_per_analysis 必须是整数")
            return False

        try:
            min_msg = int(self.config.get("min_messages_for_profile", 5))
            if min_msg <= 0:
                logger.error(f"[{self.name}] min_messages_for_profile 必须大于 0")
                return False
        except (TypeError, ValueError):
            logger.error(f"[{self.name}] min_messages_for_profile 必须是整数")
            return False

        return True

    def cleanup(self) -> None:
        """清理插件资源。"""
        profile_count = len(self._profiles)
        logger.info(f"[{self.name}] 清理用户画像插件，已缓存 {profile_count} 个用户画像")
        self._profiles.clear()
        self._message_counters.clear()
        super().cleanup()

    def get_tools(self) -> List[Dict[str, Any]]:
        """返回插件提供的工具列表。"""
        return [
            {
                "name": "analyze_user_profile",
                "description": "根据用户聊天记录分析并生成用户画像，包含兴趣偏好、交流风格、专业领域等维度",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "username": {
                            "type": "string",
                            "description": "目标用户的用户名"
                        },
                        "messages": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "用户的聊天消息列表"
                        }
                    },
                    "required": ["username", "messages"]
                }
            },
            {
                "name": "get_user_profile",
                "description": "获取指定用户的已有画像数据",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "username": {
                            "type": "string",
                            "description": "目标用户的用户名"
                        }
                    },
                    "required": ["username"]
                }
            }
        ]
