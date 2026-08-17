"""
工具执行策略注册表：根据工具名前缀查找匹配的策略并分发执行。
"""
from typing import Dict, List, Optional
from .base import ToolExecutionStrategy, ToolExecutionContext, ToolExecutionResult


class ToolExecutionStrategyRegistry:
    """工具执行策略注册表"""

    def __init__(self):
        self._strategies: Dict[str, ToolExecutionStrategy] = {}

    def register(self, prefix: str, strategy: ToolExecutionStrategy):
        """注册策略：prefix 为工具名前缀（如 'plugin_'、'mcp_'、'builtin_'、'task_'）"""
        self._strategies[prefix] = strategy

    def unregister(self, prefix: str):
        """注销策略"""
        self._strategies.pop(prefix, None)

    def get_strategy(self, tool_name: str) -> Optional[ToolExecutionStrategy]:
        """根据工具名查找匹配的策略（按前缀匹配，最长匹配优先）"""
        # 按前缀长度降序排列，确保最长匹配优先
        sorted_prefixes = sorted(self._strategies.keys(), key=len, reverse=True)
        for prefix in sorted_prefixes:
            if tool_name.startswith(prefix):
                return self._strategies[prefix]
        return None

    def get_all_prefixes(self) -> List[str]:
        """获取所有已注册的前缀"""
        return list(self._strategies.keys())

    async def execute(self, context: ToolExecutionContext) -> ToolExecutionResult:
        """根据工具名查找策略并执行"""
        strategy = self.get_strategy(context.tool_name)
        if strategy is None:
            return ToolExecutionResult(
                output=None,
                error=f"未找到工具 '{context.tool_name}' 的执行策略",
            )

        # 权限检查
        if not await strategy.check_permission(context):
            return ToolExecutionResult(
                output=None,
                error=f"工具 '{context.tool_name}' 执行被权限检查拒绝",
                needs_permission=True,
                permission_message=f"需要用户授权执行工具 '{context.tool_name}'",
            )

        # PreToolUse 钩子
        hook_result = await strategy.apply_pre_hooks(context)
        if hook_result is not None:
            return hook_result

        # 执行工具
        result = await strategy.execute(context)

        # PostToolUse 钩子
        result = await strategy.apply_post_hooks(context, result)

        return result