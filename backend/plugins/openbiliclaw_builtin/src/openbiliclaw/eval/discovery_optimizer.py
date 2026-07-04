"""发现系统特定的 prompt 优化器配置。

定义参数注册表、可修改文件白名单、
以及内容发现 pipeline 的字段到参数映射。
复用 optimizer.py 中的核心 PromptOptimizer。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from openbiliclaw.eval.discovery_evaluator import (
    DISCOVERY_FIELD_TO_PARAM,
    DimensionScore,
)
from openbiliclaw.eval.optimizer import (
    ContinuousParam,
    PromptOptimizer,
    PromptParam,
)

if TYPE_CHECKING:
    from pathlib import Path

_SRC = "src/openbiliclaw"

# 发现系统优化器允许修改的文件。
DISCOVERY_MODIFIABLE_FILES: list[str] = [
    f"{_SRC}/llm/prompts.py",
    f"{_SRC}/discovery/strategies/search.py",
    f"{_SRC}/discovery/strategies/trending.py",
    f"{_SRC}/discovery/strategies/related_chain.py",
    f"{_SRC}/discovery/strategies/explore.py",
    f"{_SRC}/discovery/engine.py",
]

DISCOVERY_PROMPT_PARAMS: list[PromptParam] = [
    PromptParam(
        name="search_queries_prompt",
        file_path=f"{_SRC}/llm/prompts.py",
        function_name="build_search_queries_prompt",
    ),
    PromptParam(
        name="trending_rids_prompt",
        file_path=f"{_SRC}/llm/prompts.py",
        function_name="build_trending_rids_prompt",
    ),
    PromptParam(
        name="content_evaluation_prompt",
        file_path=f"{_SRC}/llm/prompts.py",
        function_name="build_content_evaluation_prompt",
    ),
    PromptParam(
        name="explore_domains_prompt",
        file_path=f"{_SRC}/llm/prompts.py",
        function_name="build_explore_domains_prompt",
    ),
    PromptParam(
        name="recommendation_expression_prompt",
        file_path=f"{_SRC}/llm/prompts.py",
        function_name="build_recommendation_expression_prompt",
    ),
]

# 无连续参数——阈值和策略代码不自动优化。
# 只有 prompts.py 中的 prompt 模板会自动优化。
DISCOVERY_CONTINUOUS_PARAMS: list[ContinuousParam] = []


def create_discovery_optimizer(
    *,
    project_root: Path | None = None,
    llm: Any = None,
    use_agent_sdk: bool = True,
) -> PromptOptimizer:
    """创建配置为发现 pipeline 的 PromptOptimizer。"""
    return PromptOptimizer(
        llm=llm,
        use_agent_sdk=use_agent_sdk,
        project_root=project_root,
        continuous_params=list(DISCOVERY_CONTINUOUS_PARAMS),
        prompt_params=list(DISCOVERY_PROMPT_PARAMS),
        modifiable_files=list(DISCOVERY_MODIFIABLE_FILES),
        field_to_param=dict(DISCOVERY_FIELD_TO_PARAM),
    )


def dimension_scores_to_field_scores(
    worst_dims: list[DimensionScore],
) -> list[Any]:
    """将 DimensionScore 列表转换为优化器兼容的 FieldScore 对象。

    PromptOptimizer.exploit() 期望具有 .layer、.field、.score、
    .deviation 属性的对象。我们将 DimensionScore（dimension="strategy.dim"）
    转换为该结构。
    """
    from openbiliclaw.eval.evaluator import FieldScore

    results: list[FieldScore] = []
    for dim in worst_dims:
        parts = dim.dimension.split(".", 1)
        layer = parts[0] if len(parts) > 1 else ""
        field_name = parts[1] if len(parts) > 1 else parts[0]
        results.append(
            FieldScore(
                layer=layer,
                field=field_name,
                score=dim.score,
                expected=None,
                predicted=None,
                deviation=dim.details or f"score={dim.score:.2f}",
                severity=dim.severity,
            )
        )
    return results
