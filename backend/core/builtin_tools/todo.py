"""
Todo 任务管理工具，提供 Claude Code 兼容的 todo_write 工具。
采用替换式协议：每次调用传入完整任务列表，自动合并更新状态。

参考 OpenHanako lib/tools/todo.js 设计。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

# ── 任务状态枚举 ──
TODO_STATE_PENDING = "pending"
TODO_STATE_IN_PROGRESS = "in_progress"
TODO_STATE_COMPLETED = "completed"
VALID_TODO_STATES = {TODO_STATE_PENDING, TODO_STATE_IN_PROGRESS, TODO_STATE_COMPLETED}

# 持久化文件名
TODO_FILE_NAME = "todos.json"


def _build_summary(todos: List[Dict[str, Any]], warning: Optional[str] = None) -> str:
    """
    根据当前任务列表构建状态摘要文本。

    Args:
        todos: 当前任务列表，每项包含 status 字段。
        warning: 可选的警告信息（如多个 in_progress）。

    Returns:
        格式化的状态摘要字符串。
    """
    if not todos:
        base = "Todo 状态：暂无任务"
    else:
        pending = sum(1 for t in todos if t.get("status") == TODO_STATE_PENDING)
        in_progress = sum(1 for t in todos if t.get("status") == TODO_STATE_IN_PROGRESS)
        completed = sum(1 for t in todos if t.get("status") == TODO_STATE_COMPLETED)
        base = (
            f"Todo 状态：共 {len(todos)} 项，"
            f"待处理 {pending}，进行中 {in_progress}，已完成 {completed}"
        )
    if warning:
        base += f"\n⚠️ {warning}"
    return base


def _detect_multi_in_progress(todos: List[Dict[str, Any]]) -> Optional[str]:
    """
    检测是否存在多个 in_progress 状态的任务（违反最佳实践：应只有一个进行中任务）。

    Args:
        todos: 当前任务列表。

    Returns:
        若检测到多个 in_progress，返回警告字符串；否则返回 None。
    """
    count = sum(1 for t in todos if t.get("status") == TODO_STATE_IN_PROGRESS)
    if count > 1:
        return f"检测到 {count} 个任务同时处于进行中状态（建议每次只进行一项）"
    return None


class TodoManager:
    """
    Todo 任务管理器。

    支持：
    - 替换式协议：每次调用传入完整任务列表，自动合并状态更新
    - 会话级持久化：通过 session_dir 将任务保存到磁盘
    - 多 in_progress 检测与警告
    - Claude Code 兼容的 todo_write 工具接口
    """

    def __init__(self, session_dir: Optional[str] = None):
        """
        初始化 Todo 管理器。

        Args:
            session_dir: 会话目录路径，用于持久化存储任务数据。
                         为 None 时仅使用内存存储。
        """
        self.name = "todo_manager"
        self.description = "Todo 任务管理工具，提供任务创建、状态更新和持久化能力"
        self.version = "1.0.0"

        self._session_dir = session_dir
        self._todos: List[Dict[str, Any]] = []
        self._loaded = False

    # ── 工具系统接口 ──

    async def initialize(self) -> None:
        """
        工具初始化（从磁盘加载已有任务数据）。
        符合内置工具的懒加载接口约定。
        """
        self._load_from_disk()

    def get_tools(self) -> List[Dict[str, Any]]:
        """
        返回工具的 API 定义列表（用于 /api/tools/list 展示）。

        Returns:
            包含 todo_write 工具定义的列表。
        """
        return [
            {
                "name": "todo_write",
                "description": "创建和管理任务列表。使用替换式协议，每次调用传入完整的 todos 数组来更新所有任务状态。支持 pending、in_progress、completed 三种状态。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "todos": {
                            "type": "array",
                            "description": "完整的任务列表（替换式，每次传入全部任务）",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string", "description": "任务唯一标识"},
                                    "content": {"type": "string", "description": "任务内容描述"},
                                    "status": {
                                        "type": "string",
                                        "enum": ["pending", "in_progress", "completed"],
                                        "description": "任务状态",
                                    },
                                },
                                "required": ["id", "content", "status"],
                            },
                        }
                    },
                    "required": ["todos"],
                },
            }
        ]

    async def execute(self, action: str, **params: Any) -> Dict[str, Any]:
        """
        执行内置工具操作（统一入口，由 BuiltInToolManager 调用）。

        Args:
            action: 操作名称，当前仅支持 "todo_write"。
            **params: 操作参数，对于 todo_write 需传入 todos 列表。

        Returns:
            操作结果字典。
        """
        if action != "todo_write":
            return {"success": False, "error": f"未知 Todo 操作: {action}"}

        try:
            todos = params.get("todos", [])
            result = self.update_todos(todos)
            logger.info(
                f"Todo 更新完成: total={result['counts']['total']}, "
                f"pending={result['counts']['pending']}, "
                f"in_progress={result['counts']['in_progress']}, "
                f"completed={result['counts']['completed']}"
            )
            return result
        except Exception as exc:
            logger.bind(module="todo_manager", action=action).exception(
                f"todo_manager 执行失败: {exc}"
            )
            return {"success": False, "error": str(exc)}

    # ── 持久化 ──

    def _get_todo_file_path(self) -> Optional[Path]:
        """获取 todo 持久化文件的完整路径。"""
        if not self._session_dir:
            return None
        return Path(self._session_dir) / TODO_FILE_NAME

    def _load_from_disk(self) -> None:
        """
        从磁盘加载已保存的任务列表（仅在首次访问时加载）。
        加载失败时静默降级为空列表。
        """
        if self._loaded:
            return
        self._loaded = True

        file_path = self._get_todo_file_path()
        if not file_path or not file_path.exists():
            return

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, list):
                self._todos = data
                logger.info(f"从磁盘加载了 {len(self._todos)} 个 Todo 项")
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(f"加载 Todo 数据失败: {e}")

    def _save_to_disk(self) -> None:
        """
        将当前任务列表持久化到磁盘。
        保存失败时记录错误日志但不抛出异常。
        """
        file_path = self._get_todo_file_path()
        if not file_path:
            return

        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(self._todos, f, ensure_ascii=False, indent=2)
        except OSError as e:
            logger.error(f"保存 Todo 数据失败: {e}")

    # ── 核心业务逻辑 ──

    def set_session_dir(self, session_dir: str) -> None:
        """
        设置（或切换）会话目录。

        切换会话目录时会丢弃当前内存中的数据并从新目录加载。

        Args:
            session_dir: 新的会话目录路径。
        """
        self._session_dir = session_dir
        self._loaded = False
        self._todos = []
        self._load_from_disk()

    def update_todos(self, todos: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        更新任务列表（替换式协议）。

        每次调用传入完整任务列表，系统自动：
        1. 校验每个任务的状态值
        2. 保留已有任务的时间戳（createdAt）和 activeForm 字段
        3. 为新任务生成时间戳
        4. 检测多个 in_progress 并产生警告

        Args:
            todos: 完整任务列表，每项需包含 id、content、status 字段。

        Returns:
            操作结果字典，包含 success、todos、summary、counts 字段。
        """
        self._load_from_disk()

        # 构建现有任务映射（按 id 索引，用于保留时间戳等元数据）
        existing: Dict[str, Dict[str, Any]] = {}
        for t in self._todos:
            tid = t.get("id")
            if tid:
                existing[tid] = t

        # 合并更新：遍历传入的任务列表，保留已有的元数据
        new_todos: List[Dict[str, Any]] = []
        for item in todos:
            tid = item.get("id")
            content = item.get("content", "")
            status = item.get("status", TODO_STATE_PENDING)

            # 校验状态值，无效值回退到 pending
            if status not in VALID_TODO_STATES:
                status = TODO_STATE_PENDING

            # 构建任务项，优先使用传入的 activeForm，其次保留已有的
            todo_item: Dict[str, Any] = {
                "id": tid,
                "content": content,
                "status": status,
                "updatedAt": datetime.now(timezone.utc).isoformat(),
            }

            active_form = item.get("activeForm")
            if active_form:
                # 传入的活跃表单文本
                todo_item["activeForm"] = active_form
            elif tid in existing and "activeForm" in existing[tid]:
                # 保留已有的活跃表单文本
                todo_item["activeForm"] = existing[tid]["activeForm"]
            elif tid in existing and "createdAt" in existing[tid]:
                # 保留已有的创建时间
                todo_item["createdAt"] = existing[tid]["createdAt"]
            else:
                # 新任务：生成创建时间
                todo_item["createdAt"] = datetime.now(timezone.utc).isoformat()

            new_todos.append(todo_item)

        self._todos = new_todos
        self._save_to_disk()

        # 构建计数与摘要
        pending = sum(1 for t in self._todos if t["status"] == TODO_STATE_PENDING)
        in_progress = sum(1 for t in self._todos if t["status"] == TODO_STATE_IN_PROGRESS)
        completed = sum(1 for t in self._todos if t["status"] == TODO_STATE_COMPLETED)

        warning = _detect_multi_in_progress(self._todos)
        summary_text = _build_summary(self._todos, warning)

        result: Dict[str, Any] = {
            "success": True,
            "todos": self._todos,
            "summary": summary_text,
            "counts": {
                "total": len(self._todos),
                "pending": pending,
                "in_progress": in_progress,
                "completed": completed,
            },
        }

        # 将警告信息放入 content 字段（兼容 Claude Code 协议）
        result["content"] = [{"type": "text", "text": summary_text}]
        if warning:
            result["warning"] = warning
            logger.warning(f"[todo_write] {warning}")

        return result

    def get_todos(self) -> Dict[str, Any]:
        """
        获取当前任务列表（只读）。

        Returns:
            包含 success、todos、count 字段的结果字典。
        """
        self._load_from_disk()
        return {
            "success": True,
            "todos": self._todos,
            "count": len(self._todos),
        }
