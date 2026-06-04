"""
画像上下文注入适配器，将用户画像注入到 Agent 的系统上下文中。

参考:
- ChatGPT Memory: 四层架构中的用户记忆层直接注入，不使用 RAG
- Letta: Memory Blocks XML 编译模式
"""

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from db.models import ProfileFact
from .profile_dimensions import PROFILE_CATEGORIES
from .profile_confidence import ConfidenceModel


class ProfileInjector:
    """
    将用户画像编译为 Agent 上下文文本。

    采用"零检索"策略：精选高置信度画像事实直接注入系统上下文，
    不走 RAG 检索。画像总量控制在 2000 token 以内。
    """

    # 上下文注入的最大字符数
    MAX_CONTEXT_CHARS = 3000
    # 每类最大注入事实数
    MAX_FACTS_PER_CATEGORY = 15
    # 注入的最低置信度
    MIN_CONFIDENCE = 0.3

    def __init__(self, db: Session, user_id: str):
        self.db = db
        self.user_id = user_id

    def build_profile_context(
        self,
        max_chars: Optional[int] = None,
        min_confidence: Optional[float] = None,
        categories: Optional[List[str]] = None,
    ) -> str:
        """
        构建注入 Agent 系统上下文的画像文本。

        Args:
            max_chars: 最大字符数
            min_confidence: 最低置信度
            categories: 限定类别列表

        Returns:
            格式化的画像上下文 XML 文本
        """
        max_chars = max_chars or self.MAX_CONTEXT_CHARS
        min_confidence = min_confidence or self.MIN_CONFIDENCE

        # 获取活跃事实，按优先级和置信度排序
        facts = self._get_sorted_facts(min_confidence, categories)

        # 按类别组织
        blocks = self._organize_into_blocks(facts)

        # 编译为 XML 标签格式
        context = self._compile_to_context(blocks)

        # 控制在最大字符数以内
        if len(context) > max_chars:
            context = self._truncate_context(context, max_chars)

        return context

    def build_profile_summary(self) -> Dict[str, Any]:
        """
        构建画像摘要（用于 API 返回）。

        包含每个类别的前 N 个高置信度事实。
        """
        facts = self._get_sorted_facts(min_confidence=0.0)

        summary: Dict[str, Any] = {
            "total_facts": len(facts),
            "categories": {},
            "high_confidence_count": 0,
            "medium_confidence_count": 0,
            "low_confidence_count": 0,
        }

        for fact in facts:
            cat = fact.category
            if cat not in summary["categories"]:
                summary["categories"][cat] = {
                    "label": PROFILE_CATEGORIES.get(cat, {}).get("label", cat),
                    "facts": [],
                }

            fact_data = {
                "id": fact.id,
                "fact_key": fact.fact_key,
                "fact_value": fact.fact_value,
                "confidence": fact.confidence,
                "confidence_label": ConfidenceModel.get_confidence_label(
                    fact.confidence
                ),
                "source_type": fact.source_type,
                "last_updated_at": (
                    fact.last_updated_at.isoformat()
                    if fact.last_updated_at else None
                ),
                "verification_count": fact.verification_count,
            }

            summary["categories"][cat]["facts"].append(fact_data)

            # 置信度统计
            label = ConfidenceModel.get_confidence_label(fact.confidence)
            if label == "高":
                summary["high_confidence_count"] += 1
            elif label == "中":
                summary["medium_confidence_count"] += 1
            else:
                summary["low_confidence_count"] += 1

        return summary

    def _get_sorted_facts(
        self,
        min_confidence: float = 0.0,
        categories: Optional[List[str]] = None,
    ) -> List[ProfileFact]:
        """获取按优先级和置信度排序的活跃事实"""
        query = self.db.query(ProfileFact).filter(
            ProfileFact.user_id == self.user_id,
            ProfileFact.is_active == True,
        )

        if min_confidence > 0:
            query = query.filter(ProfileFact.confidence >= min_confidence)

        if categories:
            query = query.filter(ProfileFact.category.in_(categories))

        facts = query.all()

        # 按类别优先级 + 置信度排序
        def sort_key(f):
            cat_priority = PROFILE_CATEGORIES.get(f.category, {}).get("priority", 9)
            return (cat_priority, -f.confidence)

        return sorted(facts, key=sort_key)

    def _organize_into_blocks(
        self, facts: List[ProfileFact]
    ) -> Dict[str, List[ProfileFact]]:
        """将事实按类别组织，每类限制数量"""
        blocks: Dict[str, List[ProfileFact]] = {}
        for fact in facts:
            cat = fact.category
            if cat not in blocks:
                blocks[cat] = []
            if len(blocks[cat]) < self.MAX_FACTS_PER_CATEGORY:
                blocks[cat].append(fact)
        return blocks

    def _compile_to_context(
        self, blocks: Dict[str, List[ProfileFact]]
    ) -> str:
        """编译为 XML 格式的 Agent 上下文"""
        from xml.sax.saxutils import escape as xml_escape

        context_parts = ["<user_profile>"]

        # 按类别优先级排序
        sorted_cats = sorted(
            blocks.items(),
            key=lambda item: PROFILE_CATEGORIES.get(item[0], {}).get("priority", 9),
        )

        for category, facts in sorted_cats:
            if not facts:
                continue
            cat_config = PROFILE_CATEGORIES.get(category, {})
            cat_label = xml_escape(cat_config.get("label", category))
            cat_desc = xml_escape(cat_config.get("description", ""))

            context_parts.append(
                f'  <{category} label="{cat_label}" description="{cat_desc}">'
            )
            for fact in facts:
                value = xml_escape(fact.fact_value)
                context_parts.append(
                    f'    <fact key="{xml_escape(fact.fact_key)}" '
                    f'confidence="{fact.confidence:.2f}">'
                    f'{value}</fact>'
                )
            context_parts.append(f'  </{category}>')

        context_parts.append('</user_profile>')
        return '\n'.join(context_parts)

    def _truncate_context(self, context: str, max_chars: int) -> str:
        """截断上下文到最大字符数，保证 XML 结构完整"""
        if len(context) <= max_chars:
            return context

        # 简单截断：保留前面的内容，添加截断标记
        truncated = context[:max_chars - 50]
        last_newline = truncated.rfind('\n')
        if last_newline > 0:
            truncated = truncated[:last_newline]

        truncated += '\n  <!-- 上下文已截断，超出 token 限制 -->'
        truncated += '\n</user_profile>'
        return truncated
