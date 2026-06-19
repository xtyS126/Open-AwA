"""
Chain-of-Thought 问题复杂度评估器，根据用户输入自动选择推理深度。

复杂度分级：
- simple（简单）: 问候、闲聊、事实查询 → 推理深度 0-1
- moderate（中等）: 解释、总结、翻译 → 推理深度 2-3
- complex（复杂）: 数学、编程、逻辑推理、多步规划 → 推理深度 4-5

评估策略：
1. 关键词匹配（编程/数学/逻辑等高复杂度关键词）
2. 输入长度（长输入通常更复杂）
3. 问题类型识别（疑问词、命令式等）
4. 用户可覆盖自动选择

与 build_thinking_params 配合使用：
- 自动模式：complexity_assessor.assess(user_input) → thinking_depth
- 手动模式：用户指定 thinking_depth，跳过自动评估
"""

import re
from typing import Optional

from loguru import logger


# 复杂度等级
COMPLEXITY_SIMPLE = "simple"
COMPLEXITY_MODERATE = "moderate"
COMPLEXITY_COMPLEX = "complex"

# 各复杂度对应的推理深度
COMPLEXITY_DEPTH_MAP: dict[str, int] = {
    COMPLEXITY_SIMPLE: 1,
    COMPLEXITY_MODERATE: 3,
    COMPLEXITY_COMPLEX: 5,
}

# 高复杂度关键词（数学/编程/逻辑/多步规划）
HIGH_COMPLEXITY_KEYWORDS: list[str] = [
    # 编程相关
    "代码", "编程", "函数", "算法", "debug", "bug", "重构", "refactor",
    "实现", "开发", "api", "sql", "数据库", "正则", "regex",
    # 数学相关
    "计算", "数学", "方程", "证明", "概率", "统计", "微积分", "几何",
    "矩阵", "向量", "求导", "积分",
    # 逻辑推理
    "推理", "逻辑", "分析", "推导", "证明", "论证",
    # 多步规划
    "规划", "设计", "架构", "方案", "策略", "流程", "步骤",
    # 复杂问题
    "优化", "对比", "权衡", "tradeoff", "复杂", "难点",
]

# 中等复杂度关键词（解释/总结/翻译）
MODERATE_COMPLEXITY_KEYWORDS: list[str] = [
    "解释", "说明", "总结", "概括", "翻译", "转换", "改写",
    "区别", "对比", "列举", "归纳", "整理", "分类",
    "什么", "为什么", "如何", "怎么",
]

# 简单复杂度关键词（问候/闲聊/事实查询）
# 注意：避免加入 "是"/"不是" 等高频字，会误伤正常提问
SIMPLE_COMPLEXITY_KEYWORDS: list[str] = [
    "你好", "hello", "hi", "嗨", "早上好", "晚上好", "再见",
    "谢谢", "感谢", "对不起", "抱歉",
    "好的", "可以",
]

# 代码块/数学公式特征正则
CODE_BLOCK_PATTERN = re.compile(r"```[\s\S]*?```", re.MULTILINE)
MATH_FORMULA_PATTERN = re.compile(r"\$[^$]+\$|\\\([^)]+\\\)\\\[[^\]]+\\\]", re.MULTILINE)
URL_PATTERN = re.compile(r"https?://[^\s]+")


class ComplexityAssessor:
    """
    问题复杂度评估器，根据用户输入特征自动判断复杂度等级。

    评估流程：
    1. 检查代码块/数学公式 → 直接判定为 complex
    2. 关键词匹配 → 高复杂度关键词命中数加权
    3. 输入长度 → 长输入提升复杂度
    4. 问题类型 → 命令式/多问号提升复杂度
    5. 综合评分映射到 simple/moderate/complex
    """

    def __init__(self):
        """初始化复杂度评估器。"""
        logger.debug("ComplexityAssessor initialized")

    def assess(self, user_input: str) -> dict:
        """
        评估用户输入的复杂度。

        Args:
            user_input: 用户输入文本。

        Returns:
            评估结果字典：
            - complexity: str 复杂度等级（simple/moderate/complex）
            - thinking_depth: int 推荐推理深度（0-5）
            - score: int 复杂度评分（0-100）
            - reasons: list[str] 评估依据列表
        """
        if not user_input or not user_input.strip():
            return {
                "complexity": COMPLEXITY_SIMPLE,
                "thinking_depth": 0,
                "score": 0,
                "reasons": ["输入为空"],
            }

        text = user_input.strip()
        reasons: list[str] = []
        score = 0

        # 1. 代码块检测 → 强信号，直接接近 complex 阈值
        code_blocks = CODE_BLOCK_PATTERN.findall(text)
        if code_blocks:
            score += 50
            reasons.append(f"包含 {len(code_blocks)} 个代码块")

        # 2. 数学公式检测 → 强信号
        math_formulas = MATH_FORMULA_PATTERN.findall(text)
        if math_formulas:
            score += 50
            reasons.append(f"包含 {len(math_formulas)} 个数学公式")

        # 3. 高复杂度关键词匹配
        high_hits = sum(1 for kw in HIGH_COMPLEXITY_KEYWORDS if kw in text.lower())
        if high_hits > 0:
            score += min(high_hits * 15, 45)
            reasons.append(f"命中 {high_hits} 个高复杂度关键词")

        # 4. 中等复杂度关键词匹配
        moderate_hits = sum(1 for kw in MODERATE_COMPLEXITY_KEYWORDS if kw in text.lower())
        if moderate_hits > 0:
            score += min(moderate_hits * 8, 32)
            reasons.append(f"命中 {moderate_hits} 个中等复杂度关键词")

        # 5. 简单复杂度关键词匹配（降低评分）
        simple_hits = sum(1 for kw in SIMPLE_COMPLEXITY_KEYWORDS if kw in text.lower())
        if simple_hits > 0:
            score -= min(simple_hits * 8, 16)
            reasons.append(f"命中 {simple_hits} 个简单关键词")

        # 6. 输入长度评估（仅加分，不扣分，避免短问题被误判）
        text_len = len(text)
        if text_len > 1000:
            score += 15
            reasons.append(f"输入较长（{text_len} 字符）")
        elif text_len > 300:
            score += 8
            reasons.append(f"输入中等长度（{text_len} 字符）")

        # 7. 多问号检测（连续问题）
        question_marks = text.count("?") + text.count("？")
        if question_marks >= 3:
            score += 10
            reasons.append(f"包含 {question_marks} 个问号（多问题）")

        # 8. URL 检测（可能需要分析网页内容）
        urls = URL_PATTERN.findall(text)
        if urls:
            score += 5
            reasons.append(f"包含 {len(urls)} 个 URL")

        # 评分钳制到 0-100
        score = max(0, min(100, score))

        # 映射到复杂度等级
        if score >= 45:
            complexity = COMPLEXITY_COMPLEX
        elif score >= 15:
            complexity = COMPLEXITY_MODERATE
        else:
            complexity = COMPLEXITY_SIMPLE

        thinking_depth = COMPLEXITY_DEPTH_MAP[complexity]

        if not reasons:
            reasons.append("默认评估")

        result = {
            "complexity": complexity,
            "thinking_depth": thinking_depth,
            "score": score,
            "reasons": reasons,
        }
        logger.bind(
            event="complexity_assessed",
            complexity=complexity,
            score=score,
            depth=thinking_depth,
        ).debug(f"复杂度评估: {complexity} (score={score}, depth={thinking_depth})")
        return result

    def assess_depth(
        self,
        user_input: str,
        user_override: Optional[int] = None,
    ) -> int:
        """
        评估并返回推理深度。

        若用户提供了 override 值（0-5），则直接返回用户指定值。
        否则根据复杂度自动选择。

        Args:
            user_input: 用户输入文本。
            user_override: 用户手动指定的推理深度（0-5），None 表示自动评估。

        Returns:
            推理深度（0-5）。
        """
        if user_override is not None:
            # 钳制到 0-5
            depth = max(0, min(5, int(user_override)))
            logger.bind(
                event="thinking_depth_override",
                depth=depth,
            ).debug(f"用户手动指定推理深度: {depth}")
            return depth

        result = self.assess(user_input)
        return result["thinking_depth"]


# 全局单例
_assessor: Optional[ComplexityAssessor] = None


def get_complexity_assessor() -> ComplexityAssessor:
    """
    获取全局复杂度评估器单例。

    Returns:
        ComplexityAssessor 实例。
    """
    global _assessor
    if _assessor is None:
        _assessor = ComplexityAssessor()
    return _assessor
