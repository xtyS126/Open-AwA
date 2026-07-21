"""
Transcript 序列化模块，负责将代理执行过程持久化为 JSON 行记录并提供摘要构建。
SSE 事件构造已统一迁移到 core.streaming_events。
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from config.settings import settings
from loguru import logger


def get_transcript_dir() -> Path:
    """获取 transcript 存储目录，确保目录存在。"""
    base = Path(settings.BASE_DIR) if hasattr(settings, "BASE_DIR") else Path.cwd()
    transcript_dir = base / "data" / "task_runtime" / "transcripts"
    transcript_dir.mkdir(parents=True, exist_ok=True)
    return transcript_dir


def save_transcript_entry(agent_id: str, entry: Dict[str, Any]) -> None:
    """向 agent 的 transcript 文件追加一条 JSON 行记录。"""
    transcript_dir = get_transcript_dir()
    transcript_path = transcript_dir / f"{agent_id}.jsonl"
    entry["_ts"] = datetime.now(timezone.utc).isoformat()
    with open(transcript_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")


def get_transcript_path(agent_id: str) -> str:
    """获取 agent transcript 文件的绝对路径。"""
    transcript_dir = get_transcript_dir()
    return str(transcript_dir / f"{agent_id}.jsonl")


def read_transcript(agent_id: str) -> list:
    """读取 agent 的完整 transcript 记录列表。"""
    transcript_path = get_transcript_dir() / f"{agent_id}.jsonl"
    if not transcript_path.exists():
        return []
    entries = []
    with open(transcript_path, "r", encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    logger.bind(
                        module="task_runtime",
                        agent_id=agent_id,
                        transcript_path=str(transcript_path),
                        line_number=line_number,
                    ).warning(
                        f"transcript 存在损坏行，已跳过: agent_id={agent_id}, line={line_number}, error={exc.msg}"
                    )
    return entries


def build_summary(result: Dict[str, Any], max_length: int = 2000) -> str:
    """从执行结果构建文本摘要，限制最大长度。"""
    if isinstance(result.get("response"), str) and result["response"]:
        text = result["response"]
        return text[:max_length] + ("..." if len(text) > max_length else "")
    if isinstance(result.get("content"), str) and result["content"]:
        text = result["content"]
        return text[:max_length] + ("..." if len(text) > max_length else "")
    if result.get("ok") and result.get("summary"):
        text = str(result["summary"])
        return text[:max_length] + ("..." if len(text) > max_length else "")
    if result.get("error"):
        return f"[ERROR] {str(result['error'])[:max_length]}"
    return json.dumps(result, ensure_ascii=False, default=str)[:max_length]
