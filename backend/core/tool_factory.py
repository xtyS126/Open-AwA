"""
工具工厂模块。

提供基于配置字典构造 ToolDefinition 的工厂方法，
统一内置工具的并发属性默认值（失败关闭原则）。

主要导出：
- TOOL_DEFAULTS：并发属性失败关闭默认值
- VALID_INTERRUPT_BEHAVIORS：合法的中断行为枚举
- build_tool：根据配置字典构造 ToolDefinition
- is_command_read_only：基于输入参数判定命令是否只读
"""

from typing import Any, Dict

from core.tool_registry import ToolDefinition, ToolPriority


# 并发属性失败关闭默认值
# 所有缺失字段均回退到此默认值，确保未显式声明的工具偏向不并发执行
TOOL_DEFAULTS: Dict[str, Any] = {
    "is_concurrency_safe": False,
    "is_read_only": False,
    "is_destructive": False,
    "should_defer": False,
    "always_load": False,
    "max_result_size_chars": None,
    "interrupt_behavior": "cancel",
}

# 合法的中断行为取值
VALID_INTERRUPT_BEHAVIORS = ("cancel", "wait", "detach")

# 只读命令白名单（前缀匹配）
# 这些命令无副作用，可安全并发执行
READ_ONLY_COMMAND_PREFIXES = (
    "ls",
    "cat",
    "grep",
    "find",
    "git status",
    "git log",
    "git diff",
    "pwd",
    "echo",
    "whoami",
    "env",
)


def is_command_read_only(input_params: dict) -> bool:
    """
    根据输入参数判定 shell 命令是否只读（无副作用）。

    失败关闭原则：无法判定或非只读命令均返回 False。

    Args:
        input_params: 工具调用输入参数，应包含 "command" 字段

    Returns:
        命令只读返回 True，否则返回 False
    """
    if not isinstance(input_params, dict):
        return False
    command = input_params.get("command", "")
    if not isinstance(command, str) or not command:
        return False
    # 去除首尾空白后按前缀匹配白名单
    stripped = command.strip()
    for prefix in READ_ONLY_COMMAND_PREFIXES:
        # 精确匹配或后接空白字符（避免 "lsv" 误匹配 "ls"）
        if stripped == prefix or stripped.startswith(prefix + " "):
            return True
    return False


def build_tool(config: dict) -> ToolDefinition:
    """
    根据配置字典构造 ToolDefinition 实例。

    缺失的并发属性字段回退到 TOOL_DEFAULTS（失败关闭默认值）。

    Args:
        config: 工具配置字典，需包含 name 和 description，
                可选包含 parameters_schema、execute、permission_action、
                permission_resource、priority、enabled、metadata 以及并发属性字段

    Returns:
        构造完成的 ToolDefinition 实例

    Raises:
        ValueError: interrupt_behavior 非法或 is_concurrency_safe 类型非法时抛出
        TypeError: config 不是字典时抛出
    """
    if not isinstance(config, dict):
        raise TypeError(f"config 必须为字典，实际类型: {type(config).__name__}")

    # 解析并发属性字段，缺失时回退到 TOOL_DEFAULTS
    is_concurrency_safe = config.get(
        "is_concurrency_safe", TOOL_DEFAULTS["is_concurrency_safe"]
    )
    is_read_only = config.get("is_read_only", TOOL_DEFAULTS["is_read_only"])
    is_destructive = config.get("is_destructive", TOOL_DEFAULTS["is_destructive"])
    should_defer = config.get("should_defer", TOOL_DEFAULTS["should_defer"])
    always_load = config.get("always_load", TOOL_DEFAULTS["always_load"])
    max_result_size_chars = config.get(
        "max_result_size_chars", TOOL_DEFAULTS["max_result_size_chars"]
    )
    interrupt_behavior = config.get(
        "interrupt_behavior", TOOL_DEFAULTS["interrupt_behavior"]
    )

    # 验证 is_concurrency_safe 必须是 bool 或 callable
    if not isinstance(is_concurrency_safe, bool) and not callable(is_concurrency_safe):
        raise ValueError(
            f"is_concurrency_safe 必须为 bool 或 callable，"
            f"实际类型: {type(is_concurrency_safe).__name__}"
        )

    # 验证 interrupt_behavior 必须是合法取值
    if interrupt_behavior not in VALID_INTERRUPT_BEHAVIORS:
        raise ValueError(
            f"interrupt_behavior 必须为 {VALID_INTERRUPT_BEHAVIORS} 之一，"
            f"实际值: {interrupt_behavior!r}"
        )

    # 构造 ToolDefinition
    return ToolDefinition(
        name=config.get("name", ""),
        description=config.get("description", ""),
        parameters_schema=config.get(
            "parameters_schema", {"type": "object", "properties": {}}
        ),
        success_schema=config.get("success_schema"),
        execute=config.get("execute"),
        permission_action=config.get("permission_action", ""),
        permission_resource=config.get("permission_resource", "*"),
        priority=config.get("priority", ToolPriority.APPLICATION),
        enabled=config.get("enabled", True),
        metadata=config.get("metadata", {}),
        is_concurrency_safe=is_concurrency_safe,
        is_read_only=is_read_only,
        is_destructive=is_destructive,
        should_defer=should_defer,
        always_load=always_load,
        max_result_size_chars=max_result_size_chars,
        interrupt_behavior=interrupt_behavior,
    )
