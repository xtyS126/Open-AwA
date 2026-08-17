"""
结构化上下文压缩引擎，实现自动溢出检测和模板化摘要生成。

参考 OpenCode SessionCompaction 设计：
- 检测上下文 token 是否超过模型窗口限制
- 自动触发压缩：保留最近 N tokens，对旧内容生成结构化摘要
- 7 段式摘要模板：Goal/Constraints/Progress/Decisions/NextSteps/CriticalContext/RelevantFiles
- 支持增量摘要合并（新摘要与旧摘要融合）
"""

import asyncio
import json
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from config.thresholds import (
    BUFFER_TOKENS,
    COMPACTION_TOOL_OUTPUT_MAX_CHARS,
    MAX_CONSECUTIVE_FAILURES,
    MICRO_COMPACT_KEEP_RECENT,
    RESERVED_TOKENS_MIN,
    SUMMARY_OUTPUT_TOKENS,
)
from core.context.token_budget import TokenBudget


# 摘要生成模板（参考 OpenCode SUMMARY_TEMPLATE）
SUMMARY_TEMPLATE = """Output exactly the Markdown structure shown inside <template> and keep the section order unchanged. Do not include the <template> tags in your response.
<template>
## 目标
- [任务目标总结]

## 约束与偏好
- [用户约束、偏好、规格说明，或 "(无)"]

## 进度
### 已完成
- [已完成的工作，或 "(无)"]

### 进行中
- [当前进行的工作，或 "(无)"]

### 阻塞
- [阻塞问题，或 "(无)"]

## 关键决策
- [决策内容及原因，或 "(无)"]

## 下一步
- [下一步计划，或 "(无)"]

## 关键上下文
- [重要的技术事实、错误信息、未解决问题，或 "(无)"]

## 相关文件
- [文件路径: 为什么重要，或 "(无)"]
</template>

规则：
- 保留每个部分，即使为空也要写 "(无)"
- 使用简洁的要点形式，不要写段落
- 保留精确的文件路径、命令、错误字符串和标识符
- 不要提及摘要过程或上下文被压缩的事实"""


@dataclass
class CompactionConfig:
    """压缩配置参数"""
    auto: bool = True
    buffer_tokens: int = BUFFER_TOKENS
    keep_tokens: int = RESERVED_TOKENS_MIN
    summary_output_tokens: int = SUMMARY_OUTPUT_TOKENS
    tool_output_max_chars: int = COMPACTION_TOOL_OUTPUT_MAX_CHARS


# 断路器阈值：连续摘要生成失败达到此次数后，跳过压缩以保护系统
# 值由 config.thresholds.MAX_CONSECUTIVE_FAILURES 提供

# 可安全清除输出的工具集合
# 这些工具的输出通常较大且可安全清除，用于 MicroCompact 轻量级压缩
COMPACTABLE_TOOLS = {"Read", "Shell", "Grep", "Glob", "WebSearch", "Edit", "Write"}

# MicroCompact 保留的最近消息条数：超出此阈值之前的工具输出会被清除
MICRO_COMPACT_RECENT_THRESHOLD = 5

# 会话级 CompactionManager 注册表：同一 session_id 复用同一实例，
# 使断路器失败计数在多次 compact() 调用之间保持（跨 agent / magic_commands / 路由调用点共享）。
# 使用可重入锁保护模块级可变状态：get_session_manager 持锁构造实例时，
# __init__ 会再次获取同一把锁（非重入锁会死锁），故必须使用 RLock。
_SESSION_MANAGERS: Dict[str, "CompactionManager"] = {}
_SESSION_MANAGERS_LOCK = threading.RLock()


def get_session_manager(
    session_id: Optional[str] = None,
    model_context_window: int = 128_000,
    config: Optional[CompactionConfig] = None,
) -> "CompactionManager":
    """
    获取会话级 CompactionManager 实例。

    同一 session_id 复用注册表中的同一实例，保证断路器连续失败计数跨多次
    compact() 调用（以及跨不同调用点）保持连续；session_id 为空时返回
    全新实例（不注册，不共享计数）。
    """
    if not session_id:
        return CompactionManager(
            model_context_window=model_context_window,
            config=config,
        )
    with _SESSION_MANAGERS_LOCK:
        manager = _SESSION_MANAGERS.get(session_id)
        if manager is None:
            manager = CompactionManager(
                session_id=session_id,
                model_context_window=model_context_window,
                config=config,
            )
            _SESSION_MANAGERS[session_id] = manager
        return manager


def clear_session_managers() -> None:
    """清空会话级实例注册表（主要用于测试隔离）。"""
    with _SESSION_MANAGERS_LOCK:
        _SESSION_MANAGERS.clear()


@dataclass
class TokenEstimate:
    """Token 估算结果"""
    total: int = 0
    system_tokens: int = 0
    messages_tokens: int = 0
    tools_tokens: int = 0


@dataclass
class PreservedSegment:
    """保留段标识，记录压缩边界保留的消息段 UUID"""
    anchor_uuid: str
    head_uuid: str
    tail_uuid: str


@dataclass
class CompactBoundaryMessage:
    """压缩边界消息，标记上下文压缩发生的位置"""
    is_compact_boundary: bool = True
    preserved_segment: Optional[PreservedSegment] = None


def create_compact_boundary_message(
    anchor_uuid: str,
    head_uuid: str,
    tail_uuid: str,
) -> Dict[str, Any]:
    """
    创建压缩边界消息。

    Args:
        anchor_uuid: 锚定消息 UUID
        head_uuid: 保留段头部 UUID
        tail_uuid: 保留段尾部 UUID

    Returns:
        dict 格式的系统消息，标记压缩边界
    """
    # 构建保留段标识，封装 UUID 信息
    segment = PreservedSegment(
        anchor_uuid=anchor_uuid,
        head_uuid=head_uuid,
        tail_uuid=tail_uuid,
    )
    content = (
        "[CompactBoundary] 此处为上下文压缩边界。\n"
        f"保留段: anchor={segment.anchor_uuid}, "
        f"head={segment.head_uuid}, tail={segment.tail_uuid}"
    )
    return {
        "role": "system",
        "content": content,
    }


# 模块级 TokenBudget 实例，用于统一 token 估算
# 使用中文 1.5 字符/token + 英文 4 字符/token 的启发式
_token_budget = TokenBudget()


def _estimate_text_tokens(text: str) -> int:
    """使用 TokenBudget 估算文本的 token 数量"""
    return _token_budget.estimate_tokens(text)


def _estimate_message_tokens(message: Dict[str, Any]) -> int:
    """估算单条消息的 token 数量"""
    content = message.get("content", "")
    if isinstance(content, str):
        return _estimate_text_tokens(content)
    if isinstance(content, list):
        # 多模态内容：累加各文本部分
        total = 0
        for part in content:
            if isinstance(part, dict) and "text" in part:
                total += _estimate_text_tokens(part["text"])
        return total
    return _estimate_text_tokens(str(content))


def _estimate_messages_tokens(messages: List[Dict[str, Any]]) -> int:
    """估算消息列表的总 token 数量"""
    return sum(_estimate_message_tokens(msg) for msg in messages)


def _estimate_tools_tokens(tools: List[Dict[str, Any]]) -> int:
    """估算工具定义的 token 数量"""
    tools_json = json.dumps(tools, ensure_ascii=False)
    return _estimate_text_tokens(tools_json)


def _estimate_total_tokens(
    system_prompt: str = "",
    messages: Optional[List[Dict[str, Any]]] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
) -> TokenEstimate:
    """估算完整请求的总 token 数量，返回分项明细"""
    system_tokens = _estimate_text_tokens(system_prompt)
    messages_tokens = _estimate_messages_tokens(messages or [])
    tools_tokens = _estimate_tools_tokens(tools or [])
    return TokenEstimate(
        total=system_tokens + messages_tokens + tools_tokens,
        system_tokens=system_tokens,
        messages_tokens=messages_tokens,
        tools_tokens=tools_tokens,
    )


class CompactionManager:
    """
    上下文压缩管理器。

    负责：
    1. 检测对话上下文是否超出模型窗口限制
    2. 选择需要保留的最近消息
    3. 生成被压缩部分的结构化摘要
    4. 合并增量摘要
    """

    def __init__(
        self,
        model_context_window: int = 128_000,
        config: Optional[CompactionConfig] = None,
        session_id: Optional[str] = None,
    ):
        self.model_context_window = model_context_window
        self.config = config or CompactionConfig()
        self.session_id = session_id
        self.llm_call: Optional[callable] = None  # LLM 调用函数
        # 压缩结果落库回调：async def(session_id, messages) -> None，
        # 由调用方注册，将摘要与边界写回持久层，避免每轮重复压缩重复计费
        self._persistence_hook: Optional[callable] = None
        # 断路器：连续摘要生成失败计数，达到 MAX_CONSECUTIVE_FAILURES 后跳过压缩
        self._consecutive_failures: int = 0
        # 提供 session_id 时注册到会话级注册表，供 get_session_manager 复用
        if session_id:
            with _SESSION_MANAGERS_LOCK:
                _SESSION_MANAGERS[session_id] = self

    def set_llm_call(self, llm_call: callable) -> None:
        """
        设置 LLM 调用函数。

        llm_call 签名为 async def(prompt: str, **kwargs) -> str
        """
        self.llm_call = llm_call

    def set_persistence_hook(self, persistence_hook: Optional[callable]) -> None:
        """
        设置压缩结果落库回调。

        hook 签名为 async def(session_id: Optional[str], messages: List[Dict[str, Any]]) -> None，
        在压缩成功后携带摘要系统消息与压缩边界消息调用，由调用方写入
        ShortTermMemory 等持久层，避免摘要每轮重复生成重复计费。
        """
        self._persistence_hook = persistence_hook

    def should_compact(
        self,
        system_prompt: str = "",
        messages: Optional[List[Dict[str, Any]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        output_tokens: int = 0,
    ) -> bool:
        """
        检测是否需要压缩上下文。

        条件：当前 token 数 > 模型窗口 - max(输出 token, 缓冲 token)
        """
        if not self.config.auto:
            return False
        if self.model_context_window <= 0:
            return False

        estimate = _estimate_total_tokens(system_prompt, messages, tools)
        available = self.model_context_window - max(output_tokens, self.config.buffer_tokens)

        return estimate.total > available

    def select_messages(
        self,
        messages: List[Dict[str, Any]],
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        按 token 预算分离消息。

        返回 (head_messages, recent_messages)：
        - recent_messages: 保留的最近消息（不超过 keep_tokens）
        - head_messages: 需要被压缩的旧消息
        """
        if not messages:
            return [], []

        keep = self.config.keep_tokens
        selected_recent: List[Dict[str, Any]] = []
        selected_head: List[Dict[str, Any]] = []
        accumulated = 0

        # 从后往前扫描，优先保留最近的消息
        for msg in reversed(messages):
            msg_tokens = _estimate_message_tokens(msg)
            if accumulated + msg_tokens <= keep:
                selected_recent.insert(0, msg)
                accumulated += msg_tokens
            else:
                selected_head.insert(0, msg)

        return selected_head, selected_recent

    def _serialize_message(self, message: Dict[str, Any]) -> str:
        """
        将消息序列化为压缩用的文本格式。

        参考 OpenCode serialize() 方法，将不同类型消息转换为
        易于 LLM 理解和摘要的文本格式。
        """
        role = message.get("role", "")
        content = message.get("content", "")

        if role == "user":
            text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
            return f"[用户]: {text}"

        if role == "assistant":
            if isinstance(content, str):
                return f"[助手]: {content}"
            # 处理 tool_calls 内容
            parts = []
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict):
                        if item.get("type") == "text":
                            parts.append(f"[助手]: {item.get('text', '')}")
                        elif item.get("type") == "tool_use":
                            name = item.get("name", "unknown")
                            tool_input = item.get("input", {})
                            input_str = json.dumps(tool_input, ensure_ascii=False)
                            parts.append(f"[工具调用]: {name}({input_str})")
            return "\n".join(parts) if parts else f"[助手]: {str(content)}"

        if role == "tool":
            name = message.get("name", message.get("tool_call_id", "unknown"))
            return f"[工具结果 {name}]: {self._truncate_output(str(content))}"

        if role == "system":
            return f"[系统]: {str(content)}"

        return f"[{role}]: {str(content)}"

    def _truncate_output(self, text: str) -> str:
        """截断工具输出，保留关键信息"""
        max_chars = self.config.tool_output_max_chars
        if len(text) <= max_chars:
            return text
        return f"{text[:max_chars]}\n[已截断]"

    def build_summary_prompt(
        self,
        head_messages: List[Dict[str, Any]],
        previous_summary: Optional[str] = None,
    ) -> str:
        """
        构建摘要生成提示词。

        Args:
            head_messages: 需要被压缩的消息
            previous_summary: 之前的摘要（用于增量合并）

        Returns:
            完整的摘要生成提示词
        """
        # 序列化旧消息
        serialized = []
        for msg in head_messages:
            text = self._serialize_message(msg)
            if text:
                serialized.append(text)

        context = "\n\n".join(serialized)

        if previous_summary:
            instruction = (
                "使用上面的对话历史更新锚定摘要。\n"
                "保留仍然真实的细节，删除过时的细节，合并新的事实。\n"
                f"<previous-summary>\n{previous_summary}\n</previous-summary>"
            )
        else:
            instruction = "从对话历史中创建新的锚定摘要。"

        return f"{instruction}\n\n{SUMMARY_TEMPLATE}\n\n{context}"

    async def generate_summary(
        self,
        head_messages: List[Dict[str, Any]],
        previous_summary: Optional[str] = None,
    ) -> Optional[str]:
        """
        调用 LLM 生成结构化摘要。

        成功时重置断路器计数，失败时递增计数。

        Args:
            head_messages: 需要被压缩的消息
            previous_summary: 之前的摘要（用于增量合并）

        Returns:
            生成的摘要文本，失败时返回 None
        """
        if not self.llm_call:
            logger.warning("CompactionManager 未配置 LLM 调用函数，无法生成摘要")
            self._consecutive_failures += 1
            return None

        if not head_messages:
            return previous_summary

        prompt = self.build_summary_prompt(head_messages, previous_summary)

        # 验证摘要 prompt 不会超过上下文窗口
        prompt_tokens = _estimate_text_tokens(prompt)
        if prompt_tokens > self.model_context_window - self.config.summary_output_tokens:
            logger.warning(
                f"摘要 prompt 过大 ({prompt_tokens} tokens)，"
                f"超过窗口限制 ({self.model_context_window})"
            )
            self._consecutive_failures += 1
            return None

        try:
            summary = await self.llm_call(
                prompt=prompt,
                max_tokens=self.config.summary_output_tokens,
                temperature=0.1,  # 低温度以获得稳定输出
            )
            if not summary or not summary.strip():
                self._consecutive_failures += 1
                return None
            # 成功生成摘要，重置断路器计数
            self._consecutive_failures = 0
            return summary.strip()
        except Exception as e:
            logger.error(f"生成摘要失败: {e}")
            self._consecutive_failures += 1
            return None

    def micro_compact(
        self,
        messages: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        轻量级压缩：替换旧工具输出为清除标记。

        不调用 LLM，仅替换 COMPACTABLE_TOOLS 中工具的旧输出内容。
        "旧"定义为消息索引早于最近 N 条消息（N=MICRO_COMPACT_RECENT_THRESHOLD）。

        Args:
            messages: 消息列表

        Returns:
            新的消息列表（不修改原列表）
        """
        if not messages:
            return []

        total = len(messages)
        result: List[Dict[str, Any]] = []

        for index, msg in enumerate(messages):
            if msg.get("role") == "tool":
                tool_name = msg.get("name", "")
                # 判断是否为可压缩工具且为旧消息
                is_compactable = tool_name in COMPACTABLE_TOOLS
                is_old = index < total - MICRO_COMPACT_RECENT_THRESHOLD
                if is_compactable and is_old:
                    # 替换 content 为清除标记，复制消息避免修改原列表
                    new_msg = dict(msg)
                    new_msg["content"] = "[Old tool result content cleared]"
                    result.append(new_msg)
                    continue
            result.append(msg)

        return result

    def group_messages_by_api_round(
        self,
        messages: List[Dict[str, Any]],
    ) -> List[List[Dict[str, Any]]]:
        """
        按 API 轮次分组消息。

        以"新 assistant 响应开始"为边界分组：
        - 遇到 role="assistant" 的消息开始新的一组
        - 后续的 role="tool" 消息归入当前组
        - 其他消息（user/system）归入当前组（若无当前组则新建）

        Args:
            messages: 消息列表

        Returns:
            分组后的消息列表
        """
        if not messages:
            return []

        groups: List[List[Dict[str, Any]]] = []
        current_group: List[Dict[str, Any]] = []

        for msg in messages:
            if msg.get("role") == "assistant":
                # assistant 消息开始新的一组
                if current_group:
                    groups.append(current_group)
                current_group = [msg]
            else:
                # 其他消息归入当前组
                current_group.append(msg)

        if current_group:
            groups.append(current_group)

        return groups

    async def compact(
        self,
        system_prompt: str = "",
        messages: Optional[List[Dict[str, Any]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        output_tokens: int = 0,
        previous_summary: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        执行完整压缩流程。

        优先尝试 MicroCompact 轻量级压缩（不调用 LLM），若 token 数降至阈值以下则直接返回；
        否则继续执行全量压缩（调用 LLM 生成摘要）。

        Returns:
            {
                "compacted": bool,         # 是否实际执行了压缩
                "messages": List[Dict],    # 压缩后的消息列表
                "summary": Optional[str],  # 生成的摘要
                "summary_message": Optional[Dict],  # 摘要系统消息
            }
        """
        messages = messages or []

        if not self.should_compact(system_prompt, messages, tools, output_tokens):
            return {
                "compacted": False,
                "messages": messages,
                "summary": previous_summary,
                "summary_message": None,
            }

        # 优先尝试 MicroCompact（轻量级压缩，不调用 LLM）
        micro_compacted = self.micro_compact(messages)
        micro_estimate = _estimate_total_tokens(
            system_prompt, micro_compacted, tools
        )
        available = self.model_context_window - max(
            output_tokens, self.config.buffer_tokens
        )

        if micro_estimate.total <= available:
            logger.info(
                f"MicroCompact 压缩成功: token {micro_estimate.total} <= {available},"
                f" 无需调用 LLM"
            )
            return {
                "compacted": True,
                "messages": micro_compacted,
                "summary": previous_summary,
                "summary_message": None,
            }

        logger.info("MicroCompact 不足以降低 token，执行全量压缩")

        # 断路器保护：连续失败达上限时跳过压缩，避免反复触发失败的 LLM 调用。
        # 跳过必须通过 error 字段显式告知调用方，禁止静默继续
        if self._consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            logger.warning(
                f"断路器触发：连续摘要生成失败 {self._consecutive_failures} 次，"
                f"跳过压缩（阈值 {MAX_CONSECUTIVE_FAILURES}）"
            )
            return {
                "compacted": False,
                "messages": messages,
                "summary": previous_summary,
                "summary_message": None,
                "error": (
                    f"摘要生成连续失败 {self._consecutive_failures} 次（断路器触发），"
                    f"上下文未压缩，原始历史已保留"
                ),
            }

        # 分离消息（使用 micro_compacted 以利用已清除的工具输出）
        head_messages, recent_messages = self.select_messages(micro_compacted)

        if not head_messages:
            return {
                "compacted": False,
                "messages": micro_compacted,
                "summary": previous_summary,
                "summary_message": None,
                "error": "上下文无历史消息可供摘要，未执行压缩",
            }

        # 生成摘要（失败时 generate_summary 内部已递增断路器计数）
        summary = await self.generate_summary(head_messages, previous_summary)

        if not summary:
            # 摘要生成失败：返回显式失败状态，历史保留但调用方可见错误
            logger.warning("摘要生成失败，使用 MicroCompact 后的消息列表")
            return {
                "compacted": False,
                "messages": micro_compacted,
                "summary": previous_summary,
                "summary_message": None,
                "error": "摘要生成失败，上下文未压缩（原始历史已保留）",
            }

        # 构建摘要系统消息
        summary_message = {
            "role": "system",
            "content": f"## 对话上下文摘要\n\n{summary}\n\n---\n以上是历史对话的结构化摘要。请基于摘要和以下最近的对话继续工作。",
        }

        # 构建压缩边界消息（复用 CompactBoundaryMessage 标记），标记压缩发生的位置
        anchor_uuid = self._extract_message_uuid(
            head_messages[-1], "compact-anchor"
        ) if head_messages else "compact-anchor"
        head_uuid = self._extract_message_uuid(
            head_messages[0], "compact-head"
        ) if head_messages else "compact-head"
        tail_uuid = self._extract_message_uuid(
            recent_messages[0], "compact-tail"
        ) if recent_messages else "compact-tail"
        boundary_message = create_compact_boundary_message(
            anchor_uuid, head_uuid, tail_uuid
        )
        boundary = CompactBoundaryMessage(
            preserved_segment=PreservedSegment(
                anchor_uuid=anchor_uuid,
                head_uuid=head_uuid,
                tail_uuid=tail_uuid,
            ),
        )

        # 组装压缩后的消息列表：[摘要消息] + [压缩边界消息] + [最近消息]
        compacted_messages = [summary_message, boundary_message] + recent_messages

        # 将压缩结果写回持久层：调用方注册的落库回调负责写入 ShortTermMemory 等，
        # 使后续轮次消费摘要边界，避免摘要每轮重复生成重复计费
        if self._persistence_hook is not None:
            try:
                await self._persistence_hook(
                    self.session_id,
                    [summary_message, boundary_message],
                )
            except Exception as exc:
                # 落库失败不阻断压缩结果，但必须记录日志以便排查
                logger.error(f"压缩结果落库失败: {exc}")

        logger.info(
            f"上下文压缩完成: {len(messages)} -> {len(compacted_messages)} 条消息,"
            f" 摘要长度: {len(summary)} 字符"
        )

        return {
            "compacted": True,
            "messages": compacted_messages,
            "summary": summary,
            "summary_message": summary_message,
            "boundary_message": boundary_message,
            "boundary": boundary,
            "_reset_cache_baseline": True,  # 压缩后需重置 Prompt Cache 基线
        }

    @staticmethod
    def _extract_message_uuid(message: Dict[str, Any], fallback: str) -> str:
        """
        提取消息的 uuid 标识，缺失时使用占位标记。

        消息可能来自短期记忆转换（无 uuid 字段）或 JSONL 回放（带 uuid），
        边界标记对缺失 uuid 的消息使用语义化占位，保证边界信息始终可构造。
        """
        raw = message.get("uuid") or message.get("id")
        if isinstance(raw, str) and raw:
            return raw
        return fallback

    @staticmethod
    def parse_compaction_sections(summary: str) -> Dict[str, str]:
        """
        解析摘要文本为各个部分。

        返回以段落标题为键的字典。
        """
        sections: Dict[str, str] = {
            "目标": "",
            "约束与偏好": "",
            "已完成": "",
            "进行中": "",
            "阻塞": "",
            "关键决策": "",
            "下一步": "",
            "关键上下文": "",
            "相关文件": "",
        }

        current_section = ""
        current_content: List[str] = []

        for line in summary.split("\n"):
            line = line.strip()
            # 匹配 Markdown 标题
            match = re.match(r"^#{1,3}\s+(.+)$", line)
            if match:
                # 保存上一个部分
                if current_section and current_section in sections:
                    sections[current_section] = "\n".join(current_content).strip()
                current_section = match.group(1).strip()
                current_content = []
            elif current_section:
                # 跳过 "(无)" 条目
                if line not in ("- (无)", "- (none)", "- (None)", "(无)"):
                    current_content.append(line)

        # 保存最后一个部分
        if current_section and current_section in sections:
            sections[current_section] = "\n".join(current_content).strip()

        return sections
