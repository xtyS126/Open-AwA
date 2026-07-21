"""
技能自动匹配器 — 基于用户意图从技能库中自动选择合适的技能。

使用 L1 元数据（name + description）进行关键词匹配，无需加载完整的 L2/L3 内容。
匹配策略：关键词频率 + 描述相关性 → 排序 → Top-N 推荐。

用法:
    matcher = SkillMatcher()
    results = matcher.match("帮我处理这个PDF文件", available_skills)
    for r in results:
        print(f"{r.skill_name}: score={r.score}")
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List

from loguru import logger


@dataclass
class MatchResult:
    """单个技能匹配结果。"""
    skill_name: str
    description: str
    score: float  # 0.0 ~ 1.0
    matched_keywords: List[str] = field(default_factory=list)
    category: str = "general"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "skill_name": self.skill_name,
            "description": self.description,
            "score": round(self.score, 3),
            "matched_keywords": self.matched_keywords,
            "category": self.category,
        }


# ---------------------------------------------------------------------------
# 技能关键词索引 — 中文 + 英文覆盖
# ---------------------------------------------------------------------------

# 格式：关键词 → 相关技能名称列表
_KEYWORD_INDEX: Dict[str, List[str]] = {
    # 文档处理
    "pdf": ["pdf"],
    "word": ["docx"],
    "docx": ["docx"],
    "文档": ["pdf", "docx"],
    "ppt": ["pptx"],
    "pptx": ["pptx"],
    "演示": ["pptx"],
    "幻灯片": ["pptx"],
    "excel": ["xlsx"],
    "xlsx": ["xlsx"],
    "表格": ["xlsx"],
    "电子表格": ["xlsx"],
    "csv": ["xlsx"],
    "文件": ["pdf", "docx", "pptx", "xlsx", "file_reader"],
    "读取": ["file_reader", "pdf"],
    "阅读": ["file_reader", "pdf"],

    # 浏览器
    "浏览器": ["browser_cdp", "browser_visible"],
    "browser": ["browser_cdp", "browser_visible"],
    "网页": ["browser_cdp", "browser_visible"],
    "web": ["browser_cdp", "browser_visible"],
    "截图": ["browser_cdp", "browser_visible"],
    "爬虫": ["browser_cdp"],
    "自动化": ["browser_cdp", "browser_visible"],
    "chrome": ["browser_cdp"],
    "chromium": ["browser_cdp"],

    # 微信
    "微信": ["weixin_dispatch"],
    "weixin": ["weixin_dispatch"],
    "wechat": ["weixin_dispatch"],
    "公众号": ["weixin_dispatch"],
    "小程序": ["weixin_dispatch"],
    "二维码": ["weixin_dispatch"],

    # 消息/通知
    "消息": ["channel_message", "weixin_dispatch"],
    "通知": ["channel_message"],
    "发送": ["channel_message", "weixin_dispatch"],
    "钉钉": ["dingtalk_channel"],
    "dingtalk": ["dingtalk_channel"],

    # 定时任务
    "定时": ["cron"],
    "cron": ["cron"],
    "调度": ["cron"],
    "计划": ["cron"],
    "周期": ["cron"],
    "schedule": ["cron"],

    # 新闻/信息
    "新闻": ["news"],
    "news": ["news"],
    "资讯": ["news"],
    "信息": ["news"],

    # 测试
    "测试": ["api-testing", "webapp-testing"],
    "test": ["api-testing", "webapp-testing"],
    "api": ["api-testing"],
    "接口": ["api-testing"],
    "e2e": ["webapp-testing"],
    "端到端": ["webapp-testing"],

    # 多 Agent
    "协作": ["multi_agent_collaboration"],
    "collaboration": ["multi_agent_collaboration"],
    "多agent": ["multi_agent_collaboration"],
    "团队": ["multi_agent_collaboration"],

    # 问答
    "问答": ["qa_source_index"],
    "qa": ["qa_source_index"],
    "知识库": ["qa_source_index"],
    "索引": ["qa_source_index"],
}


class SkillMatcher:
    """
    技能匹配器 — 根据用户意图推荐最合适的技能。

    使用两层策略：
    1. 关键词预索引快速筛选
    2. 描述文本相关性评分

    只使用 L1 元数据，不加载完整技能内容。
    """

    def __init__(self, keyword_index: Optional[Dict[str, List[str]]] = None):
        """
        Args:
            keyword_index: 自定义关键词索引，默认使用内置 _KEYWORD_INDEX。
        """
        self.keyword_index = keyword_index or _KEYWORD_INDEX

    def match(
        self,
        user_intent: str,
        available_skills: List[Dict[str, Any]],
        top_n: int = 5,
        min_score: float = 0.05,
    ) -> List[MatchResult]:
        """
        根据用户意图匹配技能。

        Args:
            user_intent: 用户的自然语言意图描述。
            available_skills: 可用技能列表，每项需包含 name 和 description。
            top_n: 返回 Top-N 结果。
            min_score: 最低匹配分数阈值。

        Returns:
            按得分降序排列的 MatchResult 列表。
        """
        if not available_skills:
            logger.debug("无可匹配的技能")
            return []

        intent_lower = user_intent.lower()

        # 步骤1：通过关键词索引快速筛选候选技能
        candidate_names: Dict[str, int] = {}  # skill_name → hit count
        for keyword, skill_names in self.keyword_index.items():
            if keyword.lower() in intent_lower:
                for name in skill_names:
                    candidate_names[name] = candidate_names.get(name, 0) + 1

        logger.debug(f"关键词预筛选命中 {len(candidate_names)} 个候选技能")

        # 步骤2：对候选技能进行描述相关性评分
        results: List[MatchResult] = []
        for skill in available_skills:
            skill_name = skill.get("name", "")
            description = skill.get("description", "")

            keyword_hits = candidate_names.get(skill_name, 0)
            desc_score = self._calculate_description_similarity(intent_lower, description)
            name_score = self._calculate_name_similarity(intent_lower, skill_name)

            # 综合评分：关键词命中（权重 0.5）+ 描述匹配（权重 0.3）+ 名称匹配（权重 0.2）
            combined_score = (
                min(keyword_hits / max(len(self.keyword_index), 1), 1.0) * 0.5
                + desc_score * 0.3
                + name_score * 0.2
            )

            # 限制在 [0, 1]
            combined_score = max(0.0, min(1.0, combined_score))

            if combined_score >= min_score:
                matched_keywords = [
                    kw for kw, names in self.keyword_index.items()
                    if kw.lower() in intent_lower and skill_name in names
                ]
                results.append(MatchResult(
                    skill_name=skill_name,
                    description=description,
                    score=combined_score,
                    matched_keywords=matched_keywords,
                    category=skill.get("category", "general"),
                ))

        results.sort(key=lambda r: r.score, reverse=True)
        top_results = results[:top_n]

        logger.info(
            f"技能匹配完成: intent='{user_intent[:60]}', "
            f"candidates={len(candidate_names)}, results={len(top_results)}"
        )

        return top_results

    def _calculate_description_similarity(self, intent: str, description: str) -> float:
        """
        计算意图与技能描述的相关性分数。
        使用基于词的重叠系数：2 * |A ∩ B| / (|A| + |B|)。
        """
        if not description:
            return 0.0

        desc_lower = description.lower()
        intent_words = set(self._tokenize(intent))
        desc_words = set(self._tokenize(desc_lower))

        if not intent_words or not desc_words:
            return 0.0

        intersection = intent_words & desc_words
        if not intersection:
            return 0.0

        # Sørensen–Dice 系数
        score = 2.0 * len(intersection) / (len(intent_words) + len(desc_words))
        return score

    def _calculate_name_similarity(self, intent: str, skill_name: str) -> float:
        """
        计算技能名称与意图的相关性。
        技能名称中的连字符/下划线分割的词段是否出现在意图中。
        """
        if not skill_name:
            return 0.0

        name_parts = set(self._tokenize(skill_name.lower().replace("_", " ").replace("-", " ")))
        intent_parts = set(self._tokenize(intent))

        if not name_parts:
            return 0.0

        matches = name_parts & intent_parts
        return len(matches) / len(name_parts)

    def match_single_best(
        self,
        user_intent: str,
        available_skills: List[Dict[str, Any]],
        threshold: float = 0.3,
    ) -> Optional[MatchResult]:
        """
        返回最佳匹配结果，仅在分数超过阈值时返回。

        Args:
            user_intent: 用户意图。
            available_skills: 可用技能列表。
            threshold: 最低阈值，低于此分数的匹配返回 None。

        Returns:
            最佳匹配或 None（无可信匹配）。
        """
        results = self.match(user_intent, available_skills, top_n=1, min_score=threshold)
        return results[0] if results else None

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        """
        简单分词：按非字母数字字符分割，过滤掉短词和停用词。
        支持中英文混合文本。
        """
        # 英文/数字分词
        tokens = re.findall(r'[a-zA-Z0-9一-鿿]+', text.lower())

        # 中文字符拆分为单字 token
        chinese_chars = re.findall(r'[一-鿿]', text)
        tokens.extend(chinese_chars)

        # 过滤停用词和短 token
        stopwords = {
            'a', 'an', 'the', 'is', 'are', 'was', 'were', 'be', 'been',
            'i', 'you', 'he', 'she', 'it', 'we', 'they',
            'this', 'that', 'these', 'those',
            'to', 'of', 'in', 'for', 'on', 'with', 'at', 'by', 'from',
            'and', 'or', 'but', 'not', 'so', 'if', 'as',
            '的', '了', '是', '在', '我', '有', '和', '就',
            '不', '人', '都', '一', '个', '上', '也', '很', '到', '说',
            '要', '去', '你', '会', '着', '没有', '看', '好', '自己',
        }
        return [t for t in tokens if t not in stopwords and len(t) > 1 or (
            len(t) == 1 and '一' <= t <= '鿿'
        )]
