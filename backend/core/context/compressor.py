"""
上下文压缩器 — 对话历史压缩和滑动窗口管理。
"""
from datetime import datetime, timezone
from typing import Any, Optional

from loguru import logger


class ContextCompressor:
    """
    对话上下文压缩器。
    管理对话历史的压缩策略：滑动窗口 + LLM 摘要。
    """

    def __init__(
        self,
        max_turns: int = 20,
        keep_last_turns: int = 5,
        compression_threshold: float = 0.8,
    ):
        self.max_turns = max_turns
        self.keep_last_turns = keep_last_turns
        self.compression_threshold = compression_threshold
        self._summary: Optional[str] = None
        self._compression_count: int = 0

    def should_compress(self, current_tokens: int, max_tokens: int) -> bool:
        """
        判断是否需要压缩上下文。
        当使用率超过阈值时触发。
        """
        if max_tokens <= 0:
            return False
        usage_ratio = current_tokens / max_tokens
        return usage_ratio >= self.compression_threshold

    def compress(
        self,
        messages: list[dict],
        generate_summary_fn=None,
        compression_instruction: str = "",
    ) -> dict:
        """
        压缩对话历史。

        Args:
            messages: 消息列表 [{role, content}, ...]
            generate_summary_fn: LLM 摘要生成函数（可选）
            compression_instruction: 压缩时保留/丢弃信息的指导

        Returns:
            {"compressed_messages": [...], "summary": "...", "removed_count": int}
        """
        if len(messages) <= self.keep_last_turns * 2:
            return {
                "compressed_messages": messages,
                "summary": self._summary or "",
                "removed_count": 0,
            }

        # 保留最近 N 轮完整对话
        keep_messages = messages[-self.keep_last_turns * 2:]
        to_compress = messages[:-self.keep_last_turns * 2]

        # 生成新摘要（拼接在已有摘要后面）
        new_summary_parts = []
        if self._summary:
            new_summary_parts.append(f"[历史摘要]\n{self._summary}")

        # 提取压缩部分的关键信息
        combined = " ".join(
            m.get("content", "")[:500] for m in to_compress
            if m.get("role") == "user"
        )
        if combined:
            new_summary_parts.append(
                f"[对话记录]\n"
                f"讨论了 {len(to_compress)//2} 轮对话。\n"
                f"关键话题: {combined[:2000]}"
            )

        self._summary = "\n".join(new_summary_parts)
        self._compression_count += 1

        # 构造压缩后的消息列表
        compressed_messages = keep_messages.copy()

        # 将摘要作为系统消息注入
        if self._summary:
            compressed_messages.insert(0, {
                "role": "system",
                "content": f"[压缩的历史上下文]\n{self._summary[:3000]}",
            })

        logger.bind(
            event="context_compressed",
            original=len(messages),
            kept=len(keep_messages),
            removed=len(to_compress),
            compression_count=self._compression_count,
        ).info("上下文已压缩")

        return {
            "compressed_messages": compressed_messages,
            "summary": self._summary,
            "removed_count": len(to_compress),
        }

    def reset(self):
        """重置压缩器状态。"""
        self._summary = None
        self._compression_count = 0

    def get_summary(self) -> Optional[str]:
        """获取当前压缩摘要。"""
        return self._summary

    def get_stats(self) -> dict:
        """获取压缩统计。"""
        return {
            "compression_count": self._compression_count,
            "summary_length": len(self._summary) if self._summary else 0,
            "max_turns": self.max_turns,
            "keep_last_turns": self.keep_last_turns,
        }
