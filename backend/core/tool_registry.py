"""
统一工具注册中心，管理工具的注册、发现、优先级和执行。

参考 OpenCode ToolRegistry 设计：
- 三层优先级：Location tools > Application tools > MCP tools
- 每个工具定义包含：name、description、parameters_schema、execute、permission
- 声明式工具定义模式
- 权限感知的工具过滤
- 工具输出截断与持久化

在 Open-AwA 中集成到现有 executor.py，不破坏现有工具执行逻辑。
"""

import asyncio
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

from loguru import logger
from pydantic import BaseModel, Field


class ToolPriority(int, Enum):
    """工具优先级"""
    LOCATION = 100    # Location 内置工具（最高）
    APPLICATION = 50  # 应用注册工具
    MCP = 10          # MCP 外部工具（最低）


class ToolStatus(str, Enum):
    """工具执行状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class ToolDefinition:
    """
    声明式工具定义。

    每个工具包含：
    - 元数据（名称、描述）
    - LLM 接口（parameters_schema, success_schema）
    - 执行逻辑（execute 函数）
    - 权限信息（permission action/resource）
    - 并发属性（is_concurrency_safe, is_read_only, is_destructive 等）
    """
    name: str
    description: str
    parameters_schema: Dict[str, Any] = field(default_factory=lambda: {
        "type": "object",
        "properties": {},
    })
    success_schema: Optional[Dict[str, Any]] = None
    execute: Optional[Callable] = None  # async def execute(parameters, context) -> dict
    permission_action: str = ""  # 默认使用 name 作为 action
    permission_resource: str = "*"  # 默认允许所有资源
    priority: ToolPriority = ToolPriority.APPLICATION
    enabled: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)
    # 并发属性字段（失败关闭：默认值均偏向不并发执行）
    # 是否并发安全，可为 bool 或基于输入参数判定的 callable
    is_concurrency_safe: Union[bool, Callable[[dict], bool]] = False
    # 是否只读工具（无副作用）
    is_read_only: bool = False
    # 是否破坏性操作（删除、覆写等）
    is_destructive: bool = False
    # 是否应延迟执行（避免阻塞关键路径）
    should_defer: bool = False
    # 是否总是加载到 LLM 上下文
    always_load: bool = False
    # 结果最大字符数（None 表示不限制）
    max_result_size_chars: Optional[int] = None
    # 中断行为：cancel（取消）/ wait（等待）/ detach（分离）
    interrupt_behavior: str = "cancel"

    def __post_init__(self):
        if not self.permission_action:
            self.permission_action = self.name

    def to_openai_function(self) -> Dict[str, Any]:
        """
        转换为 OpenAI function-calling 兼容格式。
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters_schema,
            },
        }


def resolve_concurrency_safe(
    definition: ToolDefinition,
    input_params: dict,
) -> bool:
    """
    根据工具定义和输入参数解析并发安全性。

    失败关闭原则：任何异常或不确定情况均返回 False（不并发执行）。

    Args:
        definition: 工具定义实例
        input_params: 工具调用的输入参数

    Returns:
        是否并发安全
    """
    is_safe = definition.is_concurrency_safe
    # bool 类型直接返回
    if isinstance(is_safe, bool):
        return is_safe
    # callable 类型调用判定函数
    if callable(is_safe):
        try:
            result = is_safe(input_params)
            return bool(result)
        except Exception as e:
            # 失败关闭：callable 抛异常时返回 False
            logger.warning(
                f"工具 '{definition.name}' 的 is_concurrency_safe callable 抛异常，"
                f"默认返回 False: {type(e).__name__}: {e}"
            )
            return False
    # 既不是 bool 也不是 callable，失败关闭返回 False
    logger.warning(
        f"工具 '{definition.name}' 的 is_concurrency_safe 类型非法: {type(is_safe).__name__}"
    )
    return False


@dataclass
class ToolExecutionResult:
    """工具执行结果"""
    tool_name: str
    status: ToolStatus
    result: Any = None
    error: Optional[str] = None
    output_path: Optional[str] = None  # 输出存储路径（需截断时）
    execution_time_ms: int = 0
    truncated: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.status == ToolStatus.COMPLETED,
            "tool_name": self.tool_name,
            "result": self.result,
            "error": self.error,
            "output_path": self.output_path,
            "execution_time_ms": self.execution_time_ms,
            "truncated": self.truncated,
        }


class ToolRegistry:
    """
    工具注册中心。

    职责：
    1. 注册/注销工具定义
    2. 按名称查找工具（遵循优先级）
    3. 生成 LLM 可见的工具定义列表
    4. 根据代理权限过滤可用工具
    5. 工具执行与输出管理
    """

    # 最大工具输出长度（字符数）
    MAX_OUTPUT_CHARS = 10_000

    def __init__(self):
        # 工具存储：name -> 优先级排序的工具列表
        self._tools: Dict[str, List[ToolDefinition]] = {}
        # 工具输出存储（按需持久化到文件）
        self._output_store: Dict[str, str] = {}
        # 工具执行统计
        self._stats: Dict[str, Dict[str, int]] = {}

    def register(self, tool: ToolDefinition) -> None:
        """注册工具定义"""
        if tool.name not in self._tools:
            self._tools[tool.name] = []

        # 按优先级插入
        tools_list = self._tools[tool.name]
        # 移除同优先级的旧定义
        tools_list[:] = [t for t in tools_list if t.priority != tool.priority]
        tools_list.append(tool)
        # 按优先级降序排列
        tools_list.sort(key=lambda t: t.priority.value, reverse=True)

        logger.debug(f"工具已注册: {tool.name} (优先级: {tool.priority.name})")

    def unregister(self, name: str, priority: Optional[ToolPriority] = None) -> None:
        """注销工具定义"""
        if name not in self._tools:
            return
        if priority is not None:
            self._tools[name] = [
                t for t in self._tools[name] if t.priority != priority
            ]
            if not self._tools[name]:
                del self._tools[name]
        else:
            del self._tools[name]

    def get(self, name: str) -> Optional[ToolDefinition]:
        """
        按名称获取工具定义（返回最高优先级）。

        优先级顺序：LOCATION > APPLICATION > MCP
        """
        tools = self._tools.get(name, [])
        return tools[0] if tools else None

    def list_all(self) -> List[ToolDefinition]:
        """列出所有已注册工具（最高优先级版本）"""
        return [
            tools[0] for tools in self._tools.values() if tools
        ]

    def get_definitions_for_llm(
        self,
        permissions: Optional[List[Dict[str, str]]] = None,
    ) -> List[Dict[str, Any]]:
        """
        生成 LLM 可见的工具定义列表（已过滤不可用工具）。

        Args:
            permissions: 代理权限规则列表

        Returns:
            OpenAI function-calling 格式的工具定义列表
        """
        from core.permission_manager import wildcard_match

        definitions = []
        for tool_name, tools_list in self._tools.items():
            if not tools_list:
                continue
            tool = tools_list[0]

            # 权限检查
            if permissions is not None:
                denied = False
                for rule in permissions:
                    if (rule.get("effect") == "deny"
                            and wildcard_match(rule.get("action", "*"), tool.permission_action)):
                        denied = True
                        break
                if denied:
                    continue

            definitions.append(tool.to_openai_function())

        return definitions

    async def execute(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> ToolExecutionResult:
        """
        执行工具调用。

        Args:
            tool_name: 工具名称
            parameters: 工具参数
            context: 执行上下文（session_id、user_id 等）

        Returns:
            工具执行结果
        """
        tool = self.get(tool_name)
        if not tool:
            return ToolExecutionResult(
                tool_name=tool_name,
                status=ToolStatus.ERROR,
                error=f"未知工具: {tool_name}",
            )

        if not tool.enabled:
            return ToolExecutionResult(
                tool_name=tool_name,
                status=ToolStatus.ERROR,
                error=f"工具已禁用: {tool_name}",
            )

        if not tool.execute:
            return ToolExecutionResult(
                tool_name=tool_name,
                status=ToolStatus.ERROR,
                error=f"工具未实现: {tool_name}",
            )

        start_time = time.perf_counter()
        try:
            result = tool.execute(parameters, context or {})
            if asyncio.iscoroutine(result):
                result = await result

            execution_time_ms = int((time.perf_counter() - start_time) * 1000)

            # 更新统计
            self._update_stats(tool_name, "completed")

            # 检查输出是否需要截断
            output_str = json.dumps(result, ensure_ascii=False)
            truncated = len(output_str) > self.MAX_OUTPUT_CHARS

            if truncated:
                output_path = await self._store_output(tool_name, output_str)
                result_summary = output_str[:self.MAX_OUTPUT_CHARS] + f"\n[输出已截断，完整内容: {output_path}]"
                return ToolExecutionResult(
                    tool_name=tool_name,
                    status=ToolStatus.COMPLETED,
                    result=result_summary,
                    output_path=output_path,
                    execution_time_ms=execution_time_ms,
                    truncated=True,
                )

            return ToolExecutionResult(
                tool_name=tool_name,
                status=ToolStatus.COMPLETED,
                result=result,
                execution_time_ms=execution_time_ms,
            )

        except Exception as e:
            execution_time_ms = int((time.perf_counter() - start_time) * 1000)
            self._update_stats(tool_name, "error")
            logger.error(f"工具执行失败 [{tool_name}]: {e}")
            return ToolExecutionResult(
                tool_name=tool_name,
                status=ToolStatus.ERROR,
                error=f"工具执行失败: {type(e).__name__}: {e}",
                execution_time_ms=execution_time_ms,
            )

    async def _store_output(self, tool_name: str, output: str) -> str:
        """将超长工具输出持久化到文件"""
        import uuid
        from pathlib import Path

        output_dir = Path("uploads/tool_outputs")
        output_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{tool_name}_{uuid.uuid4().hex[:8]}.txt"
        filepath = output_dir / filename

        def _write():
            filepath.write_text(output, encoding="utf-8")

        await asyncio.to_thread(_write)
        self._output_store[str(filepath)] = output
        return str(filepath)

    def _update_stats(self, tool_name: str, status: str) -> None:
        """更新工具执行统计"""
        if tool_name not in self._stats:
            self._stats[tool_name] = {"completed": 0, "error": 0, "total": 0}
        self._stats[tool_name][status] = self._stats[tool_name].get(status, 0) + 1
        self._stats[tool_name]["total"] += 1

    def get_stats(self, tool_name: Optional[str] = None) -> Dict[str, Any]:
        """获取工具执行统计"""
        if tool_name:
            return self._stats.get(tool_name, {"completed": 0, "error": 0, "total": 0})
        return self._stats

    def clear(self) -> None:
        """清空所有注册的工具"""
        self._tools.clear()


# 全局工具注册中心实例
tool_registry = ToolRegistry()
